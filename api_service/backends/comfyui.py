import asyncio
import copy
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import websockets

from api_service.config import backend_config, gateway_config
from api_service.logging_config import get_logger

# ── Helpers ──────────────────────────────────────────────────────────────────

def _patch_api_workflow(wf: Dict, patches: Dict[str, Dict[str, Any]]) -> Dict:
    """通用的 API 格式 Workflow 注入工具
    patches 格式: { "node_id": { "input_name": value } }
    """
    for node_id, inputs in patches.items():
        if node_id in wf:
            wf[node_id]["inputs"].update(inputs)
    return wf

def _patch_video_workflow(workflow: Dict, prompt: str, negative_prompt: str, image_url: str, num_frames: int, width: int, height: int, seed: int, fps: int, model: str = "") -> Dict:
    """针对视频 API Workflow 的特定注入"""
    patches = {
        "97": {"image": image_url.replace("/files/", "") if image_url.startswith("/files/") else image_url},
        "129:93": {"text": prompt},
        "129:89": {"text": negative_prompt},
        "129:98": {"width": width, "height": height, "length": num_frames},
        "129:86": {"noise_seed": seed} if seed != -1 else {},
        "129:94": {"fps": fps}
    }
    return _patch_api_workflow(copy.deepcopy(workflow), patches)

def _patch_image_workflow(workflow: Dict, prompt: str, width: int, height: int, seed: int) -> Dict:
    """针对图片 API Workflow 的特定注入"""
    patches = {
        "104:90": {"text": prompt},
        "104:91": {"width": width, "height": height},
        "104:92": {"seed": seed} if seed != -1 else {}
    }
    return _patch_api_workflow(copy.deepcopy(workflow), patches)

def _patch_bgm_workflow(workflow: Dict, tags: str, lyrics: str, duration: int, seed: int, bpm: int, language: str, keyscale: str) -> Dict:
    """针对音频 API Workflow 的特定注入"""
    patches = {
        "94": {
            "tags": tags,
            "lyrics": lyrics,
            "bpm": bpm,
            "duration": duration,
            "language": language,
            "keyscale": keyscale,
            "seed": seed if seed != -1 else 0
        },
        "98": {"seconds": duration}
    }
    return _patch_api_workflow(copy.deepcopy(workflow), patches)

class ComfyUIBackend:
    def __init__(self, backend_name: str = "image"):
        self.backend_name = backend_name
        cfg = backend_config(backend_name)
        self.base_url = cfg["base_url"].rstrip("/")
        self.default_workflow = cfg.get("default_workflow", "")
        self.timeout = cfg.get("timeout_seconds", 120)
        self.client_id = cfg.get("client_id", "novel-video-pipeline")
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(self.timeout, connect=10.0))
        self._log = get_logger("comfyui_backend")

    async def check_health(self) -> bool:
        try:
            resp = await self._http.get("/system_stats")
            return resp.status_code == 200
        except: return False

    async def _submit_workflow(self, workflow: Dict) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        with open("debug_comfy_payload.json", "w") as f: json.dump(payload, f, indent=2)
        try:
            resp = await self._http.post("/prompt", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            err = e.response.text
            self._log.error(f"ComfyUI HTTP {e.response.status_code}: {err}")
            raise Exception(f"ComfyUI Error: {err}")
        return resp.json()["prompt_id"]

    async def _wait_for_prompt(self, prompt_id: str) -> None:
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={self.client_id}"
        async with websockets.connect(ws_url, max_size=None) as ws:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
                if msg.get("type") == "execution_success" and msg.get("data", {}).get("prompt_id") == prompt_id: return
                if msg.get("type") == "execution_error" and msg.get("data", {}).get("prompt_id") == prompt_id:
                    raise RuntimeError(f"ComfyUI error: {msg.get('data')}")

    async def _get_output_files(self, prompt_id: str) -> List[Tuple[str, str]]:
        resp = await self._http.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        outputs = resp.json().get(prompt_id, {}).get("outputs", {})
        files = []
        for _, out in outputs.items():
            for field in ["images", "gifs", "videos", "audio"]:
                for item in out.get(field, []):
                    files.append((item.get("filename", ""), item.get("subfolder", "")))
        return [(f, s) for f, s in files if f]

    async def _download_file(self, filename: str, dest_dir: Path, subfolder: str = "") -> Path:
        resp = await self._http.get("/view", params={"filename": filename, "subfolder": subfolder, "type": "output"})
        resp.raise_for_status()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(resp.content)
        return dest

    async def _upload_image(self, image_path: Path) -> str:
        with open(image_path, "rb") as f:
            resp = await self._http.post("/upload/image", files={"image": (image_path.name, f, "image/png")})
            resp.raise_for_status()
        return resp.json()["name"]

    async def generate_video(self, image_path: Path, prompt: str, negative_prompt: str = "", **kwargs) -> Tuple[List[Path], int]:
        workflow_path = Path(f"api_service/workflows/{self.default_workflow}.json")
        with open(workflow_path) as f: wf = json.load(f)
        
        image_url = await self._upload_image(image_path)
        seed = kwargs.get("seed", -1)
        if seed == -1:
            import random
            seed = random.randint(1, 1125899906842624)

        patched_wf = _patch_video_workflow(wf, prompt, negative_prompt, image_url, 
                                           num_frames=kwargs.get("num_frames", 81), width=kwargs.get("width", 640),
                                           height=kwargs.get("height", 480), seed=seed, fps=kwargs.get("fps", 24))
        
        prompt_id = await self._submit_workflow(patched_wf)
        await self._wait_for_prompt(prompt_id)
        files = await self._get_output_files(prompt_id)
        if not files: raise Exception("No output files")
        dest_dir = Path(gateway_config().get("outputs_dir", "outputs")) / "videos"
        final_video = await self._download_file(files[0][0], dest_dir, files[0][1])
        return [final_video], seed

    async def generate_image(self, prompt: str, negative_prompt: str = "", **kwargs) -> Tuple[List[Path], int]:
        workflow_path = Path(f"api_service/workflows/{self.default_workflow}.json")
        with open(workflow_path) as f: wf = json.load(f)
        
        seed = kwargs.get("seed", -1)
        if seed == -1:
            import random
            seed = random.randint(1, 1125899906842624)

        patched_wf = _patch_image_workflow(wf, prompt, 
                                           width=kwargs.get("width", 640),
                                           height=kwargs.get("height", 480),
                                           seed=seed)
        prompt_id = await self._submit_workflow(patched_wf)
        await self._wait_for_prompt(prompt_id)
        files = await self._get_output_files(prompt_id)
        if not files: raise Exception("No output files")
        dest_dir = Path(gateway_config().get("outputs_dir", "outputs")) / "images"
        final_image = await self._download_file(files[0][0], dest_dir, files[0][1])
        return [final_image], seed

    async def generate_bgm(self, tags: str, lyrics: str, duration: int, **kwargs) -> Tuple[List[Path], int]:
        workflow_path = Path(f"api_service/workflows/{self.default_workflow}.json")
        with open(workflow_path) as f: wf = json.load(f)
        
        seed = kwargs.get("seed", -1)
        if seed == -1:
            import random
            seed = random.randint(1, 1125899906842624)

        patched_wf = _patch_bgm_workflow(wf, tags, lyrics, duration, 
                                          seed=seed, bpm=kwargs.get("bpm", 120),
                                          language=kwargs.get("language", "zh"), keyscale=kwargs.get("keyscale", "C Major"))
        prompt_id = await self._submit_workflow(patched_wf)
        await self._wait_for_prompt(prompt_id)
        files = await self._get_output_files(prompt_id)
        if not files: raise Exception("No output files")
        dest_dir = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"
        final_audio = await self._download_file(files[0][0], dest_dir, files[0][1])
        return [final_audio], seed

    async def generate_tts(self, text: str, voice: str, **kwargs) -> str:
        raise NotImplementedError("Generate TTS is not implemented yet")

_backends = {}

def get_backend(name: str):
    if name not in _backends: _backends[name] = ComfyUIBackend(name)
    return _backends[name]

def get_image_backend(): return get_backend("image")
def get_video_backend(): return get_backend("video")
def get_tts_backend(): return get_backend("tts")
def get_bgm_backend(): return get_backend("bgm")

async def generate_image(prompt: str, negative_prompt: str = "", **kwargs) -> Tuple[List[Path], int]:
    return await get_image_backend().generate_image(prompt, negative_prompt, **kwargs)

async def generate_video(image_path: Path, prompt: str, negative_prompt: str = "", **kwargs) -> Tuple[List[Path], int]:
    return await get_video_backend().generate_video(image_path, prompt, negative_prompt, **kwargs)

async def generate_bgm(tags: str, lyrics: str, duration: int, **kwargs) -> Tuple[List[Path], int]:
    return await get_bgm_backend().generate_bgm(tags, lyrics, duration, **kwargs)

async def generate_tts(text: str, voice: str, **kwargs):
    return await get_backend("tts").generate_tts(text, voice, **kwargs)

async def synthesize_video(video_path: Path, audio_path: Path, output_path: Path, bgm_path: Path = None) -> Path:
    """使用 ffmpeg 合成视频、TTS 和可选的 BGM，并以 TTS 长度为准"""
    import asyncio
    
    # 基础输入：视频（无限循环）和 TTS 音频
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(video_path),
        "-i", str(audio_path)
    ]
    
    # 如果有 BGM，增加第三个输入
    if bgm_path:
        cmd.extend(["-i", str(bgm_path)])
        # filter_complex: 
        # [1:a] 是 TTS，音量 1.0
        # [2:a] 是 BGM，音量 0.2
        # amix: duration=first 表示以第一路音频 (TTS) 的长度作为混音结束点
        filter_complex = "[1:a]volume=1.0[a1]; [2:a]volume=0.2[a2]; [a1][a2]amix=inputs=2:duration=first[a]"
    else:
        filter_complex = "[1:a]volume=1.0[a]"

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v:0",         # 视频来自第一个输入
        "-map", "[a]",           # 音频来自滤镜处理结果
        "-c:v", "libx264",       # 循环和对齐时建议重编码以确保稳定性
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-shortest",             # 在最短的流（即混音后的音频）结束时停止
        str(output_path)
    ])
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        raise Exception(f"FFmpeg failed with exit code {process.returncode}: {stderr.decode()}")
    
    return output_path

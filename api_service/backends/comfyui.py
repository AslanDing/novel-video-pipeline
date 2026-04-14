"""
api_service/backends/comfyui.py
ComfyUI HTTP API + WebSocket 推理封装

工作流程：
  1. POST /prompt  → 提交 Workflow JSON，返回 prompt_id
  2. WebSocket /ws?clientId=...  → 监听 progress / executing / executed 事件
  3. GET /history/{prompt_id}  → 拉取最终输出文件列表
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import websockets

from api_service.config import backend_config

# Workflow 模板目录（相对项目根）
_WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"


def _load_workflow(name: str) -> Dict:
    """从 api_service/workflows/ 加载 JSON workflow 模板"""
    path = _WORKFLOW_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"ComfyUI workflow not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class ComfyUIBackend:
    """ComfyUI 推理后端"""

    def __init__(self, backend_name: str = "image"):
        cfg = backend_config(backend_name)
        self.base_url = cfg["base_url"].rstrip("/")
        self.default_workflow = cfg.get("default_workflow", "t2i_flux")
        self.timeout = cfg.get("timeout_seconds", 120)
        self.client_id = cfg.get("client_id", "novel-video-pipeline")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _submit_workflow(self, workflow: Dict) -> str:
        """提交 workflow，返回 prompt_id"""
        payload = {"prompt": workflow, "client_id": self.client_id}
        resp = await self._http.post("/prompt", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["prompt_id"]

    async def _wait_for_prompt(self, prompt_id: str) -> None:
        """通过 WebSocket 等待 prompt 执行完成"""
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws?clientId={self.client_id}"

        async with websockets.connect(ws_url, max_size=None) as ws:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    msg = json.loads(raw)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"ComfyUI timed out waiting for {prompt_id}")
                except Exception:
                    continue

                msg_type = msg.get("type", "")
                data = msg.get("data", {})

                if msg_type == "executed" and data.get("prompt_id") == prompt_id:
                    return
                if msg_type == "execution_error" and data.get("prompt_id") == prompt_id:
                    raise RuntimeError(f"ComfyUI execution error: {data}")

    async def _get_output_files(self, prompt_id: str) -> List[str]:
        """从 history 获取输出文件路径列表"""
        resp = await self._http.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        history = resp.json()

        prompt_data = history.get(prompt_id, {})
        outputs = prompt_data.get("outputs", {})

        files = []
        for node_id, node_out in outputs.items():
            # 图像输出
            for img in node_out.get("images", []):
                files.append(img.get("filename", ""))
            # 视频/GIF 输出
            for vid in node_out.get("gifs", []):
                files.append(vid.get("filename", ""))
            for vid in node_out.get("videos", []):
                files.append(vid.get("filename", ""))

        return [f for f in files if f]

    async def _download_file(self, filename: str, dest_dir: Path, subfolder: str = "") -> Path:
        """从 ComfyUI /view 接口下载文件到本地"""
        params: Dict[str, str] = {"filename": filename}
        if subfolder:
            params["subfolder"] = subfolder
        params["type"] = "output"

        resp = await self._http.get("/view", params=params)
        resp.raise_for_status()

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(resp.content)
        return dest

    # ── public ────────────────────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int = -1,
        model: str = "",
        workflow_name: str = "",
        output_dir: Optional[Path] = None,
    ) -> Tuple[List[Path], int]:
        """
        文生图推理。
        Returns: (output_paths, actual_seed)
        """
        wf_name = workflow_name or self.default_workflow
        workflow = _load_workflow(wf_name)

        # 填充 workflow 参数（key 名称需与 workflow JSON 中 node id 对应）
        workflow = _patch_image_workflow(
            workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            model=model,
        )

        prompt_id = await self._submit_workflow(workflow)
        await self._wait_for_prompt(prompt_id)
        filenames = await self._get_output_files(prompt_id)

        dest_dir = output_dir or (Path("outputs") / "images")
        paths = []
        for fn in filenames:
            p = await self._download_file(fn, dest_dir)
            paths.append(p)

        return paths, seed

    async def generate_video(
        self,
        image_path: Path,
        prompt: str = "",
        motion_prompt: str = "",
        negative_prompt: str = "",
        num_frames: int = 81,
        fps: int = 24,
        width: int = 854,
        height: int = 480,
        seed: int = -1,
        model: str = "",
        workflow_name: str = "",
        output_dir: Optional[Path] = None,
    ) -> Tuple[List[Path], int]:
        """
        图生视频推理。
        Returns: (output_paths, actual_seed)
        """
        wf_name = workflow_name or self.default_workflow
        workflow = _load_workflow(wf_name)

        workflow = _patch_video_workflow(
            workflow,
            image_path=str(image_path),
            prompt=prompt,
            motion_prompt=motion_prompt,
            negative_prompt=negative_prompt,
            num_frames=num_frames,
            fps=fps,
            width=width,
            height=height,
            seed=seed,
            model=model,
        )

        prompt_id = await self._submit_workflow(workflow)
        await self._wait_for_prompt(prompt_id)
        filenames = await self._get_output_files(prompt_id)

        dest_dir = output_dir or (Path("outputs") / "videos")
        paths = []
        for fn in filenames:
            p = await self._download_file(fn, dest_dir)
            paths.append(p)

        return paths, seed

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/system_stats", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()


# ── workflow 参数注入辅助 ─────────────────────────────────────────────────────

def _patch_image_workflow(
    workflow: Dict,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
    model: str,
) -> Dict:
    """
    将参数注入 ComfyUI workflow JSON。
    约定：workflow 中使用特定 node title 来标识可配置节点:
      - title "positive" → text positive prompt
      - title "negative" → text negative prompt
      - title "sampler"  → KSampler 节点 (seed, steps, cfg)
      - title "latent"   → EmptyLatentImage (width, height)
      - title "loader"   → CheckpointLoaderSimple (ckpt_name)
    
    如果 workflow 不含上述 title，直接返回原始 workflow（使用模板默认值）。
    """
    import copy
    wf = copy.deepcopy(workflow)

    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue
        meta = node.get("_meta", {})
        title = meta.get("title", "").lower()
        inputs = node.get("inputs", {})

        if "positive" in title and "text" in inputs:
            inputs["text"] = prompt
        elif "negative" in title and "text" in inputs:
            inputs["text"] = negative_prompt
        elif "sampler" in title or node.get("class_type", "") in (
            "KSampler", "KSamplerAdvanced"
        ):
            if seed != -1:
                inputs["seed"] = seed
            inputs["steps"] = steps
            inputs["cfg"] = cfg
        elif "latent" in title or node.get("class_type", "") == "EmptyLatentImage":
            inputs["width"] = width
            inputs["height"] = height
        elif "loader" in title or node.get("class_type", "") == "CheckpointLoaderSimple":
            if model:
                inputs["ckpt_name"] = model

    return wf


def _patch_video_workflow(
    workflow: Dict,
    image_path: str,
    prompt: str,
    motion_prompt: str,
    negative_prompt: str,
    num_frames: int,
    fps: int,
    width: int,
    height: int,
    seed: int,
    model: str,
) -> Dict:
    """将图生视频参数注入 workflow"""
    import copy
    wf = copy.deepcopy(workflow)

    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue
        meta = node.get("_meta", {})
        title = meta.get("title", "").lower()
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")

        if "positive" in title and "text" in inputs:
            combined = f"{prompt} {motion_prompt}".strip()
            inputs["text"] = combined
        elif "negative" in title and "text" in inputs:
            inputs["text"] = negative_prompt
        elif class_type in ("LoadImage", "ImageLoader") or "load image" in title:
            inputs["image"] = image_path
        elif "sampler" in title or class_type in ("KSampler", "KSamplerAdvanced"):
            if seed != -1:
                inputs["seed"] = seed
        elif class_type == "ImageResizeNode" or "resize" in title:
            inputs["width"] = width
            inputs["height"] = height
        elif "frame" in title or class_type in ("SVDFrameCount",):
            inputs["num_frames"] = num_frames
        elif "loader" in title or class_type == "CheckpointLoaderSimple":
            if model:
                inputs["ckpt_name"] = model

    return wf


# ── 单例 ──────────────────────────────────────────────────────────────────────
_image_backend: Optional[ComfyUIBackend] = None
_video_backend: Optional[ComfyUIBackend] = None


def get_image_backend() -> ComfyUIBackend:
    global _image_backend
    if _image_backend is None:
        _image_backend = ComfyUIBackend("image")
    return _image_backend


def get_video_backend() -> ComfyUIBackend:
    global _video_backend
    if _video_backend is None:
        _video_backend = ComfyUIBackend("video")
    return _video_backend

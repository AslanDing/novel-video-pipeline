"""
core/api_client.py
统一 API 客户端

替代之前分散的 NVIDIA_NIM_Client、local_llm_client、diffusers 调用等。
主应用所有 AI 推理均通过此客户端转发到 api_service 网关。

使用方式：
    client = NovelAPIClient()
    response = await client.llm_generate("写第一章...", system_prompt="你是顶级网文作家")
    image    = await client.image_generate("epic scene, anime style")
    audio    = await client.tts_synthesize("林凡睁开双眼...", voice_id="narrator")
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

# ── 配置读取（优先环境变量，其次 api_services.json）────────────────────────
import os
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

_DEFAULT_GATEWAY = os.environ.get("NOVEL_API_GATEWAY", "http://localhost:9000")


# ── 返回值数据类 ──────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    content: str
    usage: Dict[str, int]
    model: str
    finish_reason: str

    @classmethod
    def from_dict(cls, d: Dict) -> "LLMResponse":
        usage = d.get("usage", {})
        if isinstance(usage, dict):
            usage = usage  # 保持 dict
        else:
            usage = {}
        return cls(
            content=d.get("content", ""),
            usage=usage,
            model=d.get("model", ""),
            finish_reason=d.get("finish_reason", "stop"),
        )


@dataclass
class ImageResult:
    task_id: str
    images: List[Dict]  # [{"url": ..., "width": ..., "height": ..., "seed": ...}]
    status: str
    elapsed_seconds: float = 0.0


@dataclass
class VideoResult:
    task_id: str
    video_url: Optional[str]
    status: str
    duration_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0


@dataclass
class AudioResult:
    task_id: str
    audio_url: Optional[str]
    status: str
    duration_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0


@dataclass
class TaskResult:
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None


# ── 主客户端 ──────────────────────────────────────────────────────────────────

class NovelAPIClient:
    """
    统一 AI 服务客户端。

    所有方法均为 async。长任务（图像/视频/BGM）默认使用 wait=True 自动轮询。
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_GATEWAY,
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    # ── LLM ──────────────────────────────────────────────────────────────────

    async def llm_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.9,
        response_format: Optional[Dict] = None,
    ) -> LLMResponse:
        """
        非流式 LLM 生成。
        兼容旧 NVIDIA_NIM_Client.generate() 接口。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        if response_format:
            payload["response_format"] = response_format

        resp = await self._http.post("/llm/generate", json=payload)
        resp.raise_for_status()
        return LLMResponse.from_dict(resp.json())

    async def llm_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        流式 LLM 生成（SSE）。
        产出文本 token chunks。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        async with self._http.stream("POST", "/llm/stream", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    token = line[6:]
                    if token:
                        yield token

    # ── Image ─────────────────────────────────────────────────────────────────

    async def image_generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int = -1,
        model: str = "",
        workflow: str = "",
        wait: bool = True,
    ) -> ImageResult:
        """
        文生图。
        wait=True 时自动轮询直到完成，返回 ImageResult。
        """
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "seed": seed,
            "model": model,
            "workflow": workflow,
        }
        resp = await self._http.post("/image/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        task_id = data["task_id"]

        if not wait:
            return ImageResult(
                task_id=task_id,
                images=[],
                status=data.get("status", "queued"),
            )

        task = await self.wait_for_task(task_id, poll_url=f"/image/tasks/{task_id}")
        result = task.result or {}
        return ImageResult(
            task_id=task_id,
            images=result.get("images", []),
            status=task.status,
            elapsed_seconds=task.elapsed_seconds or 0.0,
        )

    # ── Video ─────────────────────────────────────────────────────────────────

    async def video_generate(
        self,
        image_url: str,
        prompt: str = "",
        motion_prompt: str = "",
        negative_prompt: str = "",
        num_frames: int = 81,
        fps: int = 24,
        width: int = 854,
        height: int = 480,
        seed: int = -1,
        model: str = "",
        workflow: str = "",
        wait: bool = True,
    ) -> VideoResult:
        """图文生视频（Image-to-Video）"""
        payload = {
            "image_url": image_url,
            "prompt": prompt,
            "motion_prompt": motion_prompt,
            "negative_prompt": negative_prompt,
            "num_frames": num_frames,
            "fps": fps,
            "width": width,
            "height": height,
            "seed": seed,
            "model": model,
            "workflow": workflow,
        }
        resp = await self._http.post("/video/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        task_id = data["task_id"]

        if not wait:
            return VideoResult(task_id=task_id, video_url=None, status="queued")

        task = await self.wait_for_task(task_id, poll_url=f"/video/tasks/{task_id}")
        result = task.result or {}
        return VideoResult(
            task_id=task_id,
            video_url=result.get("video_url"),
            status=task.status,
            duration_seconds=result.get("duration_seconds"),
            elapsed_seconds=task.elapsed_seconds or 0.0,
        )

    # ── TTS ───────────────────────────────────────────────────────────────────

    async def tts_synthesize(
        self,
        text: str,
        voice_id: str = "",
        speed: float = 1.0,
        format: str = "mp3",
        wait: bool = True,
    ) -> AudioResult:
        """TTS 语音合成（Fish Audio）"""
        payload = {
            "text": text,
            "reference_id": voice_id,
            "speed": speed,
            "format": format,
        }
        resp = await self._http.post("/tts/synthesize", json=payload)
        resp.raise_for_status()
        data = resp.json()
        task_id = data["task_id"]

        if not wait:
            return AudioResult(task_id=task_id, audio_url=None, status="queued")

        task = await self.wait_for_task(task_id, poll_url=f"/tts/tasks/{task_id}")
        result = task.result or {}
        return AudioResult(
            task_id=task_id,
            audio_url=result.get("audio_url"),
            status=task.status,
            duration_seconds=result.get("duration_seconds"),
            elapsed_seconds=task.elapsed_seconds or 0.0,
        )

    # ── BGM ───────────────────────────────────────────────────────────────────

    async def bgm_generate(
        self,
        prompt: str,
        tags: Optional[List[str]] = None,
        duration_seconds: int = 30,
        format: str = "wav",
        seed: int = -1,
        wait: bool = True,
    ) -> AudioResult:
        """背景音乐/音效生成（ACE-Step）"""
        payload = {
            "prompt": prompt,
            "tags": tags or [],
            "duration_seconds": duration_seconds,
            "format": format,
            "seed": seed,
        }
        resp = await self._http.post("/bgm/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        task_id = data["task_id"]

        if not wait:
            return AudioResult(task_id=task_id, audio_url=None, status="queued")

        task = await self.wait_for_task(task_id, poll_url=f"/bgm/tasks/{task_id}")
        result = task.result or {}
        return AudioResult(
            task_id=task_id,
            audio_url=result.get("audio_url"),
            status=task.status,
            duration_seconds=result.get("duration_seconds"),
            elapsed_seconds=task.elapsed_seconds or 0.0,
        )

    # ── Task Polling ──────────────────────────────────────────────────────────

    async def wait_for_task(
        self,
        task_id: str,
        poll_url: Optional[str] = None,
        poll_interval: Optional[float] = None,
        max_wait_seconds: float = 600.0,
    ) -> TaskResult:
        """
        轮询任务状态直到完成或超时。
        Returns: TaskResult
        """
        url = poll_url or f"/tasks/{task_id}"
        interval = poll_interval or self.poll_interval
        waited = 0.0

        while waited < max_wait_seconds:
            resp = await self._http.get(url)
            if resp.status_code == 404:
                # 任务还未创建，稍等
                await asyncio.sleep(interval)
                waited += interval
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "unknown")

            if status in ("completed", "failed"):
                return TaskResult(
                    task_id=task_id,
                    status=status,
                    result=data.get("result"),
                    error=data.get("error"),
                    elapsed_seconds=data.get("elapsed_seconds"),
                )

            await asyncio.sleep(interval)
            waited += interval

        raise TimeoutError(f"Task {task_id} timed out after {max_wait_seconds}s")

    # ── Utility ───────────────────────────────────────────────────────────────

    async def health(self) -> Dict:
        """检查 api_service 网关健康状态"""
        resp = await self._http.get("/health", timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        """关闭 HTTP 客户端"""
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


# ── 便捷函数 ──────────────────────────────────────────────────────────────────

_default_client: Optional[NovelAPIClient] = None


def get_api_client(base_url: str = _DEFAULT_GATEWAY) -> NovelAPIClient:
    """获取全局默认客户端（单例）"""
    global _default_client
    if _default_client is None:
        _default_client = NovelAPIClient(base_url=base_url)
    return _default_client


# ── 向后兼容：提供 generate() 接口，供旧代码过渡 ─────────────────────────────

class _CompatLLMClient:
    """
    向后兼容适配器。
    现有代码中使用 llm_client.generate(prompt, ...) 的调用可无缝替换为此类实例。

    替换方式：
        # 旧代码
        from core.llm_client import NVIDIA_NIM_Client
        client = NVIDIA_NIM_Client()

        # 新代码
        from core.api_client import get_compat_llm_client
        client = get_compat_llm_client()
    """

    def __init__(self, api_client: Optional[NovelAPIClient] = None):
        self._api = api_client or get_api_client()

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history=None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        **kwargs,
    ) -> LLMResponse:
        return await self._api.llm_generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )

    async def generate_stream(self, prompt: str, system_prompt=None, **kwargs):
        async for token in self._api.llm_stream(prompt, system_prompt=system_prompt):
            yield token

    async def close(self):
        pass  # 共享客户端，不关闭


def get_compat_llm_client() -> _CompatLLMClient:
    """
    获取向后兼容 LLM 客户端。
    可直接替换 NVIDIA_NIM_Client / local_llm_client。
    """
    return _CompatLLMClient()

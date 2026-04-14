"""
api_service/backends/fish_audio.py
Fish Audio TTS 封装

支持两种模式：
  1. Cloud API  — 通过 wss://api.fish.audio/v1/tts (WebSocket 流式)
  2. Local      — 本地 fish-speech HTTP 服务（同样 OpenAI 兼容）

文档参考：https://docs.fish.audio/text-to-speech/text-to-speech
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from api_service.config import backend_config


class FishAudioBackend:
    """Fish Audio TTS 后端"""

    def __init__(self):
        cfg = backend_config("tts")
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url", "https://api.fish.audio").rstrip("/")
        self.ws_url = cfg.get("ws_url", "wss://api.fish.audio/v1/tts")
        self.default_voice_id = cfg.get("default_voice_id", "")
        self.default_format = cfg.get("default_format", "mp3")
        self.timeout = cfg.get("timeout_seconds", 60)
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    # ── public ────────────────────────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        reference_id: str = "",
        speed: float = 1.0,
        format: str = "mp3",
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        合成 TTS 音频，保存到文件。
        Returns: 保存的文件路径
        """
        voice_id = reference_id or self.default_voice_id
        fmt = format or self.default_format

        if output_path is None:
            output_path = Path("outputs") / "audio" / f"tts_{uuid.uuid4().hex[:8]}.{fmt}"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 优先使用 WebSocket 流式（官方推荐）
        try:
            await self._synthesize_ws(text, voice_id, speed, fmt, output_path)
        except Exception:
            # Fallback: HTTP REST API（部分本地部署版本支持）
            await self._synthesize_http(text, voice_id, speed, fmt, output_path)

        return output_path

    async def _synthesize_ws(
        self,
        text: str,
        voice_id: str,
        speed: float,
        fmt: str,
        output_path: Path,
    ) -> None:
        """WebSocket 流式请求（官方 Cloud API）"""
        import websockets

        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with websockets.connect(self.ws_url, extra_headers=headers, max_size=None) as ws:
                # 发送请求 JSON
                request = {
                    "text": text,
                    "reference_id": voice_id,
                    "format": fmt,
                    "mp3_bitrate": 128,
                    "chunk_length": 200,
                    "normalize": True,
                    "prosody": {"speed": speed},
                }
                await ws.send(json.dumps(request))

                # 收集音频 bytes
                audio_chunks = []
                async for msg in ws:
                    if isinstance(msg, bytes):
                        audio_chunks.append(msg)
                    elif isinstance(msg, str):
                        # 可能是控制消息，忽略
                        pass

                audio_data = b"".join(audio_chunks)
                if not audio_data:
                    raise RuntimeError("Fish Audio WebSocket returned no audio data")
                output_path.write_bytes(audio_data)
        except ImportError:
            raise RuntimeError(
                "websockets 未安装，请运行: pip install websockets"
            )

    async def _synthesize_http(
        self,
        text: str,
        voice_id: str,
        speed: float,
        fmt: str,
        output_path: Path,
    ) -> None:
        """HTTP REST 请求（本地 fish-speech 兼容）"""
        payload = {
            "text": text,
            "format": fmt,
            "mp3_bitrate": 128,
        }
        if voice_id:
            payload["reference_id"] = voice_id

        # fish-speech 本地通常是 /v1/tts
        resp = await self._http.post(
            f"{self.base_url}/v1/tts",
            json=payload,
        )
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    async def list_voices(self):
        """列出可用音色（Cloud API）"""
        try:
            resp = await self._http.get(f"{self.base_url}/model")
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

    async def health(self) -> bool:
        try:
            # fish-speech 本地健康检查
            resp = await self._http.get(
                f"{self.base_url}/v1/health",
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception:
            # Cloud 版本：只要 API key 存在即视为健康（不发真实请求）
            return bool(self.api_key)

    async def close(self):
        await self._http.aclose()


# ── 单例 ──────────────────────────────────────────────────────────────────────
_backend: Optional[FishAudioBackend] = None


def get_tts_backend() -> FishAudioBackend:
    global _backend
    if _backend is None:
        _backend = FishAudioBackend()
    return _backend

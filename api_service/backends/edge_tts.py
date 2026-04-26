"""
api_service/backends/edge_tts.py
Edge TTS 后端封装（微软在线 TTS）
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

import httpx

from api_service.config import gateway_config

# edge-tts 异步通信
import edge_tts


class EdgeTTS_Backend:
    """Edge TTS 语音合成后端"""

    def __init__(self):
        self.timeout = 60
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10.0))

    async def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        format: str = "mp3",
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        合成 TTS 音频，保存到文件。
        Returns: 保存的文件路径
        """
        if output_path is None:
            outputs_dir = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"
            output_path = outputs_dir / f"tts_{uuid.uuid4().hex[:8]}.{format}"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))

        return output_path

    async def list_voices(self) -> list:
        """列出可用音色（按语言分组）"""
        try:
            voices = await edge_tts.list_voices()
            return [v for v in voices if v["Locale"].startswith("zh-")]
        except Exception:
            return []

    async def health(self) -> bool:
        """Edge TTS 健康检查（直接尝试合成测试）"""
        try:
            test_path = Path("/tmp") / f"edge_tts_health_{uuid.uuid4().hex[:8]}.mp3"
            communicate = edge_tts.Communicate("测试", "zh-CN-XiaoxiaoNeural")
            await communicate.save(str(test_path))
            test_path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()


# ── 单例 ──────────────────────────────────────────────────────────────────────
_backend: Optional[EdgeTTS_Backend] = None


def get_tts_backend() -> EdgeTTS_Backend:
    global _backend
    if _backend is None:
        _backend = EdgeTTS_Backend()
    return _backend
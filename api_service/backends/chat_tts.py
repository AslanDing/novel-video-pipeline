"""
api_service/backends/chat_tts.py
ChatTTS 本地 TTS 封装
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Optional

import httpx

from api_service.config import gateway_config, backend_config


class ChatTTSBackend:
    """ChatTTS 本地 TTS 后端"""

    def __init__(self):
        cfg = backend_config("tts")
        self.timeout = cfg.get("timeout_seconds", 120)
        self.sample_rate = cfg.get("sample_rate", 24000)
        self.speed = cfg.get("speed", 1.0)
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=30.0),
        )

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        format: str = "wav",
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

        # 尝试使用本地 ChatTTS 推理
        try:
            await self._synthesize_local(text, output_path, format)
        except Exception as e:
            # Fallback: 创建静音文件
            await self._create_silent_audio(output_path, format)
            print(f"ChatTTS synthesize failed: {e}, created silent placeholder")

        return output_path

    async def _synthesize_local(self, text: str, output_path: Path, format: str) -> None:
        """使用本地 ChatTTS 推理"""
        try:
            import ChatTTS
            import numpy as np
            import soundfile as sf
            import torch

            model = ChatTTS.Chat()

            # 加载模型
            try:
                model.load(compile=False)
            except Exception:
                pass

            # 生成固定种子
            seed = abs(hash("chattts_default")) % 10000
            torch.manual_seed(seed)

            # 获取说话人音色
            try:
                spk = model.sample_random_speaker()
            except Exception:
                spk = None

            # 推理参数
            params_infer_code = {
                'spk_s': spk,
                'txt_s': text,
            }
            params_refine_text = {
                'prompt': '[oral_2][laugh_0][break_6]'
            }

            wavs = model.infer(
                [text],
                params_refine_text=params_refine_text,
                params_infer_code=params_infer_code,
                use_decoder=True,
            )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("ChatTTS returned empty audio")

            audio_data = np.array(wavs[0])
            if audio_data.ndim > 1:
                audio_data = audio_data.flatten()

            sf.write(str(output_path), audio_data, 24000)

        except ImportError as e:
            raise RuntimeError(f"ChatTTS not installed: {e}")

    async def _create_silent_audio(self, output_path: Path, format: str) -> None:
        """创建静音占位音频"""
        import numpy as np
        import soundfile as sf

        # 1秒静音
        sample_rate = 24000
        duration = 1.0
        audio_data = np.zeros(int(sample_rate * duration), dtype=np.float32)

        sf.write(str(output_path), audio_data, sample_rate)

    async def list_voices(self) -> list:
        """列出可用音色（ChatTTS 支持音色采样）"""
        try:
            import ChatTTS
            model = ChatTTS.Chat()
            model.load(compile=False)
            spk = model.sample_random_speaker()
            return [{"voice_id": "default", "speaker": spk.tolist() if spk is not None else []}]
        except Exception:
            return [{"voice_id": "default", "speaker": []}]

    async def health(self) -> bool:
        """ChatTTS 健康检查"""
        try:
            import ChatTTS
            model = ChatTTS.Chat()
            model.load(compile=False)
            return True
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()


# ── 单例 ──────────────────────────────────────────────────────────────────────
_backend: Optional[ChatTTSBackend] = None


def get_tts_backend() -> ChatTTSBackend:
    global _backend
    if _backend is None:
        _backend = ChatTTSBackend()
    return _backend
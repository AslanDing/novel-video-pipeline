"""
api_service/backends/ace_step.py
ACE-Step 1.5 背景音乐/音效生成封装

ACE-Step 是专为音乐生成设计的扩散模型。
本模块通过子进程调用 ACE-Step CLI 或其内置推理接口。

项目地址：https://github.com/ace-step/ACE-Step
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import List, Optional

from api_service.config import backend_config


class ACEStepBackend:
    """ACE-Step 1.5 本地推理后端"""

    def __init__(self):
        cfg = backend_config("bgm")
        self.model_path = cfg.get("model_path", "models/sound/ace-step-v1.5")
        self.device = cfg.get("device", "cuda")
        self.timeout = cfg.get("timeout_seconds", 180)
        self._pipeline = None  # 懒加载

    # ── 懒加载 pipeline ───────────────────────────────────────────────────────

    def _load_pipeline(self):
        """懒加载 ACE-Step pipeline（首次调用时加载）"""
        if self._pipeline is not None:
            return

        try:
            # ACE-Step 提供两种调用方式：
            # 1. Python API（推荐）: from acestep.pipeline import ACEStepPipeline
            # 2. CLI: python -m acestep.infer ...
            # 此处尝试 Python API，若未安装则回退到 CLI
            from acestep.pipeline import ACEStepPipeline  # type: ignore
            self._pipeline = ACEStepPipeline.from_pretrained(
                self.model_path,
                device=self.device,
            )
            print(f"✅ ACE-Step pipeline loaded from {self.model_path}")
        except ImportError:
            # CLI 模式，_pipeline 保持 None，使用 _generate_via_cli
            print("⚠️  acestep Python API not installed, will use CLI mode")
            self._pipeline = "cli"
        except Exception as e:
            print(f"⚠️  ACE-Step load failed: {e}, using CLI fallback")
            self._pipeline = "cli"

    # ── public ────────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        tags: Optional[List[str]] = None,
        duration_seconds: int = 30,
        format: str = "wav",
        seed: int = -1,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        生成背景音乐/音效。
        Returns: 生成的音频文件路径
        """
        self._load_pipeline()

        if output_path is None:
            output_path = Path("outputs") / "audio" / f"bgm_{uuid.uuid4().hex[:8]}.{format}"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        tags_str = ",".join(tags or [])
        full_prompt = f"{prompt}; {tags_str}".strip("; ")

        if self._pipeline == "cli":
            await self._generate_via_cli(full_prompt, duration_seconds, seed, output_path)
        else:
            await asyncio.get_event_loop().run_in_executor(
                None,
                self._generate_sync,
                full_prompt,
                duration_seconds,
                seed,
                output_path,
            )

        return output_path

    def _generate_sync(
        self,
        prompt: str,
        duration_seconds: int,
        seed: int,
        output_path: Path,
    ) -> None:
        """同步 Python API 调用（在 executor 中运行）"""
        import soundfile as sf  # type: ignore

        result = self._pipeline(
            prompt=prompt,
            duration=duration_seconds,
            seed=seed if seed != -1 else None,
        )
        # ACE-Step 返回 (audio_array, sample_rate) 或类似结构
        if hasattr(result, "audio"):
            audio = result.audio
            sr = result.sample_rate
        elif isinstance(result, tuple):
            audio, sr = result
        else:
            raise RuntimeError(f"Unexpected ACE-Step output type: {type(result)}")

        sf.write(str(output_path), audio, sr)

    async def _generate_via_cli(
        self,
        prompt: str,
        duration_seconds: int,
        seed: int,
        output_path: Path,
    ) -> None:
        """CLI 模式：通过子进程调用 ACE-Step"""
        cmd = [
            "python", "-m", "acestep.infer",
            "--prompt", prompt,
            "--duration", str(duration_seconds),
            "--output", str(output_path),
            "--model", self.model_path,
            "--device", self.device,
        ]
        if seed != -1:
            cmd += ["--seed", str(seed)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"ACE-Step timed out after {self.timeout}s")

        if proc.returncode != 0:
            raise RuntimeError(
                f"ACE-Step CLI failed (rc={proc.returncode}): {stderr.decode()[:500]}"
            )

    async def health(self) -> bool:
        """健康检查：模型路径存在即视为可用"""
        return Path(self.model_path).exists() or Path(self.model_path).is_dir()

    async def close(self):
        pass  # pipeline 无需显式关闭


# ── 单例 ──────────────────────────────────────────────────────────────────────
_backend: Optional[ACEStepBackend] = None


def get_bgm_backend() -> ACEStepBackend:
    global _backend
    if _backend is None:
        _backend = ACEStepBackend()
    return _backend

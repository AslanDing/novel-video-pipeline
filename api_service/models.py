"""
api_service/models.py
所有路由共享的 Pydantic 请求/响应模型
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─── 通用 ────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    elapsed_seconds: Optional[float] = None


# ─── LLM ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., description="system / user / assistant")
    content: str


class LLMRequest(BaseModel):
    messages: List[ChatMessage]
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9
    response_format: Optional[Dict[str, str]] = None  # e.g. {"type": "json_object"}
    stream: bool = False


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    content: str
    usage: LLMUsage = LLMUsage()
    model: str = ""
    finish_reason: str = "stop"


# ─── Image ───────────────────────────────────────────────────────────────────

class ImageRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 640                    # 默认640 (Z-Image-Turbo)
    height: int = 480                   # 默认480
    steps: int = 4                      # Z-Image-Turbo 推荐4步
    cfg: float = 1.0                    # Z-Image-Turbo 推荐 CFG 1.0
    seed: int = -1                      # -1 = random
    model: str = ""                      # ComfyUI checkpoint name; "" = default
    workflow: str = ""                   # ComfyUI workflow override; "" = default
    batch_size: int = 1


class GeneratedImage(BaseModel):
    url: str                          # /files/... 相对路径或 base64
    width: int
    height: int
    seed: int


class ImageResponse(BaseModel):
    task_id: str
    status: TaskStatus
    images: List[GeneratedImage] = []
    elapsed_seconds: float = 0.0


# ─── Video ───────────────────────────────────────────────────────────────────

class VideoRequest(BaseModel):
    image_url: str                    # 输入图像 URL（/files/... 或 http://）
    prompt: str = ""
    motion_prompt: str = ""
    negative_prompt: str = ""
    num_frames: int = 81              # Wan2.2 默认81帧
    fps: int = 24
    width: int = 640                  # 默认640 (Wan2.2)
    height: int = 480                 # 默认480
    seed: int = -1
    model: str = ""
    workflow: str = ""


class VideoResponse(BaseModel):
    task_id: str
    status: TaskStatus
    video_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    poll_url: Optional[str] = None


# ─── Video Synthesis ─────────────────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    video_url: str
    audio_url: str  # 通常作为 TTS 轨道
    bgm_url: Optional[str] = None  # 背景音乐轨道
    output_filename: Optional[str] = None


class SynthesizeResponse(BaseModel):
    status: str
    video_url: Optional[str] = None
    elapsed_seconds: float = 0.0


# ─── TTS ─────────────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"  # Edge TTS voice name
    rate: str = "+0%"                     # 语速调整
    pitch: str = "+0Hz"                  # 音调调整
    format: str = "mp3"                  # mp3 / wav / opus
    sample_rate: int = 44100


class TTSResponse(BaseModel):
    task_id: str
    status: TaskStatus
    audio_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0


# ─── BGM / SFX ───────────────────────────────────────────────────────────────

class BGMRequest(BaseModel):
    prompt: str
    tags: List[str] = []
    duration_seconds: int = 30
    format: str = "wav"
    seed: int = -1


class BGMResponse(BaseModel):
    task_id: str
    status: TaskStatus
    audio_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    poll_url: Optional[str] = None


# ─── Health ──────────────────────────────────────────────────────────────────

class BackendHealth(BaseModel):
    name: str
    healthy: bool
    url: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    healthy: bool
    backends: List[BackendHealth]

"""
api_service/main.py
FastAPI 应用入口

启动方式：
  cd ai-novel-video-v2
  uvicorn api_service.main:app --host 0.0.0.0 --port 9000 --reload
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api_service.backends.comfyui import get_image_backend, get_video_backend
from api_service.backends.edge_tts import get_tts_backend as get_edge_tts_backend
from api_service.backends.chat_tts import get_tts_backend as get_chat_tts_backend
from api_service.backends.nvidia_nim import get_llm_backend
from api_service.backends.ace_step import get_bgm_backend
from api_service.config import gateway_config
from api_service.models import BackendHealth, HealthResponse, TaskResult
from api_service.routers import bgm, image, llm, tts, video, projects, shots
from api_service.task_manager import get_task_manager
from api_service.logging_config import get_logger

_log = get_logger("api_gateway")

_cfg = gateway_config()
_OUTPUTS_ROOT = Path(_cfg.get("outputs_dir", "outputs")).resolve()


# ── Lifespan（启动/关闭钩子）────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """应用启动初始化"""
    _log.log_pipeline_stage(stage="api_gateway", step="startup", status="running")
    print("🚀 AI服务网关启动...")
    print(f"   输出目录: {_OUTPUTS_ROOT}")
    # 可在此预热 backend 连接
    yield
    # 关闭时清理资源
    await get_llm_backend().close()
    await get_image_backend().close()
    await get_video_backend().close()
    await get_edge_tts_backend().close()
    await get_chat_tts_backend().close()
    _log.log_pipeline_stage(stage="api_gateway", step="shutdown", status="completed")
    print("🔴 AI服务网关已关闭")


# ── 应用实例 ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Novel Video — API 服务网关",
    description=(
        "统一管理 LLM、文生图、图生视频、TTS、BGM 等 AI 推理服务。\n\n"
        "后端：\n"
        "- LLM: NVIDIA NIM (nemotron-3-super-120b-a12b)\n"
        "- Image: ComfyUI + Z-Image-Turbo (640x480)\n"
        "- Video: ComfyUI + Wan2.2 I2V (640x480)\n"
        "- TTS: Edge TTS (微软)\n"
        "- BGM/SFX: ACE-Step 1.5"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS（允许主应用跨域调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ───────────────────────────────────────────────────────────────────

app.include_router(llm.router)
app.include_router(image.router)
app.include_router(video.router)
app.include_router(tts.router)
app.include_router(bgm.router)
app.include_router(projects.router)
app.include_router(shots.router)


# ── 公共端点 ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "AI Novel Video API Gateway", "docs": "/docs"}


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """所有后端服务健康状态汇总"""
    backends = await asyncio.gather(
        _check_backend("llm (nvidia_nim)", get_llm_backend().health(), "https://integrate.api.nvidia.com"),
        _check_backend("image (comfyui)", get_image_backend().health(), "http://comfyui"),
        _check_backend("video (comfyui)", get_video_backend().health(), "http://comfyui"),
        _check_backend("tts (edge_tts)", get_edge_tts_backend().health(), "edge_tts"),
        _check_backend("tts (chat_tts)", get_chat_tts_backend().health(), "local"),
        _check_backend("bgm (comfyui-ace-step)", get_video_backend().health(), "http://comfyui"),
    )
    all_healthy = all(b.healthy for b in backends)
    return HealthResponse(healthy=all_healthy, backends=list(backends))


async def _check_backend(name: str, health_coro, url: str) -> BackendHealth:
    try:
        ok = await health_coro
        return BackendHealth(name=name, healthy=ok, url=url)
    except Exception as e:
        return BackendHealth(name=name, healthy=False, url=url, error=str(e))


@app.get("/tasks/{task_id}", response_model=TaskResult, tags=["Tasks"])
async def get_task(task_id: str) -> TaskResult:
    """通用任务状态查询（任意类型任务）"""
    mgr = get_task_manager()
    task = await mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@app.get("/files/{file_path:path}", tags=["Files"])
async def serve_file(file_path: str) -> FileResponse:
    """
    静态文件服务：提供 outputs/ 目录下生成的文件下载。
    用于主应用通过 URL 访问生成的图像、视频、音频。
    """
    # 安全检查：防止路径穿越
    target = (_OUTPUTS_ROOT / file_path).resolve()
    if not str(target).startswith(str(_OUTPUTS_ROOT)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return FileResponse(target)

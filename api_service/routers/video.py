"""
api_service/routers/video.py
图文生视频路由（Image-to-Video）

端点：
  POST /video/generate       → 提交生成任务（异步）
  POST /video/synthesize     → 合成视频+音频
  GET  /video/tasks/{id}    → 查询任务状态
  GET  /video/health         → 健康检查
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.comfyui import get_video_backend, synthesize_video
from api_service.config import gateway_config
from api_service.models import (
    TaskResult,
    TaskStatus,
    VideoRequest,
    VideoResponse,
    SynthesizeRequest,
    SynthesizeResponse,
)
from api_service.task_manager import get_task_manager
from api_service.logging_config import get_logger

router = APIRouter(prefix="/video", tags=["Video"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "videos"
_log = get_logger("video_router")


def _make_file_url(path: Path) -> str:
    try:
        rel = path.relative_to(Path(gateway_config().get("outputs_dir", "outputs")).parent)
        return f"/files/{rel}"
    except ValueError:
        return f"/files/{path.name}"


def _resolve_image_path(image_url: str) -> Path:
    """将 /files/... URL 还原为本地文件路径"""
    if image_url.startswith("/files/"):
        rel = image_url[7:]
        path = Path(rel)
        if not path.exists() and not rel.startswith("outputs/"):
            # 尝试补全 outputs/ 前缀
            alt_path = Path("outputs") / rel
            if alt_path.exists():
                return alt_path
        return path
    return Path(image_url)


async def _run_video_generation(task_id: str, req: VideoRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)
    _log.log_task_start(task_id, "video_generation", params=req.model_dump())

    try:
        backend = get_video_backend()
        image_path = _resolve_image_path(req.image_url)

        paths, actual_seed = await backend.generate_video(
            image_path=image_path,
            prompt=req.prompt,
            motion_prompt=req.motion_prompt,
            negative_prompt=req.negative_prompt,
            num_frames=req.num_frames,
            fps=req.fps,
            width=req.width,
            height=req.height,
            seed=req.seed,
            model=req.model,
            workflow_name=req.workflow,
            output_dir=_OUTPUTS_DIR,
        )
        elapsed = time.monotonic() - start

        video_url = _make_file_url(paths[0]) if paths else None
        duration = req.num_frames / req.fps if req.fps > 0 else None

        result = VideoResponse(
            task_id=task_id,
            status=TaskStatus.completed,
            video_url=video_url,
            duration_seconds=duration,
            elapsed_seconds=elapsed,
        )
        await mgr.set_completed(task_id, result.model_dump(), elapsed)
        _log.log_task_complete(task_id, "video_generation", elapsed * 1000, result=result.model_dump())
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)
        _log.log_task_complete(task_id, "video_generation", elapsed * 1000, error=str(e))


@router.post("/generate", response_model=VideoResponse)
async def generate_video(req: VideoRequest, background_tasks: BackgroundTasks) -> VideoResponse:
    """
    提交图文生视频任务（异步）。
    默认使用 Wan2.2 模型 (640x480)。
    通过 GET /video/tasks/{task_id} 轮询结果。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("vid")
    _log.log_api_request("POST", "/video/generate", task_id=task_id)
    _log.info(f"Video generation request: image={req.image_url}, prompt={req.prompt[:100]}...", task_id=task_id)

    background_tasks.add_task(_run_video_generation, task_id, req)

    return VideoResponse(
        task_id=task_id,
        status=TaskStatus.queued,
        poll_url=f"/video/tasks/{task_id}",
    )


@router.get("/tasks/{task_id}", response_model=TaskResult)
async def get_task(task_id: str) -> TaskResult:
    mgr = get_task_manager()
    task = await mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.get("/health")
async def health():
    backend = get_video_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "comfyui_i2v"}


@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize_video_endpoint(req: SynthesizeRequest) -> SynthesizeResponse:
    """合成视频和音频"""
    start = time.monotonic()
    _log.log_api_request("POST", "/video/synthesize", params=req.model_dump())

    # 路径解析（带 outputs/ 补全）
    def resolve(url: str) -> Path:
        if url.startswith("/files/"):
            rel = url[7:]
            path = Path(rel)
            if not path.exists() and not rel.startswith("outputs/"):
                alt = Path("outputs") / rel
                if alt.exists(): return alt
            return path
        return Path(url)

    video_path = resolve(req.video_url)
    audio_path = resolve(req.audio_url)
    bgm_path = resolve(req.bgm_url) if req.bgm_url else None

    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio not found: {audio_path}")
    if bgm_path and not bgm_path.exists():
        _log.warning(f"BGM path not found, skipping: {bgm_path}")
        bgm_path = None

    output_name = req.output_filename or f"synth_{video_path.stem}.mp4"
    output_dir = Path(gateway_config().get("outputs_dir", "outputs")) / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_name

    try:
        result_path = await synthesize_video(video_path, audio_path, output_path, bgm_path=bgm_path)
        elapsed = time.monotonic() - start
        return SynthesizeResponse(
            status="completed",
            video_url=_make_file_url(result_path),
            elapsed_seconds=elapsed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {e}")

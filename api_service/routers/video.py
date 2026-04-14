"""
api_service/routers/video.py
图文生视频路由（Image-to-Video）

端点：
  POST /video/generate       → 提交生成任务（异步）
  GET  /video/tasks/{id}     → 查询任务状态
  GET  /video/health         → 健康检查
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.comfyui import get_video_backend
from api_service.config import gateway_config
from api_service.models import (
    TaskResult,
    TaskStatus,
    VideoRequest,
    VideoResponse,
)
from api_service.task_manager import get_task_manager

router = APIRouter(prefix="/video", tags=["Video"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "videos"


def _make_file_url(path: Path) -> str:
    try:
        rel = path.relative_to(Path(gateway_config().get("outputs_dir", "outputs")).parent)
        return f"/files/{rel}"
    except ValueError:
        return f"/files/{path.name}"


def _resolve_image_path(image_url: str) -> Path:
    """将 /files/... URL 还原为本地文件路径"""
    if image_url.startswith("/files/"):
        # 项目根 / 去掉 /files/ 前缀后的路径
        rel = image_url[7:]  # 去掉 /files/
        return Path(rel)
    return Path(image_url)


async def _run_video_generation(task_id: str, req: VideoRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)

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
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)


@router.post("/generate", response_model=VideoResponse)
async def generate_video(req: VideoRequest, background_tasks: BackgroundTasks) -> VideoResponse:
    """
    提交图文生视频任务（异步）。
    通过 GET /video/tasks/{task_id} 轮询结果。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("vid")
    background_tasks.add_task(_run_video_generation, task_id, req)

    return VideoResponse(
        task_id=task_id,
        status=TaskStatus.queued,
        poll_url=f"/video/tasks/{task_id}",  # type: ignore[call-arg]
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

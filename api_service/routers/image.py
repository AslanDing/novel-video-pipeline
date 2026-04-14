"""
api_service/routers/image.py
文生图路由

端点：
  POST /image/generate       → 提交生成任务（同步等待或异步）
  GET  /image/tasks/{id}     → 查询任务状态
  GET  /image/models         → 列出可用模型（从 ComfyUI 查询）
  GET  /image/health         → 健康检查
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.comfyui import get_image_backend
from api_service.config import backend_config, gateway_config
from api_service.models import (
    GeneratedImage,
    ImageRequest,
    ImageResponse,
    TaskResult,
    TaskStatus,
)
from api_service.task_manager import get_task_manager

router = APIRouter(prefix="/image", tags=["Image"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "images"


def _make_file_url(path: Path) -> str:
    """将本地文件路径转为 /files/... 可访问的 URL"""
    try:
        rel = path.relative_to(Path(gateway_config().get("outputs_dir", "outputs")).parent)
        return f"/files/{rel}"
    except ValueError:
        return f"/files/{path.name}"


async def _run_image_generation(task_id: str, req: ImageRequest) -> None:
    """后台执行图像生成并更新任务状态"""
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)

    try:
        backend = get_image_backend()
        paths, actual_seed = await backend.generate_image(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            steps=req.steps,
            cfg=req.cfg,
            seed=req.seed,
            model=req.model,
            workflow_name=req.workflow,
            output_dir=_OUTPUTS_DIR,
        )
        elapsed = time.monotonic() - start

        images = [
            GeneratedImage(
                url=_make_file_url(p),
                width=req.width,
                height=req.height,
                seed=actual_seed,
            )
            for p in paths
        ]
        result = ImageResponse(
            task_id=task_id,
            status=TaskStatus.completed,
            images=images,
            elapsed_seconds=elapsed,
        )
        await mgr.set_completed(task_id, result.model_dump(), elapsed)
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)


@router.post("/generate", response_model=ImageResponse)
async def generate_image(req: ImageRequest, background_tasks: BackgroundTasks) -> ImageResponse:
    """
    提交文生图任务。
    - 立即返回 task_id。
    - 通过 GET /image/tasks/{task_id} 轮询结果。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("img")

    # 后台运行，不阻塞响应
    background_tasks.add_task(_run_image_generation, task_id, req)

    return ImageResponse(
        task_id=task_id,
        status=TaskStatus.queued,
        poll_url=f"/image/tasks/{task_id}",  # type: ignore[call-arg]
    )


@router.get("/tasks/{task_id}", response_model=TaskResult)
async def get_task(task_id: str) -> TaskResult:
    """查询图像生成任务状态"""
    mgr = get_task_manager()
    task = await mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.get("/health")
async def health():
    backend = get_image_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "comfyui"}

"""
api_service/routers/bgm.py
背景音乐/音效生成路由（ACE-Step 1.5）

端点：
  POST /bgm/generate         → 提交生成任务（异步）
  GET  /bgm/tasks/{id}       → 查询任务状态
  GET  /bgm/health           → 健康检查
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.ace_step import get_bgm_backend
from api_service.config import gateway_config
from api_service.models import (
    BGMRequest,
    BGMResponse,
    TaskResult,
    TaskStatus,
)
from api_service.task_manager import get_task_manager

router = APIRouter(prefix="/bgm", tags=["BGM"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"


def _make_file_url(path: Path) -> str:
    try:
        rel = path.relative_to(Path(gateway_config().get("outputs_dir", "outputs")).parent)
        return f"/files/{rel}"
    except ValueError:
        return f"/files/{path.name}"


async def _run_bgm_generation(task_id: str, req: BGMRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)

    try:
        backend = get_bgm_backend()
        output_path = _OUTPUTS_DIR / f"bgm_{task_id}.{req.format}"

        path = await backend.generate(
            prompt=req.prompt,
            tags=req.tags,
            duration_seconds=req.duration_seconds,
            format=req.format,
            seed=req.seed,
            output_path=output_path,
        )
        elapsed = time.monotonic() - start

        result = BGMResponse(
            task_id=task_id,
            status=TaskStatus.completed,
            audio_url=_make_file_url(path),
            duration_seconds=float(req.duration_seconds),
            elapsed_seconds=elapsed,
        )
        await mgr.set_completed(task_id, result.model_dump(), elapsed)
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)


@router.post("/generate", response_model=BGMResponse)
async def generate_bgm(req: BGMRequest, background_tasks: BackgroundTasks) -> BGMResponse:
    """
    提交背景音乐生成任务（异步）。
    通过 GET /bgm/tasks/{task_id} 轮询结果。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("bgm")
    background_tasks.add_task(_run_bgm_generation, task_id, req)

    return BGMResponse(
        task_id=task_id,
        status=TaskStatus.queued,
        poll_url=f"/bgm/tasks/{task_id}",  # type: ignore[call-arg]
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
    backend = get_bgm_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "ace_step"}

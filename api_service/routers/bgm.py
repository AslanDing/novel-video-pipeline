"""
api_service/routers/bgm.py
背景音乐/音效生成路由（ComfyUI ACE-Step）

端点：
  POST /bgm/generate         → 提交 BGM 生成任务
  GET  /bgm/tasks/{id}     → 查询任务状态
  GET  /bgm/health         → 健康检查
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.comfyui import generate_bgm
from api_service.config import gateway_config
from api_service.models import BGMRequest, BGMResponse, TaskResult, TaskStatus
from api_service.task_manager import get_task_manager
from api_service.logging_config import get_logger

router = APIRouter(prefix="/bgm", tags=["BGM"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"
_log = get_logger("bgm_router")


def _make_file_url(path: Path) -> str:
    """将本地文件路径转为 /files/... 可访问的 URL"""
    # 去掉 outputs/ 前缀（file server 根已经是 outputs）
    name = path.name
    if "audio" in str(path):
        return f"/files/audio/{name}"
    return f"/files/{name}"


async def _run_bgm_generation(task_id: str, req: BGMRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)
    _log.log_task_start(task_id, "bgm_generation", params=req.model_dump())

    try:
        output_path = _OUTPUTS_DIR / f"bgm_{task_id}.mp3"

        paths, _ = await generate_bgm(
            tags=req.prompt or "Epic: A powerful orchestral track.",
            lyrics="",
            duration=req.duration_seconds,
            seed=req.seed if req.seed != -1 else -1,
            bpm=120,
            language="en",
            keyscale="C minor",
            output_dir=_OUTPUTS_DIR,
        )

        elapsed = time.monotonic() - start

        # 取第一个生成的音频文件
        audio_path = paths[0] if paths else output_path

        result = BGMResponse(
            task_id=task_id,
            status=TaskStatus.completed,
            audio_url=_make_file_url(audio_path),
            duration_seconds=float(req.duration_seconds),
            elapsed_seconds=elapsed,
        )
        await mgr.set_completed(task_id, result.model_dump(), elapsed)
        _log.log_task_complete(task_id, "bgm_generation", elapsed * 1000, result=result.model_dump())
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)
        _log.log_task_complete(task_id, "bgm_generation", elapsed * 1000, error=str(e))


@router.post("/generate", response_model=BGMResponse)
async def generate_bgm_endpoint(req: BGMRequest, background_tasks: BackgroundTasks) -> BGMResponse:
    """
    提交 BGM 生成任务（通过 ComfyUI ACE-Step）。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("bgm")
    _log.log_api_request("POST", "/bgm/generate", task_id=task_id)
    _log.info(f"BGM generation request: prompt={req.prompt[:100]}...", task_id=task_id)
    background_tasks.add_task(_run_bgm_generation, task_id, req)

    return BGMResponse(
        task_id=task_id,
        status=TaskStatus.queued,
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
    from api_service.backends.comfyui import get_video_backend
    backend = get_video_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "comfyui-ace-step"}
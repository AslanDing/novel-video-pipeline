"""
api_service/routers/tts.py
TTS 语音合成路由（Fish Audio）

端点：
  POST /tts/synthesize       → 合成语音（同步，返回音频 URL）
  GET  /tts/voices           → 列出可用音色
  GET  /tts/health           → 健康检查
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.fish_audio import get_tts_backend
from api_service.config import gateway_config
from api_service.models import (
    TaskResult,
    TaskStatus,
    TTSRequest,
    TTSResponse,
)
from api_service.task_manager import get_task_manager

router = APIRouter(prefix="/tts", tags=["TTS"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"


def _make_file_url(path: Path) -> str:
    try:
        rel = path.relative_to(Path(gateway_config().get("outputs_dir", "outputs")).parent)
        return f"/files/{rel}"
    except ValueError:
        return f"/files/{path.name}"


def _estimate_duration(text: str) -> float:
    """简单估算中文 TTS 时长（约 3.5 字/秒）"""
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return chinese_chars / 3.5 + other_chars / 10.0


async def _run_tts(task_id: str, req: TTSRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)

    try:
        backend = get_tts_backend()
        output_path = _OUTPUTS_DIR / f"tts_{task_id}.{req.format}"

        path = await backend.synthesize(
            text=req.text,
            reference_id=req.reference_id,
            speed=req.speed,
            format=req.format,
            output_path=output_path,
        )
        elapsed = time.monotonic() - start
        duration = _estimate_duration(req.text)

        result = TTSResponse(
            task_id=task_id,
            status=TaskStatus.completed,
            audio_url=_make_file_url(path),
            duration_seconds=duration,
            elapsed_seconds=elapsed,
        )
        await mgr.set_completed(task_id, result.model_dump(), elapsed)
    except Exception as e:
        elapsed = time.monotonic() - start
        await mgr.set_failed(task_id, str(e), elapsed)


@router.post("/synthesize", response_model=TTSResponse)
async def synthesize(req: TTSRequest, background_tasks: BackgroundTasks) -> TTSResponse:
    """
    提交 TTS 合成任务。
    通过 GET /tasks/{task_id} 轮询结果。
    """
    mgr = get_task_manager()
    task_id = await mgr.create_task("tts")
    background_tasks.add_task(_run_tts, task_id, req)

    return TTSResponse(
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


@router.get("/voices")
async def list_voices():
    """列出 Fish Audio 可用音色"""
    backend = get_tts_backend()
    voices = await backend.list_voices()
    return {"voices": voices}


@router.get("/health")
async def health():
    backend = get_tts_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "fish_audio"}

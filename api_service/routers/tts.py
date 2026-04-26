"""
api_service/routers/tts.py
TTS 语音合成路由

端点：
  POST /tts/synthesize       → 合成语音（同步，返回音频 URL）
  GET  /tts/voices           → 列出可用音色
  GET  /tts/health           → 健康检查
  GET  /tts/backends         → 获取可用后端列表
  POST /tts/switch           → 切换 TTS 后端
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api_service.backends.edge_tts import EdgeTTS_Backend, get_tts_backend as get_edge_backend
from api_service.backends.chat_tts import ChatTTSBackend, get_tts_backend as get_chat_backend
from api_service.config import gateway_config, backend_config
from api_service.models import (
    TaskResult,
    TaskStatus,
    TTSRequest,
    TTSResponse,
)
from api_service.task_manager import get_task_manager

router = APIRouter(prefix="/tts", tags=["TTS"])

_OUTPUTS_DIR = Path(gateway_config().get("outputs_dir", "outputs")) / "audio"

# 当前激活的后端: "edge_tts" 或 "chat_tts"
_current_backend: str = backend_config("tts").get("backend", "edge_tts")


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


def _get_active_backend():
    """获取当前激活的 TTS 后端"""
    global _current_backend
    if _current_backend == "chat_tts":
        return get_chat_backend()
    return get_edge_backend()


async def _run_tts(task_id: str, req: TTSRequest) -> None:
    mgr = get_task_manager()
    start = time.monotonic()
    await mgr.set_running(task_id)

    try:
        backend = _get_active_backend()
        output_path = _OUTPUTS_DIR / f"tts_{task_id}.{req.format}"

        path = await backend.synthesize(
            text=req.text,
            voice=req.voice,
            rate=req.rate,
            pitch=req.pitch,
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
    """列出当前 TTS 后端的可用音色"""
    backend = _get_active_backend()
    voices = await backend.list_voices()
    return {"voices": voices, "backend": _current_backend}


@router.get("/backends")
async def list_backends():
    """获取可用 TTS 后端列表"""
    backends = []
    try:
        edge = get_edge_backend()
        edge_ok = await edge.health()
        backends.append({"name": "edge_tts", "healthy": edge_ok, "active": _current_backend == "edge_tts"})
    except Exception:
        backends.append({"name": "edge_tts", "healthy": False, "active": False})

    try:
        chat = get_chat_backend()
        chat_ok = await chat.health()
        backends.append({"name": "chat_tts", "healthy": chat_ok, "active": _current_backend == "chat_tts"})
    except Exception:
        backends.append({"name": "chat_tts", "healthy": False, "active": False})

    return {"backends": backends, "current": _current_backend}


@router.post("/switch")
async def switch_backend(backend_name: str):
    """切换 TTS 后端"""
    global _current_backend
    if backend_name not in ("edge_tts", "chat_tts"):
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend_name}")

    _current_backend = backend_name

    # 更新配置文件
    import json
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent / "config" / "api_services.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config["backends"]["tts"]["backend"] = backend_name
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return {"message": f"Switched to {backend_name}", "current_backend": _current_backend}


@router.get("/health")
async def health():
    backend = _get_active_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": _current_backend}
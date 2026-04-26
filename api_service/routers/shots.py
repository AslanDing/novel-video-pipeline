"""
api_service/routers/shots.py
镜头管理端点

实现 Shot Spec (Layer 3 配置) 的 API 接口。
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, List
from pydantic import BaseModel, Field

import sys

sys.path.append(str(Path(__file__).parent.parent))

from api_service.models import TaskStatus, TaskResult
from core.config_models import ShotSpec, VideoMode, ShotStatus

router = APIRouter(prefix="/shots", tags=["Shots"])


# ─── Request/Response Models ──────────────────────────────────────────────────


class ShotSpecUpdate(BaseModel):
    """镜头规格更新"""

    workflow: Optional[str] = None
    purpose: Optional[str] = None
    shot_type: Optional[str] = None
    mood: Optional[str] = None
    dialogue: Optional[str] = None
    narrator: Optional[str] = None
    needs_character_consistency: Optional[bool] = None
    needs_scene_consistency: Optional[bool] = None
    video_mode: Optional[str] = None
    status: Optional[str] = None


class ShotSpecResponse(BaseModel):
    """镜头规格响应"""

    shot_id: str
    chapter_id: str
    workflow: str
    purpose: str
    characters: List[str]
    scene: str
    shot_type: str
    mood: str
    dialogue: Optional[str]
    narrator: Optional[str]
    needs_character_consistency: bool
    needs_scene_consistency: bool
    video_mode: str
    status: str
    result_image: Optional[str]
    result_video: Optional[str]


class RerenderRequest(BaseModel):
    """重新渲染请求"""

    shot_id: str
    regenerate_assets: bool = Field(default=False, description="是否重新生成资产")


class RerenderResponse(BaseModel):
    """重新渲染响应"""

    task_id: str
    shot_id: str
    status: str
    message: str


# ─── Shot Endpoints ────────────────────────────────────────────────────────────


@router.get("/{shot_id}", response_model=ShotSpecResponse)
async def get_shot(shot_id: str) -> ShotSpecResponse:
    """
    获取镜头规格

    从对应的 Chapter Manifest 中加载 Shot Spec。
    """
    # 解析 shot_id (格式: ch01_sh01)
    parts = shot_id.split("_")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid shot_id format")

    chapter_id = parts[0]  # ch01
    chapter_num = int(chapter_id.replace("ch", ""))

    from config.settings import OUTPUTS_DIR
    from core.storage import ProjectStorage
    from core.config_models import ChapterManifest

    # 搜索项目目录
    outputs_dir = Path(OUTPUTS_DIR)

    for project_dir in outputs_dir.iterdir():
        if not project_dir.is_dir():
            continue

        manifest_path = (
            project_dir / "data" / "chapter_manifests" / f"{chapter_id}_manifest.json"
        )
        if manifest_path.exists():
            manifest = ChapterManifest.load(manifest_path)

            # 在 manifest 中查找 shot
            # 注意：ShotSpec 存储在 manifest 的 shots 列表中
            # 这里简化处理，实际应该从单独的文件加载

            # 返回占位响应
            return ShotSpecResponse(
                shot_id=shot_id,
                chapter_id=chapter_id,
                workflow="character_closeup_i2v_v1",
                purpose="",
                characters=[],
                scene="",
                shot_type="medium",
                mood="neutral",
                dialogue=None,
                narrator=None,
                needs_character_consistency=True,
                needs_scene_consistency=True,
                video_mode="i2v",
                status="pending",
                result_image=None,
                result_video=None,
            )

    raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found")


@router.put("/{shot_id}", response_model=ShotSpecResponse)
async def update_shot(
    shot_id: str,
    updates: ShotSpecUpdate,
) -> ShotSpecResponse:
    """
    更新镜头规格

    修改 Shot Spec (Layer 3 配置) 的参数。
    """
    # 解析 shot_id
    parts = shot_id.split("_")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid shot_id format")

    chapter_id = parts[0]

    # TODO: 实现实际的更新逻辑
    # 目前返回占位响应
    return ShotSpecResponse(
        shot_id=shot_id,
        chapter_id=chapter_id,
        workflow=updates.workflow or "character_closeup_i2v_v1",
        purpose=updates.purpose or "",
        characters=[],
        scene=updates.scene if hasattr(updates, "scene") else "",
        shot_type=updates.shot_type or "medium",
        mood=updates.mood or "neutral",
        dialogue=updates.dialogue,
        narrator=updates.narrator,
        needs_character_consistency=updates.needs_character_consistency
        if updates.needs_character_consistency is not None
        else True,
        needs_scene_consistency=updates.needs_scene_consistency
        if updates.needs_scene_consistency is not None
        else True,
        video_mode=updates.video_mode or "i2v",
        status=updates.status or "pending",
        result_image=None,
        result_video=None,
    )


@router.post("/{shot_id}/rerender", response_model=RerenderResponse)
async def rerender_shot(
    shot_id: str,
    request: RerenderRequest,
    background_tasks: BackgroundTasks,
) -> RerenderResponse:
    """
    重新渲染单个镜头

    触发单个镜头的重新生成。
    """
    # 解析 shot_id
    parts = shot_id.split("_")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid shot_id format")

    chapter_id = parts[0]  # ch01
    chapter_num = int(chapter_id.replace("ch", ""))

    # 创建任务
    from api_service.task_manager import get_task_manager

    task_manager = get_task_manager()

    task = await task_manager.create_task(
        task_type="rerender_shot",
        params={
            "shot_id": shot_id,
            "chapter_number": chapter_num,
            "regenerate_assets": request.regenerate_assets,
        },
    )

    # 启动后台任务
    background_tasks.add_task(
        _run_rerender_background,
        shot_id=shot_id,
        regenerate_assets=request.regenerate_assets,
        task_id=task.task_id,
    )

    return RerenderResponse(
        task_id=task.task_id,
        shot_id=shot_id,
        status="queued",
        message=f"重新渲染任务已创建: {shot_id}",
    )


async def _run_rerender_background(
    shot_id: str,
    regenerate_assets: bool,
    task_id: str,
):
    """后台运行重新渲染任务"""
    from api_service.task_manager import get_task_manager
    from config.settings import OUTPUTS_DIR
    from pathlib import Path

    task_manager = get_task_manager()

    try:
        await task_manager.update_task(task_id, TaskStatus.running, {})

        # 解析 shot_id
        parts = shot_id.split("_")
        chapter_id = parts[0]
        chapter_num = int(chapter_id.replace("ch", ""))

        # 搜索项目目录
        outputs_dir = Path(OUTPUTS_DIR)
        project_dir = None
        for pdir in outputs_dir.iterdir():
            if pdir.is_dir():
                manifest_path = (
                    pdir / "data" / "chapter_manifests" / f"{chapter_id}_manifest.json"
                )
                if manifest_path.exists():
                    project_dir = pdir
                    break

        if not project_dir:
            raise Exception(f"Project not found for shot {shot_id}")

        # TODO: 实现实际的重新渲染逻辑
        # 1. 如果 regenerate_assets，重新生成角色/场景资产
        # 2. 重新生成关键帧
        # 3. 重新生成视频

        print(f"Re-rendering shot {shot_id} (regenerate_assets={regenerate_assets})")

        await task_manager.update_task(
            task_id,
            TaskStatus.completed,
            {
                "shot_id": shot_id,
            },
        )

    except Exception as e:
        await task_manager.update_task(
            task_id,
            TaskStatus.failed,
            {
                "error": str(e),
            },
        )


# ─── Bulk Operations ────────────────────────────────────────────────────────────


@router.post("/bulk/rerender")
async def bulk_rerender_shots(
    shot_ids: List[str],
    regenerate_assets: bool = False,
) -> dict:
    """
    批量重新渲染多个镜头
    """
    from api_service.task_manager import get_task_manager

    task_manager = get_task_manager()

    tasks = []
    for shot_id in shot_ids:
        task = await task_manager.create_task(
            task_type="rerender_shot",
            params={
                "shot_id": shot_id,
                "regenerate_assets": regenerate_assets,
            },
        )
        tasks.append(
            {
                "shot_id": shot_id,
                "task_id": task.task_id,
            }
        )

    return {
        "total": len(shot_ids),
        "tasks": tasks,
    }


from pathlib import Path

"""
api_service/routers/projects.py
项目管理和渲染端点

实现三层配置模型的 API 接口。
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, List
from pydantic import BaseModel, Field

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.storage import ProjectStorage, create_project_storage
from core.config_models import (
    ProjectPreset, ChapterManifest, ShotSpec,
    create_default_project_preset, VideoMode, ShotStatus
)
from api_service.models import TaskStatus, TaskResult

router = APIRouter(prefix="/projects", tags=["Projects"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    """创建项目请求"""
    title: str = Field(..., description="项目标题")
    genre: str = Field(default="修仙", description="小说类型")
    visual_style: str = Field(default="cinematic", description="视觉风格")
    total_chapters: int = Field(default=3, description="总章节数")


class ProjectResponse(BaseModel):
    """项目响应"""
    project_id: str
    title: str
    genre: str
    visual_style: str
    status: str


class ChapterManifestResponse(BaseModel):
    """章节清单响应"""
    chapter_id: str
    chapter_number: int
    project_id: str
    scene_order: List[str]
    characters_involved: List[str]
    shots: List[str]
    status: str


class RenderRequest(BaseModel):
    """渲染请求"""
    chapter_number: int = Field(..., description="章节号")
    force_regenerate: bool = Field(default=False, description="是否强制重新生成")


class RenderResponse(BaseModel):
    """渲染响应"""
    task_id: str
    chapter_number: int
    status: str
    message: str


# ─── Project Endpoints ────────────────────────────────────────────────────────

@router.post("/create", response_model=ProjectResponse)
async def create_project(request: CreateProjectRequest) -> ProjectResponse:
    """
    创建新项目

    创建项目目录结构和 Project Preset (Layer 1 配置)。
    """
    from config.settings import OUTPUTS_DIR

    # 生成项目ID (使用标题的拼音或slug)
    project_id = request.title.replace(" ", "_")

    # 创建项目存储
    storage = create_project_storage(
        project_id=project_id,
        title=request.title,
        genre=request.genre,
        base_dir=OUTPUTS_DIR,
    )

    # 创建项目预设
    preset = create_default_project_preset(
        project_id=project_id,
        title=request.title,
        genre=request.genre,
    )
    preset.visual_style = request.visual_style
    preset.save(storage.get_project_dir())

    return ProjectResponse(
        project_id=project_id,
        title=request.title,
        genre=request.genre,
        visual_style=request.visual_style,
        status="created",
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """
    获取项目信息
    """
    from config.settings import OUTPUTS_DIR

    storage = ProjectStorage(project_id, OUTPUTS_DIR)

    if not storage.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    preset_path = storage.get_project_preset_path()
    if not preset_path.exists():
        raise HTTPException(status_code=404, detail=f"Project preset not found")

    preset = ProjectPreset.load(storage.get_project_dir())

    return ProjectResponse(
        project_id=project_id,
        title=preset.title,
        genre=preset.genre,
        visual_style=preset.visual_style,
        status="active",
    )


@router.get("/{project_id}/assets")
async def get_project_assets(project_id: str) -> dict:
    """
    获取项目资产清单

    返回角色包和场景包的列表。
    """
    from config.settings import OUTPUTS_DIR

    storage = ProjectStorage(project_id, OUTPUTS_DIR)

    if not storage.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    characters = storage.list_characters()
    scenes = storage.list_scenes()
    chapters = storage.list_chapters()

    return {
        "project_id": project_id,
        "characters": characters,
        "scenes": scenes,
        "chapters": chapters,
    }


# ─── Chapter Manifest Endpoints ────────────────────────────────────────────────

@router.post("/{project_id}/chapters/{chapter_number}/manifest", response_model=ChapterManifestResponse)
async def generate_chapter_manifest(
    project_id: str,
    chapter_number: int,
) -> ChapterManifestResponse:
    """
    生成章节清单

    创建 Chapter Manifest (Layer 2 配置)，包含场景顺序、角色列表、镜头列表。
    """
    from config.settings import OUTPUTS_DIR

    storage = ProjectStorage(project_id, OUTPUTS_DIR)

    if not storage.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # 加载项目预设
    preset = ProjectPreset.load(storage.get_project_dir())

    # 加载故事蓝图
    blueprint_path = storage.get_story_bible_path()
    if not blueprint_path.exists():
        raise HTTPException(status_code=400, detail="Story bible not found, please generate novel first")

    import json
    with open(blueprint_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    blueprint_data = data.get("blueprint", {})
    characters_data = blueprint_data.get("characters", [])
    chapter_plans = blueprint_data.get("chapter_plans", [])

    # 获取本章的角色
    chapter_plan = None
    for plan in chapter_plans:
        if plan.get("number") == chapter_number:
            chapter_plan = plan
            break

    # 提取场景
    scene_order = _extract_scenes_from_chapter(storage, chapter_number)

    # 提取角色
    characters_involved = [c.get("name", "") for c in characters_data[:5]]

    # 生成 shot ID 列表
    shots = [f"ch{chapter_number:02d}_sh{i:02d}" for i in range(1, 9)]

    # 创建章节清单
    manifest = ChapterManifest(
        chapter_id=f"ch{chapter_number:02d}",
        project_id=project_id,
        chapter_number=chapter_number,
        scene_order=scene_order,
        characters_involved=characters_involved,
        required_assets=[],  # TODO: 填充资产列表
        shots=shots,
        tts_required=True,
        estimated_duration=180.0,
        status="pending",
    )

    # 保存
    manifest_path = storage.get_chapter_manifest_path(manifest.chapter_id)
    manifest.save(manifest_path.parent)

    return ChapterManifestResponse(
        chapter_id=manifest.chapter_id,
        chapter_number=chapter_number,
        project_id=project_id,
        scene_order=scene_order,
        characters_involved=characters_involved,
        shots=shots,
        status="created",
    )


@router.get("/{project_id}/chapters/{chapter_number}/manifest")
async def get_chapter_manifest(
    project_id: str,
    chapter_number: int,
) -> ChapterManifestResponse:
    """
    获取章节清单
    """
    from config.settings import OUTPUTS_DIR

    storage = ProjectStorage(project_id, OUTPUTS_DIR)
    chapter_id = f"ch{chapter_number:02d}"
    manifest_path = storage.get_chapter_manifest_path(chapter_id)

    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail=f"Chapter manifest not found")

    manifest = ChapterManifest.load(manifest_path)

    return ChapterManifestResponse(
        chapter_id=manifest.chapter_id,
        chapter_number=manifest.chapter_number,
        project_id=manifest.project_id,
        scene_order=manifest.scene_order,
        characters_involved=manifest.characters_involved,
        shots=manifest.shots,
        status=manifest.status,
    )


# ─── Render Endpoint ──────────────────────────────────────────────────────────

@router.post("/{project_id}/render", response_model=RenderResponse)
async def render_chapter(
    project_id: str,
    request: RenderRequest,
    background_tasks: BackgroundTasks,
) -> RenderResponse:
    """
    渲染章节

    这是主要的渲染端点，会触发整个 Phase 2 工作流。
    """
    from config.settings import OUTPUTS_DIR
    from api_service.task_manager import get_task_manager

    storage = ProjectStorage(project_id, OUTPUTS_DIR)

    if not storage.exists():
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # 创建任务
    task_manager = get_task_manager()
    task = await task_manager.create_task(
        task_type="render_chapter",
        params={
            "project_id": project_id,
            "chapter_number": request.chapter_number,
            "force_regenerate": request.force_regenerate,
        }
    )

    # 启动后台任务
    background_tasks.add_task(
        _run_render_background,
        project_id=project_id,
        chapter_number=request.chapter_number,
        force_regenerate=request.force_regenerate,
        task_id=task.task_id,
    )

    return RenderResponse(
        task_id=task.task_id,
        chapter_number=request.chapter_number,
        status="queued",
        message=f"渲染任务已创建: 第 {request.chapter_number} 章",
    )


async def _run_render_background(
    project_id: str,
    chapter_number: int,
    force_regenerate: bool,
    task_id: str,
):
    """后台运行渲染任务"""
    from api_service.task_manager import get_task_manager
    from config.settings import OUTPUTS_DIR

    storage = ProjectStorage(project_id, OUTPUTS_DIR)
    task_manager = get_task_manager()

    try:
        await task_manager.update_task(task_id, TaskStatus.running, {})

        # 导入并运行流水线
        from run_pipeline import AssetFirstPipeline

        pipeline = AssetFirstPipeline(project_id)
        await pipeline._run_phase_2(chapter_number)

        await task_manager.update_task(task_id, TaskStatus.completed, {
            "chapter_number": chapter_number,
        })

    except Exception as e:
        await task_manager.update_task(task_id, TaskStatus.failed, {
            "error": str(e),
        })


# ─── Helper Functions ──────────────────────────────────────────────────────────

def _extract_scenes_from_chapter(storage: ProjectStorage, chapter_number: int) -> List[str]:
    """从章节内容中提取场景列表"""
    content = storage.load_chapter_content(chapter_number)

    # 常见场景关键词
    scene_keywords = [
        "酒馆", "客栈", "山洞", "森林", "山顶", "悬崖", "大殿",
        "广场", "街道", "小巷", "皇宫", "宗门", "修炼场", "书房",
        "卧室", "厨房", "花园", "湖边", "河边", "海边", "沙漠",
    ]

    scenes = []
    for keyword in scene_keywords:
        if keyword in content and keyword not in scenes:
            scenes.append(keyword)

    return scenes if scenes else ["默认场景"]


from pathlib import Path

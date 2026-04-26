#!/usr/bin/env python3
"""
Pipeline Runner - 主编排器

完整流程: 小说生成 → 分镜脚本 → 图像生成 → TTS音频 → 视频合成

所有 AI 服务通过以下方式调用:
  - Mock 模式 (默认): 直接调用现有 stage 类，不依赖外部服务
  - API 模式: 通过 FastAPI 网关调用 (需要 api_service 运行)

设计原则:
  - Prompt 与代码分离: 所有提示词从 config/prompts.json 读取
  - 中间结果保留: 每个阶段的结果都保存到 outputs/ 目录
  - 可断点续跑: 每个阶段独立，检查已完成的阶段跳过

用法:
    # Mock 模式 (默认，不依赖外部服务)
    python run_pipeline.py --project-id "test_project" --genre 修仙 --chapters 3

    # API 模式 (需要启动 api_service)
    python run_pipeline.py --project-id "test_project" --use-api --api-url http://localhost:9000

    # 单独阶段
    python run_pipeline.py --project-id "test_project" --phase 1
    python run_pipeline.py --project-id "test_project" --phase 2
    python run_pipeline.py --project-id "test_project" --phase 3
"""

import asyncio
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

try:
    from core.api_client import NovelAPIClient
except ImportError:
    NovelAPIClient = None

# ============================================================
# 基础配置
# ============================================================

OUTPUTS_DIR = Path("outputs")
NOVELS_DIR = OUTPUTS_DIR / "novels"
IMAGES_DIR = OUTPUTS_DIR / "images"
AUDIO_DIR = OUTPUTS_DIR / "audio"
VIDEOS_DIR = OUTPUTS_DIR / "videos"


# ============================================================
# 数据模型
# ============================================================

class PhaseStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseResult:
    """阶段执行结果"""
    phase: int
    name: str
    status: PhaseStatus
    duration_seconds: float = 0.0
    output_path: Optional[Path] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "name": self.name,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "output_path": str(self.output_path) if self.output_path else None,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class PipelineContext:
    """流水线上下文，贯穿所有阶段"""
    project_id: str
    genre: str
    chapters: int
    words_per_chapter: int
    core_idea: str
    created_at: datetime = field(default_factory=datetime.now)
    style: str = "爽文"
    shuangdian_intensity: str = "high"
    use_streaming: bool = True

    # 各阶段输出路径
    project_dir: Path = field(init=False)
    novel_dir: Path = field(init=False)
    data_dir: Path = field(init=False)
    scripts_dir: Path = field(init=False)
    images_dir: Path = field(init=False)
    audio_dir: Path = field(init=False)
    videos_dir: Path = field(init=False)

    def __post_init__(self):
        self.project_dir = NOVELS_DIR / self.project_id
        self.novel_dir = self.project_dir
        self.data_dir = self.project_dir / "data"
        self.scripts_dir = self.data_dir / "scripts"
        self.images_dir = IMAGES_DIR / self.project_id
        self.audio_dir = AUDIO_DIR / self.project_id
        self.videos_dir = VIDEOS_DIR / self.project_id

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "genre": self.genre,
            "chapters": self.chapters,
            "words_per_chapter": self.words_per_chapter,
            "core_idea": self.core_idea,
            "style": self.style,
            "shuangdian_intensity": self.shuangdian_intensity,
            "use_streaming": self.use_streaming,
            "created_at": self.created_at.isoformat(),
            "paths": {
                "project_dir": str(self.project_dir),
                "novel_dir": str(self.novel_dir),
                "data_dir": str(self.data_dir),
                "scripts_dir": str(self.scripts_dir),
                "images_dir": str(self.images_dir),
                "audio_dir": str(self.audio_dir),
                "videos_dir": str(self.videos_dir),
            }
        }

    def save(self):
        """保存上下文到项目目录"""
        self.project_dir.mkdir(parents=True, exist_ok=True)
        context_path = self.project_dir / "pipeline_context.json"
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return context_path

    @classmethod
    def load(cls, project_id: str) -> Optional["PipelineContext"]:
        """从项目目录加载上下文"""
        context_path = NOVELS_DIR / project_id / "pipeline_context.json"
        if not context_path.exists():
            return None
        with open(context_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ctx = cls(
            project_id=data["project_id"],
            genre=data["genre"],
            chapters=data["chapters"],
            words_per_chapter=data["words_per_chapter"],
            core_idea=data["core_idea"],
        )
        ctx.created_at = datetime.fromisoformat(data["created_at"])
        return ctx


# ============================================================
# Mock API 客户端 (用于不依赖外部服务)
# ============================================================

class MockAPIClient:
    """
    Mock API 客户端 - 模拟 API 服务响应

    用于开发和测试，不依赖外部服务。
    实际调用底层的 stage 类。
    """

    def __init__(self, context: PipelineContext):
        self.context = context
        self._mock_mode = True
        self.base_url = "http://localhost"

    # ── LLM ──────────────────────────────────────────────────

    async def llm_generate(
        self,
        messages: List[Dict],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Optional[Dict] = None,
    ) -> Dict:
        """
        Mock LLM 生成
        直接复用 NovelGenerator 的 LLM 调用逻辑
        """
        from core.llm_client import NVIDIA_NIM_Client
        from utils.streaming_json_generator import robust_json_generate

        # 提取最后一条 user 消息
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg["content"]
                break

        if not user_content:
            return {"content": "", "usage": {"total_tokens": 0}}

        # 构建 system prompt
        system_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
                break

        # 调用 LLM
        llm_client = NVIDIA_NIM_Client()
        try:
            if response_format and response_format.get("type") == "json_object":
                result, _ = await robust_json_generate(
                    llm_client=llm_client,
                    prompt=user_content,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    required_fields=[],
                    max_attempts=2,
                    response_format=response_format,
                )
                content = json.dumps(result, ensure_ascii=False) if result else ""
            else:
                response = await llm_client.generate(
                    prompt=user_content,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                )
                content = response.content if hasattr(response, "content") else str(response)
        finally:
            await llm_client.close()

        return {
            "content": content,
            "usage": {"total_tokens": len(content) // 4},
        }

    async def llm_stream(self, messages: List[Dict], **kwargs) -> str:
        """Mock LLM 流式生成"""
        result = await self.llm_generate(messages, **kwargs)
        return result.get("content", "")

    # ── Image ────────────────────────────────────────────────

    async def image_generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 640,
        height: int = 480,
        **kwargs,
    ) -> str:
        """
        Mock 图像生成
        保存 prompt 到缓存目录，实际生成由 stage2 完成
        """
        task_id = f"img_{uuid.uuid4().hex[:8]}"

        # 保存 prompt 到缓存
        cache_dir = self.context.images_dir / ".prompt_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / f"{task_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "kwargs": kwargs,
                "created_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

        return task_id

    async def image_wait(self, task_id: str, **kwargs) -> Dict:
        """Mock 等待图像生成 - 返回缓存的 prompt 信息"""
        cache_dir = self.context.images_dir / ".prompt_cache"
        cache_file = cache_dir / f"{task_id}.json"

        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "status": "completed",
                "images": [{
                    "url": f"/files/{self.context.images_dir.name}/prompt_cache/{task_id}.json",
                    "width": data.get("width", 640),
                    "height": data.get("height", 480),
                    "seed": -1,
                }],
            }

        return {"status": "completed", "images": []}

    # ── TTS ─────────────────────────────────────────────────

    async def tts_synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        **kwargs,
    ) -> str:
        """Mock TTS 合成"""
        task_id = f"tts_{uuid.uuid4().hex[:8]}"

        # 保存文本到缓存
        cache_dir = self.context.audio_dir / ".text_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / f"{task_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "text": text,
                "voice": voice,
                "kwargs": kwargs,
                "created_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

        return task_id

    async def tts_wait(self, task_id: str, **kwargs) -> Dict:
        """Mock 等待 TTS 完成"""
        return {
            "status": "completed",
            "audio_url": f"/files/{self.context.audio_dir.name}/.text_cache/{task_id}.json",
            "duration_seconds": 5.0,
        }

    # ── Video ────────────────────────────────────────────────

    async def video_generate(self, image_url: str, **kwargs) -> str:
        """Mock 视频生成"""
        task_id = f"vid_{uuid.uuid4().hex[:8]}"
        return task_id

    async def video_wait(self, task_id: str, **kwargs) -> Dict:
        """Mock 等待视频完成"""
        return {
            "status": "completed",
            "video_url": f"/mock_video_{task_id}.mp4",
            "duration_seconds": 3.0,
        }

    # ── Health ───────────────────────────────────────────────

    async def full_health(self) -> Dict:
        """Mock 健康检查"""
        return {
            "healthy": True,
            "backends": [
                {"name": "llm", "healthy": True},
                {"name": "image", "healthy": True},
                {"name": "tts", "healthy": True},
                {"name": "video", "healthy": True},
            ]
        }



# ============================================================
# 真实 API 客户端
# ============================================================

class APIClient:
    """
    真实 API 客户端 - 封装 NovelAPIClient 并提供与 MockAPIClient 兼容的接口
    """

    def __init__(self, base_url: str):
        if NovelAPIClient is None:
            raise ImportError("无法导入 core.api_client.NovelAPIClient，请检查文件是否存在")
        self.base_url = base_url
        self._client = NovelAPIClient(base_url=base_url)

    async def close(self):
        await self._client.close()

    # ── LLM ──────────────────────────────────────────────────

    async def generate(self, *args, **kwargs):
        """兼容 NovelGenerator/ScriptGenerator 的 generate 接口"""
        return await self._client.llm_generate(*args, **kwargs)

    async def llm_generate(self, messages: List[Dict], **kwargs) -> Dict:
        """兼容 MockAPIClient 的 llm_generate 接口"""
        # 提取 system_prompt 和 user prompt
        system_prompt = next((m["content"] for m in messages if m["role"] == "system"), None)
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")

        res = await self._client.llm_generate(
            prompt=user_content,
            system_prompt=system_prompt,
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", 0.7),
            response_format=kwargs.get("response_format")
        )
        return {
            "content": res.content,
            "usage": res.usage
        }

    # ── Image ────────────────────────────────────────────────

    async def image_generate(self, **kwargs) -> str:
        """兼容 MockAPIClient 的接口，返回 task_id"""
        kwargs["wait"] = False
        res = await self._client.image_generate(**kwargs)
        return res.task_id

    async def image_wait(self, task_id: str, **kwargs) -> Dict:
        """兼容 MockAPIClient 的接口"""
        timeout = kwargs.get("timeout", 600)
        res = await self._client.wait_for_task(task_id, poll_url=f"/image/tasks/{task_id}", max_wait_seconds=timeout)
        return {
            "status": res.status,
            "images": res.result.get("images", []) if res.result else []
        }

    # ── TTS ──────────────────────────────────────────────────

    async def tts_synthesize(self, **kwargs) -> str:
        """兼容 MockAPIClient 的接口，返回 task_id"""
        kwargs["wait"] = False
        res = await self._client.tts_synthesize(**kwargs)
        return res.task_id

    async def tts_wait(self, task_id: str, **kwargs) -> Dict:
        """兼容 MockAPIClient 的接口"""
        res = await self._client.wait_for_task(task_id, poll_url=f"/tts/tasks/{task_id}")
        return {
            "status": res.status,
            "audio_url": res.result.get("audio_url") if res.result else None,
            "duration_seconds": res.result.get("duration_seconds") if res.result else 0
        }

    # ── Video ────────────────────────────────────────────────

    async def video_generate(self, **kwargs) -> str:
        """兼容 MockAPIClient 的接口，返回 task_id"""
        kwargs["wait"] = False
        res = await self._client.video_generate(**kwargs)
        return res.task_id

    async def video_wait(self, task_id: str, **kwargs) -> Dict:
        """兼容 MockAPIClient 的接口"""
        timeout = kwargs.get("timeout", 1800)
        res = await self._client.wait_for_task(task_id, poll_url=f"/video/tasks/{task_id}", max_wait_seconds=timeout)
        return {
            "status": res.status,
            "video_url": res.result.get("video_url") if res.result else None,
            "duration_seconds": res.result.get("duration_seconds") if res.result else 0
        }

    async def full_health(self) -> Dict:
        """健康检查"""
        try:
            health = await self._client.health()
            return {"healthy": health.get("healthy", False), "backends": health.get("backends", [])}
        except:
            return {"healthy": False, "backends": []}


# ============================================================
# 提示词管理器
# ============================================================

class PromptManager:
    """提示词管理器 - 从配置文件加载"""

    def __init__(self, prompts_file: Optional[Path] = None):
        if prompts_file is None:
            prompts_file = Path(__file__).parent / "config" / "prompts.json"

        self.prompts_file = prompts_file
        self._prompts: Dict = {}
        self._load()

    def _load(self):
        """加载提示词配置"""
        if self.prompts_file.exists():
            with open(self.prompts_file, "r", encoding="utf-8") as f:
                self._prompts = json.load(f)
        else:
            print(f"⚠️  提示词配置文件不存在: {self.prompts_file}")
            self._prompts = {"stage1": {}, "stage2": {}}

    def get(self, key: str, default: str = "") -> str:
        """获取提示词，支持点号分隔的路径"""
        keys = key.split(".")
        value = self._prompts
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, "")
            else:
                return default
        return value if value else default

    def format(self, key: str, **kwargs) -> str:
        """获取并格式化提示词"""
        template = self.get(key)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            print(f"⚠️  提示词格式化失败，缺少参数: {e}")
            return template


# ============================================================
# Mock 数据生成器
# ============================================================

def generate_mock_novel_data(context: PipelineContext) -> Dict:
    """
    生成模拟小说数据 (用于测试流程)

    生成完整的 story_bible.json 和章节内容，
    以便测试后续的 分镜脚本 → 图像 → TTS 流程。
    """
    print(f"   ⚠️  使用 Mock 模式生成示例小说数据")

    # 模拟的世界观
    world_building = {
        "setting": "这是一个神秘的修仙世界，天地灵气充沛，修士林立。主角林凡是一个普通的都市青年，意外获得上古传承，开启了修仙之路。",
        "power_system": "修炼分为炼气、筑基、金丹、元婴、化神等境界。每境九层，突破需要感悟天地灵气。",
        "factions": [
            {"name": "青云宗", "description": "正道领袖，主角入门宗门", "type": "正"},
            {"name": "魔道联盟", "description": "反派势力，与主角为敌", "type": "邪"},
        ],
        "rules": ["修士不可屠戮凡人", "宗门之争不得波及世俗"]
    }

    # 模拟角色
    characters = [
        {
            "id": "linfan",
            "name": "林凡",
            "role": "protagonist",
            "description": "主角，都市青年，获得上古传承后开始修炼",
            "personality": "坚韧不拔，聪明机智",
            "goals": "修炼成仙，保护家人",
            "background": "普通上班族，意外获得传承",
            "appearance": "清秀帅气，剑眉星目",
            "age": "young",
            "gender": "male",
            "voice_type": "protagonist"
        },
        {
            "id": "evil_cultivator",
            "name": "魔道尊者",
            "role": "antagonist",
            "description": "魔道高手，与主角为敌",
            "personality": "阴险狡诈",
            "goals": "毁灭青云宗",
            "background": "百年前被青云宗封印",
            "appearance": "黑袍笼罩，面目模糊",
            "age": "middle",
            "gender": "male",
            "voice_type": "antagonist"
        }
    ]

    # 模拟情节结构
    plot_structure = [
        {"chapter": 1, "description": "主角获得传承，踏入修炼之路", "shuangdian_type": "升级", "intensity": "high"},
        {"chapter": 2, "description": "主角初入宗门，展现天赋", "shuangdian_type": "打脸", "intensity": "medium"},
    ]

    # 模拟章节
    chapters = []
    for i in range(1, context.chapters + 1):
        chapter_content = f"""第{i}章：修炼之路

        夜幕降临，林凡独自坐在窗前，回想着今天发生的一切。

        {context.core_idea}

        "我一定要变强！"林凡握紧拳头，眼中闪烁着坚定的光芒。

        就在这时，一道金光从天而降，没入他的眉心。一股庞大的信息流涌入脑海——那是上古大能的修炼记忆！

        林凡浑身一震，只觉得体内的灵气开始运转。他，竟然真的可以修炼了！

        与此同时，遥远的魔道总部，魔道尊者睁开了双眼，似乎感应到了什么。
        """
        chapters.append({
            "number": i,
            "title": f"第{i}章：意外的传承",
            "content": chapter_content,
            "word_count": len(chapter_content),
            "summary": f"这是第{i}章的摘要内容",
            "key_events": [f"主角获得传承", f"开始修炼", f"魔道尊者感应"],
            "character_appearances": ["林凡", "魔道尊者"]
        })

    return {
        "metadata": {
            "title": context.project_id,
            "genre": context.genre,
            "style": "爽文",
            "total_chapters": context.chapters,
            "total_word_count": sum(c["word_count"] for c in chapters),
            "creation_time": datetime.now().isoformat(),
            "status": "completed",
            "mock": True,
        },
        "blueprint": {
            "title": context.project_id,
            "genre": context.genre,
            "world_building": world_building,
            "characters": characters,
            "plot_structure": plot_structure,
            "chapter_plans": [{"number": i, "title": chapters[i-1]["title"], "summary": chapters[i-1]["summary"]} for i in range(1, context.chapters + 1)]
        },
        "chapters": chapters
    }


def save_mock_novel(context: PipelineContext, novel_data: Dict):
    """保存模拟小说数据到文件"""
    # 创建目录
    context.data_dir.mkdir(parents=True, exist_ok=True)
    context.scripts_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir = context.data_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    # 保存 story_bible.json
    bible_path = context.data_dir / "story_bible.json"
    with open(bible_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": novel_data["metadata"],
            "blueprint": novel_data["blueprint"]
        }, f, ensure_ascii=False, indent=2)
    print(f"   💾 保存: {bible_path.relative_to(context.project_dir.parent)}")

    # 保存各章
    for chapter in novel_data["chapters"]:
        # 保存正文
        md_path = chapters_dir / f"chapter_{chapter['number']:03d}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {chapter['title']}\n\n")
            f.write(chapter["content"])
        print(f"   💾 保存: {md_path.relative_to(context.project_dir.parent)}")

        # 保存摘要
        summary_path = chapters_dir / f"chapter_{chapter['number']:03d}_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "number": chapter["number"],
                "title": chapter["title"],
                "summary": chapter["summary"],
                "key_events": chapter["key_events"],
                "character_appearances": chapter["character_appearances"],
                "word_count": chapter["word_count"]
            }, f, ensure_ascii=False, indent=2)

    print(f"   ✅ Mock 小说数据已保存")


# ============================================================
# 阶段 1: 小说生成
# ============================================================

async def run_phase1_novel(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 1: 小说生成

    流程:
      1. 生成世界观、角色、修炼体系
      2. 生成情节结构
      3. 生成章节规划
      4. 生成各章正文
      5. 生成分镜脚本

    输出:
      - data/story_bible.json: 故事设定
      - data/chapters/chapter_XXX.md: 各章正文
      - data/chapters/chapter_XXX_summary.json: 各章摘要
      - data/scripts/script_XXX.jsonl: 各章分镜脚本
    """
    phase_name = "小说生成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"📝 Phase 1: {phase_name}")
    print(f"{'='*60}")

    # 检查是否已完成
    bible_path = context.data_dir / "story_bible.json"
    if bible_path.exists() and not force:
        print(f"   ✓ 故事设定已存在，跳过 (使用 --force 重新生成)")
        return PhaseResult(
            phase=1,
            name=phase_name,
            status=PhaseStatus.SKIPPED,
            duration_seconds=0,
            output_path=context.data_dir,
        )

    # 创建目录
    context.data_dir.mkdir(parents=True, exist_ok=True)
    context.scripts_dir.mkdir(parents=True, exist_ok=True)

    # 构建 NovelConcept
    from stages.stage1_novel.models import NovelConcept

    concept = NovelConcept(
        title=context.project_id,
        genre=context.genre,
        style=context.style,
        core_idea=context.core_idea,
        total_chapters=context.chapters,
        target_word_count=context.words_per_chapter,
        shuangdian_intensity=context.shuangdian_intensity,
    )

    # 使用增强型流式生成器 (对齐 run_stage1.py)
    try:
        from stages.stage1_novel.streaming_novel_generator import create_novel_generator
        STREAMING_AVAILABLE = True
    except ImportError:
        from stages.stage1_novel.novel_generator import NovelGenerator as create_novel_generator
        STREAMING_AVAILABLE = False

    # 如果是 API 模式，将 api 传入作为 llm_client
    llm_client = api if not isinstance(api, MockAPIClient) else None
    
    if context.use_streaming and STREAMING_AVAILABLE:
        generator = create_novel_generator(llm_client=llm_client, use_streaming=True)
    else:
        # 如果不可用或未启用，回退到标准生成器
        if context.use_streaming and not STREAMING_AVAILABLE:
            print("   ⚠️  流式生成器不可用，使用标准生成器")
        from stages.stage1_novel.novel_generator import NovelGenerator
        generator = NovelGenerator(llm_client=llm_client)
    generator.output_dir = context.novel_dir

    try:
        # 执行生成
        print(f"   🎯 开始生成小说...")
        novel = await generator.process(concept)

        # Novel.save() 已经保存了所有文件
        duration = time.monotonic() - start_time

        print(f"\n   ✅ 小说生成完成!")
        print(f"      总章节: {len(novel.chapters)}")
        print(f"      总字数: {novel.metadata.get('total_word_count', 0):,}")
        print(f"      保存位置: {context.novel_dir}")

        # 保存上下文
        context.save()

        return PhaseResult(
            phase=1,
            name=phase_name,
            status=PhaseStatus.COMPLETED,
            duration_seconds=duration,
            output_path=context.data_dir,
            metadata={
                "total_chapters": len(novel.chapters),
                "total_word_count": novel.metadata.get("total_word_count", 0),
            },
        )

    except Exception as e:
        duration = time.monotonic() - start_time
        print(f"\n   ⚠️  小说生成失败: {e}")
        print(f"   🔄 尝试生成 Mock 数据以继续测试流程...")

        try:
            # 生成 Mock 数据
            mock_data = generate_mock_novel_data(context)
            save_mock_novel(context, mock_data)
            context.save()

            return PhaseResult(
                phase=1,
                name=phase_name,
                status=PhaseStatus.COMPLETED,
                duration_seconds=duration,
                output_path=context.data_dir,
                metadata={
                    "total_chapters": len(mock_data["chapters"]),
                    "total_word_count": mock_data["metadata"]["total_word_count"],
                    "mock": True,
                },
            )
        except Exception as mock_error:
            print(f"\n   ❌ Mock 数据生成也失败: {mock_error}")
            import traceback
            traceback.print_exc()

            return PhaseResult(
                phase=1,
                name=phase_name,
                status=PhaseStatus.FAILED,
                duration_seconds=duration,
                error=str(e),
            )


# ============================================================
# 阶段 2: 分镜脚本生成 (从小说内容)
# ============================================================

async def run_phase2_scripts(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 2: 分镜脚本生成

    从阶段1生成的小说内容，拆分为分镜脚本。
    每个分镜包含:
      - visual_prompt: 图像生成提示词
      - motion_prompt: 镜头运动描述
      - camera: 景别
      - text: 朗读文本
      - emotion: 情感标签
    """
    phase_name = "分镜脚本生成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"🎬 Phase 2: {phase_name}")
    print(f"{'='*60}")

    # 检查输入
    bible_path = context.data_dir / "story_bible.json"
    if not bible_path.exists():
        return PhaseResult(
            phase=2,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="缺少故事设定，请先运行 Phase 1",
        )

    # 检查是否已完成
    sample_script = context.scripts_dir / "script_001.jsonl"
    if sample_script.exists() and not force:
        print(f"   ✓ 分镜脚本已存在，跳过")
        return PhaseResult(
            phase=2,
            name=phase_name,
            status=PhaseStatus.SKIPPED,
            duration_seconds=0,
            output_path=context.scripts_dir,
        )

    # 加载小说数据
    with open(bible_path, "r", encoding="utf-8") as f:
        bible_data = json.load(f)

    # 重建对象
    from stages.stage1_novel.models import (
        Novel, StoryBlueprint, WorldBuilding, Character,
        PlotPoint, Chapter, NovelConcept
    )

    blueprint_data = bible_data.get("blueprint", {})

    # 重建 WorldBuilding
    wb_data = blueprint_data.get("world_building", {})
    world_building = WorldBuilding(
        setting=wb_data.get("setting", ""),
        power_system=wb_data.get("power_system", ""),
        factions=wb_data.get("factions", []),
        rules=wb_data.get("rules", []),
    )

    # 重建 Characters
    characters = [Character(**c) for c in blueprint_data.get("characters", [])]

    # 重建 PlotStructure
    plot_structure = [
        PlotPoint(**p) for p in blueprint_data.get("plot_structure", [])
    ]

    # 构建 Blueprint
    blueprint = StoryBlueprint(
        title=blueprint_data.get("title", context.project_id),
        genre=blueprint_data.get("genre", context.genre),
        world_building=world_building,
        characters=characters,
        plot_structure=plot_structure,
        chapter_plans=blueprint_data.get("chapter_plans", []),
    )

    # 加载章节
    chapters = []
    chapters_dir = context.data_dir / "chapters"
    if chapters_dir.exists():
        for i in range(1, context.chapters + 1):
            md_path = chapters_dir / f"chapter_{i:03d}.md"
            summary_path = chapters_dir / f"chapter_{i:03d}_summary.json"

            content = ""
            if md_path.exists():
                with open(md_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    content = "".join(lines[2:]) if len(lines) > 2 else "".join(lines)

            summary_data = {}
            if summary_path.exists():
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary_data = json.load(f)

            chapters.append(Chapter(
                number=i,
                title=summary_data.get("title", f"第{i}章"),
                content=content,
                word_count=summary_data.get("word_count", len(content)),
                summary=summary_data.get("summary", ""),
                key_events=summary_data.get("key_events", []),
                character_appearances=summary_data.get("character_appearances", []),
            ))

    if not chapters:
        return PhaseResult(
            phase=2,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="未找到章节内容",
        )

    # 生成分镜脚本
    from stages.stage1_novel.script_generator import ScriptGenerator

    # 如果是 API 模式，将 api 传入作为 llm_client
    llm_client = api if not isinstance(api, MockAPIClient) else None
    script_gen = ScriptGenerator(llm_client=llm_client)

    total_shots = 0
    for chapter in chapters:
        script_path = context.scripts_dir / f"script_{chapter.number:03d}.jsonl"

        # 检查是否已存在
        if script_path.exists() and not force:
            # 统计已有脚本数量
            with open(script_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                total_shots += len([l for l in lines if l.strip()])
            continue

        print(f"   🎬 第{chapter.number}章: 生成分镜脚本...")

        # 生成脚本
        script_lines = await script_gen.generate_script_lines(
            chapter=chapter,
            blueprint=blueprint,
            shots_per_chapter=8,
        )

        # 保存到 JSONL
        with open(script_path, "w", encoding="utf-8") as f:
            for line in script_lines:
                f.write(json.dumps(line.to_dict(), ensure_ascii=False) + "\n")

        total_shots += len(script_lines)
        print(f"      ✓ {len(script_lines)} 个镜头")

    duration = time.monotonic() - start_time

    print(f"\n   ✅ 分镜脚本生成完成!")
    print(f"      总镜头数: {total_shots}")
    print(f"      保存位置: {context.scripts_dir}")

    return PhaseResult(
        phase=2,
        name=phase_name,
        status=PhaseStatus.COMPLETED,
        duration_seconds=duration,
        output_path=context.scripts_dir,
        metadata={"total_shots": total_shots},
    )


# ============================================================
# 阶段 3: 图像生成
# ============================================================

async def run_phase3_images(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 3: 图像生成

    从分镜脚本读取 visual_prompt，调用图像生成服务。
    支持 ComfyUI / Mock 模式。
    """
    phase_name = "图像生成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"🎨 Phase 3: {phase_name}")
    print(f"{'='*60}")

    # 检查输入
    if not context.scripts_dir.exists() or not list(context.scripts_dir.glob("*.jsonl")):
        return PhaseResult(
            phase=3,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="缺少分镜脚本，请先运行 Phase 2",
        )

    # 创建输出目录
    context.images_dir.mkdir(parents=True, exist_ok=True)

    # 加载分镜脚本
    from stages.models import ScriptLine

    all_shots = []
    for script_file in sorted(context.scripts_dir.glob("script_*.jsonl")):
        # 从文件名提取章节号 (e.g., script_001.jsonl -> 1)
        try:
            current_chapter_num = int(script_file.stem.split("_")[1])
        except (IndexError, ValueError):
            current_chapter_num = 1
            
        with open(script_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        shot = ScriptLine(**data)
                        all_shots.append((shot, current_chapter_num))
                    except json.JSONDecodeError:
                        continue

    if not all_shots:
        return PhaseResult(
            phase=3,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="分镜脚本为空",
        )

    print(f"   📋 共 {len(all_shots)} 个镜头需要生成图像")

    # 生成图像
    generated_count = 0
    failed_count = 0
    image_results = []

    for i, (shot, chapter_num) in enumerate(all_shots):
        if not shot.visual_prompt:
            continue

        # 按章节和场景组织目录 (e.g., chapter_001/SC01/)
        chapter_dir = context.images_dir / f"chapter_{chapter_num:03d}"
        scene_dir = chapter_dir / shot.scene_id
        scene_dir.mkdir(parents=True, exist_ok=True)

        image_path = scene_dir / f"{shot.shot_id}.png"

        # 检查是否已存在
        if image_path.exists() and not force:
            generated_count += 1
            continue

        print(f"   [{i+1}/{len(all_shots)}] {shot.shot_id}: {shot.visual_prompt[:50]}...")

        try:
            # 调用图像生成 API
            task_id = await api.image_generate(
                prompt=shot.visual_prompt,
                negative_prompt="blurry, low quality, bad anatomy, distorted face",
                width=640,
                height=480,
            )

            # Mock 模式下，记录 prompt 到缓存
            result = await api.image_wait(task_id)

            if result.get("images"):
                # 提取图片结果
                image_info = result["images"][0]
                
                # 处理 Mock 模式
                if isinstance(api, MockAPIClient):
                    # 创建占位文件
                    with open(image_path, "w") as f:
                        f.write(f"Mock image for: {shot.visual_prompt}")
                    generated_count += 1
                else:
                    # 真实 API 模式：下载图片
                    image_url = image_info.get("url")
                    if image_url:
                        import httpx
                        full_url = f"{api.base_url.rstrip('/')}{image_url}"
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(full_url)
                            if resp.status_code == 200:
                                with open(image_path, "wb") as f:
                                    f.write(resp.content)
                                generated_count += 1
                                image_results.append({
                                    "shot_id": shot.shot_id,
                                    "status": "success",
                                    "local_path": str(image_path)
                                })
                            else:
                                raise Exception(f"下载失败: HTTP {resp.status_code}")
                    else:
                        raise Exception("API 返回结果中缺失图像 URL")
            else:
                failed_count += 1
                image_results.append({
                    "shot_id": shot.shot_id,
                    "status": "failed",
                    "error": "No images returned"
                })

        except Exception as e:
            print(f"      ⚠️  生成失败: {e}")
            failed_count += 1
            image_results.append({
                "shot_id": shot.shot_id,
                "prompt": shot.visual_prompt,
                "status": "error",
                "error": str(e),
            })

    duration = time.monotonic() - start_time

    # 保存生成记录
    results_path = context.images_dir / "generation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated": generated_count,
            "failed": failed_count,
            "shots": image_results,
            "generated_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)

    print(f"\n   ✅ 图像生成完成!")
    print(f"      成功: {generated_count}")
    print(f"      失败: {failed_count}")
    print(f"      保存位置: {context.images_dir}")

    return PhaseResult(
        phase=3,
        name=phase_name,
        status=PhaseStatus.COMPLETED,
        duration_seconds=duration,
        output_path=context.images_dir,
        metadata={
            "generated": generated_count,
            "failed": failed_count,
        },
    )


# ============================================================
# 阶段 4: TTS 音频生成
# ============================================================

async def run_phase4_tts(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 4: TTS 音频生成

    从分镜脚本读取 text，调用 TTS 服务生成音频。
    """
    phase_name = "TTS 音频生成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"🔊 Phase 4: {phase_name}")
    print(f"{'='*60}")

    # 检查输入
    if not context.scripts_dir.exists() or not list(context.scripts_dir.glob("*.jsonl")):
        return PhaseResult(
            phase=4,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="缺少分镜脚本，请先运行 Phase 2",
        )

    # 创建输出目录
    context.audio_dir.mkdir(parents=True, exist_ok=True)

    # 加载分镜脚本
    from stages.models import ScriptLine

    all_shots = []
    for script_file in sorted(context.scripts_dir.glob("script_*.jsonl")):
        # 从文件名提取章节号 (e.g., script_001.jsonl -> 1)
        try:
            current_chapter_num = int(script_file.stem.split("_")[1])
        except (IndexError, ValueError):
            current_chapter_num = 1
            
        with open(script_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        shot = ScriptLine(**data)
                        all_shots.append((shot, current_chapter_num))
                    except json.JSONDecodeError:
                        continue

    if not all_shots:
        return PhaseResult(
            phase=4,
            name=phase_name,
            status=PhaseStatus.FAILED,
            duration_seconds=0,
            error="分镜脚本为空",
        )

    print(f"   📋 共 {len(all_shots)} 个镜头需要生成音频")

    # 语音角色映射
    VOICE_MAP = {
        "narrator": "zh-CN-XiaoxiaoNeural",
        " protagonist": "zh-CN-YunxiNeural",
        "antagonist": "zh-CN-YunyangNeural",
    }

    def get_voice(speaker: str) -> str:
        speaker_lower = speaker.lower()
        for key, voice in VOICE_MAP.items():
            if key in speaker_lower:
                return voice
        return "zh-CN-XiaoxiaoNeural"

    # 生成音频
    generated_count = 0
    failed_count = 0
    audio_results = []

    for i, (shot, chapter_num) in enumerate(all_shots):
        if not shot.text:
            continue

        # 使用从脚本中提取的准确章节号
        chapter_dir = context.audio_dir / f"chapter_{chapter_num:03d}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        audio_path = chapter_dir / f"{shot.shot_id}.mp3"

        # 检查是否已存在
        if audio_path.exists() and not force:
            generated_count += 1
            continue

        print(f"   [{i+1}/{len(all_shots)}] {shot.shot_id}: {shot.text[:30]}...")

        try:
            voice = get_voice(shot.speaker)

            # 调用 TTS API
            task_id = await api.tts_synthesize(
                text=shot.text[:500],  # 限制长度
                voice=voice,
                rate="+0%",
                pitch="+0Hz",
            )

            result = await api.tts_wait(task_id)

            if result.get("audio_url"):
                # 处理 Mock 模式
                if isinstance(api, MockAPIClient):
                    # 创建占位文件
                    with open(audio_path, "w") as f:
                        f.write(f"Mock audio for: {shot.text[:50]}")
                    generated_count += 1
                else:
                    # 真实 API 模式：下载音频
                    audio_url = result.get("audio_url")
                    if audio_url:
                        import httpx
                        full_url = f"{api.base_url.rstrip('/')}{audio_url}"
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(full_url)
                            if resp.status_code == 200:
                                with open(audio_path, "wb") as f:
                                    f.write(resp.content)
                                generated_count += 1
                                audio_results.append({
                                    "shot_id": shot.shot_id,
                                    "status": "success",
                                    "local_path": str(audio_path)
                                })
                            else:
                                raise Exception(f"下载音频失败: HTTP {resp.status_code}")
                    else:
                        raise Exception("API 返回结果中缺失音频 URL")
            else:
                failed_count += 1

        except Exception as e:
            print(f"      ⚠️  生成失败: {e}")
            failed_count += 1
            audio_results.append({
                "shot_id": shot.shot_id,
                "text": shot.text[:100],
                "status": "error",
                "error": str(e),
            })

    duration = time.monotonic() - start_time

    # 保存生成记录
    results_path = context.audio_dir / "generation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated": generated_count,
            "failed": failed_count,
            "shots": audio_results,
            "generated_at": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)

    print(f"\n   ✅ TTS 音频生成完成!")
    print(f"      成功: {generated_count}")
    print(f"      失败: {failed_count}")
    print(f"      保存位置: {context.audio_dir}")

    return PhaseResult(
        phase=4,
        name=phase_name,
        status=PhaseStatus.COMPLETED,
        duration_seconds=duration,
        output_path=context.audio_dir,
        metadata={
            "generated": generated_count,
            "failed": failed_count,
        },
    )


# ============================================================
# 阶段 5: 视频合成
# ============================================================

async def run_phase5_video(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 5: 视频片段生成
    为每个镜头根据图像生成基础视频片段 (无音频)。
    """
    phase_name = "视频生成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"🎬 Phase 5: {phase_name}")
    print(f"{'='*60}")

    if not context.images_dir.exists():
        return PhaseResult(phase=5, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=0, error="缺少图像，请先运行 Phase 3")

    clips_dir = context.videos_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    from stages.models import ScriptLine
    all_shots = []
    for script_file in sorted(context.scripts_dir.glob("script_*.jsonl")):
        try:
            current_chapter_num = int(script_file.stem.split("_")[1])
        except (IndexError, ValueError):
            current_chapter_num = 1
        with open(script_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        all_shots.append((ScriptLine(**data), current_chapter_num))
                    except json.JSONDecodeError:
                        continue

    if not all_shots:
        return PhaseResult(phase=5, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=0, error="分镜脚本为空")

    print(f"   📋 共 {len(all_shots)} 个镜头需要生成视频")

    generated_count = 0
    failed_count = 0
    video_results = []

    for i, (shot, chapter_num) in enumerate(all_shots):
        chapter_dir = clips_dir / f"chapter_{chapter_num:03d}"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        video_path = chapter_dir / f"{shot.shot_id}.mp4"

        if video_path.exists() and not force:
            generated_count += 1
            continue

        image_path = context.images_dir / f"chapter_{chapter_num:03d}" / shot.scene_id / f"{shot.shot_id}.png"
        if not image_path.exists():
            print(f"      ⚠️  跳过 {shot.shot_id}: 找不到输入图像 {image_path.name}")
            failed_count += 1
            continue

        print(f"   [{i+1}/{len(all_shots)}] {shot.shot_id}...")

        try:
            image_url = f"/files/{image_path}"
            task_id = await api.video_generate(
                image_url=image_url,
                prompt=shot.visual_prompt,
                motion_prompt=shot.motion_prompt,
                num_frames=81,
                fps=24,
            )

            result = await api.video_wait(task_id)

            if result.get("video_url"):
                if isinstance(api, MockAPIClient):
                    with open(video_path, "w") as f:
                        f.write(f"Mock video for: {shot.shot_id}")
                    generated_count += 1
                else:
                    video_url = result.get("video_url")
                    if video_url:
                        import httpx
                        full_url = f"{api.base_url.rstrip('/')}{video_url}"
                        async with httpx.AsyncClient(timeout=300) as client:
                            resp = await client.get(full_url)
                            if resp.status_code == 200:
                                with open(video_path, "wb") as f:
                                    f.write(resp.content)
                                generated_count += 1
                                video_results.append({
                                    "shot_id": shot.shot_id,
                                    "status": "success",
                                    "local_path": str(video_path)
                                })
                            else:
                                raise Exception(f"下载失败: HTTP {resp.status_code}")
                    else:
                        raise Exception("API 返回结果中缺失视频 URL")
            else:
                failed_count += 1

        except Exception as e:
            print(f"      ⚠️  生成失败: {e}")
            failed_count += 1
            video_results.append({
                "shot_id": shot.shot_id,
                "status": "error",
                "error": str(e),
            })

    duration = time.monotonic() - start_time
    results_path = context.videos_dir / "generation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"generated": generated_count, "failed": failed_count, "shots": video_results}, f, ensure_ascii=False, indent=2)

    print(f"\n   ✅ 视频生成完成! 成功: {generated_count}, 失败: {failed_count}")
    return PhaseResult(
        phase=5,
        name=phase_name,
        status=PhaseStatus.COMPLETED,
        duration_seconds=duration,
        output_path=clips_dir,
    )


# ============================================================
# 阶段 6: 视频合成
# ============================================================

async def run_phase6_synthesis(
    context: PipelineContext,
    api: Union[MockAPIClient, Any],
    prompt_manager: PromptManager,
    force: bool = False,
) -> PhaseResult:
    """
    Phase 6: 视频合成
    合并单独生成的视频片段与 TTS 音频，并拼接为最终视频。
    """
    phase_name = "视频合成"
    start_time = time.monotonic()

    print(f"\n{'='*60}")
    print(f"🎬 Phase 6: {phase_name}")
    print(f"{'='*60}")

    clips_dir = context.videos_dir / "clips"
    if not clips_dir.exists():
        return PhaseResult(phase=6, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=0, error="缺少视频片段，请先运行 Phase 5")
    if not context.audio_dir.exists():
        return PhaseResult(phase=6, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=0, error="缺少音频，请先运行 Phase 4")

    synth_dir = context.videos_dir / "synth_clips"
    synth_dir.mkdir(parents=True, exist_ok=True)

    from stages.models import ScriptLine
    all_shots = []
    for script_file in sorted(context.scripts_dir.glob("script_*.jsonl")):
        try:
            chapter_num = int(script_file.stem.split("_")[1])
        except (IndexError, ValueError):
            chapter_num = 1
        with open(script_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        all_shots.append((ScriptLine(**data), chapter_num))
                    except json.JSONDecodeError:
                        continue

    print(f"   📋 共 {len(all_shots)} 个镜头需要合成")
    
    synth_files = []
    failed_count = 0

    if isinstance(api, MockAPIClient):
        print("   ⚠️  Mock 模式，跳过 FFmpeg 实际合成")
        return PhaseResult(phase=6, name=phase_name, status=PhaseStatus.COMPLETED, duration_seconds=0, output_path=context.videos_dir)

    for i, (shot, chapter_num) in enumerate(all_shots):
        video_path = clips_dir / f"chapter_{chapter_num:03d}" / f"{shot.shot_id}.mp4"
        audio_path = context.audio_dir / f"chapter_{chapter_num:03d}" / f"{shot.shot_id}.mp3"
        synth_path = synth_dir / f"synth_{shot.shot_id}.mp4"

        if not video_path.exists():
            print(f"      ⚠️  跳过 {shot.shot_id}: 缺少视频文件")
            continue
        if not audio_path.exists():
            print(f"      ⚠️  跳过 {shot.shot_id}: 缺少音频文件")
            continue

        synth_files.append(synth_path)

        if synth_path.exists() and not force:
            continue

        print(f"   [{i+1}/{len(all_shots)}] 合成 {shot.shot_id}...")
        
        # FFmpeg: loop video, add audio, stop at shortest (audio)
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            "-shortest",
            str(synth_path)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"      ⚠️  合成失败: {stderr.decode()}")
            failed_count += 1
            # Remove failed file from list
            synth_files.remove(synth_path)
    
    if not synth_files:
        return PhaseResult(phase=6, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=0, error="没有成功合成的片段")

    # 最终拼接
    print(f"\n   🎞️  开始拼接最终视频...")
    concat_list = context.videos_dir / "concat_list.txt"
    final_video = context.videos_dir / f"{context.project_id}_final.mp4"

    with open(concat_list, "w", encoding="utf-8") as f:
        for p in synth_files:
            # path string needs to be properly escaped for ffmpeg
            f.write(f"file '{p.absolute()}'\n")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(final_video)
    ]

    process = await asyncio.create_subprocess_exec(
        *concat_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    duration = time.monotonic() - start_time
    
    if process.returncode != 0:
        print(f"      ⚠️  拼接失败: {stderr.decode()}")
        return PhaseResult(phase=6, name=phase_name, status=PhaseStatus.FAILED, duration_seconds=duration, error="拼接最终视频失败")

    print(f"\n   ✅ 视频合成与拼接完成! 最终文件: {final_video}")
    return PhaseResult(
        phase=6,
        name=phase_name,
        status=PhaseStatus.COMPLETED,
        duration_seconds=duration,
        output_path=final_video,
    )


# ============================================================
# 流水线执行器
# ============================================================

class PipelineRunner:
    """流水线执行器"""

    def __init__(
        self,
        context: PipelineContext,
        use_api: bool = False,
        api_url: str = "http://localhost:9000",
    ):
        self.context = context
        self.use_api = use_api

        if use_api:
            # 真实 API 模式
            self.api = APIClient(api_url)
        else:
            # Mock 模式
            self.api = MockAPIClient(context)

        self.prompt_manager = PromptManager()
        self.phases: Dict[int, callable] = {
            1: run_phase1_novel,
            2: run_phase2_scripts,
            3: run_phase3_images,
            4: run_phase4_tts,
            5: run_phase5_video,
            6: run_phase6_synthesis,
        }
        self.phase_results: List[PhaseResult] = []

    async def close(self):
        """关闭连接"""
        if hasattr(self.api, "close"):
            await self.api.close()

    async def run(
        self,
        phases: Optional[List[int]] = None,
        force: bool = False,
    ) -> List[PhaseResult]:
        """
        运行流水线

        Args:
            phases: 要运行的阶段列表，None 表示全部
            force: 是否强制重新生成
        """
        print(f"\n{'#'*70}")
        print(f"#{'🎬 AI 爽文视频流水线':^58}#")
        print(f"{'#'*70}")
        print(f"\n📋 项目: {self.context.project_id}")
        print(f"   类型: {self.context.genre}")
        print(f"   章节: {self.context.chapters}")
        print(f"   模式: {'API' if self.use_api else 'Mock'}")
        print(f"   目录: {self.context.project_dir}")

        if phases is None:
            phases = list(self.phases.keys())

        total_start = time.monotonic()

        for phase_num in phases:
            if phase_num not in self.phases:
                print(f"\n⚠️  未知阶段: {phase_num}")
                continue

            phase_func = self.phases[phase_num]

            # 执行阶段
            result = await phase_func(
                context=self.context,
                api=self.api,
                prompt_manager=self.prompt_manager,
                force=force,
            )

            self.phase_results.append(result)

            # 如果失败，询问是否继续 (非交互模式下自动继续)
            if result.status == PhaseStatus.FAILED:
                print(f"\n⚠️  阶段 {phase_num} 失败: {result.error}")
                try:
                    response = input("   是否继续? (y/n): ").strip().lower()
                    if response != "y":
                        break
                except EOFError:
                    # 非交互模式，自动继续
                    print("   (非交互模式，自动继续)")
                    continue

        total_duration = time.monotonic() - total_start

        # 打印总结
        print(f"\n{'='*70}")
        print(f"#{'📊 流水线执行总结':^58}#")
        print(f"{'='*70}")
        print(f"\n   项目: {self.context.project_id}")
        print(f"   总耗时: {total_duration:.1f} 秒")
        print(f"\n   阶段结果:")
        for r in self.phase_results:
            status_icon = {
                PhaseStatus.COMPLETED: "✅",
                PhaseStatus.FAILED: "❌",
                PhaseStatus.SKIPPED: "⏭️",
                PhaseStatus.RUNNING: "🔄",
            }.get(r.status, "❓")
            print(f"      {status_icon} Phase {r.phase}: {r.name}")
            print(f"         状态: {r.status.value}")
            print(f"         耗时: {r.duration_seconds:.1f} 秒")
            if r.error:
                print(f"         错误: {r.error}")

        # 保存执行记录
        self._save_run_record(total_duration)

        return self.phase_results

    def _save_run_record(self, total_duration: float):
        """保存执行记录"""
        record_path = self.context.project_dir / "run_record.json"
        record = {
            "project_id": self.context.project_id,
            "run_at": datetime.now().isoformat(),
            "total_duration_seconds": total_duration,
            "phases": [r.to_dict() for r in self.phase_results],
        }
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print(f"\n   📁 执行记录已保存: {record_path}")


# ============================================================
# 导入 API 客户端 (仅 API 模式使用)
# ============================================================

def _import_api_client():
    """延迟导入 API 客户端"""
    try:
        import httpx
        return httpx
    except ImportError:
        return None


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(
        description="AI 爽文视频流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            示例:
            # Mock 模式 (默认)
            python run_pipeline.py --project-id "test_project" --genre 修仙 --chapters 3

            # 指定阶段
            python run_pipeline.py --project-id "test_project" --phase 1
            python run_pipeline.py --project-id "test_project" --phase 2 --force

            # API 模式
            python run_pipeline.py --project-id "test_project" --use-api --api-url http://localhost:9000
                    """,
                )

    parser.add_argument(
        "--project-id", "-p",
        type=str,
        required=True,
        help="项目 ID (用于组织输出文件)",
    )
    parser.add_argument(
        "--genre", "-g",
        type=str,
        default="修仙",
        help="小说类型 (默认: 修仙)",
    )
    parser.add_argument(
        "--chapters", "-c",
        type=int,
        default=3,
        help="章节数量 (默认: 3)",
    )
    parser.add_argument(
        "--words",
        type=int,
        default=5000,
        help="每章字数 (默认: 5000)",
    )
    parser.add_argument(
        "--core-idea",
        type=str,
        default="",
        help="核心创意描述",
    )
    parser.add_argument(
        "--style",
        type=str,
        default="爽文",
        help="小说风格 (默认: 爽文)",
    )
    parser.add_argument(
        "--intensity",
        choices=["low", "medium", "high"],
        default="high",
        help="爽点强度 (默认: high)",
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        default=True,
        help="使用流式生成器 (支持断点续传和质量控制)",
    )
    parser.add_argument(
        "--no-streaming",
        action="store_false",
        dest="streaming",
        help="禁用流式生成器",
    )
    parser.add_argument(
        "--phase",
        type=int,
        nargs="+",
        choices=[1, 2, 3, 4, 5, 6],
        help="运行指定阶段 (可指定多个，如 --phase 1 2 3)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制重新生成 (跳过缓存)",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        default=True,
        help="使用真实 API 服务 (需要启动 api_service)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:9000",
        help="API 服务地址 (默认: http://localhost:9000)",
    )

    args = parser.parse_args()

    # 创建上下文
    context = PipelineContext(
        project_id=args.project_id,
        genre=args.genre,
        chapters=args.chapters,
        words_per_chapter=args.words,
        core_idea=args.core_idea or f"这是一个精彩的{args.genre}故事",
        style=args.style,
        shuangdian_intensity=args.intensity,
        use_streaming=args.streaming,
    )

    # 创建执行器
    runner = PipelineRunner(
        context=context,
        use_api=args.use_api,
        api_url=args.api_url,
    )

    try:
        # 确定要运行的阶段
        phases = args.phase if args.phase else None

        # 运行流水线
        await runner.run(phases=phases, force=args.force)

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断执行")
    except Exception as e:
        print(f"\n\n❌ 执行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())

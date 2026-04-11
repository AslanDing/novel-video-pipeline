"""
小说生成模块 (Stage 1)

提供完整的小说生成功能，包括：
- 爽点系统
- 质量评估
- 上下文管理
- 一致性检查
- 节奏控制
"""

from .models import (
    NovelConcept, Novel, StoryBlueprint, WorldBuilding,
    Character, PlotPoint, Chapter, ChapterPlan,
    ShuangDian, ShuangDianType, ShuangDianIntensity,
    QualityScore
)
from .novel_generator import (
    NovelGenerator, NovelGenerationPipeline, quick_generate_novel
)
from .shuangdian_system import ShuangDianSystem
from .quality_controller import QualityController
from .context_manager import ContextManager
from .consistency_checker import ConsistencyChecker
from .rhythm_controller import RhythmController

__all__ = [
    # 数据模型
    "NovelConcept", "Novel", "StoryBlueprint", "WorldBuilding",
    "Character", "PlotPoint", "Chapter", "ChapterPlan",
    "ShuangDian", "ShuangDianType", "ShuangDianIntensity",
    "QualityScore",
    # 生成器
    "NovelGenerator", "NovelGenerationPipeline", "quick_generate_novel",
    # 子系统
    "ShuangDianSystem", "QualityController", "ContextManager",
    "ConsistencyChecker", "RhythmController",
]

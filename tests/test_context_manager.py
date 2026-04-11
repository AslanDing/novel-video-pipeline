"""
测试上下文管理器
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from stage1_novel.context_manager import ContextManager
from stage1_novel.models import (
    Chapter, StoryBlueprint, WorldBuilding, Character, PlotPoint
)


class TestContextManager:
    """测试上下文管理器"""

    def setup_method(self):
        """每个测试前运行"""
        self.manager = ContextManager()

        # 创建测试用的蓝图
        self.world = WorldBuilding(
            setting="测试世界，修仙界",
            power_system="炼气、筑基、金丹、元婴",
            factions=[{"name": "测试宗门", "description": "测试", "type": "正"}],
            rules=["规则1", "规则2"],
        )

        self.characters = [
            Character(
                id="char_001",
                name="张三",
                role="protagonist",
                description="主角描述",
                personality="性格描述",
                goals="目标",
                background="背景",
                appearance="外貌",
            )
        ]

        self.plot = [
            PlotPoint(chapter=1, description="情节1"),
            PlotPoint(chapter=2, description="情节2"),
        ]

        self.blueprint = StoryBlueprint(
            title="测试小说",
            genre="修仙",
            world_building=self.world,
            characters=self.characters,
            plot_structure=self.plot,
            chapter_plans=[],
        )

    def test_generate_summary(self):
        """测试生成摘要"""
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="开头内容" * 10 + "中间内容" * 10 + "结尾内容" * 10,
            word_count=500,
            summary="",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        summary = self.manager.generate_summary(chapter)
        assert len(summary) > 0
        assert "开头" in summary or "结尾" in summary

        # 如果已有摘要，应该直接返回
        chapter.summary = "已有摘要"
        summary = self.manager.generate_summary(chapter)
        assert summary == "已有摘要"

    def test_build_chapter_context(self):
        """测试构建章节上下文"""
        # 创建前文
        prev_chapters = [
            Chapter(
                number=1,
                title="第1章",
                content="第1章内容",
                word_count=100,
                summary="第1章摘要",
                key_events=["事件1"],
                character_appearances=["张三"],
            )
        ]

        context = self.manager.build_chapter_context(
            current_chapter=2,
            blueprint=self.blueprint,
            previous_chapters=prev_chapters,
        )

        # 验证上下文包含关键部分
        assert "核心设定" in context
        assert "主要角色" in context
        assert "主线剧情" in context
        assert "前文摘要" in context
        assert "张三" in context

    def test_cache_chapter_summary(self):
        """测试缓存摘要"""
        chapter = Chapter(
            number=5,
            title="第5章",
            content="内容",
            word_count=100,
            summary="第5章的摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        self.manager.cache_chapter_summary(chapter)

        # 获取缓存
        cached = self.manager.get_cached_summary(5)
        assert cached == "第5章的摘要"

        # 不存在的章节返回None
        cached = self.manager.get_cached_summary(999)
        assert cached is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

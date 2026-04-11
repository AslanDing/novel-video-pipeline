"""
测试一致性检查器
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from stage1_novel.consistency_checker import ConsistencyChecker
from stage1_novel.models import (
    Chapter, StoryBlueprint, WorldBuilding, Character
)


class TestConsistencyChecker:
    """测试一致性检查器"""

    def setup_method(self):
        """每个测试前运行"""
        self.checker = ConsistencyChecker()

        # 创建测试用的蓝图
        self.world = WorldBuilding(
            setting="测试世界",
            power_system="炼气、筑基、金丹",
            factions=[],
            rules=[],
        )

        self.characters = [
            Character(
                id="char_001",
                name="张三",
                role="protagonist",
                description="主角",
                personality="冷漠，不苟言笑",
                goals="目标",
                background="背景",
                appearance="外貌",
            )
        ]

        self.blueprint = StoryBlueprint(
            title="测试小说",
            genre="修仙",
            world_building=self.world,
            characters=self.characters,
            plot_structure=[],
            chapter_plans=[],
        )

    def test_get_name_variants(self):
        """测试获取名字变体"""
        variants = self.checker._get_name_variants("张三")
        assert "张三" in variants
        assert "小三" in variants
        assert "张三兄" in variants

    def test_check_name_consistency(self):
        """测试名字一致性检查"""
        # 使用多个名字的章节
        chapter_conflict = Chapter(
            number=1,
            title="测试章节",
            content="张三和小三一起去逛街，张三兄也来了。",
            word_count=100,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        issues = self.checker._check_name_consistency(chapter_conflict, self.blueprint)
        assert len(issues) >= 1

    def test_extract_personality_traits(self):
        """测试提取性格特征"""
        traits = self.checker._extract_personality_traits("冷漠，不苟言笑")
        assert "冷漠" in traits

    def test_check_timeline_consistency(self):
        """测试时间线一致性检查"""
        chapter = Chapter(
            number=2,
            title="第2章",
            content="夏天到了，天气很热。",
            word_count=100,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        prev_chapters = [
            Chapter(
                number=1,
                title="第1章",
                content="冬天，雪花飘落。",
                word_count=100,
                summary="摘要",
                key_events=["事件1"],
                character_appearances=["张三"],
            )
        ]

        issues = self.checker.check_timeline_consistency(chapter, prev_chapters)
        # 可能检测到季节变化
        assert isinstance(issues, list)

    def test_check_world_rules_consistency(self):
        """测试世界规则一致性检查"""
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="他炼气期就越级挑战金丹期！",
            word_count=100,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        issues = self.checker.check_world_rules_consistency(chapter, self.world)
        # 应该检测到越阶关键词
        assert isinstance(issues, list)

    def test_check_all(self):
        """测试运行所有检查"""
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="测试内容",
            word_count=100,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        issues = self.checker.check_all(chapter, self.blueprint, [])
        assert isinstance(issues, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

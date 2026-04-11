"""
测试质量评估器
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from stage1_novel.quality_controller import QualityController
from stage1_novel.models import Chapter, QualityScore


class TestQualityController:
    """测试质量评估器"""

    def setup_method(self):
        """每个测试前运行"""
        self.controller = QualityController()

    def test_check_readability(self):
        """测试可读性检查"""
        # 创建一个章节
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="这是一段测试内容。" * 100,
            word_count=500,
            summary="测试摘要",
            key_events=["事件1"],
            character_appearances=["角色1"],
        )

        score = self.controller.check_readability(chapter)
        assert 0.0 <= score <= 10.0

    def test_check_completeness(self):
        """测试完整性检查"""
        # 完整的章节
        chapter_complete = Chapter(
            number=1,
            title="测试章节",
            content="这是一段测试内容。" * 100,
            word_count=2000,
            summary="这是一个比较长的摘要，超过20个字。",
            key_events=["事件1", "事件2"],
            character_appearances=["角色1"],
        )

        score = self.controller.check_completeness(chapter_complete)
        assert score > 5.0

        # 不完整的章节
        chapter_incomplete = Chapter(
            number=1,
            title="",
            content="短内容",
            word_count=50,
            summary="",
            key_events=[],
            character_appearances=[],
        )

        score = self.controller.check_completeness(chapter_incomplete)
        assert score < 8.0

    def test_check_length(self):
        """测试长度检查"""
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="测试内容",
            word_count=5000,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["角色1"],
        )

        # 目标5000字，应该得分很高
        score, issue = self.controller.check_length(chapter, 5000)
        assert score == 10.0
        assert issue is None

        # 目标10000字，只有5000，得分应该低一些
        score, issue = self.controller.check_length(chapter, 10000)
        assert score < 10.0
        assert issue is not None

    def test_check_shuangdian(self):
        """测试爽点检查"""
        # 有爽点的章节
        chapter_with = Chapter(
            number=1,
            title="测试章节",
            content="众人震惊！打脸了！突破了！获得了宝物！反转了！" * 10,
            word_count=1000,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["角色1"],
        )

        import asyncio
        score = asyncio.run(self.controller.check_shuangdian(chapter_with))
        assert score > 5.0

        # 没有爽点的章节
        chapter_without = Chapter(
            number=1,
            title="测试章节",
            content="今天天气很好。太阳很大。我们去散步。" * 10,
            word_count=1000,
            summary="摘要",
            key_events=["事件1"],
            character_appearances=["角色1"],
        )

        score = asyncio.run(self.controller.check_shuangdian(chapter_without))
        assert score < 7.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

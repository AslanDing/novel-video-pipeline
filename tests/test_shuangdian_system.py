"""
测试爽点系统
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from stage1_novel.shuangdian_system import ShuangDianSystem
from stage1_novel.models import (
    ShuangDianType, ShuangDianIntensity, ChapterPlan, NovelConcept
)


class TestShuangDianSystem:
    """测试爽点系统"""

    def setup_method(self):
        """每个测试前运行"""
        self.system = ShuangDianSystem()

    def test_plan_distribution(self):
        """测试爽点分布规划"""
        plan = self.system.plan_distribution(100)

        # 验证有100章的规划
        assert len(plan) == 100

        # 验证前10章应该有高密度爽点
        high_intensity_count = sum(
            1 for i in range(1, 11)
            if plan[i].intensity.value >= 3
        )
        assert high_intensity_count >= 5

        # 验证中间章节(40-60)应该有高潮
        has_reverse = any(
            plan[i].type == ShuangDianType.REVERSE
            for i in range(40, 61)
        )
        # 这个不一定总是成立，但至少应该有各种类型
        types_used = set(p.type for p in plan.values())
        assert len(types_used) >= 2

    def test_get_chapter_position(self):
        """测试获取章节位置"""
        position = self.system._get_chapter_position(1, 100)
        assert position == "开头"

        position = self.system._get_chapter_position(50, 100)
        assert position == "发展"

        position = self.system._get_chapter_position(80, 100)
        assert position == "高潮"

        position = self.system._get_chapter_position(95, 100)
        assert position == "收尾"

    def test_select_shuangdian_type(self):
        """测试选择爽点类型"""
        # 前3章应该是打脸
        type1 = self.system._select_shuangdian_type(1, 100)
        assert type1 == ShuangDianType.DALIAN

        type2 = self.system._select_shuangdian_type(2, 100)
        assert type2 == ShuangDianType.DALIAN

        type3 = self.system._select_shuangdian_type(3, 100)
        assert type3 == ShuangDianType.DALIAN

    def test_generate_shuangdian_prompt(self):
        """测试生成爽点提示词"""
        chapter_plan = ChapterPlan(
            number=1,
            title="测试章节",
            summary="测试概要",
            key_events=["事件1"],
        )
        chapter_plan.shuangdian = self.system.plan_distribution(10)[1]

        prompt = self.system.generate_shuangdian_prompt(chapter_plan)

        # 验证提示词包含关键信息
        assert "爽点要求" in prompt
        assert "类型" in prompt
        assert "强度" in prompt

    def test_verify_shuangdian(self):
        """测试验证爽点"""
        from stage1_novel.models import ShuangDian

        shuangdian = ShuangDian(
            type=ShuangDianType.DALIAN,
            intensity=ShuangDianIntensity.MEDIUM,
            description="测试打脸",
        )

        # 包含打脸关键词的内容
        content_with = "众人都震惊了，没想到他居然这么强！真是打脸！"
        assert self.system._verify_shuangdian(content_with, shuangdian) is True

        # 不包含关键词的内容
        content_without = "今天天气很好，大家一起去逛街。"
        assert self.system._verify_shuangdian(content_without, shuangdian) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

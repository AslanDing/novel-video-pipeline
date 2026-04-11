"""
测试节奏控制器
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from stage1_novel.rhythm_controller import RhythmController
from stage1_novel.models import ChapterPlan, PlotPoint


class TestRhythmController:
    """测试节奏控制器"""

    def setup_method(self):
        """每个测试前运行"""
        self.controller = RhythmController()

    def test_select_chapter_template(self):
        """测试选择章节模板"""
        plot_structure = [PlotPoint(chapter=i, description=f"情节{i}") for i in range(1, 101)]

        # 开头章节
        template = self.controller.select_chapter_template(1, 100, plot_structure)
        assert template in ["standard", "climax"]

        # 中间章节
        template = self.controller.select_chapter_template(50, 100, plot_structure)
        assert template in ["standard", "climax", "transition"]

        # 高潮章节
        template = self.controller.select_chapter_template(80, 100, plot_structure)
        assert template in ["standard", "climax"]

        # 收尾章节
        template = self.controller.select_chapter_template(95, 100, plot_structure)
        assert template in ["climax", "transition"]

    def test_generate_rhythm_prompt(self):
        """测试生成节奏提示词"""
        chapter_plan = ChapterPlan(
            number=1,
            title="测试章节",
            summary="概要",
            key_events=["事件1"],
        )

        prompt = self.controller.generate_rhythm_prompt("standard", chapter_plan)
        assert "节奏要求" in prompt
        assert "章节类型" in prompt
        assert "章节结构" in prompt

        # 高潮章节
        prompt = self.controller.generate_rhythm_prompt("climax", chapter_plan)
        assert "高潮章节" in prompt

    def test_plan_novel_chapters(self):
        """测试规划小说章节"""
        plot_structure = [
            PlotPoint(chapter=i, description=f"第{i}章情节")
            for i in range(1, 11)
        ]

        plans = self.controller.plan_novel_chapters(10, plot_structure)

        # 验证有10章规划
        assert len(plans) == 10

        # 验证每章都有模板类型
        template_types = [p.template_type for p in plans]
        assert all(tt in ["standard", "climax", "transition"] for tt in template_types)

        # 应该有不同类型的模板
        assert len(set(template_types)) >= 2

    def test_chapter_templates_exist(self):
        """测试章节模板存在"""
        assert "standard" in self.controller.CHAPTER_TEMPLATES
        assert "climax" in self.controller.CHAPTER_TEMPLATES
        assert "transition" in self.controller.CHAPTER_TEMPLATES

        # 验证模板结构
        for template_name, template in self.controller.CHAPTER_TEMPLATES.items():
            assert "structure" in template
            assert "word_count" in template


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

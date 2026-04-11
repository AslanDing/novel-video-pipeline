"""
节奏控制器 - 控制爽文节奏
"""
from typing import List, Dict

from stages.stage1_novel.models import ChapterPlan, PlotPoint


class RhythmController:
    """爽文节奏控制"""

    CHAPTER_TEMPLATES = {
        "standard": {
            "structure": [
                {"section": "开场", "ratio": 0.1, "function": "承接上文"},
                {"section": "铺垫", "ratio": 0.2, "function": "营造氛围"},
                {"section": "冲突", "ratio": 0.3, "function": "矛盾爆发"},
                {"section": "高潮", "ratio": 0.25, "function": "爽点释放"},
                {"section": "收尾", "ratio": 0.15, "function": "悬念设置"}
            ],
            "word_count": "2000-3000"
        },
        "climax": {
            "structure": [
                {"section": "直入", "ratio": 0.1, "function": "直接冲突"},
                {"section": "升级", "ratio": 0.2, "function": "对抗升级"},
                {"section": "爆发", "ratio": 0.4, "function": "连续爽点"},
                {"section": "震撼", "ratio": 0.2, "function": "反转或收割"},
                {"section": "钩子", "ratio": 0.1, "function": "强烈悬念"}
            ],
            "word_count": "2500-3500"
        },
        "transition": {
            "structure": [
                {"section": "承接", "ratio": 0.3},
                {"section": "发展", "ratio": 0.4},
                {"section": "预示", "ratio": 0.3}
            ],
            "word_count": "1500-2000"
        }
    }

    def __init__(self):
        pass

    def select_chapter_template(
        self,
        chapter_number: int,
        total_chapters: int,
        plot_structure: List[PlotPoint]
    ) -> str:
        """选择章节模板类型"""
        ratio = chapter_number / total_chapters

        # 前20%：标准或高潮
        if ratio <= 0.2:
            if chapter_number % 3 == 0:
                return "climax"
            return "standard"

        # 20%-70%：发展期，混合使用
        elif ratio <= 0.7:
            if chapter_number % 5 == 0:
                return "climax"
            if chapter_number % 4 == 0:
                return "transition"
            return "standard"

        # 70%-90%：高潮期
        elif ratio <= 0.9:
            if chapter_number % 2 == 0:
                return "climax"
            return "standard"

        # 最后10%：收尾
        else:
            if chapter_number == total_chapters:
                return "climax"
            return "transition"

    def generate_rhythm_prompt(
        self,
        template: str,
        chapter_plan: ChapterPlan
    ) -> str:
        """生成带节奏要求的提示词"""
        template_config = self.CHAPTER_TEMPLATES.get(template, self.CHAPTER_TEMPLATES["standard"])

        prompt_parts = [
            f"【节奏要求】",
            f"章节类型: {'标准章节' if template == 'standard' else '高潮章节' if template == 'climax' else '过渡章节'}",
            f"目标字数: {template_config['word_count']}",
        ]

        structure = template_config.get("structure", [])
        if structure:
            prompt_parts.append("\n章节结构:")
            for part in structure:
                section_name = part.get("section", "")
                function = part.get("function", "")
                ratio = part.get("ratio", 0)
                prompt_parts.append(f"- {section_name} ({int(ratio*100)}%): {function}")

        prompt_parts.append("")
        return "\n".join(prompt_parts)

    def plan_novel_chapters(
        self,
        total_chapters: int,
        plot_structure: List[PlotPoint]
    ) -> List[ChapterPlan]:
        """
        规划整部小说的章节

        策略:
        - 前20%: 开篇吸引，快速爽点
        - 中间50%: 升级为主，间有小高潮
        - 后30%: 大高潮+收尾
        """
        chapter_plans = []

        for chapter_num in range(1, total_chapters + 1):
            template_type = self.select_chapter_template(
                chapter_num, total_chapters, plot_structure
            )

            # 从plot_structure中找到对应的情节点
            plot_point = None
            for pp in plot_structure:
                if pp.chapter == chapter_num:
                    plot_point = pp
                    break

            chapter_plan = ChapterPlan(
                number=chapter_num,
                title=f"第{chapter_num}章",
                summary=plot_point.description if plot_point else "",
                key_events=[plot_point.description] if plot_point else [],
                template_type=template_type,
            )

            chapter_plans.append(chapter_plan)

        return chapter_plans

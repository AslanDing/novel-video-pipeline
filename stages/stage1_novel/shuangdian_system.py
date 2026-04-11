"""
爽点系统 - 设计和管理小说爽点
"""
from typing import Dict, List, Optional
from dataclasses import asdict

from stages.stage1_novel.models import (
    ShuangDian, ShuangDianType, ShuangDianIntensity,
    ChapterPlan, NovelConcept, PlotPoint
)


class ShuangDianSystem:
    """爽点设计与管理核心类"""

    TYPES = {
        "打脸": {
            "subtypes": ["当众打脸", "身份反转打脸", "实力碾压打脸", "舆论反转打脸"],
            "triggers": ["众人嘲讽", "家族测试", "秘境开启", "大比"],
            "templates": ["主角被嘲笑 → 展现实力 → 众人震惊"],
        },
        "升级": {
            "subtypes": ["境界突破", "技能觉醒", "装备强化", "血脉觉醒"],
            "triggers": ["修炼", "战斗", "传承", "顿悟"],
            "templates": ["主角遇险 → 潜力爆发 → 突破"],
        },
        "收获": {
            "subtypes": ["意外传承", "天材地宝", "贵人相助", "空间发现"],
            "triggers": ["探险", "救人", "交易", "考核"],
            "templates": ["探索秘境 → 发现宝藏 → 收获满满"],
        },
        "反转": {
            "subtypes": ["身份揭露", "阴谋识破", "绝境逢生", "真相大白"],
            "triggers": ["对决", "危机", "审问", "回忆"],
            "templates": ["幕后黑手暴露 → 主角逆转"],
        }
    }

    PACING = {
        "开头": {"density": 0.3, "intensity": "high", "target": "快速抓住读者"},
        "发展": {"density": 0.5, "intensity": "medium", "target": "保持阅读快感"},
        "高潮": {"density": 0.8, "intensity": "extreme", "target": "情绪顶点"},
        "收尾": {"density": 0.4, "intensity": "medium", "target": "满足+期待"}
    }

    def __init__(self):
        pass

    def plan_distribution(self, total_chapters: int) -> Dict[int, ShuangDian]:
        """规划整部小说的爽点分布"""
        distribution = {}

        for chapter_num in range(1, total_chapters + 1):
            # 确定章节位置
            position = self._get_chapter_position(chapter_num, total_chapters)
            pacing = self.PACING[position]

            # 确定爽点类型
            shuangdian_type = self._select_shuangdian_type(chapter_num, total_chapters)

            # 确定强度
            intensity_map = {
                "low": ShuangDianIntensity.LOW,
                "medium": ShuangDianIntensity.MEDIUM,
                "high": ShuangDianIntensity.HIGH,
                "extreme": ShuangDianIntensity.EXTREME,
            }
            intensity = intensity_map.get(pacing["intensity"], ShuangDianIntensity.MEDIUM)

            # 创建爽点对象
            shuangdian = ShuangDian(
                type=shuangdian_type,
                intensity=intensity,
                description=f"{shuangdian_type.value}爽点",
                target_sections=["冲突", "高潮"]
            )

            distribution[chapter_num] = shuangdian

        return distribution

    def _get_chapter_position(self, chapter_num: int, total_chapters: int) -> str:
        """确定章节在小说中的位置"""
        ratio = chapter_num / total_chapters
        if ratio <= 0.2:
            return "开头"
        elif ratio <= 0.7:
            return "发展"
        elif ratio <= 0.9:
            return "高潮"
        else:
            return "收尾"

    def _select_shuangdian_type(self, chapter_num: int, total_chapters: int) -> ShuangDianType:
        """选择爽点类型"""
        # 循环使用四种爽点类型
        types = [ShuangDianType.DALIAN, ShuangDianType.UPGRADE,
                 ShuangDianType.HARVEST, ShuangDianType.REVERSE]

        # 前几章用打脸爽点快速抓住读者
        if chapter_num <= 3:
            return ShuangDianType.DALIAN

        return types[(chapter_num - 1) % len(types)]

    def generate_shuangdian_prompt(self, chapter_plan: ChapterPlan) -> str:
        """生成包含爽点要求的提示词"""
        if not chapter_plan.shuangdian:
            return ""

        shuangdian = chapter_plan.shuangdian
        type_config = self.TYPES.get(shuangdian.type.value, {})

        prompt_parts = [
            f"【爽点要求】",
            f"类型: {shuangdian.type.value}",
            f"强度: {'低' if shuangdian.intensity.value == 1 else '中' if shuangdian.intensity.value == 3 else '高' if shuangdian.intensity.value == 5 else '极高'}",
        ]

        if type_config.get("subtypes"):
            prompt_parts.append(f"推荐形式: {', '.join(type_config['subtypes'][:2])}")

        if type_config.get("templates"):
            prompt_parts.append(f"参考模板: {type_config['templates'][0]}")

        prompt_parts.append("")
        return "\n".join(prompt_parts)

    def _verify_shuangdian(self, content: str, shuangdian: ShuangDian) -> bool:
        """验证爽点是否存在于内容中"""
        # 简化版验证：检查是否包含相关关键词
        keywords = {
            ShuangDianType.DALIAN: ["打脸", "震惊", "傻眼", "难以置信", "没想到", "居然"],
            ShuangDianType.UPGRADE: ["突破", "觉醒", "升级", "进阶", "更强大", "实力大增"],
            ShuangDianType.HARVEST: ["获得", "得到", "发现", "宝藏", "传承", "空间", "宝物"],
            ShuangDianType.REVERSE: ["反转", "真相", "揭露", "原来", "竟然", "没想到"],
        }

        target_keywords = keywords.get(shuangdian.type, [])
        found = sum(1 for kw in target_keywords if kw in content)

        # 根据强度调整阈值
        threshold = {
            ShuangDianIntensity.LOW: 1,
            ShuangDianIntensity.MEDIUM: 2,
            ShuangDianIntensity.HIGH: 3,
            ShuangDianIntensity.EXTREME: 4,
        }

        return found >= threshold.get(shuangdian.intensity, 2)

    def build_system_prompt(self, shuangdian: ShuangDian, concept: NovelConcept) -> str:
        """构建包含爽点要求的系统提示词"""
        type_config = self.TYPES.get(shuangdian.type.value, {})

        prompt = f"""你是一位专业的{concept.genre}爽文小说作家。
            你的任务是创作引人入胜、节奏明快、爽点密集的网文章节。

            写作要求:
            1. 每章{concept.target_word_count}字左右
            2. 必须包含明显的爽点（打脸、升级、收获、反转等）
            3. 节奏要快，不拖沓，直接进入冲突
            4. 对话要生动，符合角色性格
            5. 描写要有画面感，适合改编成漫画
            6. 每章结尾要有悬念或钩子

            【本章爽点重点】
            类型: {shuangdian.type.value}
            强度: {'低' if shuangdian.intensity.value == 1 else '中' if shuangdian.intensity.value == 3 else '高' if shuangdian.intensity.value == 5 else '极高'}
            """

        if type_config.get("triggers"):
            prompt += f"触发场景: {', '.join(type_config['triggers'][:3])}\n"

        if type_config.get("templates"):
            prompt += f"情节模板: {type_config['templates'][0]}\n"

        prompt += f"\n风格: {concept.style}"
        return prompt

    def enhance_chapter_plan(self, chapter_plan: ChapterPlan, plot_point: Optional[PlotPoint] = None) -> ChapterPlan:
        """增强章节规划，添加爽点信息"""
        # 如果已有爽点，直接返回
        if chapter_plan.shuangdian:
            return chapter_plan

        # 根据情节点或章节号选择爽点
        shuangdian_type = None
        intensity = ShuangDianIntensity.MEDIUM

        if plot_point and plot_point.shuangdian_type:
            # 从情节点获取
            type_map = {
                "打脸": ShuangDianType.DALIAN,
                "升级": ShuangDianType.UPGRADE,
                "收获": ShuangDianType.HARVEST,
                "反转": ShuangDianType.REVERSE,
            }
            shuangdian_type = type_map.get(plot_point.shuangdian_type, ShuangDianType.DALIAN)

            intensity_map = {
                "low": ShuangDianIntensity.LOW,
                "medium": ShuangDianIntensity.MEDIUM,
                "high": ShuangDianIntensity.HIGH,
            }
            intensity = intensity_map.get(plot_point.intensity, ShuangDianIntensity.MEDIUM)
        else:
            # 默认根据章节号选择
            shuangdian_type = self._select_shuangdian_type(chapter_plan.number, 100)

        chapter_plan.shuangdian = ShuangDian(
            type=shuangdian_type,
            intensity=intensity,
            description=f"{shuangdian_type.value}爽点",
        )

        return chapter_plan

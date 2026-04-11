"""
一致性检查器 - 检查角色和设定一致性
"""
import re
from typing import List, Set, Dict, Tuple

from stages.stage1_novel.models import Chapter, StoryBlueprint, Character


class ConsistencyChecker:
    """角色和设定一致性检查"""

    def __init__(self):
        # 性格关键词映射
        self.personality_keywords = {
            "冷漠": ["冷漠", "冷淡", "面无表情", "神色平静", "不为所动"],
            "热情": ["热情", "热情洋溢", "笑容满面", "亲切", "爽朗"],
            "谨慎": ["谨慎", "小心", "警惕", "警觉", "三思而后行"],
            "鲁莽": ["鲁莽", "冲动", "不假思索", "直接冲上去", "不管不顾"],
            "聪慧": ["聪慧", "聪明", "机智", "心思缜密", "一眼看穿"],
            "坚毅": ["坚毅", "坚韧", "不屈不挠", "咬牙坚持", "绝不放弃"],
            "傲慢": ["傲慢", "高傲", "不屑", "轻蔑", "目中无人"],
            "谦虚": ["谦虚", "谦逊", "虚心", "不敢当", "过奖了"],
        }

        # 时间关键词
        self.time_keywords = {
            "季节": ["春天", "夏天", "秋天", "冬天", "春季", "夏季", "秋季", "冬季"],
            "时间": ["早晨", "上午", "中午", "下午", "傍晚", "晚上", "深夜", "黎明", "黄昏"],
            "日期": ["初一", "十五", "月初", "月末", "新年", "春节", "中秋"],
            "时间流逝": ["过了", "转眼间", "一晃", "三天后", "一个月后", "一年后"],
        }

        # 修炼等级关键词（通用修仙体系）
        self.cultivation_keywords = {
            "低阶": ["炼气", "筑基", "开光", "旋照"],
            "中阶": ["融合", "心动", "灵寂", "元婴"],
            "高阶": ["出窍", "分神", "合体", "渡劫", "大乘"],
            "禁忌": ["越阶", "越级挑战", "以弱胜强"],
        }

    def check_character_consistency(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> List[str]:
        """检查角色一致性"""
        issues = []

        # 检查角色名一致性
        name_issues = self._check_name_consistency(chapter, blueprint)
        issues.extend(name_issues)

        # 检查性格一致性（深度版）
        personality_issues = self._check_personality_consistency_detailed(
            chapter, blueprint, previous_chapters
        )
        issues.extend(personality_issues)

        return issues

    def _check_name_consistency(self, chapter: Chapter, blueprint: StoryBlueprint) -> List[str]:
        """检查角色名一致性"""
        issues = []
        content = chapter.content

        for char in blueprint.characters:
            # 检查是否使用了不同的名字变体
            name_variants = self._get_name_variants(char.name)
            used_names = set()

            for name in name_variants:
                if name in content:
                    used_names.add(name)

            if len(used_names) > 1:
                issues.append(f"角色{char.name}使用了多个称呼: {sorted(used_names)}")

        return issues

    def _get_name_variants(self, name: str) -> List[str]:
        """获取名字变体"""
        variants = [name]

        # 如果是中文名，可能有"小X"、"X兄"等变体
        if len(name) >= 2:
            variants.append(f"小{name[-1]}")
            variants.append(f"{name}兄")
            variants.append(f"{name}姑娘")
            variants.append(f"{name}师姐")
            variants.append(f"{name}师弟")

        return variants

    def _check_personality_consistency_detailed(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> List[str]:
        """深度性格一致性检查"""
        issues = []
        content = chapter.content

        for char in blueprint.characters:
            # 分析角色设定中的性格描述
            expected_traits = self._extract_personality_traits(char.personality)

            # 分析本章中该角色的行为
            actual_traits = self._extract_behavior_traits(content, char.name)

            # 检查是否有矛盾的性格表现
            conflicts = self._find_personality_conflicts(expected_traits, actual_traits)

            for conflict in conflicts:
                issues.append(f"角色{char.name}: {conflict}")

        return issues

    def _extract_personality_traits(self, personality_desc: str) -> Set[str]:
        """从性格描述中提取性格特征"""
        traits = set()

        for trait, keywords in self.personality_keywords.items():
            for kw in keywords:
                if kw in personality_desc:
                    traits.add(trait)
                    break

        return traits

    def _extract_behavior_traits(self, content: str, char_name: str) -> Set[str]:
        """从文本中提取角色行为特征"""
        traits = set()

        # 找到角色出现的上下文
        char_contexts = self._extract_char_contexts(content, char_name)

        for context in char_contexts:
            for trait, keywords in self.personality_keywords.items():
                for kw in keywords:
                    if kw in context:
                        traits.add(trait)
                        break

        return traits

    def _extract_char_contexts(self, content: str, char_name: str, window_size: int = 50) -> List[str]:
        """提取角色周围的文本上下文"""
        contexts = []
        pattern = re.compile(f'(.{{0,{window_size}}}{re.escape(char_name)}.{{0,{window_size}}})')
        matches = pattern.findall(content)
        return matches

    def _find_personality_conflicts(self, expected: Set[str], actual: Set[str]) -> List[str]:
        """找性格冲突"""
        conflicts = []

        # 定义互斥的性格对
        opposites = [
            ("冷漠", "热情"),
            ("谨慎", "鲁莽"),
            ("傲慢", "谦虚"),
        ]

        for a, b in opposites:
            if a in expected and b in actual:
                conflicts.append(f"设定为{a}，但本章表现出{b}的特征")
            if b in expected and a in actual:
                conflicts.append(f"设定为{b}，但本章表现出{a}的特征")

        return conflicts

    def check_timeline_consistency(
        self,
        chapter: Chapter,
        previous_chapters: List[Chapter]
    ) -> List[str]:
        """深度时间线一致性检查"""
        issues = []
        content = chapter.content

        # 提取本章的时间描述
        current_time = self._extract_time_info(content)

        # 提取前文的时间描述
        previous_times = []
        for prev in previous_chapters[-5:]:
            prev_time = self._extract_time_info(prev.content)
            if prev_time:
                previous_times.append((prev.number, prev_time))

        # 检查时间矛盾
        issues.extend(self._check_time_conflicts(current_time, previous_times))

        return issues

    def _extract_time_info(self, content: str) -> Dict[str, List[str]]:
        """从文本中提取时间信息"""
        time_info = {
            "season": [],
            "time_of_day": [],
            "date": [],
            "time_passed": [],
        }

        for category, keywords in self.time_keywords.items():
            for kw in keywords:
                if kw in content:
                    if category == "季节":
                        time_info["season"].append(kw)
                    elif category == "时间":
                        time_info["time_of_day"].append(kw)
                    elif category == "日期":
                        time_info["date"].append(kw)
                    elif category == "时间流逝":
                        time_info["time_passed"].append(kw)

        return time_info

    def _check_time_conflicts(
        self,
        current_time: Dict,
        previous_times: List[Tuple[int, Dict]]
    ) -> List[str]:
        """检查时间冲突"""
        issues = []

        if not previous_times:
            return issues

        # 检查季节矛盾
        current_seasons = set(current_time["season"])
        prev_seasons = set()
        for _, pt in previous_times:
            prev_seasons.update(pt["season"])

        if current_seasons and prev_seasons:
            # 简化检查：如果前文说冬天，本章说夏天，就是矛盾
            season_conflicts = []
            if "冬天" in prev_seasons and "夏天" in current_seasons:
                season_conflicts.append("冬天 → 夏天")
            if "夏天" in prev_seasons and "冬天" in current_seasons:
                season_conflicts.append("夏天 → 冬天")

            if season_conflicts:
                issues.append(f"可能的季节矛盾: {'，'.join(season_conflicts)}")

        return issues

    def check_world_rules_consistency(
        self,
        chapter: Chapter,
        world_building
    ) -> List[str]:
        """深度世界规则一致性检查"""
        issues = []
        content = chapter.content

        # 检查修炼体系一致性
        cultivation_issues = self._check_cultivation_consistency(content, world_building)
        issues.extend(cultivation_issues)

        return issues

    def _check_cultivation_consistency(self, content: str, world_building) -> List[str]:
        """检查修炼体系一致性"""
        issues = []

        power_system = world_building.power_system.lower()

        # 检查是否有明显的修炼等级矛盾
        found_levels = []
        for level_type, keywords in self.cultivation_keywords.items():
            for kw in keywords:
                if kw in content:
                    found_levels.append((level_type, kw))

        # 如果同时提到低阶和高阶，可能需要注意
        low_levels = [l for t, l in found_levels if t == "低阶"]
        high_levels = [l for t, l in found_levels if t == "高阶"]

        if low_levels and high_levels:
            issues.append(f"本章同时提到低阶({low_levels[:2]})和高阶({high_levels[:2]})修炼等级，请注意一致性")

        # 检查是否有"越阶"等关键词
        for kw in self.cultivation_keywords["禁忌"]:
            if kw in content:
                issues.append(f"检测到'{kw}'，请确保符合力量体系设定")

        return issues

    def check_all(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> List[str]:
        """运行所有一致性检查"""
        all_issues = []
        all_issues.extend(self.check_character_consistency(chapter, blueprint, previous_chapters))
        all_issues.extend(self.check_timeline_consistency(chapter, previous_chapters))
        all_issues.extend(self.check_world_rules_consistency(chapter, blueprint.world_building))
        return all_issues

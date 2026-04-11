"""
故事架构师 - 负责设计小说整体结构
"""

import json
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

# 导入asyncio
import asyncio

from stage1_novel.novel_generator import (
    NovelConcept, StoryBlueprint, WorldBuilding, 
    Character, PlotPoint, NovelGenerator
)


class StoryArchitect:
    """
    故事架构师
    
    负责：
    1. 世界观构建
    2. 角色设计
    3. 情节架构
    4. 章节规划
    """
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    async def create_blueprint(self, concept: NovelConcept) -> StoryBlueprint:
        """
        创建完整的故事蓝图
        
        这个方法在novel_generator.py中通过_direct_create_blueprint直接实现了
        这里提供一个替代实现用于更精细的控制
        """
        # 并行构建各个部分
        world_task = self._build_world(concept)
        characters_task = self._design_characters(concept)
        plot_task = self._design_plot(concept)
        
        world_building, characters, plot_structure = await asyncio.gather(
            world_task, characters_task, plot_task
        )
        
        # 生成章节规划
        chapter_plans = await self._plan_chapters(
            concept=concept,
            plot_structure=plot_structure,
            characters=characters,
        )
        
        return StoryBlueprint(
            title=concept.title,
            genre=concept.genre,
            world_building=world_building,
            characters=characters,
            plot_structure=plot_structure,
            chapter_plans=chapter_plans,
        )
    
    async def _build_world(self, concept: NovelConcept) -> WorldBuilding:
        """构建世界观"""
        prompt = f"""请为{concept.genre}小说《{concept.title}》设计详细的世界观。

核心创意: {concept.core_idea}

请包含以下内容：
1. 世界背景（时间、地点、整体氛围）
2. 力量/修炼体系（等级划分、修炼方式、能力类型）
3. 主要势力（宗门、家族、国家等，包含正邪分布）
4. 世界规则（天道法则、禁制、特殊规则等）

请以JSON格式输出：
{{
    "setting": "世界背景描述",
    "power_system": "力量体系详解",
    "factions": [
        {{"name": "势力名", "description": "描述", "type": "正/邪/中"}}
    ],
    "rules": ["规则1", "规则2"]
}}"""

        response = await self.llm_client.generate(
            prompt=prompt,
            system_prompt=f"你是专业的{concept.genre}世界观架构师。",
        )
        
        # 解析JSON
        data = self._extract_json(response.content)
        
        # 安全地提取字段，使用默认值
        setting = data.get("setting", "未设定世界背景")
        power_system = data.get("power_system", "未设定力量体系")
        factions = data.get("factions", [])
        rules = data.get("rules", [])
        
        return WorldBuilding(
            setting=setting,
            power_system=power_system,
            factions=factions,
            rules=rules,
        )
    
    async def _design_characters(self, concept: NovelConcept) -> List[Character]:
        """设计角色"""
        prompt = f"""请为{concept.genre}小说《{concept.title}》设计主要角色。

核心创意: {concept.core_idea}
计划章节数: {concept.total_chapters}

请设计以下角色：
1. 主角（必须有金手指或特殊能力）
2. 重要配角2-3人（可以是盟友、爱人、导师等）
3. 主要反派1-2人

每个角色需要包含：
- ID（英文标识符）
- 姓名
- 角色类型（protagonist, antagonist, supporting）
- 角色描述
- 性格特点
- 目标动机
- 背景故事
- 外貌描述（用于AI图像生成，请详细描述面部特征、发型、服装、气质等）

请以JSON数组格式输出：
[
    {{
        "id": "char_001",
        "name": "姓名",
        "role": "protagonist",
        "description": "描述",
        "personality": "性格",
        "goals": "目标",
        "background": "背景",
        "appearance": "外貌描述（越详细越好，用于AI画图）"
    }}
]"""

        response = await self.llm_client.generate(
            prompt=prompt,
            system_prompt=f"你是专业的{concept.genre}角色设计师。",
            max_tokens=6000,
        )
        
        # 解析JSON
        data = self._extract_json(response.content)
        
        characters = []
        for idx, char_data in enumerate(data):
            try:
                char = Character(
                    id=char_data.get("id", f"char_{idx:03d}"),
                    name=char_data.get("name", f"角色{idx+1}"),
                    role=char_data.get("role", "supporting"),
                    description=char_data.get("description", "暂无描述"),
                    personality=char_data.get("personality", "性格未知"),
                    goals=char_data.get("goals", "目标未定"),
                    background=char_data.get("background", "背景不明"),
                    appearance=char_data.get("appearance", "外貌未描述"),
                )
                characters.append(char)
            except Exception as e:
                print(f"   ⚠️  角色 {idx+1} 解析失败: {e}，跳过该角色")
                continue
        
        return characters
    
    async def _design_plot(self, concept: NovelConcept) -> List[PlotPoint]:
        """设计情节结构"""
        prompt = f"""请为{concept.genre}小说《{concept.title}》设计详细的情节结构。

核心创意: {concept.core_idea}
计划章节数: {concept.total_chapters}

请设计每一章的主要情节点，包含：
- 章节号
- 情节描述（本章核心冲突或事件）
- 爽点类型（打脸/升级/收获/反转/无）
- 强度（low/medium/high）

要求：
1. 开局（第1章）要有强烈的爽点或悬念
2. 每3章至少有一次中高强度爽点
3. 剧情要有起承转合，不能平淡
4. 每章结尾要有悬念或钩子

请以JSON数组格式输出：
[
    {{
        "chapter": 1,
        "description": "本章核心情节描述",
        "shuangdian_type": "打脸/升级/收获/反转/无",
        "intensity": "high"
    }}
]"""

        response = await self.llm_client.generate(
            prompt=prompt,
            system_prompt=f"你是专业的{concept.genre}情节设计师，擅长设计爽点密集的故事。",
        )
        
        # 解析JSON
        data = self._extract_json(response.content)
        
        plot_structure = []
        for idx, plot_data in enumerate(data):
            try:
                plot_point = PlotPoint(
                    chapter=plot_data.get("chapter", idx + 1),
                    description=plot_data.get("description", "暂无情节描述"),
                    shuangdian_type=plot_data.get("shuangdian_type"),
                    intensity=plot_data.get("intensity", "medium"),
                )
                plot_structure.append(plot_point)
            except Exception as e:
                print(f"   ⚠️  情节点 {idx+1} 解析失败: {e}，跳过该情节点")
                continue
        
        return plot_structure
    
    async def _plan_chapters(
        self,
        concept: NovelConcept,
        plot_structure: List[PlotPoint],
        characters: List[Character],
    ) -> List[Dict]:
        """规划所有章节的详细内容"""
        # 这里可以添加更复杂的章节规划逻辑
        # 目前直接返回基于plot_structure生成的章节规划
        
        chapter_plans = []
        for plot_point in plot_structure:
            chapter_plans.append({
                "number": plot_point.chapter,
                "title": f"第{plot_point.chapter}章",  # 临时标题，实际生成时会更新
                "summary": plot_point.description,
                "key_events": [plot_point.description],
                "shuangdian": f"{plot_point.shuangdian_type} ({plot_point.intensity})",
            })
        
        return chapter_plans
    
    def _extract_json(self, content: str) -> any:
        """从文本中提取JSON"""
        import json
        import re
        
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取JSON块
        patterns = [
            r'```json\s*(.*?)\s*```',  # Markdown代码块
            r'\{.*\}',  # 花括号包裹的内容
            r'\[.*\]',  # 方括号包裹的内容
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        # 如果都失败了， raise错误
        raise ValueError(f"无法从响应中提取JSON: {content[:500]}")


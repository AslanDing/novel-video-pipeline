"""
小说生成模块数据模型
统一管理所有数据类定义
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class ShuangDianType(Enum):
    """爽点类型"""
    DALIAN = "打脸"        # 当众打脸、身份反转
    UPGRADE = "升级"       # 境界突破、技能觉醒
    HARVEST = "收获"       # 意外传承、天材地宝
    REVERSE = "反转"       # 身份揭露、阴谋识破


class ShuangDianIntensity(Enum):
    """爽点强度"""
    LOW = 1
    MEDIUM = 3
    HIGH = 5
    EXTREME = 8


@dataclass
class ShuangDian:
    """单个爽点"""
    type: ShuangDianType
    intensity: ShuangDianIntensity
    description: str
    target_sections: List[str] = field(default_factory=list)


@dataclass
class ChapterPlan:
    """章节规划"""
    number: int
    title: str
    summary: str
    key_events: List[str]
    shuangdian: Optional[ShuangDian] = None
    template_type: str = "standard"  # standard / climax / transition


@dataclass
class QualityScore:
    """质量评分"""
    overall: float  # 0-10
    shuangdian_score: float  # 爽点密度
    coherence_score: float   # 连贯性
    readability_score: float # 可读性
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "overall": self.overall,
            "shuangdian_score": self.shuangdian_score,
            "coherence_score": self.coherence_score,
            "readability_score": self.readability_score,
            "issues": self.issues,
        }


@dataclass
class PlotPoint:
    """情节点"""
    chapter: int
    description: str
    shuangdian_type: Optional[str] = None
    intensity: str = "medium"


@dataclass
class WorldBuilding:
    """世界观设定"""
    setting: str
    power_system: str
    factions: List[Dict]
    rules: List[str]

    def to_dict(self) -> Dict:
        return {
            "setting": self.setting,
            "power_system": self.power_system,
            "factions": self.factions,
            "rules": self.rules,
        }


@dataclass
class Character:
    """角色设定"""
    id: str
    name: str
    role: str  # protagonist, antagonist, supporting
    description: str
    personality: str
    goals: str
    background: str
    appearance: str
    age: Optional[str] = None           # young, middle, old
    gender: Optional[str] = None         # male, female
    voice_type: Optional[str] = None    # narrator, protagonist, antagonist, etc.

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "personality": self.personality,
            "goals": self.goals,
            "background": self.background,
            "appearance": self.appearance,
            "age": self.age,
            "gender": self.gender,
            "voice_type": self.voice_type,
        }


@dataclass
class ScriptLine:
    """单个分镜脚本行 (JSONL级别的数据)"""
    scene_id: str
    shot_id: str
    role: str  # dialogue 或者 narrator
    speaker: str  # 角色名或者旁白
    text: str
    emotion: str
    visual_prompt: str
    motion_prompt: str
    camera: str
    estimated_duration: float

    def to_dict(self) -> Dict:
        return {
            "scene_id": self.scene_id,
            "shot_id": self.shot_id,
            "role": self.role,
            "speaker": self.speaker,
            "text": self.text,
            "emotion": self.emotion,
            "visual_prompt": self.visual_prompt,
            "motion_prompt": self.motion_prompt,
            "camera": self.camera,
            "estimated_duration": self.estimated_duration,
        }

@dataclass
class StoryBlueprint:
    """故事蓝图"""
    title: str
    genre: str
    world_building: WorldBuilding
    characters: List[Character]
    plot_structure: List[PlotPoint]
    chapter_plans: List[Dict]

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "genre": self.genre,
            "world_building": self.world_building.to_dict(),
            "characters": [c.to_dict() for c in self.characters],
            "plot_structure": [
                {
                    "chapter": p.chapter,
                    "description": p.description,
                    "shuangdian_type": p.shuangdian_type,
                    "intensity": p.intensity,
                }
                for p in self.plot_structure
            ],
            "chapter_plans": self.chapter_plans,
        }


@dataclass
class Chapter:
    """章节内容"""
    number: int
    title: str
    content: str
    word_count: int
    summary: str
    key_events: List[str]
    character_appearances: List[str]
    script_lines: List[ScriptLine] = field(default_factory=list)
    quality_score: Optional[QualityScore] = None

    def to_dict(self) -> Dict:
        data = {
            "number": self.number,
            "title": self.title,
            "content": self.content,
            "word_count": self.word_count,
            "summary": self.summary,
            "key_events": self.key_events,
            "character_appearances": self.character_appearances,
            "script_lines": [sl.to_dict() for sl in self.script_lines],
        }
        if self.quality_score:
            data["quality_score"] = self.quality_score.to_dict()
        return data


@dataclass
class NovelConcept:
    """小说创意概念"""
    title: str
    genre: str
    style: str
    core_idea: str
    total_chapters: int = 3
    target_word_count: int = 5000
    shuangdian_intensity: str = "high"

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "genre": self.genre,
            "style": self.style,
            "core_idea": self.core_idea,
            "total_chapters": self.total_chapters,
            "target_word_count": self.target_word_count,
            "shuangdian_intensity": self.shuangdian_intensity,
        }


@dataclass
class Novel:
    """完整小说"""
    metadata: Dict
    blueprint: StoryBlueprint
    chapters: List[Chapter]

    def to_dict(self) -> Dict:
        return {
            "metadata": self.metadata,
            "blueprint": self.blueprint.to_dict(),
            "chapters": [c.to_dict() for c in self.chapters],
        }

    def save(self, output_dir):
        """保存小说到文件 - 按照设计文档标准的纯本地存储文件模式"""
        from pathlib import Path
        import json
        from datetime import datetime

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 新标准目录结构
        data_dir = output_dir / "data"
        chapters_dir = data_dir / "chapters"
        scripts_dir = data_dir / "scripts"
        
        data_dir.mkdir(exist_ok=True)
        chapters_dir.mkdir(exist_ok=True)
        scripts_dir.mkdir(exist_ok=True)

        # 1. 保存小说设定 (story_bible)
        bible_path = data_dir / "story_bible.json"
        with open(bible_path, 'w', encoding='utf-8') as f:
            json.dump({
                "metadata": self.metadata,
                "blueprint": self.blueprint.to_dict()
            }, f, ensure_ascii=False, indent=2)

        # 2. 遍历各章并保存对应的 MD 正文 / Summary / JSONL
        for chapter in self.chapters:
            # 2.1 保存 Markdown 正文
            md_path = chapters_dir / f"chapter_{chapter.number:03d}.md"
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# 第{chapter.number}章 {chapter.title}\n\n")
                f.write(chapter.content)
                f.write("\n")
            
            # 2.2 保存章节的摘要分析
            meta_path = chapters_dir / f"chapter_{chapter.number:03d}_summary.json"
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "number": chapter.number,
                    "title": chapter.title,
                    "summary": chapter.summary,
                    "key_events": chapter.key_events,
                    "character_appearances": chapter.character_appearances,
                    "word_count": chapter.word_count
                }, f, ensure_ascii=False, indent=2)

            # 2.3 最核心的部分：保存拆分后的镜头 JSONL 脚本
            if chapter.script_lines:
                jsonl_path = scripts_dir / f"script_{chapter.number:03d}.jsonl"
                with open(jsonl_path, 'w', encoding='utf-8') as f:
                    for line in chapter.script_lines:
                        # 确保每一行都是一个 JSON 反序列化项
                        f.write(json.dumps(line.to_dict(), ensure_ascii=False) + "\n")

        print(f"\n💾 小说与脚本核心资产已成功归档到: {output_dir}")
        print(f"   - 全局设定(Bible): {bible_path.relative_to(output_dir.parent)}")
        print(f"   - 结构化正文(MD): {chapters_dir.relative_to(output_dir.parent)}/")
        print(f"   - 核心分镜脚本(JSONL): {scripts_dir.relative_to(output_dir.parent)}/")

        return output_dir


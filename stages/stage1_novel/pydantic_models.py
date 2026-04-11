from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal, Dict, Any

class WorldBuildingSchema(BaseModel):
    """世界观设定模型"""
    setting: str = Field(description="世界描述，涵盖历史、地理和当前局示", min_length=200)
    power_system: str = Field(description="修炼体系、力量等级划分及其核心逻辑")
    factions: List[Dict[str, str]] = Field(description="主要势力列表，每项包含 name, description, type (正/邪/中)")
    rules: List[str] = Field(description="世界运行的核心规则或禁忌")

    model_config = ConfigDict(extra="forbid")

class CharacterSchema(BaseModel):
    """角色设定模型"""
    id: str = Field(description="唯一标识符，如 char_001")
    name: str = Field(description="角色姓名")
    role: Literal["protagonist", "antagonist", "supporting"] = Field(description="角色身份：主角、反派、配角")
    description: str = Field(description="核心特质、性格和简短生平")
    personality: str = Field(description="详细性格描写")
    goals: str = Field(description="角色的长期和短期目标")
    background: str = Field(description="背景故事")
    appearance: str = Field(description="外貌细节描述，用于 AI 绘画提示词生成")

    model_config = ConfigDict(extra="forbid")

class PlotPointSchema(BaseModel):
    """大纲情节点模型"""
    chapter: int = Field(description="对应的起始章节号")
    description: str = Field(description="该阶段的核心冲突和情节发展")
    shuangdian_type: Optional[str] = Field(None, description="主要的爽点类型，如打脸、升级、奇遇、反转")
    intensity: Literal["low", "medium", "high", "extreme"] = Field("medium", description="情感或冲突强度")

    model_config = ConfigDict(extra="forbid")

class ChapterPlanSchema(BaseModel):
    """章节详细规划模型"""
    number: int = Field(description="章节号")
    title: str = Field(description="章节标题")
    summary: str = Field(description="本章内容概要")
    key_events: List[str] = Field(description="本章必须发生的关键事件列表")
    shuangdian: Optional[str] = Field(None, description="本章的具体爽点设计")

    model_config = ConfigDict(extra="forbid")

class StoryBlueprintOutput(BaseModel):
    """故事蓝图完整输出模型"""
    world_building: WorldBuildingSchema = Field(description="世界观架构")
    characters: List[CharacterSchema] = Field(description="核心角色库", min_length=1)
    plot_structure: List[PlotPointSchema] = Field(description="主线剧情结构")
    chapter_plans: List[ChapterPlanSchema] = Field(description="各章节细化规划")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "required": ["world_building", "characters", "plot_structure", "chapter_plans"]
        }
    )

class ChapterOutput(BaseModel):
    """单章节生成正文模型"""
    title: str = Field(description="章节最终标题")
    content: str = Field(description="章节完整正文内容，要求描写细腻，增加细节、对白和环境描写，字数尽量多", min_length=3000)
    summary: str = Field(description="本章内容精炼摘要")
    key_events: List[str] = Field(description="实际发生的关键事件")
    character_appearances: List[str] = Field(description="本章出场的所有角色姓名")

    model_config = ConfigDict(extra="forbid")


class ChunkOutput(BaseModel):
    """章节分块生成模型（单块正文）"""
    content: str = Field(
        description="本段落的完整正文内容，要求对白、心理、环境描写丰富，字数不少于1500字",
        min_length=800
    )
    summary: Optional[str] = Field(None, description="本段落的简要内容概括")
    key_events: Optional[List[str]] = Field(None, description="本段落中发生的关键事件列表")
    character_appearances: Optional[List[str]] = Field(None, description="本段落中出场的角色姓名列表")

    model_config = ConfigDict(extra="forbid")

class ScriptLineSchema(BaseModel):
    """视频分镜脚本行模型"""
    scene_id: str = Field(description="场景ID，如 SC01")
    shot_id: str = Field(description="镜头ID，如 SC01_SH01")
    role: Literal["dialogue", "narrator"] = Field(description="内容类别：对白或旁白")
    speaker: str = Field(description="发声者名称，如果是旁白则填 narrator")
    text: str = Field(description="需要朗读的文本内容")
    emotion: Optional[str] = Field("calm", description="情感标签，如 angry, calm, crying, sneering")
    visual_prompt: Optional[str] = Field("", description="英文画面描述提示词，包含人设、环境、光影")
    motion_prompt: Optional[str] = Field("", description="镜头运动指引，如 slow push in, pan right")
    camera: Optional[str] = Field("", description="景别，如 close-up, medium shot")
    estimated_duration: Optional[float] = Field(3.0, description="预计语音时长（秒）")

    model_config = ConfigDict(extra="forbid")

class ScriptOutput(BaseModel):
    """分镜脚本完整输出模型"""
    script: List[ScriptLineSchema] = Field(description="分条目的分镜脚本列表")

    model_config = ConfigDict(extra="forbid")

# ========== 拆分蓝图生成用的 Output 模型 ==========

class WorldBuildingOutput(BaseModel):
    """世界观输出模型"""
    setting: str = Field(description="世界描述，涵盖历史、地理和当前局势", min_length=200)
    factions: List[Dict[str, str]] = Field(description="主要势力列表，每项包含 name, description, type (正/邪/中)")
    rules: List[str] = Field(description="世界运行的核心规则或禁忌")

    model_config = ConfigDict(extra="forbid")


class CharactersOutput(BaseModel):
    """角色列表输出模型"""
    characters: List[CharacterSchema] = Field(description="核心角色库", min_length=1, max_length=10)

    model_config = ConfigDict(extra="forbid")


class PowerSystemOutput(BaseModel):
    """修炼体系输出模型"""
    power_system: str = Field(description="修炼体系、力量等级划分及其核心逻辑")
    cultivation_realms: List[Dict[str, str]] = Field(description="修炼境界列表，每项包含 name, description, level")

    model_config = ConfigDict(extra="forbid")


class PlotStructureOutput(BaseModel):
    """情节结构输出模型"""
    plot_structure: List[PlotPointSchema] = Field(description="主线剧情结构")

    model_config = ConfigDict(extra="forbid")


class ChapterPlansOutput(BaseModel):
    """章节规划输出模型"""
    chapter_plans: List[ChapterPlanSchema] = Field(description="各章节细化规划")

    model_config = ConfigDict(extra="forbid")

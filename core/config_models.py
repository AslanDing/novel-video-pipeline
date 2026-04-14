"""
Three-Layer Configuration Model

Layer 1: Project Preset (项目级别，稳定)
Layer 2: Chapter Manifest (章节级别，较稳定)
Layer 3: Shot Spec (镜头级别，频繁变化)

这是整个资产优先(Asset-First)工作流的核心配置模型。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
from pathlib import Path
import json


class VideoMode(str, Enum):
    """视频生成模式"""
    I2V = "i2v"           # 图生视频
    T2V = "t2v"           # 文生视频
    COMPOSE = "compose"    # 图像+音频合成
    KEN_BURNS = "ken_burns"  # Ken Burns 静态效果


class ShotStatus(str, Enum):
    """镜头状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConsistencyPolicy:
    """一致性策略配置"""
    def __init__(
        self,
        character_default: float = 0.8,
        scene_default: float = 0.6,
        seed_strategy: str = "fixed_per_character",
    ):
        self.character_default = character_default
        self.scene_default = scene_default
        self.seed_strategy = seed_strategy  # fixed_per_character, random, fixed_global

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ConsistencyPolicy":
        return cls(
            character_default=data.get("character_default", 0.8),
            scene_default=data.get("scene_default", 0.6),
            seed_strategy=data.get("seed_strategy", "fixed_per_character"),
        )


class OutputSettings:
    """输出设置"""
    def __init__(
        self,
        resolution: str = "1280x720",
        fps: int = 24,
        format: str = "mp4",
        video_codec: str = "libx264",
        bitrate: str = "4000k",
    ):
        self.resolution = resolution
        self.fps = fps
        self.format = format
        self.video_codec = video_codec
        self.bitrate = bitrate

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "OutputSettings":
        return cls(
            resolution=data.get("resolution", "1280x720"),
            fps=data.get("fps", 24),
            format=data.get("format", "mp4"),
            video_codec=data.get("video_codec", "libx264"),
            bitrate=data.get("bitrate", "4000k"),
        )


@dataclass
class ProjectPreset:
    """
    Layer 1: 项目预设（项目级别，稳定）

    定义项目的全局配置，包括视觉风格、工作流选择、一致性策略等。
    """
    project_id: str
    title: str
    genre: str
    visual_style: str = "cinematic"  # cinematic, anime, realistic, etc.
    default_image_workflow: str = "character_keyframe_sd35_v1"
    default_video_workflow: str = "hunyuan15_i2v_v1"
    default_tts_voice_map: Dict[str, str] = field(default_factory=dict)
    consistency_policy: ConsistencyPolicy = field(default_factory=ConsistencyPolicy)
    output_settings: OutputSettings = field(default_factory=OutputSettings)
    enabled_services: Dict[str, bool] = field(default_factory=lambda: {
        "character_pack": True,
        "scene_pack": True,
        "tts": True,
        "sfx": False,
        "bgm": False,
    })

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "genre": self.genre,
            "visual_style": self.visual_style,
            "default_image_workflow": self.default_image_workflow,
            "default_video_workflow": self.default_video_workflow,
            "default_tts_voice_map": self.default_tts_voice_map,
            "consistency_policy": self.consistency_policy.to_dict(),
            "output_settings": self.output_settings.to_dict(),
            "enabled_services": self.enabled_services,
        }

    def save(self, output_dir: Path):
        """保存到文件"""
        path = output_dir / "project_preset.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, project_dir: Path) -> "ProjectPreset":
        """从文件加载"""
        path = project_dir / "project_preset.json"
        if not path.exists():
            raise FileNotFoundError(f"Project preset not found: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict) -> "ProjectPreset":
        """从字典创建"""
        return cls(
            project_id=data["project_id"],
            title=data["title"],
            genre=data["genre"],
            visual_style=data.get("visual_style", "cinematic"),
            default_image_workflow=data.get("default_image_workflow", "character_keyframe_sd35_v1"),
            default_video_workflow=data.get("default_video_workflow", "hunyuan15_i2v_v1"),
            default_tts_voice_map=data.get("default_tts_voice_map", {}),
            consistency_policy=ConsistencyPolicy.from_dict(data.get("consistency_policy", {})),
            output_settings=OutputSettings.from_dict(data.get("output_settings", {})),
            enabled_services=data.get("enabled_services", {"character_pack": True, "scene_pack": True, "tts": True, "sfx": False, "bgm": False}),
        )


@dataclass
class ChapterManifest:
    """
    Layer 2: 章节清单（章节级别，较稳定）

    定义单个章节的完整配置，包括场景顺序、角色列表、所需资产、镜头列表。
    """
    chapter_id: str
    project_id: str
    chapter_number: int
    scene_order: List[str] = field(default_factory=list)
    characters_involved: List[str] = field(default_factory=list)
    required_assets: List[str] = field(default_factory=list)  # 角色包和场景包ID列表
    shots: List[str] = field(default_factory=list)  # shot_id 列表
    tts_required: bool = True
    estimated_duration: float = 0.0  # 预估总时长（秒）
    status: str = "pending"  # pending, in_progress, completed, failed

    def to_dict(self) -> Dict:
        return {
            "chapter_id": self.chapter_id,
            "project_id": self.project_id,
            "chapter_number": self.chapter_number,
            "scene_order": self.scene_order,
            "characters_involved": self.characters_involved,
            "required_assets": self.required_assets,
            "shots": self.shots,
            "tts_required": self.tts_required,
            "estimated_duration": self.estimated_duration,
            "status": self.status,
        }

    def save(self, output_dir: Path):
        """保存到文件"""
        path = output_dir / f"{self.chapter_id}_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, manifest_path: Path) -> "ChapterManifest":
        """从文件加载"""
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict) -> "ChapterManifest":
        """从字典创建"""
        return cls(
            chapter_id=data["chapter_id"],
            project_id=data["project_id"],
            chapter_number=data["chapter_number"],
            scene_order=data.get("scene_order", []),
            characters_involved=data.get("characters_involved", []),
            required_assets=data.get("required_assets", []),
            shots=data.get("shots", []),
            tts_required=data.get("tts_required", True),
            estimated_duration=data.get("estimated_duration", 0.0),
            status=data.get("status", "pending"),
        )


@dataclass
class ShotSpec:
    """
    Layer 3: 镜头规格（镜头级别，频繁变化）

    定义单个镜头的完整配置，包括工作流、角色、场景、拍摄参数等。
    """
    shot_id: str
    chapter_id: str
    workflow: str = "character_closeup_i2v_v1"
    purpose: str = ""  # 意图描述
    characters: List[str] = field(default_factory=list)
    scene: str = ""  # 场景名称
    shot_type: str = "medium"  # wide, medium, close-up, extreme close-up
    mood: str = "neutral"  # tense, calm, dark, bright
    dialogue: Optional[str] = None
    narrator: Optional[str] = None
    needs_character_consistency: bool = True
    needs_scene_consistency: bool = True
    video_mode: VideoMode = VideoMode.I2V
    # 关键帧路径
    keyframes: Dict[str, Optional[str]] = field(default_factory=lambda: {
        "start": None,
        "end": None,
    })
    tts_line_id: Optional[str] = None  # 关联的 TTS 行 ID
    status: ShotStatus = ShotStatus.PENDING
    # 生成结果
    result_image: Optional[str] = None
    result_video: Optional[str] = None
    result_audio: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "shot_id": self.shot_id,
            "chapter_id": self.chapter_id,
            "workflow": self.workflow,
            "purpose": self.purpose,
            "characters": self.characters,
            "scene": self.scene,
            "shot_type": self.shot_type,
            "mood": self.mood,
            "dialogue": self.dialogue,
            "narrator": self.narrator,
            "needs_character_consistency": self.needs_character_consistency,
            "needs_scene_consistency": self.needs_scene_consistency,
            "video_mode": self.video_mode.value if isinstance(self.video_mode, Enum) else self.video_mode,
            "keyframes": self.keyframes,
            "tts_line_id": self.tts_line_id,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "result_image": self.result_image,
            "result_video": self.result_video,
            "result_audio": self.result_audio,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ShotSpec":
        """从字典创建"""
        video_mode = data.get("video_mode", "i2v")
        if isinstance(video_mode, str):
            video_mode = VideoMode(video_mode)

        status = data.get("status", "pending")
        if isinstance(status, str):
            status = ShotStatus(status)

        return cls(
            shot_id=data["shot_id"],
            chapter_id=data["chapter_id"],
            workflow=data.get("workflow", "character_closeup_i2v_v1"),
            purpose=data.get("purpose", ""),
            characters=data.get("characters", []),
            scene=data.get("scene", ""),
            shot_type=data.get("shot_type", "medium"),
            mood=data.get("mood", "neutral"),
            dialogue=data.get("dialogue"),
            narrator=data.get("narrator"),
            needs_character_consistency=data.get("needs_character_consistency", True),
            needs_scene_consistency=data.get("needs_scene_consistency", True),
            video_mode=video_mode,
            keyframes=data.get("keyframes", {"start": None, "end": None}),
            tts_line_id=data.get("tts_line_id"),
            status=status,
            result_image=data.get("result_image"),
            result_video=data.get("result_video"),
            result_audio=data.get("result_audio"),
        )


def create_default_project_preset(project_id: str, title: str, genre: str) -> ProjectPreset:
    """创建默认项目预设"""
    default_voice_map = {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "male_1": "zh-CN-YunxiNeural",
        "male_2": "zh-CN-YunjianNeural",
        "male_3": "zh-CN-YunyangNeural",
        "male_4": "zh-CN-YunhaoNeural",
        "female_1": "zh-CN-XiaoyiNeural",
        "female_2": "zh-CN-liaoning-XiaobeiNeural",
        "female_3": "zh-CN-XiaohanNeural",
        "female_4": "zh-CN-XiaomengNeural",
    }

    return ProjectPreset(
        project_id=project_id,
        title=title,
        genre=genre,
        visual_style="cinematic",
        default_image_workflow="character_keyframe_sd35_v1",
        default_video_workflow="hunyuan15_i2v_v1",
        default_tts_voice_map=default_voice_map,
        consistency_policy=ConsistencyPolicy(),
        output_settings=OutputSettings(),
        enabled_services={
            "character_pack": True,
            "scene_pack": True,
            "tts": True,
            "sfx": False,
            "bgm": False,
        },
    )

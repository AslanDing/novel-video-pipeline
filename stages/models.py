"""
跨阶段共享的数据模型
用于 Stage 1-4 之间的数据传递
"""

from pydantic import BaseModel
from typing import List, Optional, Dict
from pathlib import Path


class ScriptLine(BaseModel):
    """分镜脚本行 - Stage 1 输出，Stage 2/3/4 共享"""
    scene_id: str           # 场景ID（如 SC01）
    shot_id: str            # 镜头ID（如 SC01_SH01）
    role: str               # dialogue 或 narrator
    speaker: str            # 发声者名称
    text: str               # 朗读文本
    emotion: str            # 情绪标签
    visual_prompt: str      # 图片生成英文提示词
    motion_prompt: str      # 镜头运动指引
    camera: str             # 景别描述
    estimated_duration: float  # 预估时长(秒)


class TimelineEntry(BaseModel):
    """时间线条目 - Stage 3 输出，Stage 4 使用"""
    shot_id: str
    scene_id: str
    speaker: str
    text: str
    audio_file: str
    image_file: Optional[str] = None
    start_time: float
    end_time: float
    duration: float
    emotion: str = "neutral"


class TimelineManifest(BaseModel):
    """时间线清单 - Stage 3 输出"""
    chapter_number: int
    total_duration: float
    entries: List[TimelineEntry]


class CharacterPortrait(BaseModel):
    """角色定妆照信息"""
    character_id: str
    character_name: str
    portrait_path: Optional[str] = None
    appearance_prompt: str


def get_script_path(data_dir: Path, chapter_number: int) -> Path:
    """脚本文件路径的唯一定义处 — 修改格式只需改这里"""
    return data_dir / "scripts" / f"script_{chapter_number:03d}.jsonl"


def load_script_lines(novel_title: str, chapter_number: int, data_dir: Path) -> List[ScriptLine]:
    """加载分镜脚本"""
    import json
    script_path = get_script_path(data_dir, chapter_number)
    if not script_path.exists():
        return []
    
    script_lines = []
    with open(script_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    script_lines.append(ScriptLine(**json.loads(line)))
                except:
                    try:
                        script_lines.append(ScriptLine(**eval(line)))
                    except:
                        pass
    return script_lines


def save_timeline_manifest(manifest: TimelineManifest, output_dir: Path):
    """保存时间线清单"""
    timeline_path = output_dir / f"timeline_ch{manifest.chapter_number:03d}.json"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    
    import json
    with open(timeline_path, 'w', encoding='utf-8') as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)


def load_timeline_manifest(novel_title: str, chapter_number: int, audio_dir: Path) -> Optional[TimelineManifest]:
    """加载时间线清单"""
    timeline_path = audio_dir / f"timeline_ch{chapter_number:03d}.json"
    if not timeline_path.exists():
        return None
    
    import json
    with open(timeline_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return TimelineManifest(**data)


def check_file_exists(file_path: str) -> bool:
    """检查文件是否存在"""
    return Path(file_path).exists() if file_path else False
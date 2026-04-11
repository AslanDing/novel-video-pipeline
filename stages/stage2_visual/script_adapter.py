"""
脚本适配器 - 读取 Stage 1 产出的 script_x.jsonl
以及角色定妆照管理
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
import asyncio

from core.logger import get_logger
from stages.models import get_script_path

logger = get_logger("script_adapter")


class ScriptAdapter:
    """脚本适配器 - 读取 Stage 1 产出的分镜脚本"""
    
    def __init__(self, novel_title: str, data_dir: Path):
        self.novel_title = novel_title
        self.data_dir = Path(data_dir)
    
    def load_script_lines(self, chapter_number: int) -> List[Dict]:
        """加载指定章节的分镜脚本"""
        script_path = get_script_path(self.data_dir, chapter_number)
        
        if not script_path.exists():
            logger.warning(f"分镜脚本不存在: {script_path}")
            return []
        
        script_lines = []
        with open(script_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    # 使用 json.loads 替换 eval 以提高安全性与稳定性
                    data = json.loads(line)
                    script_lines.append(data)
                except Exception as e:
                    try:
                        # 兼容某些可能被存为 str(dict) 的旧格式
                        script_lines.append(eval(line))
                    except:
                        logger.warning(f"解析脚本行失败: {e}")
        
        logger.info(f"加载了第{chapter_number}章的{len(script_lines)}个分镜")
        return script_lines
    
    def get_scenes_from_scripts(self, script_lines: List[Dict]) -> List[Dict]:
        """从脚本行中提取场景信息"""
        scenes = {}
        ordered_scenes = []
        
        for i, line in enumerate(script_lines):
            # 优先使用 scene_id，如果没有则尝试从 shot_id 推断，最后使用行号
            scene_id = line.get('scene_id') or line.get('shot_id', '').split('_shot')[0] or f"scene_{i+1}"
            
            if scene_id not in scenes:
                scenes[scene_id] = {
                    'scene_id': scene_id,
                    'shots': [],
                    'description': line.get('visual_prompt', ''),
                }
                ordered_scenes.append(scene_id)
            
            scenes[scene_id]['shots'].append(line)
        
        return [scenes[sid] for sid in ordered_scenes]

    def get_shots_as_scenes(self, script_lines: List[Dict]) -> List[Dict]:
        """将每个分镜(shot)转换为一张独立的配图场景，使得图像生成器为每个分镜都生成配图"""
        scenes = []
        for i, shot in enumerate(script_lines):
            scenes.append({
                'scene_number': i + 1,
                'description': shot.get('visual_prompt', ''),
                'key_elements': [],
                'characters_present': [],
                'mood': shot.get('emotion', 'neutral'),
                'setting': '',
                'shot_type': shot.get('camera', 'medium'),
                'motion_prompt': shot.get('motion_prompt', ''),
                'visual_prompt': shot.get('visual_prompt', ''),
                'shot_id': shot.get('shot_id', f'shot_{i+1}'),
                'scene_id': shot.get('scene_id', ''),
                'duration': shot.get('estimated_duration', 3.0),
                'speaker': shot.get('speaker', ''),
                'text': shot.get('text', ''),
            })
        return scenes
    
    def extract_visual_prompts(self, script_lines: List[Dict]) -> List[Dict]:
        """提取所有视觉提示词"""
        prompts = []
        
        for line in script_lines:
            prompts.append({
                'shot_id': line.get('shot_id', ''),
                'scene_id': line.get('scene_id', ''),
                'visual_prompt': line.get('visual_prompt', ''),
                'motion_prompt': line.get('motion_prompt', ''),
                'camera': line.get('camera', 'medium'),
                'emotion': line.get('emotion', 'neutral'),
            })
        
        return prompts


class CharacterPortraitManager:
    """角色定妆照管理器"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.roles_dir = self.output_dir / "assets" / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)
    
    def get_portrait_path(self, character_name: str) -> Optional[Path]:
        """获取角色的定妆照路径"""
        portrait_path = self.roles_dir / f"{character_name}.png"
        return portrait_path if portrait_path.exists() else None
    
    def list_missing_portraits(self, characters: List[Dict]) -> List[Dict]:
        """列出缺少定妆照的角色"""
        missing = []
        
        for char in characters:
            char_name = char.get('name', char.get('character_name', ''))
            portrait_path = self.get_portrait_path(char_name)
            
            if not portrait_path:
                missing.append({
                    'character_id': char.get('id', char.get('character_id', '')),
                    'character_name': char_name,
                    'appearance': char.get('appearance', char.get('appearance_description', '')),
                })
        
        return missing
    
    def build_character_prompt(self, character: Dict) -> str:
        """构建角色定妆照的提示词"""
        name = character.get('character_name', character.get('name', ''))
        appearance = character.get('appearance', character.get('appearance_description', ''))
        
        prompt = f"portrait of {name}, {appearance}"
        prompt += ", high quality, detailed face, studio lighting, 8k"
        
        return prompt


def load_story_bible(novel_title: str, data_dir: Path) -> Optional[Dict]:
    """加载故事圣经 (story_bible.json)"""
    bible_path = data_dir / "story_bible.json"
    
    if not bible_path.exists():
        logger.warning(f"故事圣经不存在: {bible_path}")
        return None
    
    with open(bible_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_characters_from_bible(story_bible: Dict) -> List[Dict]:
    """从故事圣经中提取角色列表"""
    characters = []
    
    if not story_bible:
        return characters
    
    if 'characters' in story_bible:
        characters = story_bible['characters']
    elif 'worldbuilding' in story_bible and 'characters' in story_bible['worldbuilding']:
        characters = story_bible['worldbuilding']['characters']
    
    return characters


def get_output_paths(novel_title: str) -> Dict[str, Path]:
    """获取项目输出路径"""
    from config.settings import OUTPUTS_DIR, NOVELS_DIR, IMAGES_DIR
    
    novel_dir = NOVELS_DIR / novel_title.replace(' ', '_')
    
    return {
        'novel': novel_dir,
        'data': novel_dir / "data",
        'images': IMAGES_DIR / novel_title.replace(' ', '_'),
        'assets': novel_dir / "assets",
        'roles': novel_dir / "assets" / "roles",
    }
"""
TTS 脚本适配器 - 解析 script_x.jsonl 并生成 timeline_manifest.json
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

from core.logger import get_logger
from stages.models import get_script_path

logger = get_logger("tts_script_adapter")


class TTSScriptAdapter:
    """TTS 脚本适配器 - 读取 Stage 1 产出的分镜脚本进行逐行生成"""
    
    def __init__(self, novel_title: str, data_dir: Path, audio_dir: Path):
        self.novel_title = novel_title
        self.data_dir = Path(data_dir)
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
    
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
                if line:
                    try:
                        script_lines.append(json.loads(line))
                    except Exception as e:
                        try:
                            script_lines.append(eval(line))
                        except:
                            logger.warning(f"解析脚本行失败: {e}")
        
        logger.info(f"加载了第{chapter_number}章的{len(script_lines)}个分镜")
        return script_lines
    
    def get_voice_segments(self, script_lines: List[Dict]) -> List[Dict]:
        """提取需要生成音频的分段"""
        segments = []
        
        for i, line in enumerate(script_lines):
            segments.append({
                'index': i,
                'shot_id': line.get('shot_id', f'sh_{i}'),
                'scene_id': line.get('scene_id', ''),
                'speaker': line.get('speaker', 'narrator'),
                'text': line.get('text', ''),
                'emotion': line.get('emotion', 'neutral'),
            })
        
        return segments
    
    def check_existing_audio(self, chapter_number: int, shot_id: str) -> Optional[Path]:
        """检查音频是否已存在（断点续传）"""
        audio_path = self.audio_dir / "voices" / f"ch{chapter_number:03d}_{shot_id}.wav"
        return audio_path if audio_path.exists() else None
    
    def generate_audio_path(self, chapter_number: int, shot_id: str) -> Path:
        """生成音频文件路径"""
        voices_dir = self.audio_dir / "voices"
        voices_dir.mkdir(parents=True, exist_ok=True)
        return voices_dir / f"ch{chapter_number:03d}_{shot_id}.wav"


class TimelineGenerator:
    """时间线生成器 - 生成 timeline_manifest.json"""
    
    def __init__(self, audio_dir: Path):
        self.audio_dir = Path(audio_dir)
    
    def create_timeline(
        self,
        chapter_number: int,
        script_lines: List[Dict],
        audio_files: List[tuple],  # (shot_id, audio_path, duration)
    ) -> Dict:
        """创建时间线清单"""
        timeline = []
        current_time = 0.0
        
        # 创建音频文件映射
        audio_map = {}
        for shot_id, path, duration in audio_files:
            if path and Path(path).exists():
                audio_map[shot_id] = {'path': str(path), 'duration': duration}
        
        # 遍历脚本行构建时间线
        for line in script_lines:
            shot_id = line.get('shot_id', '')
            
            audio_info = audio_map.get(shot_id, {})
            audio_file = audio_info.get('path', '')
            duration = audio_info.get('duration', line.get('estimated_duration', 3.0))
            
            entry = {
                'shot_id': shot_id,
                'scene_id': line.get('scene_id', ''),
                'speaker': line.get('speaker', 'narrator'),
                'text': line.get('text', ''),
                'audio_file': audio_file,
                'image_file': '',  # Stage 4 会填充
                'start_time': current_time,
                'end_time': current_time + duration,
                'duration': duration,
                'emotion': line.get('emotion', 'neutral'),
            }
            
            timeline.append(entry)
            current_time += duration
        
        # 计算总时长
        total_duration = current_time if timeline else 0.0
        
        manifest = {
            'chapter_number': chapter_number,
            'total_duration': total_duration,
            'entries': timeline,
        }
        
        return manifest
    
    def save_timeline(self, manifest: Dict, chapter_number: int) -> Path:
        """保存时间线清单"""
        timeline_path = self.audio_dir / f"timeline_ch{chapter_number:03d}.json"
        timeline_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(timeline_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info(f"时间线清单已保存: {timeline_path}")
        return timeline_path
    
    def load_timeline(self, chapter_number: int) -> Optional[Dict]:
        """加载时间线清单"""
        timeline_path = self.audio_dir / f"timeline_ch{chapter_number:03d}.json"
        
        if not timeline_path.exists():
            return None
        
        with open(timeline_path, 'r', encoding='utf-8') as f:
            return json.load(f)


class BGMMatcher:
    """BGM 匹配器 - 根据情感自动匹配背景音乐"""
    
    EMOTION_BGM_MAPPING = {
        'happy': 'joyful',
        'excited': 'epic',
        'angry': 'tense',
        'fearful': 'suspense',
        'sad': 'sad',
        'calm': 'peaceful',
        'neutral': 'peaceful',
        'romantic': 'romantic',
        'mysterious': 'mysterious',
        'tense': 'tense',
    }
    
    BGM_LIBRARY = {
        'epic': 'bgm_epic.wav',
        'peaceful': 'bgm_peaceful.wav',
        'joyful': 'bgm_joyful.wav',
        'sad': 'bgm_sad.wav',
        'tense': 'bgm_tense.wav',
        'suspense': 'bgm_suspense.wav',
        'romantic': 'bgm_romantic.wav',
        'mysterious': 'bgm_mysterious.wav',
    }
    
    def __init__(self, bgm_dir: Path):
        self.bgm_dir = Path(bgm_dir)
    
    def match_bgm(self, emotion: str) -> Optional[str]:
        """根据情感匹配 BGM"""
        bgm_key = self.EMOTION_BGM_MAPPING.get(emotion, 'peaceful')
        
        if bgm_key in self.BGM_LIBRARY:
            bgm_file = self.BGM_LIBRARY[bgm_key]
            bgm_path = self.bgm_dir / bgm_file
            
            if bgm_path.exists():
                return str(bgm_path)
        
        return None
    
    def select_bgm_for_chapter(self, timeline: Dict) -> Optional[str]:
        """根据时间线整体情感选择章节 BGM"""
        if not timeline or 'entries' not in timeline:
            return None
        
        # 统计情感出现次数
        emotion_counts = {}
        for entry in timeline['entries']:
            emotion = entry.get('emotion', 'neutral')
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
        
        # 选择最常见的情感
        if emotion_counts:
            dominant_emotion = max(emotion_counts.items(), key=lambda x: x[1])[0]
            return self.match_bgm(dominant_emotion)
        
        return None


class SFXMatcher:
    """音效匹配器 - 根据场景关键词自动添加音效"""
    
    SCENE_SFX_MAPPING = {
        '战斗': ['sword_clash', 'explosion'],
        '雨天': ['rain', 'thunder'],
        '森林': ['birds', 'wind'],
        '河': ['water_stream'],
        '海': ['waves'],
        '城': ['crowd', 'market'],
        '室内': ['footsteps', 'door'],
        '魔法': ['magic_cast', 'energy'],
        '雷': ['thunder'],
        '风': ['wind'],
        '火': ['fire'],
    }
    
    SFX_LIBRARY = {
        'sword_clash': 'sfx_sword_clash.wav',
        'explosion': 'sfx_explosion.wav',
        'rain': 'sfx_rain.wav',
        'thunder': 'sfx_thunder.wav',
        'birds': 'sfx_birds.wav',
        'wind': 'sfx_wind.wav',
        'water_stream': 'sfx_water.wav',
        'waves': 'sfx_waves.wav',
        'crowd': 'sfx_crowd.wav',
        'market': 'sfx_market.wav',
        'footsteps': 'sfx_footsteps.wav',
        'door': 'sfx_door.wav',
        'magic_cast': 'sfx_magic.wav',
        'energy': 'sfx_energy.wav',
        'fire': 'sfx_fire.wav',
    }
    
    def __init__(self, sfx_dir: Path):
        self.sfx_dir = Path(sfx_dir)
    
    def match_sfx(self, text: str) -> List[str]:
        """根据文本内容匹配音效"""
        matched_sfx = []
        
        text_lower = text.lower()
        
        for keyword, sfx_list in self.SCREEN_SFX_MAPPING.items():
            if keyword in text_lower:
                for sfx in sfx_list:
                    if sfx in self.SFX_LIBRARY:
                        sfx_path = self.sfx_dir / self.SFX_LIBRARY[sfx]
                        if sfx_path.exists():
                            matched_sfx.append(str(sfx_path))
        
        return matched_sfx[:3]  # 最多返回3个


def get_audio_paths(novel_title: str) -> Dict[str, Path]:
    """获取音频相关路径"""
    from config.settings import OUTPUTS_DIR, NOVELS_DIR, AUDIO_DIR
    
    novel_dir = NOVELS_DIR / novel_title.replace(' ', '_')
    
    return {
        'novel': novel_dir,
        'data': novel_dir / "data",
        'audio': AUDIO_DIR / novel_title.replace(' ', '_'),
        'voices': AUDIO_DIR / novel_title.replace(' ', '_') / "voices",
        'bgm': novel_dir / "assets" / "bgm",
        'sfx': novel_dir / "assets" / "sfx",
    }
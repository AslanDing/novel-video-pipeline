"""
TTS语音合成引擎 - 第三阶段
负责将小说文本转换为配音音频
"""

import os
import json
import re
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

import sys
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import AUDIO_GENERATION, AUDIO_DIR


# 音效库配置
SFX_LIBRARY = {
    "nature": {
        "wind": "wind.wav",
        "rain": "rain.wav",
        "thunder": "thunder.wav",
        "birds": "birds.wav",
        "stream": "stream.wav",
    },
    "combat": {
        "sword_clash": "sword_clash.wav",
        "explosion": "explosion.wav",
        "magic_cast": "magic_cast.wav",
        "hit_impact": "hit_impact.wav",
    },
    "ambient": {
        "crowd": "crowd.wav",
        "silence": "silence.wav",
        "footsteps": "footsteps.wav",
        "door_open": "door_open.wav",
    },
    "emotion": {
        "dramatic": "dramatic.wav",
        "suspense": "suspense.wav",
        "joyful": "joyful.wav",
        "sad": "sad_music.wav",
    },
}

# 场景-音效映射规则
SCENE_SFX_MAPPING = {
    "战斗": ["combat.sword_clash", "combat.explosion", "combat.hit_impact"],
    "雨天": ["nature.rain", "nature.thunder"],
    "森林": ["nature.birds", "nature.wind"],
    "河流": ["nature.stream"],
    "人群": ["ambient.crowd"],
    "紧张": ["emotion.suspense"],
    "喜悦": ["emotion.joyful"],
    "悲伤": ["emotion.sad"],
}


def clean_text_for_tts(text: str) -> str:
    """
    清理文本中的无意义符号，准备用于TTS合成

    清理规则：
    1. 移除 # 符号及其内容（注释标记）
    2. 规范化换行符
    3. 移除多余的标点符号（连续的点、逗号等）
    4. 移除特殊符号（如书名号《》、引号内的内容需要保留）
    5. 规范化空格
    6. 移除 HTML/标记语言残留
    7. 移除表情符号和颜文字

    Args:
        text: 原始文本

    Returns:
        清理后的文本
    """
    if not text:
        return ""

    cleaned = text

    # 1. 移除 # 符号及其后的内容（注释/标签）
    cleaned = re.sub(r'#\S+', '', cleaned)

    # 2. 规范化换行符
    cleaned = cleaned.replace('\\n', ' ').replace('\\r', ' ')
    cleaned = cleaned.replace('\r\n', ' ').replace('\r', ' ')
    cleaned = cleaned.replace('\n', ' ')

    # 3. 移除多余的标点符号（保留中文标点的基本形式）
    # 移除连续的点（... -> .）
    cleaned = re.sub(r'\.{2,}', '。', cleaned)
    # 移除连续逗号
    cleaned = re.sub(r'[,，]{2,}', '，', cleaned)
    # 移除连续空格
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)

    # 4. 移除特殊符号但保留有意义的内容
    # 移除 [xxx] 格式的标签
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    # 移除 <xxx> 格式的标签
    cleaned = re.sub(r'<[^>]*>', '', cleaned)

    # 5. 清理句首/句尾的空白和标点
    cleaned = re.sub(r'^[，。、；：！？\s]+', '', cleaned)
    cleaned = re.sub(r'[，。、；：！？\s]+$', '', cleaned)

    # 6. 移除 HTML 实体
    cleaned = cleaned.replace('&nbsp;', ' ')
    cleaned = cleaned.replace('&lt;', '<')
    cleaned = cleaned.replace('&gt;', '>')
    cleaned = cleaned.replace('&amp;', '&')
    cleaned = cleaned.replace('&quot;', '"')
    cleaned = re.sub(r'&#\d+;', '', cleaned)

    # 7. 移除常见的颜文字和表情
    emoji_pattern = re.compile(
        r'[\u2600-\u26FF\u2700-\u27BF'  # 杂项符号
        r'\uFE00-\uFE0F'  # 变异选择器
        r'[\U0001F600-\U0001F64F]'  # 表情符号
        r'[\U0001F300-\U0001F5FF]'  # 符号和图案
        r'[\U0001F680-\U0001F6FF]'  # 运输和地图符号
        r'[\U0001F1E0-\U0001F1FF]'  # 国旗
        r']+',
        flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub('', cleaned)

    # 8. 移除连续的相同标点（但保留省略号）
    cleaned = re.sub(r'([，。！？；：])\1+', r'\1', cleaned)

    # 9. 移除句首的数字和字母（如 1. 2.）
    cleaned = re.sub(r'^[a-zA-Z0-9]+[\.、\s]+', '', cleaned)

    # 10. 最后的空格规范化
    cleaned = ' '.join(cleaned.split())

    # 11. 如果清理后为空或太短，返回原始文本的清理版本
    if len(cleaned) < 2:
        # 至少保留一些可读内容
        cleaned = text.replace('#', '').replace('\n', ' ').strip()
        cleaned = ' '.join(cleaned.split())

    return cleaned

# BGM 库配置
BGM_LIBRARY = {
    "epic": "epic_battle.wav",
    "peaceful": "peaceful.wav",
    "mysterious": "mysterious.wav",
    "romantic": "romantic.wav",
    "tense": "tense.wav",
    "sad": "sad.wav",
}

# 情感-BGM 映射
EMOTION_BGM_MAPPING = {
    "happy": "peaceful",
    "sad": "sad",
    "angry": "tense",
    "fearful": "tense",
    "excited": "epic",
    "calm": "peaceful",
    "neutral": "peaceful",
}
from core.base_pipeline import PipelineStage
from stages.stage1_novel.novel_generator import Novel, Chapter


# 尝试导入TTS相关库
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except Exception as e:
    EDGE_TTS_AVAILABLE = False
    print(f"⚠️  edge-tts未安装或无法加载: {e}")

try:
    import ChatTTS
    CHATTTS_AVAILABLE = True
except Exception as e:
    CHATTTS_AVAILABLE = False
    print(f"⚠️  ChatTTS未安装或无法加载: {e}")

try:
    # GPT-SoVITS 导入（占位，实际项目中需要正确的导入）
    GPT_SOVITS_AVAILABLE = False
    print("⚠️  GPT-SoVITS 框架占位实现")
except Exception as e:
    GPT_SOVITS_AVAILABLE = False
    print(f"⚠️  GPT-SoVITS未安装或无法加载: {e}")


@dataclass
class TTSSegment:
    """TTS音频片段"""
    segment_id: str
    chapter_number: int
    text: str
    speaker: str  # 说话人标识
    emotion: str  # 情感标签
    speed: float  # 语速
    file_path: str
    duration: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ChapterAudio:
    """章节的音频集合"""
    chapter_number: int
    segments: List[TTSSegment]
    combined_file: Optional[str] = None  # 合并后的完整音频
    total_duration: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "chapter_number": self.chapter_number,
            "segments": [s.to_dict() for s in self.segments],
            "combined_file": self.combined_file,
            "total_duration": self.total_duration,
        }


# 语音特征映射
VOICE_CHARACTERISTICS = {
    "zh-CN-XiaoxiaoNeural": {
        "gender": "female",
        "age": "young",
        "tone": "calm",
        "suitable_for": ["narrator", "young_female"],
        "supports_emotion": True,
    },
    "zh-CN-YunxiNeural": {
        "gender": "male",
        "age": "young",
        "tone": "energetic",
        "suitable_for": ["protagonist", "young_male"],
        "supports_emotion": True,
    },
    "zh-CN-YunjianNeural": {
        "gender": "male",
        "age": "middle",
        "tone": "deep",
        "suitable_for": ["antagonist", "middle_male", "father_figure"],
        "supports_emotion": True,
    },
    "zh-CN-XiaoyiNeural": {
        "gender": "female",
        "age": "young",
        "tone": "bright",
        "suitable_for": ["heroine", "young_female"],
        "supports_emotion": True,
    },
    "zh-CN-liaoning-XiaobeiNeural": {
        "gender": "female",
        "age": "young",
        "tone": "casual",
        "suitable_for": ["supporting_female", "friend"],
        "supports_emotion": False,
    },
    "zh-CN-XiaohanNeural": {
        "gender": "female",
        "age": "child",
        "tone": "cute",
        "suitable_for": ["child", "young_sibling"],
        "supports_emotion": True,
    },
    "zh-CN-YunyangNeural": {
        "gender": "male",
        "age": "elder",
        "tone": "wise",
        "suitable_for": ["elder", "mentor", "grandfather"],
        "supports_emotion": True,
    },
    "zh-CN-XiaomengNeural": {
        "gender": "female",
        "age": "young",
        "tone": "sweet",
        "suitable_for": ["love_interest", "princess"],
        "supports_emotion": True,
    },
    "zh-CN-YunhaoNeural": {
        "gender": "male",
        "age": "young",
        "tone": "authoritative",
        "suitable_for": ["leader", "emperor", "general"],
        "supports_emotion": True,
    },
}

# 情感映射配置
EMOTION_MAPPING = {
    "happy": {
        "rate": "+10%",
        "pitch": "+5Hz",
        "style": "cheerful",
    },
    "sad": {
        "rate": "-10%",
        "pitch": "-5Hz",
        "style": "sad",
    },
    "angry": {
        "rate": "+15%",
        "pitch": "+10Hz",
        "style": "angry",
    },
    "fearful": {
        "rate": "+5%",
        "pitch": "-10Hz",
        "style": "fearful",
    },
    "excited": {
        "rate": "+20%",
        "pitch": "+8Hz",
        "style": "excited",
    },
    "calm": {
        "rate": "-5%",
        "pitch": "+0Hz",
        "style": "gentle",
    },
    "neutral": {
        "rate": "+0%",
        "pitch": "+0Hz",
        "style": "default",
    },
}


class BaseTTSEngine:
    """TTS 引擎基类"""
    
    def __init__(self, config: Dict):
        self.config = config
    
    async def generate(self, text: str, voice: str, output_path: Path, **kwargs) -> float:
        """
        生成 TTS 音频
        
        Args:
            text: 要合成的文本
            voice: 语音标识
            output_path: 输出文件路径
            **kwargs: 其他参数
            
        Returns:
            音频时长（秒）
        """
        raise NotImplementedError
    
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        return True


class EdgeTTSEngine(BaseTTSEngine):
    """Edge TTS 引擎（微软在线 TTS）"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
    
    async def generate(self, text: str, voice: str, output_path: Path, rate: str = "+0%", pitch: str = "+0Hz", **kwargs) -> float:
        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError("Edge TTS 不可用")
        
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))
        
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        speed_factor = 1.0
        if '%' in rate:
            rate_val = int(rate.replace('%', '').replace('+', ''))
            speed_factor = 1.0 + rate_val / 100.0
        
        return (chinese_chars / 3.5) / speed_factor
    
    def is_available(self) -> bool:
        return EDGE_TTS_AVAILABLE


class ChatTTSEngine(BaseTTSEngine):
    """ChatTTS 本地 TTS 引擎"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.model = None
        self._init_model()
    
    def _init_model(self):
        if CHATTTS_AVAILABLE:
            try:
                print("🔄 正在加载 ChatTTS 模型...")
                self.model = ChatTTS.Chat()
                cache_dir = self.config.get("model_cache_dir")
                if cache_dir and os.path.exists(cache_dir):
                    print(f"   使用本地缓存: {cache_dir}")
                    self.model.load(compile=False, custom_path=cache_dir)
                else:
                    self.model.load(compile=False)
                print("✅ ChatTTS 模型加载完成")
            except Exception as e:
                print(f"⚠️  ChatTTS 加载失败: {e}")
                self.model = None
    
    async def generate(self, text: str, voice: str, output_path: Path, **kwargs) -> float:
        if not self.model:
            raise RuntimeError("ChatTTS 不可用")
            
        import torch
        import numpy as np
        import soundfile as sf
        
        # 种子映射（简单实现，可以根据 voice 字符串生成固定种子）
        seed = hash(voice) % 10000
        torch.manual_seed(seed)
        
        # 获取说话人音色码
        try:
            spk = self.model.sample_random_speaker()
        except:
            spk = None

        # ChatTTS 使用推理生成
        params_infer_code = {
            'spk_s': spk, 
            'txt_s': text,
        }
        
        params_refine_text = {
            'prompt': '[oral_2][laugh_0][break_6]'
        }

        wavs = self.model.infer(
            [text],
            params_refine_text=params_refine_text,
            params_infer_code=params_infer_code,
            use_decoder=True,
        )
        
        if not wavs or len(wavs) == 0:
            raise RuntimeError("ChatTTS 生成音频为空")

        audio_data = np.array(wavs[0])
        # 如果是 2D (1, N), 扁平化
        if audio_data.ndim > 1:
            audio_data = audio_data.flatten()
            
        sf.write(str(output_path), audio_data, 24000)
        
        # 估计时长
        return len(audio_data) / 24000
    
    def is_available(self) -> bool:
        return CHATTTS_AVAILABLE and self.model is not None


class GPTSoVITSEngine(BaseTTSEngine):
    """GPT-SoVITS 声音克隆引擎"""
    
    def __init__(self, config: Dict):
        super().__init__(config)
        self.model = None
        self.reference_audio = config.get("voice_clone", {}).get("reference_audio", None)
        self._init_model()
    
    def _init_model(self):
        if GPT_SOVITS_AVAILABLE:
            try:
                print("🔄 正在加载 GPT-SoVITS 模型...")
                print("⚠️  GPT-SoVITS 为占位实现，实际项目中需要集成完整的 GPT-SoVITS")
                self.model = "placeholder"
                print("✅ GPT-SoVITS 模型占位加载完成")
            except Exception as e:
                print(f"⚠️  GPT-SoVITS 加载失败: {e}")
                self.model = None
        else:
            print("⚠️  GPT-SoVITS 框架占位实现")
            self.model = "placeholder"
    
    async def generate(self, text: str, voice: str, output_path: Path, **kwargs) -> float:
        if not self.model:
            raise RuntimeError("GPT-SoVITS 不可用")
        
        print(f"🎤 GPT-SoVITS: 使用参考音频={self.reference_audio}")
        print(f"⚠️  GPT-SoVITS 为占位实现，实际项目中需要调用完整的 GPT-SoVITS 接口")
        
        # 占位实现：创建一个简单的音频文件
        import numpy as np
        import soundfile as sf
        
        sample_rate = 44100
        duration = len(text) / 3.5
        num_samples = int(sample_rate * duration)
        
        # 生成一个简单的音频（占位）
        audio_data = np.zeros(num_samples, dtype=np.float32)
        
        sf.write(str(output_path), audio_data, sample_rate)
        
        return duration
    
    def is_available(self) -> bool:
        return self.model is not None


class TTSEngine(PipelineStage):
    """
    TTS语音合成引擎
    
    支持：
    1. 多 TTS 引擎切换（Edge TTS、ChatTTS 等）
    2. 角色特征映射
    3. 情感控制
    4. 语速控制
    """
    
    def __init__(self, config=None):
        super().__init__("TTS语音合成", config or AUDIO_GENERATION)
        self.voice_mapping = self._init_voice_mapping()
        self.voice_characteristics = VOICE_CHARACTERISTICS
        self.emotion_mapping = EMOTION_MAPPING
        self.tts_engine = self._init_tts_engine()
        self.sfx_library = SFX_LIBRARY
        self.scene_sfx_mapping = SCENE_SFX_MAPPING
        self.bgm_library = BGM_LIBRARY
        self.emotion_bgm_mapping = EMOTION_BGM_MAPPING
        self.enable_sfx = self.config.get("enable_sfx", False)
        self.enable_music = self.config.get("enable_music", False)
        self.sfx_dir = Path(self.config.get("sfx_dir", "assets/sfx"))
        self.bgm_dir = Path(self.config.get("bgm_dir", "assets/bgm"))
    
    def _init_tts_engine(self) -> BaseTTSEngine:
        """初始化 TTS 引擎"""
        backend = self.config.get("local", {}).get("backend", "edge")
        
        if backend == "gpt_sovits":
            print(f"🎤 使用 GPT-SoVITS 声音克隆引擎")
            return GPTSoVITSEngine(self.config.get("local", {}))
        elif backend == "chattts" and CHATTTS_AVAILABLE:
            print(f"🎤 使用 ChatTTS 引擎")
            return ChatTTSEngine(self.config.get("local", {}))
        else:
            print(f"🎤 使用 Edge TTS 引擎")
            return EdgeTTSEngine(self.config.get("local", {}))
    
    def _init_voice_mapping(self) -> Dict[str, str]:
        """初始化角色到语音的映射"""
        # edge-tts的中文语音
        return {
            "narrator": "zh-CN-XiaoxiaoNeural",  # 旁白 - 晓晓
            "male_1": "zh-CN-YunxiNeural",       # 男声1 - 云希
            "male_2": "zh-CN-YunjianNeural",     # 男声2 - 云健
            "male_3": "zh-CN-YunyangNeural",     # 男声3 - 云扬（老年）
            "male_4": "zh-CN-YunhaoNeural",      # 男声4 - 云皓（权威）
            "female_1": "zh-CN-XiaoyiNeural",    # 女声1 - 晓伊
            "female_2": "zh-CN-liaoning-XiaobeiNeural",  # 女声2 - 小北
            "female_3": "zh-CN-XiaohanNeural",   # 女声3 - 晓涵（儿童）
            "female_4": "zh-CN-XiaomengNeural",  # 女声4 - 晓梦（甜美）
        }
    
    def _map_character_to_voice(self, character_name: str, character_attrs: Optional[Dict] = None) -> str:
        """
        根据角色特征智能映射到合适的语音
        
        Args:
            character_name: 角色名称
            character_attrs: 角色属性（gender, age, personality等）
            
        Returns:
            语音名称
        """
        if not character_attrs:
            # 简单规则：根据名字中的关键词
            if any(keyword in character_name for keyword in ['爷', '翁', '伯', '叔', '父', '老', '师']):
                return self.voice_mapping.get("male_3", "zh-CN-YunyangNeural")
            if any(keyword in character_name for keyword in ['帝', '皇', '王', '主', '公', '将', '帅']):
                return self.voice_mapping.get("male_4", "zh-CN-YunhaoNeural")
            if any(keyword in character_name for keyword in ['妹', '女', '娘', '姑', '姨', '姐']):
                return self.voice_mapping.get("female_1", "zh-CN-XiaoyiNeural")
            if any(keyword in character_name for keyword in ['童', '儿', '小', '娃']):
                return self.voice_mapping.get("female_3", "zh-CN-XiaohanNeural")
            # 默认男声1
            return self.voice_mapping.get("male_1", "zh-CN-YunxiNeural")
        
        # 根据角色属性智能匹配
        gender = character_attrs.get('gender', '')
        age = character_attrs.get('age', '')
        description = character_attrs.get('description', '').lower()
        personality = character_attrs.get('personality', '').lower()
        
        # 智能从描述中推断缺失属性
        if not gender:
            if any(k in description or k in character_name for k in ['女', '妈', '奶', '姐', '妹', '妃', '后', '仙子']):
                gender = 'female'
            else:
                gender = 'male'
        
        if not age:
            if any(k in description for k in ['老', '翁', '长辈', '祖']):
                age = 'old'
            elif any(k in description for k in ['中', '壮']):
                age = 'middle'
            elif any(k in description for k in ['幼', '童', '小']):
                age = 'child'
            else:
                age = 'young'
        
        best_voice = None
        best_score = 0
        
        for voice_name, voice_attrs in self.voice_characteristics.items():
            score = 0
            # 性别匹配
            if voice_attrs['gender'] == gender:
                score += 3
            # 年龄匹配
            if voice_attrs['age'] == age:
                score += 2
            # 性格匹配
            if voice_attrs['tone'] in personality.lower():
                score += 2
            # 适用场景
            for suitable in voice_attrs['suitable_for']:
                if suitable in personality.lower() or suitable in character_name:
                    score += 1
            
            if score > best_score:
                best_score = score
                best_voice = voice_name
        
        if best_voice:
            return best_voice
        
        # 回退到默认
        if gender == 'female':
            return self.voice_mapping.get("female_1", "zh-CN-XiaoyiNeural")
        return self.voice_mapping.get("male_1", "zh-CN-YunxiNeural")
    
    def _get_emotion_parameters(self, emotion: str) -> Dict[str, str]:
        """
        获取情感对应的TTS参数
        
        Args:
            emotion: 情感标签
            
        Returns:
            参数字典
        """
        emotion_config = self.emotion_mapping.get(emotion.lower(), self.emotion_mapping['neutral'])
        return {
            'rate': emotion_config['rate'],
            'pitch': emotion_config['pitch'],
            'style': emotion_config['style'],
        }
    
    def _analyze_emotion(self, text: str, speaker: str) -> str:
        """
        简单分析文本情感
        
        Args:
            text: 文本内容
            speaker: 说话人
            
        Returns:
            情感标签
        """
        text_lower = text.lower()
        
        # 关键词匹配
        emotion_keywords = {
            'happy': ['哈哈', '开心', '高兴', '喜悦', '快乐', '幸福', '激动', '兴奋'],
            'sad': ['哭', '悲伤', '难过', '痛苦', '伤心', '凄凉', '绝望'],
            'angry': ['怒', '气', '恨', '愤怒', '咆哮', '怒吼', '咬牙'],
            'fearful': ['怕', '恐惧', '害怕', '惊恐', '颤抖', '哆嗦'],
            'excited': ['啊！', '哇！', '太棒了', '太好', '不可思议'],
            'calm': ['平静', '淡定', '从容', '温和', '轻声'],
        }
        
        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    return emotion
        
        return 'neutral'
    
    def validate_input(self, input_data) -> bool:
        """验证输入"""
        if isinstance(input_data, Novel):
            return True
        if isinstance(input_data, dict) and "chapters" in input_data:
            return True
        return False
    
    async def process(self, novel: Novel) -> Dict[int, ChapterAudio]:
        """
        为小说生成TTS音频
        
        支持两种模式：
        1. 优先从 script_x.jsonl 读取（Stage 1产出）
        2. 回退到原有方式（从章节内容分段）
        
        Args:
            novel: 小说对象
            
        Returns:
            章节号到音频集合的映射
        """
        print(f"🔊 开始为小说《{novel.metadata['title']}》生成TTS音频")
        print(f"   章节数: {len(novel.chapters)}")
        
        # 存储当前角色信息库
        self.current_novel_characters = novel.blueprint.characters
        novel_title = novel.metadata.get('title', '')
        
        results = {}
        
        for chapter in novel.chapters:
            print(f"\n   📖 处理第{chapter.number}章...")
            
            # 尝试从 script_x.jsonl 加载
            chapter_audio = await self._generate_from_script(novel_title, chapter.number)
            
            # 如果没有脚本文件，回退到原来的方式
            if not chapter_audio or not chapter_audio.segments:
                chapter_audio = await self._generate_chapter_audio(chapter)
            
            results[chapter.number] = chapter_audio
            print(f"   ✅ 第{chapter.number}章生成 {len(chapter_audio.segments)} 个音频片段")
            print(f"      总时长: {chapter_audio.total_duration:.2f}秒")
            
            # 生成 timeline_manifest.json
            await self._save_timeline_manifest(novel_title, chapter.number, chapter_audio)
        
        print(f"\n✅ TTS生成完成！")
        
        return results
    
    async def _generate_from_script(self, novel_title: str, chapter_number: int) -> Optional[ChapterAudio]:
        """
        从 Stage 1 产出的 script_x.jsonl 生成音频
        
        Args:
            novel_title: 小说标题
            chapter_number: 章节号
            
        Returns:
            章节音频对象，如果失败返回 None
        """
        try:
            from config.settings import NOVELS_DIR, AUDIO_DIR
            from stages.stage3_audio.tts_script_adapter import TTSScriptAdapter, TimelineGenerator
            
            data_dir = NOVELS_DIR / novel_title.replace(' ', '_') / "data"
            audio_dir = AUDIO_DIR / novel_title.replace(' ', '_')
            
            if not data_dir.exists():
                return None
            
            adapter = TTSScriptAdapter(novel_title, data_dir, audio_dir)
            script_lines = adapter.load_script_lines(chapter_number)
            
            if not script_lines:
                return None
            
            # 获取音频分段
            segments_data = adapter.get_voice_segments(script_lines)
            
            segments = []
            total_duration = 0.0
            
            for i, seg_data in enumerate(segments_data):
                # 检查是否已存在
                existing = adapter.check_existing_audio(chapter_number, seg_data['shot_id'])
                if existing:
                    duration = self._get_audio_duration(str(existing)) if existing.exists() else 3.0
                    segments.append(TTSSegment(
                        segment_id=f"ch{chapter_number}_seg{i}",
                        chapter_number=chapter_number,
                        text=seg_data['text'],
                        speaker=seg_data['speaker'],
                        emotion=seg_data.get('emotion', 'neutral'),
                        speed=1.0,
                        file_path=str(existing),
                        duration=duration,
                    ))
                    total_duration += duration
                    continue
                
                # 生成新音频
                try:
                    segment = await self._generate_tts_segment(
                        text=seg_data['text'],
                        speaker=seg_data['speaker'],
                        emotion=seg_data.get('emotion', 'neutral'),
                        chapter_number=chapter_number,
                        segment_index=i,
                    )
                    
                    # 更新音频路径
                    audio_path = adapter.generate_audio_path(chapter_number, seg_data['shot_id'])
                    if segment.file_path and Path(segment.file_path).exists():
                        import shutil
                        shutil.copy(segment.file_path, audio_path)
                        segment.file_path = str(audio_path)
                    
                    segments.append(segment)
                    total_duration += segment.duration
                    
                except Exception as e:
                    print(f"      ⚠️  生成音频片段 {i} 失败: {e}")
                    continue
            
            if not segments:
                return None
            
            chapter_audio = ChapterAudio(
                chapter_number=chapter_number,
                segments=segments,
                total_duration=total_duration,
            )
            
            print(f"   📜 从 script_x.jsonl 加载了 {len(segments)} 个音频片段")
            return chapter_audio
            
        except Exception as e:
            logger.warning(f"从 script_x.jsonl 生成音频失败: {e}")
            return None
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长"""
        try:
            import subprocess
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 3.0
    
    async def _save_timeline_manifest(self, novel_title: str, chapter_number: int, chapter_audio: ChapterAudio):
        """保存时间线清单"""
        try:
            from config.settings import NOVELS_DIR, AUDIO_DIR
            from stages.stage3_audio.tts_script_adapter import TimelineGenerator
            
            data_dir = NOVELS_DIR / novel_title.replace(' ', '_') / "data"
            audio_dir = AUDIO_DIR / novel_title.replace(' ', '_')
            
            adapter = TTSScriptAdapter(novel_title, data_dir, audio_dir)
            script_lines = adapter.load_script_lines(chapter_number)
            
            if not script_lines:
                return
            
            # 收集音频文件信息
            audio_files = []
            for seg in chapter_audio.segments:
                audio_files.append((f"ch{chapter_number}_{seg.segment_id}", seg.file_path, seg.duration))
            
            generator = TimelineGenerator(audio_dir)
            manifest = generator.create_timeline(chapter_number, script_lines, audio_files)
            generator.save_timeline(manifest, chapter_number)
            
            print(f"   📜 已生成 timeline_ch{chapter_number:03d}.json")
            
        except Exception as e:
            logger.warning(f"保存时间线清单失败: {e}")
    
    async def _generate_chapter_audio(self, chapter: Chapter) -> ChapterAudio:
        """
        为单章生成音频
        
        流程：
        1. 分析章节内容，分段
        2. 为每段生成TTS
        3. 合并（可选）
        """
        # 分段处理
        segments_data = await self._segment_chapter(chapter)
        
        segments = []
        total_duration = 0.0
        
        # 为每段生成TTS
        for i, seg_data in enumerate(segments_data):
            try:
                segment = await self._generate_tts_segment(
                    text=seg_data["text"],
                    speaker=seg_data["speaker"],
                    emotion=seg_data.get("emotion", "neutral"),
                    chapter_number=chapter.number,
                    segment_index=i,
                )
                
                segments.append(segment)
                total_duration += segment.duration
                
            except Exception as e:
                print(f"      ⚠️  生成音频片段 {i} 失败: {e}")
                continue
        
        # 创建章节音频对象
        chapter_audio = ChapterAudio(
            chapter_number=chapter.number,
            segments=segments,
            total_duration=total_duration,
        )
        
        # 可选：合并所有片段
        if len(segments) > 1:
            combined_path = await self._combine_audio_segments(segments, chapter.number)
            chapter_audio.combined_file = combined_path
        
        return chapter_audio
    
    async def _segment_chapter(self, chapter: Chapter) -> List[Dict]:
        """
        将章节内容分段
        
        每段包含：文本、说话人、情感
        """
        # 复杂的分段逻辑：识别对话和旁白
        paragraphs = chapter.content.split('\n')
        segments = []
        
        # 缓存小说中的角色以便匹配
        novel_characters = {c.name: c for c in getattr(self, 'current_novel_characters', [])}
        
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 5:
                continue

            # 清理
            para = para.replace('\\n', ' ').replace('\\r', ' ').replace('\n', ' ').replace('\r', ' ').replace('/', ' ').replace('\\', ' ')
            para = ' '.join(para.split())

            # 几种对话模式识别
            # 模式 1: 说话人："内容" 或 说话人说道："内容"
            # 模式 2: "内容" 说话人说道
            # 模式 3: "内容"
            
            # 使用正则匹配对话和说话人
            dialogue_match = re.search(r'["“](.+?)["”]', para)
            
            if dialogue_match:
                speaker_name = ""
                content = dialogue_match.group(1)
                
                # 尝试从前后寻找说话人
                # A. 在前面: 林烨冷笑道："..."
                pre_match = re.search(r'^([^"“”]{1,10}?)(?:说道|喊道|冷笑道|怒喝|轻声说|问道|：|:)', para[:dialogue_match.start()+5])
                if pre_match:
                    speaker_name = pre_match.group(1).strip()
                
                # B. 在后面: "..." 林烨说道
                if not speaker_name:
                    post_match = re.search(r'["”]\s*([^"“”]{1,10}?)(?:说道|喊道|说道|低声自语|笑道|说道)', para[dialogue_match.end()-1:dialogue_match.end()+20])
                    if post_match:
                        speaker_name = post_match.group(1).strip()

                # C. 如果还没找到，尝试全局角色库匹配
                if not speaker_name:
                    for name in novel_characters.keys():
                        if name in para:
                            speaker_name = name
                            break
                
                # 映射语音
                if speaker_name:
                    char_obj = novel_characters.get(speaker_name)
                    char_attrs = char_obj.to_dict() if char_obj else None
                    speaker_id = self._map_character_to_voice(speaker_name, char_attrs)
                else:
                    # 默认对话人（女/男）
                    if '她' in para:
                        speaker_id = self.voice_mapping.get("female_1")
                    else:
                        speaker_id = self.voice_mapping.get("male_1")
                
                emotion = self._analyze_emotion(para, speaker_id)
                segments.append({
                    "text": content,
                    "speaker": speaker_id,
                    "character_name": speaker_name or "未知角色",
                    "emotion": emotion,
                    "type": "dialogue",
                })
            else:
                # 旁白
                emotion = self._analyze_emotion(para, "narrator")
                segments.append({
                    "text": para,
                    "speaker": self.voice_mapping.get("narrator", "zh-CN-XiaoxiaoNeural"),
                    "emotion": emotion,
                    "type": "narration",
                })
        
        # 合并相邻的同声源片段以减少断点
        if len(segments) > 1:
            merged = []
            current = segments[0]
            for seg in segments[1:]:
                if current["speaker"] == seg["speaker"] and current["emotion"] == seg["emotion"] and len(current["text"]) < 500:
                    current["text"] += " " + seg["text"]
                else:
                    merged.append(current)
                    current = seg
            merged.append(current)
            segments = merged
        
        return segments[:20]
    
    async def _generate_tts_segment(
        self,
        text: str,
        speaker: str,
        emotion: str,
        chapter_number: int,
        segment_index: int,
    ) -> TTSSegment:
        """
        生成单个TTS片段

        使用多引擎架构（Edge TTS 或 ChatTTS），支持情感和语速控制
        """
        # 清理文本，移除无意义符号
        text = clean_text_for_tts(text)

        # 获取语音
        voice = speaker if speaker in self.voice_characteristics else self.voice_mapping.get(speaker, "zh-CN-XiaoxiaoNeural")
        
        # 获取情感参数
        emotion_params = self._get_emotion_parameters(emotion)
        rate = emotion_params['rate']
        pitch = emotion_params['pitch']
        
        # 从配置获取全局语速
        global_speed = self.config.get("local", {}).get("speed", 1.0)
        if global_speed != 1.0 and isinstance(self.tts_engine, EdgeTTSEngine):
            # 调整语速（仅 Edge TTS 支持）
            rate_percent = int(rate.replace('%', '')) if '%' in rate else 0
            new_rate = rate_percent + int((global_speed - 1.0) * 100)
            rate = f"{new_rate:+d}%"
        
        # 生成唯一ID
        segment_id = f"ch{chapter_number}_seg{segment_index}"
        
        # 输出路径
        output_dir = AUDIO_DIR / f"chapter_{chapter_number:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 根据引擎类型选择输出格式
        if isinstance(self.tts_engine, ChatTTSEngine):
            output_path = output_dir / f"segment_{segment_index:03d}.wav"
        else:
            output_path = output_dir / f"segment_{segment_index:03d}.mp3"
        
        # 使用 TTS 引擎生成
        try:
            if isinstance(self.tts_engine, EdgeTTSEngine):
                print(f"      🎤 Edge TTS: 语音={voice}, 情感={emotion}, 语速={rate}, 音调={pitch}")
                duration = await self.tts_engine.generate(
                    text, voice, output_path, rate=rate, pitch=pitch
                )
            else:
                print(f"      🎤 ChatTTS: 生成长度={len(text)} 字符")
                duration = await self.tts_engine.generate(
                    text, voice, output_path
                )
                
        except Exception as e:
            print(f"      ⚠️  TTS引擎失败: {e}，创建模拟音频")
            output_path = await self._create_mock_audio(output_path, text)
            duration = len(text) / 5
        
        return TTSSegment(
            segment_id=segment_id,
            chapter_number=chapter_number,
            text=text,
            speaker=speaker,
            emotion=emotion,
            speed=global_speed,
            file_path=str(output_path),
            duration=duration,
        )
    
    async def _create_mock_audio(self, output_path: Path, text: str) -> Path:
        """创建模拟音频文件（当TTS不可用时）"""
        # 尝试使用 ffmpeg 生成 1 秒的静音
        ffmpeg_available = os.system("which ffmpeg > /dev/null 2>&1") == 0
        if ffmpeg_available:
            try:
                # 采样率 24000 (ChatTTS默认), 1秒静音, MP3 格式
                cmd = f'ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t 1 -acodec libmp3lame -y {output_path} > /dev/null 2>&1'
                os.system(cmd)
                if output_path.exists():
                    return output_path
            except Exception:
                pass

        # 如果 ffmpeg 失败，写入一个极小的有效静音 MP3 数据（约 0.1s）
        # 这是一个包含 ID3 标签和单一安静帧的最小 MP3
        # 数据说明：1k采样率，单声道，对 ffmpeg 友好
        minimal_silent_mp3 = (
            b'\xff\xfb\x90\x44\x00\x00\x00\x03\x48\x00\x00\x00\x00\x4c\x41\x4d'
            b'\x45\x33\x2e\x39\x38\x2e\x32\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        )
        with open(output_path, 'wb') as f:
            f.write(minimal_silent_mp3)
        
        return output_path
    
    async def _combine_audio_segments(
        self,
        segments: List[TTSSegment],
        chapter_number: int,
    ) -> str:
        """
        合并音频片段
        
        使用FFmpeg或pydub合并多个MP3文件
        """
        # 输出路径
        output_dir = AUDIO_DIR / f"chapter_{chapter_number:03d}"
        output_path = output_dir / "combined.mp3"
        
        # 检查FFmpeg是否可用
        ffmpeg_available = os.system("which ffmpeg > /dev/null 2>&1") == 0
        
        if ffmpeg_available:
            # 使用FFmpeg合并
            # 创建文件列表
            list_file = output_dir / "file_list.txt"
            with open(list_file, 'w') as f:
                for seg in segments:
                    f.write(f"file '{seg.file_path}'\n")
            
            # 执行FFmpeg命令
            cmd = f'ffmpeg -f concat -safe 0 -i {list_file} -c copy {output_path} -y'
            os.system(cmd)
            
            # 清理临时文件
            list_file.unlink(missing_ok=True)
            
        else:
            # 使用pydub（如果可用）
            try:
                from pydub import AudioSegment
                
                combined = AudioSegment.empty()
                for seg in segments:
                    audio = AudioSegment.from_mp3(seg.file_path)
                    combined += audio
                
                combined.export(output_path, format="mp3")
                
            except ImportError:
                print("      ⚠️  无法合并音频（FFmpeg和pydub都不可用）")
                # 创建一个空的合并文件
                with open(output_path, 'wb') as f:
                    f.write(b'ID3')
        
        return str(output_path)
    
    def _select_sfx_for_scene(self, scene_description: str) -> List[str]:
        """
        根据场景描述选择合适的音效
        
        Args:
            scene_description: 场景描述文本
            
        Returns:
            音效文件路径列表
        """
        if not self.enable_sfx:
            return []
        
        selected_sfx = []
        
        for keyword, sfx_list in self.scene_sfx_mapping.items():
            if keyword in scene_description:
                for sfx_key in sfx_list:
                    category, sfx_name = sfx_key.split(".")
                    if category in self.sfx_library and sfx_name in self.sfx_library[category]:
                        sfx_path = self.sfx_dir / self.sfx_library[category][sfx_name]
                        if sfx_path.exists():
                            selected_sfx.append(str(sfx_path))
        
        return selected_sfx
    
    def _select_bgm_for_emotion(self, emotion: str, scene_mood: str = "") -> Optional[str]:
        """
        根据情感选择合适的 BGM
        
        Args:
            emotion: 情感标签
            scene_mood: 场景氛围（可选）
            
        Returns:
            BGM 文件路径
        """
        if not self.enable_music:
            return None
        
        bgm_key = self.emotion_bgm_mapping.get(emotion, "peaceful")
        
        if bgm_key in self.bgm_library:
            bgm_path = self.bgm_dir / self.bgm_library[bgm_key]
            if bgm_path.exists():
                return str(bgm_path)
            else:
                print(f"   ⚠️  BGM 文件不存在: {bgm_path}")
        return None
        
        return None
    
    async def _mix_audio_with_sfx_and_bgm(
        self,
        voice_audio_path: str,
        sfx_paths: List[str],
        bgm_path: Optional[str],
        output_path: str,
        chapter_number: int,
    ) -> str:
        """
        使用 FFmpeg 混音合成
        
        Args:
            voice_audio_path: 语音音频路径
            sfx_paths: 音效文件路径列表
            bgm_path: BGM 文件路径
            output_path: 输出路径
            chapter_number: 章节号
            
        Returns:
            混音后文件路径
        """
        # 检查 FFmpeg 是否可用
        ffmpeg_available = os.system("which ffmpeg > /dev/null 2>&1") == 0
        
        if not ffmpeg_available:
            print("      ⚠️  FFmpeg 不可用，跳过混音")
            return voice_audio_path
        
        try:
            # 构建 FFmpeg 命令
            inputs = [f"-i {voice_audio_path}"]
            filter_parts = []
            
            # 添加音效
            for i, sfx_path in enumerate(sfx_paths):
                inputs.append(f"-i {sfx_path}")
                filter_parts.append(f"[{i+1}:a]volume=0.3[a{i+1}]")
            
            # 添加 BGM
            if bgm_path:
                inputs.append(f"-i {bgm_path}")
                bgm_idx = len(sfx_paths) + 1
                filter_parts.append(f"[{bgm_idx}:a]volume=0.2[bgm]")
            
            # 构建混音滤镜
            if filter_parts:
                all_inputs = "[0:a]" + "".join([f"[a{i+1}]" for i in range(len(sfx_paths))])
                if bgm_path:
                    all_inputs += "[bgm]"
                
                num_inputs = 1 + len(sfx_paths) + (1 if bgm_path else 0)
                filter_complex = f"{';'.join(filter_parts)};{all_inputs}amix=inputs={num_inputs}:duration=longest"
            else:
                filter_complex = "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
            
            cmd = f'ffmpeg {" ".join(inputs)} -filter_complex "{filter_complex}" -y {output_path}'
            os.system(cmd)
            
            print(f"      ✅ 混音完成: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"      ⚠️  混音失败: {e}")
            return voice_audio_path


# ========== 便捷函数 ==========

async def quick_generate_audio(
    novel: Novel,
) -> Dict[int, ChapterAudio]:
    """
    快速生成音频的便捷函数
    """
    engine = TTSEngine()
    return await engine.process(novel)


# ========== 测试代码 ==========

async def test_tts_engine():
    """测试TTS引擎"""
    print("🧪 测试TTS引擎...")
    
    # 创建测试用的Chapter
    from stage1_novel.novel_generator import Chapter
    
    chapter = Chapter(
        number=1,
        title="测试章节",
        content="""林云站在山巅，眼中闪烁着坚定的光芒。

"我一定能成为最强者！"他大声说道。

突然，一道金光从天而降，笼罩了他的身体。

"这是...上古传承？"林云惊讶地看着眼前的一切。

他感觉到体内涌动着强大的力量，仿佛可以毁天灭地。

"哈哈哈！从今天开始，我林云将踏上无敌之路！"
""",
        word_count=200,
        summary="主角获得传承",
        key_events=["获得传承"],
        character_appearances=["林云"],
    )
    
    # 创建简化的Novel对象
    from stage1_novel.novel_generator import Novel, StoryBlueprint, WorldBuilding, Character
    
    novel = Novel(
        metadata={"title": "测试小说", "genre": "修仙"},
        blueprint=StoryBlueprint(
            title="测试",
            genre="修仙",
            world_building=WorldBuilding("", "", [], []),
            characters=[Character(
                id="char_001", name="林云", role="protagonist",
                description="", personality="", goals="", background="", appearance=""
            )],
            plot_structure=[],
            chapter_plans=[],
        ),
        chapters=[chapter],
    )
    
    # 创建TTS引擎
    engine = TTSEngine()
    
    try:
        results = await engine.process(novel)
        print(f"\n✅ 测试成功！生成了 {len(results)} 章的音频")
        for chapter_num, chapter_audio in results.items():
            print(f"   第{chapter_num}章: {len(chapter_audio.segments)} 个片段")
            print(f"      总时长: {chapter_audio.total_duration:.2f}秒")
            for seg in chapter_audio.segments:
                print(f"      - {seg.speaker}: {seg.file_path}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n✅ TTS引擎测试完成!")


if __name__ == "__main__":
    asyncio.run(test_tts_engine())

"""
项目全局配置
支持NVIDIA NIM云服务和本地模型
"""

import os
from pathlib import Path
from typing import Dict, Optional

# ========== 项目路径 ==========
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
NOVELS_DIR = OUTPUTS_DIR / "novels"
IMAGES_DIR = OUTPUTS_DIR / "images"
AUDIO_DIR = OUTPUTS_DIR / "audio"
VIDEOS_DIR = OUTPUTS_DIR / "videos"
SUBTITLES_DIR = OUTPUTS_DIR / "subtitles"
CACHE_DIR = PROJECT_ROOT / "cache"
MODELS_DIR = PROJECT_ROOT / "models"
LLM_MODELS_DIR = MODELS_DIR / "llm"
IMAGE_MODELS_DIR = MODELS_DIR / "image"
SOUND_MODELS_DIR = MODELS_DIR / "sound"
VIDEO_MODELS_DIR = MODELS_DIR / "video"

# 确保目录存在
for d in [NOVELS_DIR, IMAGES_DIR, AUDIO_DIR, VIDEOS_DIR, SUBTITLES_DIR, CACHE_DIR, 
          MODELS_DIR, LLM_MODELS_DIR, IMAGE_MODELS_DIR, SOUND_MODELS_DIR, VIDEO_MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 设置全局模型缓存环境变量
# 默认指向模型总目录，具体的库会根据子目录进一步分配或由代码指定
os.environ["HF_HOME"] = str(MODELS_DIR)
os.environ["TRANSFORMERS_CACHE"] = str(MODELS_DIR)

# ========== 缓存配置 ==========
CACHE_CONFIG = {
    "enabled": True,
    "cache_dir": str(CACHE_DIR),
    "max_memory_cache_size": 100 * 1024 * 1024,  # 100MB
    "ttl": 86400,  # 24小时
}

# ========== 应用配置 ==========
APP_CONFIG = {
    "debug": False,
    "log_level": "INFO",
    "output_dir": str(OUTPUTS_DIR),
    "max_workers": 4,
    "force_regenerate": False,
}

# ========== LLM 全局配置 ==========
LLM_GLOBAL_CONFIG = {
    "max_tokens": 12000,
    "temperature": 0.7,
    "top_p": 0.9,
    # 各阶段max_tokens配置
    "max_tokens_per_stage": {
        "world_building": 4000,
        "characters": 4000,
        "power_system": 2000,
        "plot_structure": 4000,
        "chapter_plans": 4000,
        "chapter": 16000,   # 章节正文需要更多 token
        "chapter_chunk": 8000,  # 分块生成每块的 token 上限
        "script": 16000,
    },
}

# ========== NVIDIA NIM LLM配置 ==========
# 请在环境变量中设置或在此处填写
NVIDIA_NIM_CONFIG = {
    "base_url": os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"), # /chat/completions
    "api_key": os.getenv("NVIDIA_NIM_API_KEY", ""),
    "model": os.getenv("NVIDIA_NIM_MODEL", "nvidia/nemotron-3-super-120b-a12b"),
    # openai/gpt-oss-120b
    # nvidia/nemotron-3-super-120b-a12b
    # minimaxai/minimax-m2.5
    # qwen/qwen3.5-397b-a17b
    # z-ai/glm5  stepfun-ai/step-3.5-flash
    # minimaxai/minimax-m2.1
    # moonshotai/kimi-k2.5
    # deepseek-ai/deepseek-v3.2  google/gemma-4-31b-it
    # 备选模型: meta/llama3-8b-instruct, mistralai/mixtral-8x22b-instruct-v0.1
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 0.9,
}

# ========== 本地LLM配置 ==========
LOCAL_LLM_CONFIG = {
    "enabled": os.getenv("LOCAL_LLM_ENABLED", "false").lower() == "true",
    "provider": os.getenv("LOCAL_LLM_PROVIDER", "ollama"),  # ollama, vllm
    "ollama": {
        "base_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
    },
    "vllm": {
        "base_url": os.getenv("VLLM_URL", "http://localhost:8080/v1"),
        "model": os.getenv("VLLM_MODEL", "Qwen/Qwen3-14B-AWQ"),
        "api_key": os.getenv("VLLM_API_KEY", "EMPTY"),
    },
    "model_cache_dir": str(LLM_MODELS_DIR),
    "temperature": 0.7,
    "max_tokens": 12000,  # 提升以支持长文本章节生成
}

# ========== 图像生成配置 ==========
IMAGE_GENERATION = {
    # 云端API选项 (保留接口)
    "cloud_api": {
        "enabled": False,  # 设为True启用云端
        "provider": "stability",  # stability, midjourney, etc.
        "api_key": os.getenv("IMAGE_API_KEY", ""),
    },
    # 本地模型选项 (默认)
    "local": {
        "enabled": True,
        "model_type": "sdxl",  # sdxl, flux, sd15  Tongyi-MAI/Z-Image-Turbo
        # "model_path": os.getenv("LOCAL_SD_MODEL", "stabilityai/stable-diffusion-xl-base-1.0"),
        "model_path": os.getenv("LOCAL_SD_MODEL", "Tongyi-MAI/Z-Image-Turbo"),
        "model_cache_dir": str(IMAGE_MODELS_DIR),
        "controlnet_enabled": True,
        "lora_dir": os.getenv("LORA_DIR", ""),
        # 生成参数
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "cfg_scale": 7.5,
        "sampler": "DPM++ 2M Karras",
    },
    # 每章图像数量
    "images_per_chapter": 3,
    # 新增: 角色一致性
    "character_consistency": {
        "enabled": True,
        "type": "ipadapter",  # ipadapter, instantid
        "model_path": "h94/IP-Adapter",
        "scale": 0.5,  # IP-Adapter 影响强度 (0.0-1.0, 越高越接近定妆照)
    },
    # 新增: 分镜规划
    "storyboard": {
        "enabled": True,
        "shots_per_scene": 1,
    },
    # 是否将prompt翻译为英文 (SDXL等英文模型建议开启)
    "translate_to_english": False,
}

# ========== 视频生成配置 ==========
VIDEO_GENERATION = {
    # 图生视频配置
    "image_to_video": {
        "enabled": False,
        "backend": "svd",  # animate-diff, svd
        "frames": 24,
    },
    # SVD 模型配置
    "svd": {
        "model_path": "stabilityai/stable-video-diffusion-img2vid-xt",
        "frames": 24,           # 生成帧数 (14-24)
        "motion_bucket_id": 127,  # 运动强度 (0-255)
        "fps": 24,               # 输出帧率
        "noise_aug_strength": 0.02,  # 噪声增强强度
        "decode_chunk_size": 8,  # 解码块大小
    },
    # 本地模型缓存目录
    "model_cache_dir": str(VIDEO_MODELS_DIR),
}

# ========== 音频/TTS配置 ==========
AUDIO_GENERATION = {
    # 云端TTS选项 (保留接口)
    "cloud_tts": {
        "enabled": False,
        "provider": "azure",  # azure, elevenlabs, etc.
        "api_key": os.getenv("TTS_API_KEY", ""),
        "region": os.getenv("AZURE_REGION", ""),
    },
    # 本地TTS选项 (默认)
    "local": {
        "enabled": True,
        "backend": "edge",  # edge, chattts, gpt_sovits, fishspeech
        "model_path": os.getenv("TTS_MODEL_PATH", ""),
        # ChatTTS 参数
        "temperature": 0.3,
        "top_p": 0.7,
        # Edge TTS 参数
        "speed": 1.0,
        "model_cache_dir": str(SOUND_MODELS_DIR),
    },
    # 声音克隆配置
    "voice_clone": {
        "enabled": False,
        "backend": "gpt_sovits",  # gpt_sovits, xtts
        "reference_audio": None,  # 参考音频文件路径
        "reference_text": None,    # 参考音频对应的文本
    },
    # 角色声音配置
    "voice_mapping": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "male_1": "zh-CN-YunxiNeural",
        "male_2": "zh-CN-YunjianNeural",
        "male_3": "zh-CN-YunyangNeural",
        "male_4": "zh-CN-YunhaoNeural",
        "female_1": "zh-CN-XiaoyiNeural",
        "female_2": "zh-CN-liaoning-XiaobeiNeural",
        "female_3": "zh-CN-XiaohanNeural",
        "female_4": "zh-CN-XiaomengNeural",
    },
    # 语音特征配置
    "voice_characteristics": {
        "zh-CN-XiaoxiaoNeural": {"gender": "female", "age": "young", "tone": "calm"},
        "zh-CN-YunxiNeural": {"gender": "male", "age": "young", "tone": "energetic"},
        "zh-CN-YunjianNeural": {"gender": "male", "age": "middle", "tone": "deep"},
        "zh-CN-XiaoyiNeural": {"gender": "female", "age": "young", "tone": "bright"},
        "zh-CN-liaoning-XiaobeiNeural": {"gender": "female", "age": "young", "tone": "casual"},
        "zh-CN-XiaohanNeural": {"gender": "female", "age": "child", "tone": "cute"},
        "zh-CN-YunyangNeural": {"gender": "male", "age": "elder", "tone": "wise"},
        "zh-CN-XiaomengNeural": {"gender": "female", "age": "young", "tone": "sweet"},
        "zh-CN-YunhaoNeural": {"gender": "male", "age": "young", "tone": "authoritative"},
    },
    # 情感配置
    "emotion_config": {
        "enabled": True,
        "happy": {"rate": "+10%", "pitch": "+5%"},
        "sad": {"rate": "-10%", "pitch": "-5%"},
        "angry": {"rate": "+15%", "pitch": "+10%"},
        "fearful": {"rate": "+5%", "pitch": "-10%"},
        "excited": {"rate": "+20%", "pitch": "+8%"},
        "calm": {"rate": "-5%", "pitch": "0%"},
    },
    # 是否生成音效和背景音乐
    "enable_sfx": False,  # 本地实现较复杂，默认关闭
    "enable_music": False,
    "sfx_dir": "assets/sfx",
    "bgm_dir": "assets/bgm",
}

# ========== 视频合成配置 ==========
VIDEO_COMPOSITION = {
    "output_format": "mp4",
    "resolution": (1280, 720),  # 720p
    "fps": 24,
    "bitrate": "4000k",
    # 视频编码器: libx264 (H.264), libx265 (H.265), av1 (AV1)
    "video_codec": "libx264",
    # 每章视频时长（分钟）
    "target_duration_per_chapter": 3,
    # 图像展示时长（秒）
    "image_display_duration": 8,
    # 转场效果: fade, slideleft, slideright, slideup, slidedown,
    #           circlecrop, rectcrop, distance, wipeleft, wiperight, etc.
    "transition_effect": "none",
    "transition_duration": 0.5,
    # 批量处理
    "parallel_processing": False,
}

# ========== 字幕配置 ==========
SUBTITLE_CONFIG = {
    "enabled": True,
    "format": "srt",  # srt, vtt, ass
    "font": "Noto Sans CJK SC",  # 需要系统安装
    "font_size": 24,
    "color": "white",
    "stroke_color": "black",
    "stroke_width": 2,
    "position": "bottom",  # top, middle, bottom
}

# ========== 默认小说配置 ==========
DEFAULT_NOVEL_CONFIG = {
    "genre": "修仙",  # 修仙, 玄幻, 都市, etc.
    "style": "爽文",
    "total_chapters": 3,  # 默认3章
    "target_word_count": 5000,  # 每章字数
    "shuangdian_intensity": "high",
    "images_per_chapter": 3,
    "generate_audio": True,
    "generate_video": True,
}


def get_config() -> Dict:
    """获取完整配置"""
    return {
        "nvidia_nim": NVIDIA_NIM_CONFIG,
        "image": IMAGE_GENERATION,
        "video_generation": VIDEO_GENERATION,
        "audio": AUDIO_GENERATION,
        "video": VIDEO_COMPOSITION,
        "subtitle": SUBTITLE_CONFIG,
        "novel": DEFAULT_NOVEL_CONFIG,
        "cache": CACHE_CONFIG,
        "app": APP_CONFIG,
        "force_regenerate": APP_CONFIG.get("force_regenerate", False),
    }


def load_subsystem_config() -> Dict:
    """从JSON文件加载子系统配置"""
    import json
    config_path = PROJECT_ROOT / "config" / "subsystem_config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"警告: 加载子系统配置失败，使用默认配置: {e}")
        return {}


def get_llm_max_tokens(stage: str) -> int:
    """获取指定阶段的max_tokens"""
    return LLM_GLOBAL_CONFIG.get("max_tokens_per_stage", {}).get(stage, LLM_GLOBAL_CONFIG.get("max_tokens", 4096))

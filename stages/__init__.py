"""
阶段模块

包含四个处理阶段：小说生成、图像生成、音频生成、视频合成
"""
from stages.stage1_novel import NovelGenerator, NovelConcept, NovelGenerationPipeline, Novel
from stages.stage2_visual import ImageGenerator, ImageGenerationPipeline
from stages.stage3_audio import TTSEngine
from stages.stage4_merge import VideoComposer

from stages.stage3_audio.audio_post_processor import (
    AudioPostProcessor,
    FishAudioEngine,
    CosyVoiceEngine,
    get_audio_post_processor,
)
from stages.stage2_visual.video_generation import (
    HunyuanVideoEngine,
    KenBurnsEffect,
    VideoPostProcessor,
    get_ken_burns_engine,
    get_hunyuan_video_engine,
    get_video_post_processor,
)

__all__ = [
    # Stage 1: 小说生成
    'NovelGenerator',
    'NovelConcept',
    'NovelGenerationPipeline',
    'Novel',
    # Stage 2: 图像生成
    'ImageGenerator',
    'ImageGenerationPipeline',
    # Stage 3: 音频生成
    'TTSEngine',
    'AudioPostProcessor',
    'FishAudioEngine',
    'CosyVoiceEngine',
    'get_audio_post_processor',
    # Stage 4: 视频合成
    'VideoComposer',
    # 视频生成
    'HunyuanVideoEngine',
    'KenBurnsEffect',
    'VideoPostProcessor',
    'get_ken_burns_engine',
    'get_hunyuan_video_engine',
    'get_video_post_processor',
]

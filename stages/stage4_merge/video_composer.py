"""
视频合成引擎 - 第四阶段
负责将图像、音频合成为最终视频
"""

import os
import json
import subprocess
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

import sys
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import (
    VIDEO_COMPOSITION, SUBTITLE_CONFIG, VIDEO_GENERATION,
    VIDEOS_DIR, SUBTITLES_DIR
)
from core.base_pipeline import PipelineStage
from stages.stage1_novel.novel_generator import Novel, Chapter
from stages.stage2_visual.image_generator import ChapterImages, GeneratedImage, StoryboardFrame
from stages.stage3_audio.tts_engine import ChapterAudio, TTSSegment


@dataclass
class VideoClip:
    """视频片段信息"""
    clip_id: str
    chapter_number: int
    image_path: str
    audio_path: Optional[str]
    subtitle_path: Optional[str]
    duration: float
    transition: str
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FinalVideo:
    """最终视频信息"""
    chapter_number: int
    video_path: str
    subtitle_path: Optional[str]
    duration: float
    resolution: Tuple[int, int]
    file_size: int
    
    def to_dict(self) -> Dict:
        return {
            "chapter_number": self.chapter_number,
            "video_path": self.video_path,
            "subtitle_path": self.subtitle_path,
            "duration": self.duration,
            "resolution": self.resolution,
            "file_size": self.file_size,
        }


@dataclass
class GeneratedVideo:
    """生成的视频信息（图生视频）"""
    video_id: str
    chapter_number: int
    scene_description: str
    source_image_path: str
    file_path: str
    width: int
    height: int
    frames: int
    fps: int
    generation_time: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


class VideoGenerator:
    """
    视频生成器 - 图生视频（SVD）
    
    负责从图像生成动态视频
    """
    
    def __init__(self, config=None):
        """
        初始化视频生成器
        
        Args:
            config: VIDEO_GENERATION 配置字典
        """
        self.config = config or VIDEO_GENERATION
        self.svd_model = None
        self.device = None
        
        # 检查 PyTorch 和 diffusers 是否可用
        self.torch_available = self._check_torch()
        
        # 如果配置启用，初始化 SVD 模型
        if self.torch_available:
            self._init_svd_model()
    
    def _check_torch(self) -> bool:
        """检查 PyTorch 和 diffusers 是否可用"""
        try:
            import torch
            from diffusers import StableVideoDiffusionPipeline
            return True
        except ImportError:
            return False
    
    def _init_svd_model(self):
        """初始化 SVD 图生视频模型"""
        if not self.torch_available:
            return
        
        import torch
        from diffusers import StableVideoDiffusionPipeline
        
        try:
            # 检测 GPU
            if torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
            
            logger = __import__('logging').getLogger("video_generator")
            logger.info(f"使用设备: {self.device}")
            
            # 获取 SVD 配置
            svd_config = self.config.get("svd", {})
            svd_model_path = svd_config.get("model_path", "stabilityai/stable-video-diffusion-img2vid-xt")
            cache_dir = self.config.get("model_cache_dir", "models")
            
            logger.info(f"正在加载 SVD 模型: {svd_model_path}")
            
            load_kwargs = {
                "torch_dtype": torch.bfloat16, #if self.device == "cuda" else torch.float32,
                "use_safetensors": True,
            }
            
            if cache_dir:
                load_kwargs["cache_dir"] = cache_dir
            
            self.svd_model = StableVideoDiffusionPipeline.from_pretrained(
                svd_model_path,
                **load_kwargs
            )
            
            self.svd_model = self.svd_model.to(self.device)
            
            if self.device == "cuda":
                self.svd_model.enable_attention_slicing()
            
            logger.info("SVD 模型加载完成")
            
        except Exception as e:
            logger = __import__('logging').getLogger("video_generator")
            logger.error(f"SVD 模型加载失败", exc_info=True)
            self.svd_model = None
    
    async def generate_from_image(
        self,
        image_path: Path,
        chapter_number: int,
        video_index: int,
        scene_description: str = "",
    ) -> Path:
        """
        使用 SVD 模型从图像生成视频
        
        Args:
            image_path: 源图像路径
            chapter_number: 章节号
            video_index: 视频索引
            scene_description: 场景描述
            
        Returns:
            生成的视频路径
        """
        if not self.svd_model:
            raise ValueError("SVD 模型未加载")
        
        import torch
        logger = __import__('logging').getLogger("video_generator")
        logger.debug("使用 SVD 生成视频...")
        
        # 加载图像
        from PIL import Image
        image = Image.open(image_path).convert("RGB")
        original_width, original_height = image.size
        
        # 计算适合 SVD 的尺寸 (64 的倍数)
        # SVD XT 通常在总像素约 512k-600k 左右表现稳定，标准分辨率为 1024x576 或 576x1024
        aspect_ratio = original_width / original_height
        
        if aspect_ratio > 1.2:  # 横屏
            target_width = 1024
            target_height = int(1024 / aspect_ratio)
        elif aspect_ratio < 0.8:  # 竖屏
            target_height = 1024
            target_width = int(1024 * aspect_ratio)
        else:  # 接近正方形
            # 正方形或接近正方形建议使用 768x768 或 512x512
            target_width = 768
            target_height = int(768 / aspect_ratio)
            
        # 确保是 64 的倍数（SVD 模型要求）
        target_width = max(64, (target_width // 64) * 64)
        target_height = max(64, (target_height // 64) * 64)
        
        logger.info(f"   🎞️ SVD 分辨率调整: {original_width}x{original_height} -> {target_width}x{target_height} (比例: {aspect_ratio:.2f})")
        image = image.resize((target_width, target_height), Image.LANCZOS)
        
        # 获取 SVD 配置
        svd_config = self.config.get("svd", {})
        num_frames = svd_config.get("frames", 24)
        motion_bucket_id = svd_config.get("motion_bucket_id", 127)
        fps = svd_config.get("fps", 24)
        noise_aug_strength = svd_config.get("noise_aug_strength", 0.02)
        decode_chunk_size = svd_config.get("decode_chunk_size", 8)
        
        # 生成视频
        result = self.svd_model(
            image,
            width=target_width,
            height=target_height,
            num_frames=num_frames,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            decode_chunk_size=decode_chunk_size,
            generator=torch.Generator(device=self.device).manual_seed(42),
        )
        
        # 保存视频
        output_dir = VIDEOS_DIR / f"chapter_{chapter_number:03d}" / "svd"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        video_path = output_dir / f"video_{video_index:02d}.mp4"
        
        # 使用 imageio 保存视频
        try:
            import imageio
            import numpy as np
            
            frames = []
            for frame in result.frames[0]:
                frames.append(np.array(frame))
            
            imageio.mimwrite(video_path, frames, fps=fps, quality=8)
            print(f"      ✅ 视频已保存: {video_path}")
            
        except ImportError:
            print(f"      ⚠️  imageio 未安装，保存帧为图片")
            # 作为备选，保存每一帧为图片
            for i, frame in enumerate(result.frames[0]):
                frame_path = output_dir / f"video_{video_index:02d}_frame_{i:03d}.png"
                frame.save(frame_path)
            video_path = output_dir / f"video_{video_index:02d}_frames"
            print(f"      ✅ 视频帧已保存到: {video_path}")
        
        return video_path
    
    async def process_novel(
        self,
        novel,
        images: Dict,
    ) -> Dict[int, List[str]]:
        """
        为小说的所有图像生成视频
        
        Args:
            novel: 小说对象
            images: 章节图像字典
            
        Returns:
            章节号到视频路径列表的映射
        """
        all_videos = {}
        
        for chapter in novel.chapters:
            chapter_images = images.get(chapter.number)
            if not chapter_images:
                print(f"   ⚠️  第{chapter.number}章没有图像，跳过")
                continue
            
            print(f"\n   📹 处理第{chapter.number}章...")
            
            chapter_videos = []
            
            for i, image in enumerate(chapter_images.images):
                print(f"      🎬 图像 {i + 1}/{len(chapter_images.images)} -> 视频")
                
                try:
                    video_path = await self.generate_from_image(
                        image_path=Path(image.file_path),
                        chapter_number=chapter.number,
                        video_index=i,
                        scene_description=image.scene_description,
                    )
                    chapter_videos.append(str(video_path))
                    
                except Exception as e:
                    print(f"      ❌ 视频生成失败: {e}")
            
            if chapter_videos:
                all_videos[chapter.number] = chapter_videos
        
        return all_videos


class VideoComposer(PipelineStage):
    """
    视频合成器
    
    将图像、音频、字幕合成为最终视频
    
    依赖：FFmpeg
    """
    
    def __init__(self, config=None):
        super().__init__("视频合成", config or VIDEO_COMPOSITION)
        self.subtitle_config = SUBTITLE_CONFIG
        self.ffmpeg_available = self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except:
            return False
    
    def validate_input(self, input_data) -> bool:
        """验证输入"""
        # 期望的输入格式：字典包含novel, images, audio
        if isinstance(input_data, dict):
            return all(k in input_data for k in ["novel", "images", "audio"])
        return False
    
    async def process(self, input_data: Dict) -> Dict[int, FinalVideo]:
        """
        合成视频
        
        Args:
            input_data: 包含novel, images, audio的字典
            
        Returns:
            章节号到最终视频的映射
        """
        if not self.ffmpeg_available:
            raise RuntimeError("FFmpeg未安装，无法合成视频")
        
        novel = input_data["novel"]
        images = input_data["images"]
        audio = input_data["audio"]
        
        # 存储小说标题供后续使用
        self.current_novel_title = novel.metadata.get('title', '')
        
        print(f"🎬 开始合成视频《{novel.metadata['title']}》")
        print(f"   章节数: {len(novel.chapters)}")
        print(f"   分辨率: {self.config['resolution']}")
        print(f"   帧率: {self.config['fps']}fps")
        
        parallel_enabled = self.config.get("parallel_processing", False)
        
        if parallel_enabled and len(novel.chapters) > 1:
            print(f"   🚀 启用并行处理")
            results = await self._process_parallel(novel, images, audio)
        else:
            print(f"   ℹ️  使用顺序处理")
            results = await self._process_sequential(novel, images, audio)
        
        print(f"\n✅ 视频合成完成！共合成 {len(results)} 章视频")
        
        return results
    
    async def _process_sequential(
        self,
        novel: Novel,
        images: Dict[int, ChapterImages],
        audio: Dict[int, ChapterAudio],
    ) -> Dict[int, FinalVideo]:
        """顺序处理多章视频"""
        results = {}
        
        for chapter in novel.chapters:
            print(f"\n   📽️  合成第{chapter.number}章视频...")
            final_video = await self._process_single_chapter(chapter, images, audio)
            if final_video:
                results[chapter.number] = final_video
        
        return results
    
    async def _process_parallel(
        self,
        novel: Novel,
        images: Dict[int, ChapterImages],
        audio: Dict[int, ChapterAudio],
    ) -> Dict[int, FinalVideo]:
        """并行处理多章视频"""
        tasks = []
        for chapter in novel.chapters:
            tasks.append(self._process_single_chapter(chapter, images, audio))
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for i, result in enumerate(results_list):
            if isinstance(result, FinalVideo):
                results[novel.chapters[i].number] = result
            elif isinstance(result, Exception):
                print(f"   ❌ 第{novel.chapters[i].number}章视频合成失败: {result}")
        
        return results
    
    async def _process_single_chapter(
        self,
        chapter: Chapter,
        images: Dict[int, ChapterImages],
        audio: Dict[int, ChapterAudio],
        novel_title: str = None,
    ) -> Optional[FinalVideo]:
        """处理单个章节的视频合成"""
        chapter_images = images.get(chapter.number)
        chapter_audio = audio.get(chapter.number)
        
        # 获取小说标题
        novel_title = None
        if hasattr(chapter, 'metadata') and chapter.metadata:
            novel_title = chapter.metadata.get('title')
        elif hasattr(self, 'current_novel_title'):
            novel_title = self.current_novel_title
        
        if not chapter_images or not chapter_audio:
            print(f"   ⚠️  第{chapter.number}章缺少图像或音频，跳过")
            return None
        
        try:
            final_video = await self._compose_chapter_video(
                chapter=chapter,
                images=chapter_images,
                audio=chapter_audio,
                novel_title=novel_title,
            )
            print(f"   ✅ 第{chapter.number}章视频合成完成")
            print(f"      时长: {final_video.duration:.2f}秒")
            print(f"      文件: {final_video.video_path}")
            return final_video
        except Exception as e:
            print(f"   ❌ 第{chapter.number}章视频合成失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _load_timeline(self, novel_title: str, chapter_number: int) -> Optional[Dict]:
        """加载时间线清单"""
        try:
            from config.settings import AUDIO_DIR
            audio_dir = AUDIO_DIR / novel_title.replace(' ', '_')
            timeline_path = audio_dir / f"timeline_ch{chapter_number:03d}.json"
            
            if timeline_path.exists():
                import json
                with open(timeline_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return None
    
    def _find_image_for_shot(self, shot_id: str, images_dir: Path) -> Optional[Path]:
        """根据 shot_id 查找图像"""
        if not images_dir.exists():
            return None
        
        # 提取 scene_id (例如从 SC01_SH01 提取 SC01)
        scene_id = shot_id.split('_')[0] if '_' in shot_id else shot_id
        
        # 尝试多种命名方式
        possible_names = [
            f"{shot_id}.png",
            f"{shot_id}.jpg",
            f"{scene_id}.png",  # 尝试按场景名查找
            f"{scene_id}.jpg",
            f"keyframe_{shot_id}.png",
            f"image_{shot_id}.png",
        ]
        
        for name in possible_names:
            path = images_dir / name
            if path.exists():
                return path
        
        # 尝试匹配 image_XX.png (旧版命名)
        image_files = sorted(list(images_dir.glob("image_*.png")))
        if image_files:
            return image_files[0]
        
        return None
    
    def _generate_subtitles_from_timeline(self, timeline_entries: List[Dict], subtitle_path: Path):
        """从时间线生成字幕"""
        srt_content = []
        
        for i, entry in enumerate(timeline_entries, 1):
            start_time = self._format_srt_time(entry.get('start_time', 0.0))
            end_time = self._format_srt_time(entry.get('end_time', 0.0))
            text = entry.get('text', '')
            
            srt_content.append(f"{i}\n{start_time} --> {end_time}\n{text}\n")
        
        subtitle_path.write_text('\n'.join(srt_content), encoding='utf-8')
    
    def _format_srt_time(self, seconds: float) -> str:
        """格式化 SRT 时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    async def _compose_chapter_video(
        self,
        chapter: Chapter,
        images: ChapterImages,
        audio: ChapterAudio,
        novel_title: str = None,
    ) -> FinalVideo:
        """
        合成单章视频（增强版：支持分镜信息和时间线）
        
        优先使用：
        1. timeline_manifest.json (Stage 3产出) - 精确时间线
        2. storyboard_frames - 分镜信息
        3. 默认配置
        
        使用FFmpeg将图像和音频合成为视频
        """
        chapter_num = chapter.number
        
        # 输出路径
        output_dir = VIDEOS_DIR / f"chapter_{chapter_num:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        video_path = output_dir / f"chapter_{chapter_num:03d}.mp4"
        subtitle_path = output_dir / f"chapter_{chapter_num:03d}.srt"
        
        # 优先尝试使用 timeline_manifest.json
        timeline_data = None
        if novel_title:
            timeline_data = self._load_timeline(novel_title, chapter_num)
        
        # 准备输入文件
        image_list_file = output_dir / "image_list.txt"
        
        display_durations = []
        
        # 1. 使用 timeline (最精确)
        if timeline_data and 'entries' in timeline_data:
            timeline_entries = timeline_data['entries']
            if timeline_entries:
                print(f"      📜 使用 timeline_manifest.json，共 {len(timeline_entries)} 个片段")
                
                # 从时间线构建图像列表
                from config.settings import IMAGES_DIR
                images_dir = IMAGES_DIR / novel_title.replace(' ', '_')
                
                with open(image_list_file, 'w') as f:
                    for entry in timeline_entries:
                        # 查找对应图像
                        shot_id = entry.get('shot_id', '')
                        image_file = self._find_image_for_shot(shot_id, images_dir)
                        
                        if image_file and Path(image_file).exists():
                            path_str = str(image_file).replace("'", "'\\''")
                            duration = entry.get('duration', 3.0)
                            f.write(f"file '{path_str}'\n")
                            f.write(f"duration {duration}\n")
                            display_durations.append(duration)
                
                # 生成字幕
                self._generate_subtitles_from_timeline(timeline_entries, subtitle_path)
                
        # 2. 回退到 storyboard_frames
        elif hasattr(images, 'storyboard_frames') and images.storyboard_frames:
            storyboard_frames = images.storyboard_frames
            if len(storyboard_frames) == len(images.images):
                display_durations = [frame.duration for frame in storyboard_frames]
                print(f"      🎬 使用分镜信息，共 {len(display_durations)} 帧")
                
                with open(image_list_file, 'w') as f:
                    for i, img in enumerate(images.images):
                        path = img.file_path.replace("'", "'\\''")
                        duration = display_durations[i] if i < len(display_durations) else display_durations[-1]
                        f.write(f"file '{path}'\n")
                        f.write(f"duration {duration}\n")
                    if images.images:
                        last_path = images.images[-1].file_path.replace("'", "'\\''")
                        f.write(f"file '{last_path}'\n")
        
        # 3. 默认方式
        else:
            if audio.combined_file and len(images.images) > 0:
                total_audio_duration = await self._get_audio_duration(audio.combined_file)
                default_duration = total_audio_duration / len(images.images)
            else:
                default_duration = self.config.get("image_display_duration", 8)
            display_durations = [default_duration] * len(images.images)
            
            with open(image_list_file, 'w') as f:
                for i, img in enumerate(images.images):
                    path = img.file_path.replace("'", "'\\''")
                    duration = display_durations[i] if i < len(display_durations) else display_durations[-1]
                    f.write(f"file '{path}'\n")
                    f.write(f"duration {duration}\n")
                if images.images:
                    last_path = images.images[-1].file_path.replace("'", "'\\''")
                    f.write(f"file '{last_path}'\n")
        
        # 2. 生成字幕（如果启用）
        if self.subtitle_config["enabled"]:
            await self._generate_subtitles(audio, subtitle_path, display_durations[0] if display_durations else 8)
        
        # 3. 构建FFmpeg命令
        resolution = self.config["resolution"]
        fps = self.config["fps"]
        bitrate = self.config["bitrate"]
        
        # 准备音频文件 - 优先使用combined.mp3，否则查找其他mp3
        audio_file = None
        if audio.combined_file and Path(audio.combined_file).exists():
            audio_file = audio.combined_file
        else:
            # 查找其他mp3文件
            audio_dir = Path(audio.segments[0].file_path).parent if audio.segments else None
            if audio_dir and audio_dir.exists():
                mp3_files = sorted(audio_dir.glob("*.mp3"))
                if mp3_files:
                    audio_file = str(mp3_files[0])
                    print(f"      ℹ️  使用音频文件: {Path(audio_file).name}")

        # 构建视频滤镜 - 保持图像比例并添加padding
        target_w, target_h = resolution
        # scale滤镜: 按比例缩放，不超出目标尺寸，然后添加padding居中
        vf_scale = f"scale=w={target_w}:h={target_h}:force_original_aspect_ratio=decrease:flags=lanczos,pad=w={target_w}:h={target_h}:x=(ow-iw)/2:y=(oh-ih)/2:color=black"

        # 获取转场配置
        transition = self.config.get("transition_effect", "none")
        transition_duration = self.config.get("transition_duration", 0.5)

        # 基础命令
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出
        ]

        # 处理转场特效
        use_concat = True
        if transition != "none" and len(images.images) > 1:
            use_concat = False
            cmd = await self._build_transition_command(
                cmd, images, display_durations, vf_scale, transition, transition_duration
            )
        else:
            # 无转场，使用原来的 concat 方式
            cmd.extend([
                "-f", "concat",
                "-safe", "0",
                "-i", str(image_list_file),
            ])

        # 添加音频（如果有）
        if audio_file:
            cmd.extend([
                "-i", audio_file,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",  # 以最短输入为准
            ])

        vf_chain = []
        if use_concat:
            vf_chain.append(vf_scale)

        # 添加字幕（如果有）
        if self.subtitle_config["enabled"] and subtitle_path.exists():
            vf_chain.append(f"subtitles={subtitle_path}:force_style='FontSize=24'")

        if vf_chain and use_concat:
            cmd.extend(["-vf", ",".join(vf_chain)])

        # 获取编码器配置
        video_codec = self.config.get("video_codec", "libx264")
        supported_codecs = {
            "libx264": {"codec": "libx264", "preset": "medium"},
            "libx265": {"codec": "libx265", "preset": "medium"},
            "av1": {"codec": "libaom-av1", "preset": "8"},
        }
        codec_config = supported_codecs.get(video_codec, supported_codecs["libx264"])

        # 视频编码参数
        cmd.extend([
            "-c:v", codec_config["codec"],
            "-preset", codec_config["preset"],
            "-r", str(fps),
            "-b:v", bitrate,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(video_path),
        ])
        
        # 执行FFmpeg
        print(f"      🎬 执行FFmpeg合成...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "未知错误"
            raise RuntimeError(f"FFmpeg执行失败: {error_msg[:500]}")
        
        # 获取视频信息
        duration = await self._get_video_duration(str(video_path))
        file_size = video_path.stat().st_size
        
        # 清理临时文件
        image_list_file.unlink(missing_ok=True)
        
        return FinalVideo(
            chapter_number=chapter_num,
            video_path=str(video_path),
            subtitle_path=str(subtitle_path) if subtitle_path.exists() else None,
            duration=duration,
            resolution=resolution,
            file_size=file_size,
        )
    
    async def _generate_subtitles(
        self,
        audio: ChapterAudio,
        output_path: Path,
        display_duration: float,
    ):
        """
        生成SRT字幕文件
        
        将TTS文本转换为SRT字幕格式
        """
        subtitles = []
        current_time = 0.0
        
        for i, segment in enumerate(audio.segments, 1):
            # 计算时间段
            start_time = current_time
            end_time = start_time + segment.duration
            
            # 格式化为SRT时间格式：HH:MM:SS,mmm
            def format_time(t):
                td = timedelta(seconds=t)
                hours, remainder = divmod(td.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                milliseconds = int(td.microseconds / 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
            
            # 清理文本（移除换行符等）
            text = segment.text.replace('\n', ' ').strip()
            if len(text) > 100:
                text = text[:100] + "..."
            
            # 添加字幕条目
            subtitles.append(f"{i}")
            subtitles.append(f"{format_time(start_time)} --> {format_time(end_time)}")
            subtitles.append(text)
            subtitles.append("")  # 空行分隔
            
            current_time = end_time
        
        # 写入SRT文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(subtitles))
        
        print(f"      📝 字幕已生成: {output_path}")
    
    async def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长"""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, _ = await process.communicate()
            
            if stdout:
                return float(stdout.decode().strip())
        except:
            pass
        
        return 0.0
    
    async def _build_transition_command(
        self,
        cmd: List[str],
        images: ChapterImages,
        display_durations: List[float],
        vf_scale: str,
        transition: str,
        transition_duration: float,
    ) -> List[str]:
        """
        构建带转场特效的 FFmpeg 命令
        
        Args:
            cmd: 基础命令列表
            images: 章节图像
            display_durations: 每张图像的显示时长
            vf_scale: 缩放滤镜
            transition: 转场类型
            transition_duration: 转场持续时间
            
        Returns:
            完整的 FFmpeg 命令列表
        """
        output_dir = Path(cmd[-1]).parent if cmd else Path(".")
        
        # 1. 先为每张图像生成单独的视频片段
        temp_videos = []
        for i, img in enumerate(images.images):
            temp_video = output_dir / f"temp_img_{i:03d}.mp4"
            temp_videos.append(temp_video)
            
            duration = display_durations[i] if i < len(display_durations) else display_durations[-1]
            
            temp_cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img.file_path,
                "-vf", f"{vf_scale},fps=24",
                "-t", str(duration),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(temp_video),
            ]
            
            process = await asyncio.create_subprocess_exec(
                *temp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
        
        # 2. 使用 xfade 滤镜创建转场
        if len(temp_videos) >= 2:
            # 添加所有临时视频作为输入
            for temp_video in temp_videos:
                cmd.extend(["-i", str(temp_video)])
            
            # 构建 xfade 滤镜链
            filter_parts = []
            current = "[0:v]"
            
            for i in range(len(temp_videos) - 1):
                offset = sum(display_durations[:i+1]) - transition_duration
                xfade_filter = f"xfade=transition={transition}:duration={transition_duration}:offset={offset}"
                filter_parts.append(f"{current}[{i+1}:v]{xfade_filter}[v{i+1}]")
                current = f"[v{i+1}]"
            
            if filter_parts:
                cmd.extend(["-filter_complex", ";".join(filter_parts)])
                cmd.extend(["-map", current])
            else:
                cmd.extend(["-map", "[0:v]"])
        
        return cmd
    
    async def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长（与音频相同实现）"""
        return await self._get_audio_duration(video_path)


# ========== 便捷函数 ==========

async def quick_compose_video(
    novel: Novel,
    images: Dict[int, ChapterImages],
    audio: Dict[int, ChapterAudio],
) -> Dict[int, FinalVideo]:
    """
    快速合成视频的便捷函数
    """
    composer = VideoComposer()
    input_data = {
        "novel": novel,
        "images": images,
        "audio": audio,
    }
    return await composer.process(input_data)


# ========== 测试代码 ==========

async def test_video_composer():
    """测试视频合成器"""
    print("🧪 测试视频合成器...")
    
    # 检查FFmpeg
    composer = VideoComposer()
    if not composer.ffmpeg_available:
        print("❌ FFmpeg未安装，跳过测试")
        print("   请安装FFmpeg: sudo apt-get install ffmpeg")
        return
    
    print("✅ FFmpeg已安装")
    print("\n注意: 完整测试需要小说、图像和音频数据")
    print("     请运行完整流程测试")
    
    print("\n✅ 视频合成器测试完成!")


if __name__ == "__main__":
    asyncio.run(test_video_composer())

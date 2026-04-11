"""
视频生成模块 - 支持多种图生视频方式
1. SVD (Stable Video Diffusion)
2. HunyuanVideo I2V
3. Ken Burns 静态效果
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, List
from PIL import Image
import numpy as np

from core.logger import get_logger

logger = get_logger("video_generation")


class HunyuanVideoEngine:
    """HunyuanVideo 图生视频引擎"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.model = None
        self.device = None
        self._init_model()
    
    def _init_model(self):
        try:
            import torch
            from diffusers import AutoencoderKL, HunyuanVideoDiffusionPipeline
            
            if torch.cuda.is_available():
                self.device = "cuda"
                logger.info(f"使用GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = "cpu"
                logger.info("使用CPU")
            
            model_path = self.config.get("model_path", "hunyuanvideo-community/HunyuanVideo-1.5-Dual-GRAD")
            
            logger.info(f"正在加载 HunyuanVideo 模型: {model_path}")
            
            self.model = HunyuanVideoDiffusionPipeline.from_pretrained(
                model_path,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            )
            
            if self.device == "cuda":
                self.model.enable_attention_slicing()
            
            logger.info("HunyuanVideo 模型加载完成")
            
        except ImportError as e:
            logger.warning(f"HunyuanVideo 依赖未安装: {e}")
        except Exception as e:
            logger.error(f"HunyuanVideo 模型加载失败: {e}")
    
    def is_available(self) -> bool:
        return self.model is not None
    
    async def generate(
        self,
        image: Image.Image,
        output_path: Path,
        num_frames: int = 81,
        fps: int = 24,
        motion_bucket_id: int = 127,
        prompt: str = "",
    ) -> float:
        """生成视频"""
        if not self.model:
            raise RuntimeError("HunyuanVideo 模型未加载")
        
        result = self.model(
            image=image,
            prompt=prompt,
            num_inference_steps=25,
            num_frames=num_frames,
            guidance_scale=7.0,
        )
        
        frames = result.frames[0]
        
        import imageio
        imageio.mimwrite(output_path, frames, fps=fps)
        
        return len(frames) / fps


class KenBurnsEffect:
    """Ken Burns 静态图动态效果引擎"""
    
    def __init__(self):
        self.ffmpeg_available = self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def generate_push_in(
        self,
        image_path: str,
        output_path: str,
        duration: float = 5.0,
        zoom_range: tuple = (1.0, 1.5),
    ) -> bool:
        """
        缓慢推镜头效果 (Slow Push-in)
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径
            duration: 视频时长（秒）
            zoom_range: 缩放范围 (起始, 结束)
        """
        if not self.ffmpeg_available:
            logger.warning("FFmpeg不可用，跳过Ken Burns效果")
            return False
        
        start_zoom = zoom_range[0]
        end_zoom = zoom_range[1]
        frames = int(duration * 24)
        
        zoom_expr = f"min(zoom+{ (end_zoom - start_zoom) / frames },{end_zoom})"
        
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"zoompan=z='{zoom_expr}':d={frames}:s=854x480:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"推镜头效果生成完成: {output_path}")
                return True
            else:
                logger.error(f"推镜头效果生成失败: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"推镜头效果异常: {e}")
            return False
    
    def generate_pan_left(
        self,
        image_path: str,
        output_path: str,
        duration: float = 5.0,
    ) -> bool:
        """
        向左平移效果 (Pan Left)
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径
            duration: 视频时长（秒）
        """
        if not self.ffmpeg_available:
            return False
        
        frames = int(duration * 24)
        
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"zoompan=z=1:x='iw/2-(iw/zoom/2)-({frames}/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=854x480",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def generate_pan_right(
        self,
        image_path: str,
        output_path: str,
        duration: float = 5.0,
    ) -> bool:
        """向右平移效果"""
        if not self.ffmpeg_available:
            return False
        
        frames = int(duration * 24)
        
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"zoompan=z=1:x='iw/2-(iw/zoom/2)+({frames}/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=854x480",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def generate_zoom_out(
        self,
        image_path: str,
        output_path: str,
        duration: float = 5.0,
    ) -> bool:
        """
        拉远镜头效果 (Zoom Out)
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径
            duration: 视频时长（秒）
        """
        if not self.ffmpeg_available:
            return False
        
        frames = int(duration * 24)
        
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"zoompan=z='max(zoom-0.001,1)':d={frames}:s=854x480:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def generate_fade_in_out(
        self,
        image_path: str,
        output_path: str,
        duration: float = 5.0,
    ) -> bool:
        """淡入淡出效果"""
        if not self.ffmpeg_available:
            return False
        
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", image_path,
            "-vf", f"fade=t=in:st=0:d=1,fade=t=out:st={duration-1}:d=1",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False


class VideoPostProcessor:
    """视频后期处理 - 颜色校正、特效等"""
    
    def __init__(self):
        self.ffmpeg_available = self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def adjust_brightness(
        self,
        input_path: str,
        output_path: str,
        brightness: float = 0.0,
    ) -> bool:
        """
        调整亮度
        
        Args:
            brightness: 亮度调整值 (-1 到 1)
        """
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", f"eq=brightness={brightness}",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def adjust_contrast(
        self,
        input_path: str,
        output_path: str,
        contrast: float = 1.0,
    ) -> bool:
        """调整对比度"""
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", f"eq=contrast={contrast}",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def adjust_saturation(
        self,
        input_path: str,
        output_path: str,
        saturation: float = 1.0,
    ) -> bool:
        """调整饱和度"""
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", f"eq=saturation={saturation}",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def apply_color_grade(
        self,
        input_path: str,
        output_path: str,
        preset: str = "cinematic",
    ) -> bool:
        """
        应用电影级调色
        
        Args:
            preset: 预设 (cinematic, warm, cool, vintage)
        """
        if not self.ffmpeg_available:
            return False
        
        color_presets = {
            "cinematic": "eq=contrast=1.1:saturation=0.9:gamma=0.9",
            "warm": "colortemperature=temperature=6500",
            "cool": "colortemperature=temperature=9000",
            "vintage": "geq=128+0*sin(PI*Y/40):128+0*cos(PI*Y/40):128+15*sin(PI*Y/60)",
        }
        
        color_filter = color_presets.get(preset, color_presets["cinematic"])
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", color_filter,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def apply_blur(
        self,
        input_path: str,
        output_path: str,
        strength: int = 5,
    ) -> bool:
        """应用模糊效果"""
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", f"boxblur={strength}",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def add_sharpen(
        self,
        input_path: str,
        output_path: str,
        amount: float = 1.0,
    ) -> bool:
        """添加锐化效果"""
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", f"unsharp=5:5:{amount}:5:5:0.0",
                "-c:a", "copy",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False


def get_video_post_processor() -> VideoPostProcessor:
    """获取视频后期处理器实例"""
    return VideoPostProcessor()


def get_ken_burns_engine() -> KenBurnsEffect:
    """获取Ken Burns引擎实例"""
    return KenBurnsEffect()


def get_hunyuan_video_engine(config: dict = None) -> HunyuanVideoEngine:
    """获取HunyuanVideo引擎实例"""
    return HunyuanVideoEngine(config)
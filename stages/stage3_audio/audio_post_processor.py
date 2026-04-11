"""
音频后期处理模块
提供音量标准化、EQ调节、混响等功能
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List
import numpy as np

from core.logger import get_logger

logger = get_logger("audio_post_processor")


class AudioPostProcessor:
    """音频后期处理器"""
    
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
    
    def normalize_loudness(
        self,
        input_path: str,
        output_path: str,
        target_loudness: float = -16.0,
    ) -> bool:
        """
        音量标准化 (Loudness Normalization)
        
        使用 EBU R128 标准进行响度标准化
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            target_loudness: 目标响度 (dB LUFS)，默认 -16
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            logger.warning("FFmpeg不可用，跳过音量标准化")
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-af", f"loudnorm=I={target_loudness}:TP=-1.5:LRA=11",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"音量标准化完成: {output_path}")
                return True
            else:
                logger.error(f"音量标准化失败: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"音量标准化异常: {e}")
            return False
    
    def apply_eq(
        self,
        input_path: str,
        output_path: str,
        preset: str = "default",
    ) -> bool:
        """
        应用均衡器
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            preset: 预设 (default, bass_boost, treble_boost, vocal, movie)
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        eq_presets = {
            "default": "equalizer=f=100:t=q:width_type=o:g=0,equalizer=f=1000:t=q:width_type=o:g=0,equalizer=f=10000:t=q:width_type=o:g=0",
            "bass_boost": "equalizer=f=60:t=q:width_type=h:g=6,equalizer=f=120:t=q:width_type=h:g=4",
            "treble_boost": "equalizer=f=6000:t=q:width_type=h:g=4,equalizer=f=12000:t=q:width_type=h:g=6",
            "vocal": "equalizer=f=300:t=q:width_type=o:g=-2,equalizer=f=2000:t=q:width_type=o:g=2,equalizer=f=4000:t=q:width_type=o:g=-1",
            "movie": "equalizer=f=80:t=q:width_type=h:g=3,equalizer=f=200:t=q:width_type=h:g=-2,equalizer=f=5000:t=q:width_type=h:g=2",
        }
        
        eq_filter = eq_presets.get(preset, eq_presets["default"])
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-af", eq_filter,
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"EQ处理异常: {e}")
            return False
    
    def add_reverb(
        self,
        input_path: str,
        output_path: str,
        wet_dry: float = 0.3,
        room_size: float = 0.5,
    ) -> bool:
        """
        添加混响效果
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            wet_dry: 混响湿/干比例 (0-1)
            room_size: 房间大小 (0-1)
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        reverb_presets = {
            0.3: "0.3",
            0.5: "0.5", 
            0.7: "0.7",
            1.0: "1.0",
        }
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-af", f"aecho=0.8:0.9:60:0.4",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"混响处理异常: {e}")
            return False
    
    def compress_dynamic_range(
        self,
        input_path: str,
        output_path: str,
        threshold: float = -20.0,
        ratio: float = 4.0,
    ) -> bool:
        """
        动态范围压缩
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            threshold: 阈值 (dB)
            ratio: 压缩比率
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-af", f"acompressor=threshold={threshold}dB:ratio={ratio}:attack=5:release=50",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"动态压缩异常: {e}")
            return False
    
    def change_speed(
        self,
        input_path: str,
        output_path: str,
        speed: float = 1.0,
        preserve_pitch: bool = True,
    ) -> bool:
        """
        改变音频速度
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            speed: 速度倍率 (>1 快, <1 慢)
            preserve_pitch: 是否保持音调
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        try:
            if preserve_pitch:
                cmd = [
                    "ffmpeg",
                    "-i", input_path,
                    "-af", f"atempo={speed}",
                    "-y",
                    output_path
                ]
            else:
                cmd = [
                    "ffmpeg",
                    "-i", input_path,
                    "-filter:a", f"setpts={1/speed*PTS}",
                    "-filter:v", f"setpts={1/speed*PTS}",
                    "-y",
                    output_path
                ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"变速异常: {e}")
            return False
    
    def change_pitch(
        self,
        input_path: str,
        output_path: str,
        semitones: float = 0.0,
    ) -> bool:
        """
        改变音频音调
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            semitones: 半音程 (+/- 12 为一个八度)
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        try:
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-af", f"asetpitch={semitones}",
                "-y",
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"变调异常: {e}")
            return False
    
    def get_audio_duration(self, audio_path: str) -> Optional[float]:
        """获取音频时长"""
        if not self.ffmpeg_available:
            return None
        
        try:
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
        return None
    
    def merge_audio_tracks(
        self,
        input_paths: List[str],
        output_path: str,
        volumes: Optional[List[float]] = None,
    ) -> bool:
        """
        合并多个音频轨道
        
        Args:
            input_paths: 输入音频路径列表
            output_path: 输出音频路径
            volumes: 各轨道的音量 (0-1)
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            return False
        
        if not input_paths:
            return False
        
        try:
            cmd = ["ffmpeg", "-y"]
            filter_parts = []
            
            for i, path in enumerate(input_paths):
                cmd.extend(["-i", path])
                vol = volumes[i] if volumes and i < len(volumes) else 1.0
                filter_parts.append(f"[{i}:a]volume={vol}[a{i}]")
            
            if len(input_paths) > 1:
                inputs_str = "".join(f"[a{i}]" for i in range(len(input_paths)))
                filter_complex = f"{';'.join(filter_parts)};{inputs_str}amix=inputs={len(input_paths)}:duration=longest"
                cmd.extend(["-filter_complex", filter_complex])
            else:
                cmd.extend(["-filter_complex", filter_parts[0]])
            
            cmd.append(output_path)
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"音频合并异常: {e}")
            return False


class FishAudioEngine:
    """Fish Audio TTS 引擎"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", "http://localhost:8080")
        self.model = None
        self._init_model()
    
    def _init_model(self):
        try:
            import requests
            self.requests = requests
            print("✅ Fish Audio 引擎初始化完成")
        except ImportError:
            print("⚠️  requests 库未安装")
    
    async def generate(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> float:
        """生成语音"""
        if not hasattr(self, 'requests'):
            raise RuntimeError("Fish Audio 不可用")
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {
                    "text": text,
                    "reference_id": voice_id,
                    "speed": speed,
                }
                async with session.post(
                    f"{self.base_url}/v1/tts",
                    json=payload,
                ) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        output_path.write_bytes(audio_data)
                        return len(audio_data) / 44100 / 2
        except Exception as e:
            logger.error(f"Fish Audio 生成失败: {e}")
            raise
    
    def is_available(self) -> bool:
        return hasattr(self, 'requests')


class CosyVoiceEngine:
    """CosyVoice TTS 引擎"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", "http://localhost:5000")
        self.model = None
    
    async def generate(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        emotion: str = "neutral",
    ) -> float:
        """生成语音"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {
                    "text": text,
                    "voice_id": voice_id,
                    "emotion": emotion,
                }
                async with session.post(
                    f"{self.base_url}/v1/tts",
                    json=payload,
                ) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        output_path.write_bytes(audio_data)
                        return len(audio_data) / 44100 / 2
        except Exception as e:
            logger.error(f"CosyVoice 生成失败: {e}")
            raise
    
    def is_available(self) -> bool:
        return False


def get_audio_post_processor() -> AudioPostProcessor:
    """获取音频后期处理器实例"""
    return AudioPostProcessor()
"""
视频合成器 - 读取 timeline_manifest.json 进行精确合成
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

from core.logger import get_logger

logger = get_logger("video_timeline_composer")


@dataclass
class TimelineEntry:
    """时间线条目"""
    shot_id: str
    scene_id: str
    speaker: str
    text: str
    audio_file: str
    image_file: str
    start_time: float
    end_time: float
    duration: float
    emotion: str


class TimelineComposer:
    """时间线合成器 - 读取 Stage 3 产出的 timeline_manifest.json"""
    
    def __init__(self, novel_title: str, output_dir: Path):
        self.novel_title = novel_title
        self.output_dir = Path(output_dir)
        self.timeline: Optional[Dict] = None
    
    def load_timeline(self, chapter_number: int, audio_dir: Path) -> Optional[Dict]:
        """加载时间线清单"""
        timeline_path = audio_dir / f"timeline_ch{chapter_number:03d}.json"
        
        if not timeline_path.exists():
            logger.warning(f"时间线清单不存在: {timeline_path}")
            return None
        
        with open(timeline_path, 'r', encoding='utf-8') as f:
            self.timeline = json.load(f)
        
        logger.info(f"加载了第{chapter_number}章的时间线，共{len(self.timeline.get('entries', []))}个片段")
        return self.timeline
    
    def get_clip_sequence(self) -> List[Dict]:
        """获取视频片段序列"""
        if not self.timeline or 'entries' not in self.timeline:
            return []
        return self.timeline['entries']
    
    def get_total_duration(self) -> float:
        """获取总时长"""
        if not self.timeline:
            return 0.0
        return self.timeline.get('total_duration', 0.0)
    
    def build_video_segments(self, images_dir: Path) -> List[Dict]:
        """构建视频片段列表"""
        segments = []
        
        for entry in self.get_clip_sequence():
            shot_id = entry.get('shot_id', '')
            image_path = self._find_image_for_shot(shot_id, images_dir)
            audio_path = entry.get('audio_file', '')
            
            segment = {
                'shot_id': shot_id,
                'scene_id': entry.get('scene_id', ''),
                'image_path': str(image_path) if image_path else '',
                'audio_path': audio_path,
                'duration': entry.get('duration', 3.0),
                'text': entry.get('text', ''),
                'speaker': entry.get('speaker', 'narrator'),
            }
            
            segments.append(segment)
        
        return segments
    
    def _find_image_for_shot(self, shot_id: str, images_dir: Path) -> Optional[Path]:
        """根据 shot_id 查找对应的图像"""
        # 尝试多种命名方式
        possible_names = [
            f"{shot_id}.png",
            f"{shot_id}.jpg",
            f"keyframe_{shot_id}.png",
            shot_id.replace('_', '_').split('_')[0] + "_*.png",  # 尝试通配符
        ]
        
        for name in possible_names[:2]:  # 精确匹配
            path = images_dir / name
            if path.exists():
                return path
        
        # 如果没找到，返回目录中第一张图片
        png_files = list(images_dir.glob("*.png"))
        if png_files:
            return png_files[0]
        
        return None
    
    def get_subtitle_segments(self) -> List[Dict]:
        """获取字幕片段"""
        segments = []
        
        for entry in self.get_clip_sequence():
            segments.append({
                'start_time': entry.get('start_time', 0.0),
                'end_time': entry.get('end_time', 0.0),
                'text': entry.get('text', ''),
                'speaker': entry.get('speaker', ''),
            })
        
        return segments


class TimelineVideoComposer:
    """基于时间线的视频合成器"""
    
    def __init__(self, novel_title: str, config: dict = None):
        self.novel_title = novel_title
        self.config = config or {}
        self.ffmpeg_available = self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def compose_with_timeline(
        self,
        timeline_path: Path,
        images_dir: Path,
        output_path: Path,
    ) -> bool:
        """
        使用时间线合成视频
        
        Args:
            timeline_path: timeline_chXX.json 路径
            images_dir: 图像目录
            output_path: 输出视频路径
            
        Returns:
            是否成功
        """
        if not self.ffmpeg_available:
            logger.error("FFmpeg 不可用")
            return False
        
        # 加载时间线
        with open(timeline_path, 'r', encoding='utf-8') as f:
            timeline = json.load(f)
        
        entries = timeline.get('entries', [])
        
        if not entries:
            logger.error("时间线为空")
            return False
        
        # 创建临时文件列表
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            concat_file = f.name
            
            for entry in entries:
                image_path = entry.get('image_file', '')
                if not image_path or not Path(image_path).exists():
                    continue
                
                duration = entry.get('duration', 3.0)
                f.write(f"file '{image_path}'\n")
                f.write(f"duration {duration}\n")
        
        try:
            # 使用 FFmpeg concat 合成
            import subprocess
            
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "24",
                "-y",
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"视频合成完成: {output_path}")
                return True
            else:
                logger.error(f"视频合成失败: {result.stderr}")
                return False
                
        finally:
            # 清理临时文件
            os.unlink(concat_file)
    
    def add_audio_to_video(
        self,
        video_path: Path,
        audio_dir: Path,
        chapter_number: int,
        output_path: Path,
    ) -> bool:
        """为视频添加音频"""
        if not self.ffmpeg_available:
            return False
        
        # 查找时间线获取音频文件
        timeline_path = audio_dir / f"timeline_ch{chapter_number:03d}.json"
        
        if not timeline_path.exists():
            logger.warning("时间线不存在，跳过音频添加")
            return False
        
        with open(timeline_path, 'r', encoding='utf-8') as f:
            timeline = json.load(f)
        
        # 收集所有音频片段
        audio_files = []
        for entry in timeline.get('entries', []):
            audio_file = entry.get('audio_file', '')
            if audio_file and Path(audio_file).exists():
                audio_files.append(audio_file)
        
        if not audio_files:
            logger.warning("没有音频文件")
            return False
        
        # 创建临时音频列表
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            concat_file = f.name
            for af in audio_files:
                f.write(f"file '{af}'\n")
        
        try:
            import subprocess
            
            # 合并音频
            temp_audio = output_path.parent / "temp_merged_audio.mp3"
            
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:a", "libmp3lame",
                "-y",
                str(temp_audio)
            ]
            
            subprocess.run(cmd, capture_output=True)
            
            # 合并视频和音频
            cmd2 = [
                "ffmpeg",
                "-i", str(video_path),
                "-i", str(temp_audio),
                "-c:v", "copy",
                "-c:a", "libmp3lame",
                "-shortest",
                "-y",
                str(output_path)
            ]
            
            result = subprocess.run(cmd2, capture_output=True, text=True)
            
            # 清理临时文件
            temp_audio.unlink(missing_ok=True)
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"音频添加失败: {e}")
            return False
        finally:
            os.unlink(concat_file)
    
    def generate_srt_subtitle(
        self,
        timeline_path: Path,
        output_path: Path,
    ) -> bool:
        """生成 SRT 字幕"""
        if not timeline_path.exists():
            return False
        
        with open(timeline_path, 'r', encoding='utf-8') as f:
            timeline = json.load(f)
        
        srt_content = []
        for i, entry in enumerate(timeline.get('entries', []), 1):
            start_time = self._format_srt_time(entry.get('start_time', 0.0))
            end_time = self._format_srt_time(entry.get('end_time', 0.0))
            text = entry.get('text', '')
            
            srt_content.append(f"{i}\n{start_time} --> {end_time}\n{text}\n")
        
        output_path.write_text('\n'.join(srt_content), encoding='utf-8')
        return True
    
    def _format_srt_time(self, seconds: float) -> str:
        """格式化 SRT 时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def get_video_paths(novel_title: str) -> Dict[str, Path]:
    """获取视频相关路径"""
    from config.settings import OUTPUTS_DIR, NOVELS_DIR, IMAGES_DIR, AUDIO_DIR, VIDEOS_DIR
    
    novel_dir = NOVELS_DIR / novel_title.replace(' ', '_')
    
    return {
        'novel': novel_dir,
        'data': novel_dir / "data",
        'images': IMAGES_DIR / novel_title.replace(' ', '_'),
        'audio': AUDIO_DIR / novel_title.replace(' ', '_'),
        'videos': VIDEOS_DIR / novel_title.replace(' ', '_'),
        'subtitles': novel_dir / "subtitles",
    }
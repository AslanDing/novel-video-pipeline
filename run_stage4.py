#!/usr/bin/env python3
"""
独立运行第四阶段：视频合成与图生视频

用法:
    # 视频合成（静态图像 + 音频 -> 视频）
    python run_stage4.py --novel-dir "outputs/novels/绝世剑仙" --mode compose

    # 图生视频（SVD 从图像生成动态视频）
    python run_stage4.py --novel-dir "outputs/novels/绝世剑仙" --mode svd

    # 同时执行两种模式
    python run_stage4.py --novel-dir "outputs/novels/绝世剑仙" --mode all
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from stage4_merge.video_composer import VideoComposer, FinalVideo, VideoGenerator
from stage1_novel.novel_generator import Novel
from stage2_visual.image_generator import ChapterImages, GeneratedImage
from stage3_audio.tts_engine import ChapterAudio, TTSSegment
from config.settings import VIDEOS_DIR, IMAGES_DIR, AUDIO_DIR, VIDEO_GENERATION


async def ensure_svd_model(config: dict) -> bool:
    """确保 SVD 模型可用"""
    from download_models import check_model_exists

    model_type = "svd"
    cache_dir = Path(config.get("model_cache_dir", "models"))

    if check_model_exists(model_type, cache_dir):
        print(f"   ✅ SVD 模型已存在")
        return True

    print(f"   ❌ SVD 模型不存在")
    return False


async def download_svd_model_if_needed(download: bool) -> bool:
    """下载 SVD 模型（如果需要）"""
    if not download:
        return False

    try:
        from download_models import download_svd_model
        cache_dir = Path(VIDEO_GENERATION.get("model_cache_dir", "models"))
        return download_svd_model(cache_dir=cache_dir)
    except Exception as e:
        print(f"   ❌ SVD 模型下载失败: {e}")
        return False


async def run_video_compose(novel: Novel, images: Dict, audio: Dict, resolution: str):
    """运行视频合成（静态图像 + 音频 -> 视频）"""
    print("\n" + "=" * 60)
    print("📹 模式: 视频合成 (静态图像 + 音频)")
    print("=" * 60)

    input_data = {
        "novel": novel,
        "images": images,
        "audio": audio,
    }

    # 创建视频合成器
    from config.settings import VIDEO_COMPOSITION
    if resolution == "1080p":
        VIDEO_COMPOSITION["resolution"] = (1920, 1080)
    else:
        VIDEO_COMPOSITION["resolution"] = (1280, 720)

    composer = VideoComposer(VIDEO_COMPOSITION)

    try:
        videos = await composer.process(input_data)

        # 打印结果
        print("\n" + "=" * 60)
        print("✅ 视频合成完成！")
        print("=" * 60)
        print(f"\n总章节: {len(videos)}")
        total_duration = sum(v.duration for v in videos.values())
        print(f"总时长: {total_duration / 60:.2f} 分钟")
        print(f"保存位置: {VIDEOS_DIR}")

        print("\n📁 生成的视频:")
        for chapter_num, video in videos.items():
            print(f"\n   第{chapter_num}章:")
            print(f"      文件: {video.video_path}")
            print(f"      时长: {video.duration:.2f}秒")
            print(f"      分辨率: {video.resolution[0]}x{video.resolution[1]}")
            print(f"      大小: {video.file_size / 1024 / 1024:.2f} MB")
            if video.subtitle_path:
                print(f"      字幕: {video.subtitle_path}")

        print("\n✅ 视频合成完成！")
        return videos

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        raise


async def run_svd_video_generation(
    novel: Novel,
    images: Dict,
    args,
):
    """运行 SVD 图生视频"""
    print("\n" + "=" * 60)
    print("🎬 模式: SVD 图生视频")
    print("=" * 60)

    # 检查并下载模型
    model_ready = await ensure_svd_model(VIDEO_GENERATION)

    if not model_ready:
        if args.download_model:
            print("   尝试下载 SVD 模型...")
            model_ready = await download_svd_model_if_needed(True)

    if not model_ready:
        print("\n❌ SVD 模型不可用，请运行: python download_models.py download --model svd")
        return None

    # 创建 VideoGenerator 配置
    video_config = VIDEO_GENERATION.copy()
    video_config["svd"]["frames"] = args.frames
    video_config["svd"]["motion_bucket_id"] = args.motion_bucket

    # 创建视频生成器
    generator = VideoGenerator(video_config)

    if not generator.svd_model:
        print("❌ SVD 模型加载失败")
        return None

    # 生成视频
    print(f"\n   帧数: {args.frames}, 运动强度: {args.motion_bucket}")

    all_videos = await generator.process_novel(novel, images)

    # 打印结果
    print("\n" + "=" * 60)
    print("✅ SVD 图生视频完成！")
    print("=" * 60)

    total_videos = sum(len(v) for v in all_videos.values())
    print(f"\n总视频数: {total_videos}")
    print(f"保存位置: {VIDEOS_DIR}")

    for chapter_num, videos in all_videos.items():
        print(f"\n   第{chapter_num}章:")
        for video_path in videos:
            print(f"      - {video_path}")

    return all_videos


def load_novel_and_data(novel_dir: Path, resolution: str):
    """加载小说、图像和音频数据"""
    # 检查 FFmpeg（视频合成需要）
    import subprocess
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        ffmpeg_available = result.returncode == 0
    except:
        ffmpeg_available = False

    # 加载小说
    print("📖 加载小说数据...")
    complete_json = novel_dir / f"{novel_dir.name}_complete.json"
    if not complete_json.exists():
        json_files = list(novel_dir.glob("*.json"))
        if json_files:
            complete_json = json_files[0]
        else:
            print(f"❌ 错误: 找不到小说JSON文件")
            return None, None, None, ffmpeg_available

    with open(complete_json, 'r', encoding='utf-8') as f:
        novel_data = json.load(f)

    novel_title = novel_data['metadata']['title']
    print(f"   标题: 《{novel_title}》")

    # 构建简化Novel对象
    from stage1_novel.novel_generator import Novel, StoryBlueprint, Chapter

    chapters = []
    chapters_dir = novel_dir / "chapters"
    for i in range(1, len(novel_data['chapters']) + 1):
        chapter_file = chapters_dir / f"chapter_{i:03d}.json"
        if chapter_file.exists():
            with open(chapter_file, 'r', encoding='utf-8') as f:
                chapter_data = json.load(f)
            chapters.append(Chapter(
                number=chapter_data['number'],
                title=chapter_data['title'],
                content=chapter_data['content'],
                word_count=chapter_data['word_count'],
                summary=chapter_data.get('summary', ''),
                key_events=chapter_data.get('key_events', []),
                character_appearances=chapter_data.get('character_appearances', []),
            ))

    novel = Novel(
        metadata=novel_data['metadata'],
        blueprint=StoryBlueprint(
            title=novel_data['blueprint']['title'],
            genre=novel_data['blueprint']['genre'],
            world_building=None,
            characters=[],
            plot_structure=[],
            chapter_plans=novel_data['blueprint'].get('chapter_plans', []),
        ),
        chapters=chapters,
    )

    # 加载图像
    print("\n🎨 加载图像数据...")
    images = {}
    images_dir = IMAGES_DIR

    for chapter in novel.chapters:
        chapter_img_dir = images_dir / f"chapter_{chapter.number:03d}"
        if chapter_img_dir.exists():
            image_files = list(chapter_img_dir.glob("*.png")) + list(chapter_img_dir.glob("*.jpg"))
            if image_files:
                images_list = []
                for i, img_file in enumerate(image_files):
                    try:
                        from PIL import Image
                        with Image.open(img_file) as img:
                            w, h = img.size
                    except:
                        w, h = 1024, 1024
                    
                    images_list.append(GeneratedImage(
                        image_id=f"ch{chapter.number}_img{i}",
                        chapter_number=chapter.number,
                        scene_description="",
                        prompt="",
                        file_path=str(img_file),
                        width=w,
                        height=h,
                        seed=42,
                        generation_time=0.0,
                    ))

                chapter_images = ChapterImages(
                    chapter_number=chapter.number,
                    images=images_list,
                )
                images[chapter.number] = chapter_images
                print(f"   第{chapter.number}章: {len(chapter_images.images)} 张图像")

    if not images:
        print("   ⚠️  未找到图像数据，请先运行第二阶段")

    # 加载音频
    print("\n🔊 加载音频数据...")
    audio = {}
    audio_dir = AUDIO_DIR

    for chapter in novel.chapters:
        chapter_audio_dir = audio_dir / f"chapter_{chapter.number:03d}"
        if chapter_audio_dir.exists():
            combined_file = chapter_audio_dir / "combined.mp3"
            segments = sorted(list(chapter_audio_dir.glob("segment_*.mp3")))

            if segments or combined_file.exists():
                chapter_audio = ChapterAudio(
                    chapter_number=chapter.number,
                    segments=[
                        TTSSegment(
                            segment_id=f"ch{chapter.number}_seg{i}",
                            chapter_number=chapter.number,
                            text="",
                            speaker="narrator",
                            emotion="neutral",
                            speed=1.0,
                            file_path=str(seg_file),
                            duration=10.0,
                        )
                        for i, seg_file in enumerate(segments)
                    ],
                    combined_file=str(combined_file) if combined_file.exists() else None,
                    total_duration=len(segments) * 10.0,
                )
                audio[chapter.number] = chapter_audio
                status = " (已合并)" if combined_file.exists() else ""
                print(f"   第{chapter.number}章: {len(segments)} 个音频片段{status}")

    if not audio:
        print("   ⚠️  未找到音频数据，请先运行第三阶段")

    return novel, images, audio, ffmpeg_available


async def main():
    parser = argparse.ArgumentParser(description="视频合成与图生视频")
    parser.add_argument("--novel-dir", "-d", required=False, default="outputs/novels/逍遥蜉蝣",
                        help="小说输出目录路径")
    parser.add_argument("--resolution", choices=["720p", "1080p"], default="720p",
                        help="视频分辨率")
    parser.add_argument("--mode", "-m", choices=["compose", "svd", "all"], default="all",
                        help="模式: compose=视频合成(图像+音频), svd=图生视频(SVD), all=全部执行")
    parser.add_argument("--download-model", action="store_true",
                        help="自动下载缺失的SVD模型")
    parser.add_argument("--frames", type=int, default=24,
                        help="SVD生成的帧数 (14-24)")
    parser.add_argument("--motion-bucket", type=int, default=127,
                        help="SVD运动强度 (0-255)")

    args = parser.parse_args()

    novel_dir = Path(args.novel_dir)
    if not novel_dir.exists():
        print(f"❌ 错误: 目录不存在: {novel_dir}")
        return

    print("=" * 60)
    print("🎬 第四阶段：视频生成")
    print("=" * 60)
    print(f"\n小说目录: {novel_dir}")
    print(f"模式: {args.mode}")
    print(f"分辨率: {args.resolution}")

    # 加载数据
    novel, images, audio, ffmpeg_available = load_novel_and_data(novel_dir, args.resolution)

    if novel is None:
        return

    # 根据模式执行
    if args.mode in ["compose", "all"]:
        if not ffmpeg_available:
            print("\n❌ FFmpeg未安装，无法进行视频合成")
            print("   请先安装FFmpeg:")
            print("   Ubuntu/Debian: sudo apt-get install ffmpeg")
            print("   macOS: brew install ffmpeg")
            print("   Windows: https://ffmpeg.org/download.html")
        elif not images:
            print("\n❌ 没有图像数据，无法进行视频合成")
        elif not audio:
            print("\n❌ 没有音频数据，无法进行视频合成")
        else:
            await run_video_compose(novel, images, audio, args.resolution)

    if args.mode in ["svd", "all"]:
        if not images:
            print("\n❌ 没有图像数据，无法进行图生视频")
        else:
            await run_svd_video_generation(novel, images, args)

    print("\n" + "=" * 60)
    print("🎉 第四阶段完成！")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n\n💥 程序异常: {e}")
        sys.exit(1)
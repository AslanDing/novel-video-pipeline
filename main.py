#!/usr/bin/env python3
"""
AI爽文小说创作平台 - 主入口

完整的四阶段流水线：
1. 小说生成 (Stage 1) - Novel Generation
2. 图像生成 (Stage 2) - Image Generation  
3. 音频生成 (Stage 3) - Audio Generation
4. 视频合成 (Stage 4) - Video Composition

使用方法:
    python main.py --novel "绝世剑仙" --genre 修仙 --chapters 3
    python main.py --config config.json
    python main.py --stage 1  # 只运行第一阶段
"""

import os
import sys
import json
import argparse
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# 确保可以导入项目模块
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    get_config, NVIDIA_NIM_CONFIG, DEFAULT_NOVEL_CONFIG,
    NOVELS_DIR, IMAGES_DIR, AUDIO_DIR, VIDEOS_DIR
)
from core.llm_client import NVIDIA_NIM_Client, get_llm_client
from core.base_pipeline import Pipeline

# 导入四个阶段
from stage1_novel import (
    NovelGenerator, NovelConcept, NovelGenerationPipeline, Novel
)
from stage2_visual.image_generator import (
    ImageGenerator, ImageGenerationPipeline
)
from stage3_audio.tts_engine import (
    TTSEngine, TTSEngine  # 修正：应该是 TTSEngine
)
from stage4_merge.video_composer import (
    VideoComposer, VideoComposer  # 修正：应该是 VideoComposer
)


# 全局变量用于存储中间结果（支持断点续传）
_pipeline_state: Dict[str, Any] = {
    "novel": None,
    "images": None,
    "audio": None,
    "videos": None,
}


def print_banner():
    """打印启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║    🎬 AI爽文小说创作平台 📝                                       ║
║                                                                  ║
║    从创意到视频，一键生成你的专属爽文！                            ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="AI爽文小说创作平台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置生成3章修仙小说
  python main.py --novel "绝世剑仙" --genre 修仙
  
  # 生成10章玄幻爽文
  python main.py --novel "至尊魔神" --genre 玄幻 --chapters 10
  
  # 只运行第一阶段（生成小说文本）
  python main.py --novel "测试小说" --stage 1
  
  # 从配置文件加载
  python main.py --config my_config.json
  
  # 使用Mock LLM（测试用）
  python main.py --novel "测试" --mock
        """
    )
    
    # 基本参数
    parser.add_argument(
        "--novel", "-n",
        type=str,
        help="小说标题"
    )
    parser.add_argument(
        "--genre", "-g",
        type=str,
        default="修仙",
        choices=["修仙", "玄幻", "都市", "科幻", "历史", "武侠"],
        help="小说类型（默认: 修仙）"
    )
    parser.add_argument(
        "--chapters", "-c",
        type=int,
        default=3,
        help="章节数量（默认: 3）"
    )
    parser.add_argument(
        "--words",
        type=int,
        default=5000,
        help="每章字数（默认: 5000）"
    )
    parser.add_argument(
        "--core-idea",
        type=str,
        default="",
        help="核心创意/一句话梗概"
    )
    
    # 执行控制
    parser.add_argument(
        "--stage", "-s",
        type=int,
        choices=[1, 2, 3, 4],
        help="只运行指定阶段 (1=小说, 2=图像, 3=音频, 4=视频)"
    )
    parser.add_argument(
        "--from-stage",
        type=int,
        choices=[1, 2, 3, 4],
        help="从指定阶段开始运行（会尝试加载之前的阶段结果）"
    )
    parser.add_argument(
        "--video-mode",
        choices=["compose", "svd", "all"],
        default="all",
        help="视频生成模式: compose=图像+音频合成, svd=SVD图生视频, all=全部执行"
    )
    parser.add_argument(
        "--images-per-chapter", "-i",
        type=int,
        default=3,
        help="每章生成的图像数量"
    )
    parser.add_argument(
        "--download-models",
        action="store_true",
        help="自动下载缺失的模型"
    )
    
    # 配置相关
    parser.add_argument(
        "--config",
        type=str,
        help="加载JSON配置文件"
    )
    parser.add_argument(
        "--save-config",
        type=str,
        help="将当前参数保存为JSON配置文件"
    )
    
    # 调试选项
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用Mock LLM（用于测试，不消耗API额度）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干运行（不实际执行，只显示计划）"
    )
    
    return parser.parse_args()


def load_config_file(config_path: str) -> Dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config_file(config_path: str, args):
    """保存配置文件"""
    config = {
        "novel": {
            "title": args.novel,
            "genre": args.genre,
            "chapters": args.chapters,
            "words_per_chapter": args.words,
            "core_idea": args.core_idea,
        },
        "generation": {
            "stages": [1, 2, 3, 4],
        },
        "created_at": datetime.now().isoformat(),
    }
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 配置已保存: {config_path}")


async def run_stage_1_novel(args, llm_client) -> Novel:
    """运行第一阶段：小说生成"""
    print("\n" + "="*70)
    print("📝 第一阶段：小说生成")
    print("="*70 + "\n")
    
    # 创建小说概念
    concept = NovelConcept(
        title=args.novel,
        genre=args.genre,
        style="爽文",
        core_idea=args.core_idea or f"{args.novel}是一部精彩的{args.genre}爽文小说",
        total_chapters=args.chapters,
        target_word_count=args.words,
        shuangdian_intensity="high",
    )
    
    # 创建生成器
    generator = NovelGenerator(llm_client)
    
    # 生成小说
    novel = await generator.process(concept)
    
    # 保存到全局状态
    _pipeline_state["novel"] = novel
    
    return novel


async def run_stage_2_images(args, novel: Novel) -> Dict:
    """运行第二阶段：图像生成"""
    print("\n" + "="*70)
    print("🎨 第二阶段：图像生成")
    print("="*70 + "\n")
    
    # 创建图像生成器
    generator = ImageGenerator()
    
    # 生成图像
    images = await generator.process(novel)
    
    # 保存到全局状态
    _pipeline_state["images"] = images
    
    return images


async def run_stage_3_audio(args, novel: Novel) -> Dict:
    """运行第三阶段：音频生成"""
    print("\n" + "="*70)
    print("🔊 第三阶段：音频生成")
    print("="*70 + "\n")
    
    # 创建TTS引擎
    engine = TTSEngine()
    
    # 生成音频
    audio = await engine.process(novel)
    
    # 保存到全局状态
    _pipeline_state["audio"] = audio
    
    return audio


async def run_stage_4_video(args, novel: Novel, images: Dict, audio: Dict) -> Dict:
    """运行第四阶段：视频合成或SVD图生视频"""
    print("\n" + "="*70)
    print("🎬 第四阶段：视频生成")
    print("="*70 + "\n")

    video_mode = getattr(args, 'video_mode', 'all')
    print(f"   视频模式: {video_mode}")

    videos = {}
    composed_videos = None
    svd_videos = None

    # 模式1: 视频合成（静态图像 + 音频）
    if video_mode in ["compose", "all"]:
        print("\n   📹 执行视频合成...")
        from config.settings import VIDEO_COMPOSITION

        composer = VideoComposer(VIDEO_COMPOSITION)
        input_data = {
            "novel": novel,
            "images": images,
            "audio": audio,
        }

        try:
            composed_videos = await composer.process(input_data)
            videos.update(composed_videos)
            print(f"   ✅ 视频合成完成: {len(composed_videos)} 个视频")
        except Exception as e:
            print(f"   ⚠️  视频合成失败: {e}")

    # 模式2: SVD 图生视频
    if video_mode in ["svd", "all"]:
        print("\n   🎬 执行 SVD 图生视频...")

        # 检查模型
        from download_models import check_model_exists
        from config.settings import IMAGE_GENERATION
        cache_dir = Path(IMAGE_GENERATION.get("local", {}).get("model_cache_dir", "models"))

        if not check_model_exists("svd", cache_dir):
            print(f"   ⚠️  SVD 模型未下载，跳过图生视频")
            print(f"      运行: python download_models.py download --model svd")
        else:
            try:
                from stage2_visual.image_generator import ImageGenerator
                from config.settings import IMAGE_GENERATION as IMG_CONFIG

                # 配置 SVD
                svd_config = IMG_CONFIG.copy()
                svd_config["local"]["enabled"] = True
                svd_config["local"]["model_type"] = "sdxl_svd"
                svd_config["svd"] = {
                    "model_path": "stabilityai/stable-video-diffusion",
                    "frames": 24,
                    "motion_bucket_id": 127,
                    "fps": 24,
                }

                generator = ImageGenerator(svd_config)

                if generator.svd_model:
                    for chapter in novel.chapters:
                        chapter_images = images.get(chapter.number)
                        if not chapter_images:
                            continue

                        print(f"      处理第{chapter.number}章...")

                        for i, image in enumerate(chapter_images.images):
                            video_path = await generator._generate_video_from_image(
                                image_path=Path(image.file_path),
                                chapter_number=chapter.number,
                                video_index=i,
                            )

                            if chapter.number not in svd_videos:
                                svd_videos = {}
                            if chapter.number not in svd_videos:
                                svd_videos[chapter.number] = []
                            svd_videos[chapter.number].append(str(video_path))

                    if svd_videos:
                        print(f"   ✅ SVD 图生视频完成: {sum(len(v) for v in svd_videos.values())} 个视频")
                else:
                    print(f"   ⚠️  SVD 模型加载失败")

            except Exception as e:
                print(f"   ⚠️  SVD 图生视频失败: {e}")

    # 保存到全局状态
    _pipeline_state["videos"] = videos

    return videos


async def main():
    """主函数"""
    # 打印横幅
    print_banner()
    
    # 解析参数
    args = parse_arguments()
    
    # 如果指定了配置文件，加载它
    if args.config:
        print(f"📂 加载配置文件: {args.config}")
        config = load_config_file(args.config)
        # 合并配置到args
        if "novel" in config:
            novel_config = config["novel"]
            args.novel = novel_config.get("title", args.novel)
            args.genre = novel_config.get("genre", args.genre)
            args.chapters = novel_config.get("chapters", args.chapters)
            args.words = novel_config.get("words_per_chapter", args.words)
            args.core_idea = novel_config.get("core_idea", args.core_idea)
    
    # 如果指定了保存配置，保存当前参数
    if args.save_config:
        save_config_file(args.save_config, args)
        return
    
    # 验证必要参数
    if not args.novel:
        print("❌ 错误: 必须指定小说标题 (--novel)")
        print("   使用 --help 查看帮助")
        return
    
    # 干运行模式
    if args.dry_run:
        print("\n🔍 干运行模式（不实际执行）\n")
        print(f"计划生成的小说:")
        print(f"  标题: {args.novel}")
        print(f"  类型: {args.genre}")
        print(f"  章节数: {args.chapters}")
        print(f"  每章字数: {args.words}")
        
        if args.stage:
            print(f"\n只运行阶段: {args.stage}")
        elif args.from_stage:
            print(f"\n从阶段 {args.from_stage} 开始运行")
        else:
            print(f"\n运行完整流程（4个阶段）")
        
        return
    
    # 初始化LLM客户端
    print("\n🤖 初始化LLM客户端...")
    llm_client = await get_llm_client(use_mock=args.mock)
    
    if args.mock:
        print("   ⚠️  使用Mock LLM（仅用于测试）")
    elif not NVIDIA_NIM_CONFIG.get("api_key"):
        print("   ⚠️  NVIDIA NIM API Key未设置，使用Mock模式")
        print("   如需使用真实API，请设置环境变量: export NVIDIA_NIM_API_KEY=your_key")
    else:
        print(f"   ✅ 使用模型: {NVIDIA_NIM_CONFIG['model']}")
    
    # 确定要运行的阶段
    stages_to_run = []
    
    if args.stage:
        # 只运行指定阶段
        stages_to_run = [args.stage]
    elif args.from_stage:
        # 从指定阶段开始
        stages_to_run = list(range(args.from_stage, 5))
    else:
        # 运行所有阶段
        stages_to_run = [1, 2, 3, 4]
    
    print(f"\n📋 执行计划: 阶段 {stages_to_run}")
    
    # 执行各阶段
    novel = None
    images = None
    audio = None
    videos = None
    
    try:
        # ===== 阶段 1: 小说生成 =====
        if 1 in stages_to_run:
            novel = await run_stage_1_novel(args, llm_client)
        
        # ===== 阶段 2: 图像生成 =====
        if 2 in stages_to_run:
            # 如果阶段1没有运行，尝试加载之前的小说
            if novel is None:
                print("\n⚠️  需要阶段1的小说数据，请先运行阶段1或提供已有小说")
                return
            
            images = await run_stage_2_images(args, novel)
        
        # ===== 阶段 3: 音频生成 =====
        if 3 in stages_to_run:
            if novel is None:
                print("\n⚠️  需要阶段1的小说数据")
                return
            
            audio = await run_stage_3_audio(args, novel)
        
        # ===== 阶段 4: 视频合成 =====
        if 4 in stages_to_run:
            if novel is None or images is None or audio is None:
                print("\n⚠️  需要阶段1-3的数据，请先运行前面的阶段")
                return
            
            videos = await run_stage_4_video(args, novel, images, audio)
        
        # ===== 完成总结 =====
        print("\n" + "="*70)
        print("🎉 所有阶段执行完成！")
        print("="*70 + "\n")
        
        if novel:
            print(f"📖 小说: 《{novel.metadata['title']}》")
            print(f"   总章节: {len(novel.chapters)}")
            print(f"   总字数: {novel.metadata.get('total_word_count', 0):,}")
            print(f"   保存位置: {NOVELS_DIR / novel.metadata['title'].replace(' ', '_')}")
        
        if videos:
            print(f"\n🎬 视频:")
            total_duration = sum(v.duration for v in videos.values())
            print(f"   总章节: {len(videos)}")
            print(f"   总时长: {total_duration/60:.2f} 分钟")
            print(f"   保存位置: {VIDEOS_DIR}")
        
        print("\n✨ 创作完成！")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断执行")
        print("   已完成的阶段结果被保留")
    except Exception as e:
        print(f"\n\n❌ 执行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # 关闭LLM客户端
        if llm_client:
            await llm_client.close()


if __name__ == "__main__":
    # 运行主函数
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n💥 程序异常退出: {e}")
        sys.exit(1)

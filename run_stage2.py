#!/usr/bin/env python3
"""
独立运行第二阶段：图像生成

用法:
    python run_stage2.py --novel-dir "outputs/novels/绝世剑仙"
    python run_stage2.py --novel-dir "outputs/novels/绝世剑仙" --download-model
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stages.stage2_visual.image_generator import ImageGenerator, ChapterImages
from stages.stage1_novel.novel_generator import Novel

from config.settings import IMAGES_DIR,IMAGE_MODELS_DIR
from core.logger import get_logger, setup_logger

# 初始化日志
setup_logger(level=20)  # INFO级别
logger = get_logger("run_stage2")


async def ensure_sd_model(config: dict) -> bool:
    """
    确保SD模型可用

    Args:
        config: 图像生成配置

    Returns:
        模型是否可用
    """
    from download_models import check_model_exists, MODEL_CONFIGS

    model_path = config.get("local", {}).get("model_path", "")
    model_type = config.get("local", {}).get("model_type", "sdxl")
    cache_dir = Path(config.get("local", {}).get("model_cache_dir", "models"))

    # 检查是否已有模型
    if check_model_exists(model_type, cache_dir):
        logger.info(f"模型已存在: {model_type}")
        return True

    logger.warning(f"模型不存在: {model_type}")
    return False


async def main():
    parser = argparse.ArgumentParser(description="生成小说配图")
    parser.add_argument("--novel-dir", "-d", required=False, default="outputs/novels/现代都市修仙秘闻",
                        help="小说输出目录路径")
    parser.add_argument("--use-local-sd", action="store_true", default=True,
                        help="使用本地Stable Diffusion模型")
    parser.add_argument("--model", "-m", choices=["sdxl", "sdxl-refiner", "z-image-turbo", "sd3.5-medium"],
                        default="z-image-turbo",
                        help="选择图像生成模型: sd3.5-medium(新版), sdxl(SDXL基础), z-image-turbo(通义万相)")
    parser.add_argument("--translate/--no-translate", dest="translate", default=False,
                        help="是否将prompt翻译为英文 (默认开启,使用英文模型建议开启)")
    
    # LLM 客户端参数 (用于预处理)
    parser.add_argument("--local-llm", default=False, action="store_true", help="使用本地LLM (Ollama/vLLM) 进行预处理")
    parser.add_argument("--provider", default="vllm", choices=["ollama", "vllm"], help="本地LLM提供商")
    parser.add_argument("--url", default="http://localhost:8080/v1", help="本地LLM API地址")
    parser.add_argument("--llm-model", default="Qwen/Qwen3-14B-AWQ", help="本地LLM模型名称")
    
    parser.add_argument("--download-model", action="store_true",
                        help="自动下载缺失的模型")
    parser.add_argument("--list-models", action="store_true",
                        help="列出所有可用模型状态")
    parser.add_argument("--preprocess-only", action="store_true",
                        help="仅预处理生成 prompt 缓存，不生成图像")
    parser.add_argument("--skip-preprocess", action="store_true",
                        help="跳过预处理，直接从缓存加载 prompt（若无缓存则报错）")
    parser.add_argument("--clear-cache", action="store_true",
                        help="清除缓存后退出")
    parser.add_argument("--force-refresh", action="store_true",
                        help="强制刷新缓存，重新生成所有 prompt")

    args = parser.parse_args()

    # 如果只是列出模型状态
    if args.list_models:
        from download_models import list_models
        list_models(IMAGE_MODELS_DIR)
        return

    novel_dir = Path(args.novel_dir)
    if not novel_dir.exists():
        logger.error(f"目录不存在: {novel_dir}")
        return

    logger.info("=" * 60)
    logger.info("图像生成器")
    logger.info("=" * 60)
    logger.info(f"小说目录: {novel_dir}")
    logger.info(f"使用本地SD: {args.use_local_sd}")
    logger.info(f"模型类型: {args.model}")

    # 加载小说数据
    novel_data = None
    
    # 尝试多种布局
    possible_paths = [
        novel_dir / "data" / "story_bible.json",
        novel_dir / f"{novel_dir.name}_complete.json",
        novel_dir / "story_bible.json",
    ]
    
    for path in possible_paths:
        if path.exists():
            logger.info(f"正在从 {path} 加载小说设定...")
            with open(path, 'r', encoding='utf-8') as f:
                novel_data = json.load(f)
            break
            
    if not novel_data:
        # 如果还没找到，尝试搜索任何 JSON
        json_files = list(novel_dir.glob("**/*.json"))
        if not json_files:
            logger.error(f"在 {novel_dir} 中找不到小说数据文件")
            return
        
        path = json_files[0]
        logger.info(f"尝试加载找到的第一个 JSON 文件: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            novel_data = json.load(f)

    # 兼容性处理: 确保有 metadata 和 blueprint
    if 'blueprint' not in novel_data and 'title' in novel_data:
        # 可能是旧版或直接存的 blueprint
        blueprint_data = novel_data
        metadata = {
            "title": novel_data.get('title', 'Unknown'),
            "genre": novel_data.get('genre', 'Unknown'),
            "total_chapters": len(novel_data.get('chapter_plans', []))
        }
    else:
        blueprint_data = novel_data.get('blueprint', {})
        metadata = novel_data.get('metadata', {})

    # 构建Novel对象
    from stages.stage1_novel.novel_generator import Novel, StoryBlueprint, WorldBuilding, Character, Chapter, PlotPoint

    # 1. 重建WorldBuilding
    wb_data = blueprint_data.get('world_building', {})
    world_building = WorldBuilding(
        setting=wb_data.get('setting', ''),
        power_system=wb_data.get('power_system', ''),
        factions=wb_data.get('factions', []),
        rules=wb_data.get('rules', [])
    )

    # 2. 重建Characters
    characters = []
    for char_data in blueprint_data.get('characters', []):
        characters.append(Character(**char_data))

    # 3. 重建PlotStructure
    plot_structure = []
    for p in blueprint_data.get('plot_structure', []):
        # 确保包含新字段 (如果有)
        plot_structure.append(PlotPoint(
            chapter=p.get('chapter'),
            description=p.get('description'),
            shuangdian_type=p.get('shuangdian_type'),
            intensity=p.get('intensity', 'medium')
        ))

    # 4. 构建Blueprint
    blueprint = StoryBlueprint(
        title=blueprint_data.get('title', metadata.get('title', '')),
        genre=blueprint_data.get('genre', metadata.get('genre', '')),
        world_building=world_building,
        characters=characters,
        plot_structure=plot_structure,
        chapter_plans=blueprint_data.get('chapter_plans', [])
    )

    # 5. 重建Chapters - 优先从 JSON 加载，如果没有则从 data/chapters 目录加载
    chapters = []
    chapters_raw = novel_data.get('chapters', [])
    
    if chapters_raw:
        for ch_data in chapters_raw:
            # 兼容处理 script_lines (如果存在)
            if 'script_lines' in ch_data and ch_data['script_lines']:
                from stages.stage1_novel.models import ScriptLine
                script_lines = [ScriptLine(**sl) if isinstance(sl, dict) else sl for sl in ch_data['script_lines']]
                ch_data['script_lines'] = script_lines
            chapters.append(Chapter(**ch_data))
    else:
        # 尝试从 data/chapters 加载
        chapters_dir = novel_dir / "data" / "chapters"
        if chapters_dir.exists():
            logger.info(f"正在从 {chapters_dir} 重建章节列表...")
            summary_files = sorted(list(chapters_dir.glob("*_summary.json")))
            for summary_path in summary_files:
                with open(summary_path, 'r', encoding='utf-8') as f:
                    summary_data = json.load(f)
                
                # 读取对应的 MD 内容
                ch_num = summary_data.get('number')
                md_path = chapters_dir / f"chapter_{ch_num:03d}.md"
                content = ""
                if md_path.exists():
                    with open(md_path, 'r', encoding='utf-8') as f:
                        # 略过标题行
                        lines = f.readlines()
                        content = "".join(lines[2:]) if len(lines) > 2 else "".join(lines)
                
                chapters.append(Chapter(
                    number=ch_num,
                    title=summary_data.get('title', ''),
                    content=content,
                    word_count=summary_data.get('word_count', 0),
                    summary=summary_data.get('summary', ''),
                    key_events=summary_data.get('key_events', []),
                    character_appearances=summary_data.get('character_appearances', []),
                    script_lines=[] # ScriptLine 在 stage 2 中通过 adapter 读取
                ))
        
    if not chapters:
        logger.warning("未找到任何章节数据，将仅能处理设定相关内容")

    # 6. 最终Novel对象
    novel = Novel(
        metadata=metadata,
        blueprint=blueprint,
        chapters=chapters
    )

    # 创建图像生成器配置
    from config.settings import IMAGE_GENERATION
    config = IMAGE_GENERATION.copy()
    # config['images_per_chapter'] = args.images_per_chapter # 移除固定数量限制，由脚本场景决定
    config['local']['enabled'] = args.use_local_sd

    # 添加 novel_dir 到配置（用于缓存）
    config['novel_dir'] = str(novel_dir)

    # 处理缓存清除
    if args.clear_cache:
        logger.info("清除缓存...")
        from stages.stage2_visual.preprocessor import ScenePreprocessor
        from config.settings import IMAGE_GENERATION
        preprocessor = ScenePreprocessor(IMAGE_GENERATION.copy(), novel)
        preprocessor.clear_cache()
        logger.info("缓存已清除")
        return


    # 设置选定的模型类型
    if args.model == "sdxl":
        config['local']['model_type'] = "sdxl"
        config['local']['model_path'] = "stabilityai/stable-diffusion-xl-base-1.0"
        config['local']['steps'] = 25
        config['local']['cfg_scale'] = 15
    elif args.model == "sdxl-refiner":
        config['local']['model_type'] = "sdxl-refiner"
        config['local']['model_path'] = "stabilityai/stable-diffusion-xl-refiner-1.0"
        config['local']['steps'] = 25
        config['local']['cfg_scale'] = 15
    elif args.model == "z-image-turbo":
        config['local']['model_type'] = "z-image-turbo"
        config['local']['model_path'] = "Tongyi-MAI/Z-Image-Turbo"
        config['local']['steps'] = 25
        config['local']['cfg_scale'] = 15  # Turbo模型需要 guidance_scale=0
    elif args.model == "sd3.5-medium":
        config['local']['model_type'] = "sd3.5-medium"
        config['local']['model_path'] = "stabilityai/stable-diffusion-3.5-medium"
        config['local']['steps'] = 25
        config['local']['cfg_scale'] = 15

    # 设置翻译选项
    if args.translate is not None:
        config['translate_to_english'] = args.translate
        logger.info(f"翻译模式: {'开启' if args.translate else '关闭'}")
    else:
        # 默认根据模型类型设置
        if args.model == "z-image-turbo":
            config['translate_to_english'] = False  # 通义万相支持中文
        else:
            config['translate_to_english'] = True  # SDXL需要英文

    # 模型检查和下载
    if args.use_local_sd:
        logger.info("检查模型状态...")

        model_ready = await ensure_sd_model(config)

        if not model_ready and args.download_model:
            logger.info("开始下载模型...")
            try:
                from download_models import download_sdxl_model
                model_type = config.get("local", {}).get("model_type", "sdxl")
                cache_dir = Path(config.get("local", {}).get("model_cache_dir", "models"))
                success = download_sdxl_model(
                    model_type=model_type,
                    cache_dir=cache_dir
                )
                if not success:
                    logger.warning("模型下载失败，将使用占位图模式")
                    config['local']['enabled'] = False
            except Exception as e:
                logger.error(f"模型下载出错: {e}", exc_info=True)
                logger.warning("将使用占位图模式")
                config['local']['enabled'] = False
        elif not model_ready:
            logger.info(f"使用 --download-model 选项自动下载模型")
            logger.info(f"或运行: python download_models.py download --model {args.model}")

    # 优雅降级：测试模型是否可用
    if config['local']['enabled']:
        logger.info("测试模型可用性...")
        try:
            generator = ImageGenerator(config)
            if not generator.local_model:
                logger.warning("本地模型不可用，自动降级为占位图模式")
                config['local']['enabled'] = False
        except Exception as e:
            logger.error(f"模型初始化失败: {e}", exc_info=True)
            logger.warning("自动降级为占位图模式")
            config['local']['enabled'] = False
            generator = ImageGenerator(config)
    else:
        logger.info("使用云端API模式")
        # 创建最终的生成器
        generator = ImageGenerator(config)

    # 初始化 LLM 客户端（用于预处理）
    llm_client = None
    if args.local_llm:
        from core.local_llm_client import get_local_llm_client
        logger.info(f"使用本地 LLM ({args.provider}) 进行预处理")
        llm_client = get_local_llm_client(
            provider=args.provider,
            base_url=args.url,
            model=args.llm_model
        )
    else:
        from core.llm_client import NVIDIA_NIM_Client
        logger.info("使用 NVIDIA NIM LLM 进行预处理")
        llm_client = NVIDIA_NIM_Client()

    # 预处理（生成 prompt 缓存）
    from stages.stage2_visual.preprocessor import ScenePreprocessor, preprocess_novel

    # 检查是否需要预处理
    preprocessor = ScenePreprocessor(config, novel, llm_client=llm_client)

    if args.preprocess_only:
        # 仅预处理模式
        logger.info("=" * 60)
        logger.info("预处理模式：仅生成 prompt 缓存")
        logger.info("=" * 60)
        stats = await preprocess_novel(novel, config, force_refresh=args.force_refresh, llm_client=llm_client)
        logger.info(f"预处理完成: {stats}")
        logger.info(f"缓存位置: {preprocessor.cache_dir}")
        return

    if not args.skip_preprocess:
        # 正常模式：先预处理再生成图像
        logger.info("=" * 60)
        logger.info("预处理：生成 prompt 缓存...")
        logger.info("=" * 60)
        await preprocess_novel(novel, config, force_refresh=args.force_refresh, llm_client=llm_client)
    else:
        # 跳过预处理模式：直接使用缓存
        logger.info("跳过预处理，从缓存加载...")

    # 生成图像
    logger.info("开始生成图像...")
    try:
        # 传入 preprocessor 以便从缓存加载
        results = await generator.process(novel, preprocessor=preprocessor)

        # 统计结果
        total_images = sum(len(ci.images) for ci in results.values())

        logger.info("=" * 60)
        logger.info("图像生成完成！")
        logger.info("=" * 60)
        save_path = Path(args.novel_dir) / "images" if args.novel_dir else IMAGES_DIR
        logger.info(f"总图像数: {total_images}, 保存位置: {save_path}")

        logger.info("生成的图像:")
        for chapter_num, chapter_images in results.items():
            logger.info(f"第{chapter_num}章: {len(chapter_images.images)} 张")
            for img in chapter_images.images:
                logger.info(f"  - {img.file_path}")

        logger.info("完成！")

    except Exception as e:
        logger.error(f"错误: {e}", exc_info=True)
        logger.info("完成！")

    # 关闭LLM客户端
    if llm_client:
        await llm_client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("用户中断")
    except Exception as e:
        logger.error(f"程序异常: {e}", exc_info=True)
        sys.exit(1)

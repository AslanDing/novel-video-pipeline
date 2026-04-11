#!/usr/bin/env python3
"""
独立运行第一阶段：小说生成

用法:
    python run_stage1.py --novel "绝世剑仙" --genre 修仙 --chapters 3
"""

import asyncio
import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.llm_client import get_llm_client
from stages.stage1_novel.novel_generator import (
    NovelGenerator, NovelConcept, Novel
)
# 导入流式生成器（可选）
try:
    from stages.stage1_novel.streaming_novel_generator import create_novel_generator
    STREAMING_AVAILABLE = True
except ImportError:
    STREAMING_AVAILABLE = False


async def main():
    parser = argparse.ArgumentParser(description="生成爽文小说")
    parser.add_argument("--novel", "-n", required=False, default="现代都市修仙秘闻", help="小说标题")
    parser.add_argument("--genre", "-g", default="修仙", help="类型")
    parser.add_argument("--chapters", "-c", type=int, default=3, help="章节数")
    parser.add_argument("--words", "-w", type=int, default=5000, help="每章字数")
    parser.add_argument("--core-idea", default="林凡是现代都市社会的牛马程序员，由于AI时代的到来即将失业，某一天他在使用电脑时被AI生成的一串代码激活了脑部神秘部位，"
    "导致他大脑中出现了人类上古记忆，记忆中人是可以通过一些特殊的方法进行修炼，最终达到长生不老的目的。但是这一过程非常的艰难，需要经历无数岁月才能成功。由于现代社会有了AI，"
    "使得原来无数的修炼资源变得踱手可得。在AI的帮助下，林凡一步步不断变强，在现代社会中靠着修仙秘术不断创造奇迹，最终寿命高达200年", help="核心创意")
    
    # LLM 客户端参数
    parser.add_argument("--local-llm", default=False, action="store_true", help="使用本地LLM (Ollama/vLLM)")
    parser.add_argument("--provider", default="vllm", choices=["ollama", "vllm"], help="本地LLM提供商")
    parser.add_argument("--url", default="http://localhost:8080/v1", help="Ollama API地址")
    parser.add_argument("--model", default="Qwen/Qwen3-14B-AWQ", help="Ollama模型名称")
    parser.add_argument("--mock", action="store_true", help="使用Mock模式进行测试")
    
    parser.add_argument("--streaming", action="store_true", default=True, help="使用流式JSON生成器（支持断点续传）")

    args = parser.parse_args()
    
    print("="*60)
    print("📝 小说生成器")
    print("="*60)
    print(f"\n标题: {args.novel}")
    print(f"类型: {args.genre}")
    print(f"章节: {args.chapters}")
    print(f"字数: {args.words}/章\n")
    
    # 初始化LLM
    print("🤖 初始化LLM客户端...")
    if args.mock:
        from core.llm_client import MockLLMClient
        llm_client = MockLLMClient()
    elif args.local_llm:
        from core.local_llm_client import get_local_llm_client
        llm_client = get_local_llm_client(
            provider=args.provider,
            base_url=args.url,
            model=args.model
        )
    else:
        from core.llm_client import NVIDIA_NIM_Client
        llm_client = NVIDIA_NIM_Client()
    
    # 创建概念
    concept = NovelConcept(
        title=args.novel,
        genre=args.genre,
        style="爽文",
        core_idea=args.core_idea or f"{args.novel}是一部精彩的{args.genre}爽文小说",
        total_chapters=args.chapters,
        target_word_count=args.words,
        shuangdian_intensity="high",
    )
    
    # 生成小说
    print("\n✨ 开始生成小说...\n")

    # 选择生成器：流式或标准
    if args.streaming and STREAMING_AVAILABLE:
        print("🚀 使用流式JSON生成器（支持断点续传）")
        generator = create_novel_generator(llm_client, use_streaming=True)
    else:
        if args.streaming and not STREAMING_AVAILABLE:
            print("⚠️  流式生成器不可用，使用标准生成器")
        generator = create_novel_generator(llm_client=llm_client)

    novel = await generator.process(concept)
    
    # 打印结果
    print("\n" + "="*60)
    print("✅ 小说生成完成！")
    print("="*60)
    print(f"\n标题: 《{novel.metadata['title']}》")
    print(f"总章节: {len(novel.chapters)}")
    print(f"总字数: {novel.metadata.get('total_word_count', 0):,}")
    print(f"\n保存位置: {generator.output_dir}")
    
    # 打印章节概览
    print("\n📖 章节概览:")
    for chapter in novel.chapters:
        print(f"   第{chapter.number}章 {chapter.title} ({chapter.word_count}字)")
    
    # 关闭LLM客户端
    await llm_client.close()
    
    print("\n🎉 完成！")
    
    return novel


if __name__ == "__main__":
    try:
        novel = asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

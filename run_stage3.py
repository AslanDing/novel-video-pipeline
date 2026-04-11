#!/usr/bin/env python3
"""
独立运行第三阶段：音频/TTS生成

用法:
    python run_stage3.py --novel-dir "outputs/novels/绝世剑仙"
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stage3_audio.tts_engine import TTSEngine, ChapterAudio
from stage1_novel.novel_generator import Novel
from config.settings import AUDIO_DIR


async def main():
    parser = argparse.ArgumentParser(description="生成TTS音频")
    parser.add_argument("--novel-dir", "-d", required=False, default="outputs/novels/逍遥蜉蝣",
                        help="小说输出目录路径")
    parser.add_argument("--use-edge-tts", action="store_true", default=False,
                        help="使用Edge TTS（免费在线TTS）")
    
    args = parser.parse_args()
    
    novel_dir = Path(args.novel_dir)
    if not novel_dir.exists():
        print(f"❌ 错误: 目录不存在: {novel_dir}")
        return
    
    # 加载小说数据
    complete_json = novel_dir / f"{novel_dir.name}_complete.json"
    if not complete_json.exists():
        json_files = list(novel_dir.glob("*.json"))
        if json_files:
            complete_json = json_files[0]
        else:
            print(f"❌ 错误: 找不到小说JSON文件")
            return
    
    print("="*60)
    print("🔊 TTS音频生成器")
    print("="*60)
    print(f"\n小说目录: {novel_dir}")
    print(f"使用Edge TTS: {args.use_edge_tts}\n")
    
    # 加载小说
    print("📖 加载小说数据...")
    with open(complete_json, 'r', encoding='utf-8') as f:
        novel_data = json.load(f)
    
    novel_title = novel_data['metadata']['title']
    total_chapters = len(novel_data['chapters'])
    
    print(f"   标题: 《{novel_title}》")
    print(f"   章节: {total_chapters}")
    
    # 构建Novel对象（简化版）
    from stage1_novel.novel_generator import Novel, StoryBlueprint, Chapter
    
    # 加载完整章节内容
    chapters = []
    chapters_dir = novel_dir / "chapters"
    for i in range(1, total_chapters + 1):
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
    
    # 加载角色
    characters = []
    if 'blueprint' in novel_data and 'characters' in novel_data['blueprint']:
        from stage1_novel.models import Character
        for char_data in novel_data['blueprint']['characters']:
            characters.append(Character(**char_data))
    
    novel = Novel(
        metadata=novel_data['metadata'],
        blueprint=StoryBlueprint(
            title=novel_data['blueprint']['title'],
            genre=novel_data['blueprint']['genre'],
            world_building=None,
            characters=characters,
            plot_structure=[],
            chapter_plans=novel_data['blueprint'].get('chapter_plans', []),
        ),
        chapters=chapters,
    )
    
    # 创建TTS引擎
    engine = TTSEngine()
    
    # 生成音频
    print("\n✨ 开始生成TTS音频...\n")
    try:
        results = await engine.process(novel)
        
        # 统计结果
        total_segments = sum(len(ca.segments) for ca in results.values())
        total_duration = sum(ca.total_duration for ca in results.values())
        
        print("\n" + "="*60)
        print("✅ TTS音频生成完成！")
        print("="*60)
        print(f"\n总音频片段: {total_segments}")
        print(f"总时长: {total_duration:.2f}秒 ({total_duration/60:.2f}分钟)")
        print(f"保存位置: {AUDIO_DIR}")
        
        print("\n📁 生成的音频:")
        for chapter_num, chapter_audio in results.items():
            print(f"   第{chapter_num}章:")
            print(f"      片段数: {len(chapter_audio.segments)}")
            print(f"      时长: {chapter_audio.total_duration:.2f}秒")
            if chapter_audio.combined_file:
                print(f"      合并文件: {chapter_audio.combined_file}")
        
        print("\n🎉 完成！")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n\n💥 程序异常: {e}")
        sys.exit(1)

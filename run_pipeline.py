#!/usr/bin/env python3
"""
Asset-First Pipeline Runner - 资产优先流水线

统一运行整个工作流：
- Phase 1: 预生产 - 角色包 + 场景包生成
- Phase 2: 正式生产 - TTS优先 → 关键帧 → 视频
- Phase 3: 后期合成 - 视频拼接 + 音频混合 + 字幕

用法:
    python run_pipeline.py --project-id "test_project" --chapter 1
    python run_pipeline.py --project-id "test_project" --all-chapters
    python run_pipeline.py --project-id "test_project" --phase 1  # 只运行 Phase 1
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from core.storage import ProjectStorage, create_project_storage
from core.config_models import (
    ProjectPreset,
    ChapterManifest,
    ShotSpec,
    create_default_project_preset,
    VideoMode,
    ShotStatus,
)
from stages.stage1_novel.models import Novel, Chapter, Character, StoryBlueprint
from stages.stage2_visual.character_pack_generator import CharacterPackManager
from stages.stage2_visual.scene_pack_generator import ScenePackManager
from stages.stage2_visual.image_generator import ImageGenerator
from stages.stage3_audio.tts_engine import TTSEngine
from stages.stage4_merge.video_composer import VideoComposer
from config.settings import NOVELS_DIR, get_config, IMAGE_GENERATION, VIDEO_GENERATION


class AssetFirstPipeline:
    """
    资产优先流水线

    Phase 1: 角色包 + 场景包 → Phase 2: TTS → 关键帧 → 视频 → Phase 3: 合成
    """

    def __init__(self, project_id: str, config: Dict = None):
        self.project_id = project_id
        self.config = config or get_config()
        self.storage = ProjectStorage(project_id, NOVELS_DIR.parent)
        self.novel: Optional[Novel] = None
        self.project_preset: Optional[ProjectPreset] = None

        # 子系统管理器
        self.character_manager = CharacterPackManager(self.storage)
        self.scene_manager = ScenePackManager(self.storage)
        self.image_generator = ImageGenerator(IMAGE_GENERATION)
        self.tts_engine = TTSEngine()
        self.video_composer = VideoComposer()

        self.generated_images: Dict[int, Any] = {}
        self.generated_audio: Dict[int, Any] = {}

    async def run(
        self,
        chapter_number: Optional[int] = None,
        all_chapters: bool = False,
        phase: Optional[int] = None,
        force_regenerate: bool = False,
    ):
        """
        运行流水线

        Args:
            chapter_number: 指定章节号
            all_chapters: 是否运行所有章节
            phase: 指定阶段 (1, 2, 3)
            force_regenerate: 是否强制重新生成
        """
        print("\n" + "=" * 70)
        print("🎬 资产优先流水线启动")
        print("=" * 70)
        print(f"项目ID: {self.project_id}")
        print(f"阶段: {phase or '全部'}")
        print(f"章节: {chapter_number or '全部' if all_chapters else '未指定'}")
        print("=" * 70)

        # 确保目录存在
        self.storage.ensure_directories()

        # 加载或创建项目预设
        await self._load_or_create_project_preset()

        # Phase 1: 预生产
        if phase is None or phase == 1:
            await self._run_phase_1(force_regenerate)

        # Phase 2: 正式生产
        if phase is None or phase == 2:
            if all_chapters:
                chapters = self._get_all_chapters()
            elif chapter_number:
                chapters = [chapter_number]
            else:
                chapters = []

            for ch in chapters:
                await self._run_phase_2(chapter_number=ch)

        # Phase 3: 后期合成
        if phase is None or phase == 3:
            if all_chapters:
                chapters = self._get_all_chapters()
            elif chapter_number:
                chapters = [chapter_number]
            else:
                chapters = []

            await self._run_phase_3(chapters)

        print("\n" + "=" * 70)
        print("✅ 流水线执行完成!")
        print("=" * 70)

    async def _load_or_create_project_preset(self):
        """加载或创建项目预设"""
        preset_path = self.storage.get_project_preset_path()

        if preset_path.exists():
            print(f"\n📂 加载项目预设: {preset_path}")
            self.project_preset = ProjectPreset.load(self.storage.get_project_dir())
        else:
            print(f"\n📂 创建新项目预设")
            # 从故事蓝图中加载
            bible_path = self.storage.get_story_bible_path()
            if bible_path.exists():
                with open(bible_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                title = data.get("metadata", {}).get("title", self.project_id)
                genre = data.get("metadata", {}).get("genre", "修仙")
            else:
                title = self.project_id
                genre = "修仙"

            self.project_preset = create_default_project_preset(
                project_id=self.project_id,
                title=title,
                genre=genre,
            )
            self.project_preset.save(self.storage.get_project_dir())

        print(f"   项目: {self.project_preset.title}")
        print(f"   类型: {self.project_preset.genre}")
        print(f"   风格: {self.project_preset.visual_style}")

    async def _run_phase_1(self, force_regenerate: bool = False):
        """
        Phase 1: 预生产 - 角色包 + 场景包生成
        """
        print("\n" + "-" * 60)
        print("📦 Phase 1: 预生产")
        print("-" * 60)

        # 加载小说数据
        self._load_novel()

        if not self.novel:
            print("⚠️  未找到小说数据，跳过 Phase 1")
            return

        # 1. 生成角色包
        if self.project_preset.enabled_services.get("character_pack", True):
            print("\n🎭 生成角色包...")
            await self.character_manager.generate_all_packs(
                self.novel.blueprint.characters,
                force_regenerate=force_regenerate,
            )

        # 2. 生成场景包
        if self.project_preset.enabled_services.get("scene_pack", True):
            print("\n🏠 生成场景包...")
            await self.scene_manager.generate_packs_from_chapters(
                self.novel.chapters,
                force_regenerate=force_regenerate,
            )

        print("\n✅ Phase 1 完成")

    async def _run_phase_2(self, chapter_number: int):
        """
        Phase 2: 正式生产 - TTS优先，然后关键帧，然后视频
        """
        print("\n" + "-" * 60)
        print(f"📹 Phase 2: 正式生产 (第 {chapter_number} 章)")
        print("-" * 60)

        # 加载小说数据
        self._load_novel()

        if not self.novel:
            print("⚠️  未找到小说数据，跳过 Phase 2")
            return

        # 找到对应章节
        chapter = None
        for ch in self.novel.chapters:
            if ch.number == chapter_number:
                chapter = ch
                break

        if not chapter:
            print(f"⚠️  未找到第 {chapter_number} 章")
            return

        # Step 1: TTS 先生成（音频长度决定视频长度）
        if self.project_preset.enabled_services.get("tts", True):
            print("\n🔊 Step 2.1: 生成 TTS 音频...")
            audio_results = await self.tts_engine.process(self.novel)
            if audio_results:
                self.generated_audio[chapter_number] = audio_results
            print(f"   ✅ TTS 生成完成")

        # Step 2: 生成关键帧图像
        print("\n🎨 Step 2.2: 生成关键帧...")
        script_lines = self.storage.load_script_lines(chapter_number)
        if script_lines:
            print(f"   加载了 {len(script_lines)} 个镜头")
        else:
            print("   ⚠️  未找到脚本，将使用章节内容生成关键帧")

        chapter_images = await self.image_generator.process(self.novel)
        if chapter_images:
            self.generated_images[chapter_number] = chapter_images.get(chapter_number)
            total = (
                len(self.generated_images[chapter_number].images)
                if self.generated_images.get(chapter_number)
                else 0
            )
            print(f"   ✅ 生成了 {total} 张关键帧")

        # Step 3: 生成视频 (如果启用)
        video_enabled = VIDEO_GENERATION.get("image_to_video", {}).get("enabled", False)
        if video_enabled and self.generated_images.get(chapter_number):
            print("\n🎬 Step 2.3: 生成视频...")
            images = self.generated_images[chapter_number]
            for i, img in enumerate(images.images):
                try:
                    video_path = await self.image_generator._generate_video_from_image(
                        image_path=Path(img.file_path),
                        chapter_number=chapter_number,
                        video_index=i + 1,
                        scene_description=img.scene_description,
                    )
                    print(f"   ✅ 视频 {i + 1} 生成完成")
                except Exception as e:
                    print(f"   ⚠️  视频 {i + 1} 生成失败: {e}")

        print(f"\n✅ Phase 2 ({chapter_number}) 完成")

    async def _run_phase_3(self, chapters: List[int]):
        print("\n" + "-" * 60)
        print("🎞️ Phase 3: 后期合成")
        print("-" * 60)

        if not chapters:
            print("⚠️  没有章节可处理")
            return

        if not self.video_composer.ffmpeg_available:
            print("⚠️  FFmpeg 未安装，跳过视频合成")
            return

        from stages.stage2_visual.image_generator import ChapterImages
        from stages.stage3_audio.tts_engine import ChapterAudio

        input_data = {
            "novel": self.novel,
            "images": self.generated_images,
            "audio": self.generated_audio,
        }

        try:
            final_videos = await self.video_composer.process(input_data)
            print(f"\n✅ Phase 3 完成，生成了 {len(final_videos)} 个最终视频")
            for ch, video in final_videos.items():
                print(f"   第{ch}章: {video.video_path}")
        except Exception as e:
            print(f"⚠️  视频合成失败: {e}")

    def _load_novel(self):
        """加载小说数据"""
        if self.novel:
            return

        bible_path = self.storage.get_story_bible_path()
        if not bible_path.exists():
            return

        try:
            with open(bible_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 重建 Novel 对象
            blueprint_data = data.get("blueprint", {})
            metadata = data.get("metadata", {})

            # 重建 WorldBuilding
            from stages.stage1_novel.models import WorldBuilding, Character, PlotPoint

            wb_data = blueprint_data.get("world_building", {})
            world_building = WorldBuilding(
                setting=wb_data.get("setting", ""),
                power_system=wb_data.get("power_system", ""),
                factions=wb_data.get("factions", []),
                rules=wb_data.get("rules", []),
            )

            # 重建 Characters
            characters = [Character(**c) for c in blueprint_data.get("characters", [])]

            # 重建 PlotStructure
            plot_structure = [
                PlotPoint(**p) for p in blueprint_data.get("plot_structure", [])
            ]

            blueprint = StoryBlueprint(
                title=blueprint_data.get("title", ""),
                genre=blueprint_data.get("genre", ""),
                world_building=world_building,
                characters=characters,
                plot_structure=plot_structure,
                chapter_plans=blueprint_data.get("chapter_plans", []),
            )

            # 加载章节
            chapters = []
            chapter_numbers = self.storage.list_chapters()
            for ch_num in chapter_numbers:
                content = self.storage.load_chapter_content(ch_num)
                summary = self.storage.load_chapter_summary(ch_num)
                chapters.append(
                    Chapter(
                        number=ch_num,
                        title=summary.get("title", f"第{ch_num}章"),
                        content=content,
                        word_count=summary.get("word_count", 0),
                        summary=summary.get("summary", ""),
                        key_events=summary.get("key_events", []),
                        character_appearances=summary.get("character_appearances", []),
                    )
                )

            self.novel = Novel(
                metadata=metadata,
                blueprint=blueprint,
                chapters=chapters,
            )

        except Exception as e:
            print(f"⚠️  加载小说失败: {e}")

    def _get_all_chapters(self) -> List[int]:
        """获取所有章节号"""
        return self.storage.list_chapters()


async def main():
    parser = argparse.ArgumentParser(
        description="资产优先流水线 - 统一运行整个工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 运行完整流水线
  python run_pipeline.py --project-id "test_project"

  # 只运行 Phase 1 (角色/场景包)
  python run_pipeline.py --project-id "test_project" --phase 1

  # 指定章节运行
  python run_pipeline.py --project-id "test_project" --chapter 1

  # 运行所有章节
  python run_pipeline.py --project-id "test_project" --all-chapters

  # 强制重新生成
  python run_pipeline.py --project-id "test_project" --all-chapters --force
        """,
    )

    parser.add_argument("--project-id", "-p", type=str, required=True, help="项目ID")
    parser.add_argument("--chapter", "-c", type=int, help="指定章节号")
    parser.add_argument(
        "--all-chapters", "-a", action="store_true", help="运行所有章节"
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        help="指定阶段 (1=预生产, 2=正式生产, 3=后期合成)",
    )
    parser.add_argument(
        "--force", "-f", action="store_true", help="强制重新生成所有资产"
    )

    args = parser.parse_args()

    # 验证参数
    if not args.all_chapters and not args.phase and not args.chapter:
        parser.error("请指定 --chapter 或 --all-chapters 或 --phase")

    # 创建并运行流水线
    pipeline = AssetFirstPipeline(args.project_id)

    try:
        await pipeline.run(
            chapter_number=args.chapter,
            all_chapters=args.all_chapters,
            phase=args.phase,
            force_regenerate=args.force,
        )
    except KeyboardInterrupt:
        print("\n⚠️  用户中断执行")
    except Exception as e:
        print(f"\n❌ 执行错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

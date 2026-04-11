"""
流式小说生成器

集成StreamingJSONGenerator的增强版小说生成器
提供更健壮的JSON生成和断点续传能力
"""
import asyncio
from typing import Optional, Dict, List, Any
from pathlib import Path

from stages.stage1_novel.novel_generator import NovelGenerator, NovelConcept, StoryBlueprint
from stages.stage1_novel.models import Chapter, ChapterPlan
from stages.stage1_novel.pydantic_models import (
    StoryBlueprintOutput, ChapterOutput, ScriptOutput,
    WorldBuildingOutput, CharactersOutput, PowerSystemOutput, PlotStructureOutput, ChapterPlansOutput
)
from stages.stage1_novel.prompts.protocol_prompts import (
    generate_protocol_prompt, STORY_ARCHITECT_CORE, NOVEL_WRITER_CORE, SCRIPT_ADAPTER_CORE,
    get_world_building_protocol_prompt, get_characters_protocol_prompt,
    get_power_system_protocol_prompt, get_plot_structure_protocol_prompt,
    get_chapter_plans_protocol_prompt
)
from utils.streaming_json_generator import (
    StreamingJSONGenerator,
    JSONRepairTool,
    GenerationState,
    robust_json_generate
)
from utils.json_helper import extract_json
from config.settings import get_llm_max_tokens


class StreamingNovelGenerator(NovelGenerator):
    """
    增强版小说生成器，集成流式JSON生成

    特点：
    1. 断点续传 - 从JSON截断处继续生成
    2. 智能修复 - 自动修复不完整的JSON
    3. 稳定性保障 - 多次尝试和回退策略
    """

    def __init__(self, llm_client=None, use_local_llm=False, config=None):
        super().__init__(llm_client, use_local_llm, config)
        self.streaming_generator = StreamingJSONGenerator(self.llm_client)
        self.repair_tool = JSONRepairTool()

    async def _create_blueprint(self, concept: NovelConcept) -> StoryBlueprint:
        """
        使用流式生成创建故事蓝图（分步版本）

        继承自基类，但使用流式JSON生成增强的版本
        """
        print("\n🏗️  正在分步构建故事蓝图（流式生成模式）...")

        from stages.stage1_novel.models import WorldBuilding, Character, PlotPoint
        from utils.streaming_json_generator import robust_json_generate

        max_retries = 5  # 流式版本更多重试次数

        # ========== Step 1: 生成世界观 (流式) ==========
        print("   📍 Step 1/5: 生成世界观（流式）...")
        world_building_data = None
        for attempt in range(max_retries):
            try:
                system_prompt = get_world_building_protocol_prompt(concept)
                result, metadata = await robust_json_generate(
                    llm_client=self.llm_client,
                    prompt="",
                    system_prompt=system_prompt,
                    max_tokens=get_llm_max_tokens("world_building"),
                    required_fields=["setting", "factions", "rules"],
                    max_attempts=3,
                    response_format={"type": "json_object"}
                )
                if result:
                    world_building_data = result
                    print(f"   ✓ 世界观生成成功")
                    break
            except Exception as e:
                print(f"   ⚠️ 世界观生成失败 ({attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1: raise

        world_building = WorldBuilding(
            setting=world_building_data.get("setting", ""),
            power_system="",
            factions=world_building_data.get("factions", []),
            rules=world_building_data.get("rules", []),
        )

        # ========== Step 2: 生成角色 (流式) ==========
        print("   📍 Step 2/5: 生成角色（流式）...")
        characters_data = None
        for attempt in range(max_retries):
            try:
                system_prompt = get_characters_protocol_prompt(concept, world_building)
                result, metadata = await robust_json_generate(
                    llm_client=self.llm_client,
                    prompt="",
                    system_prompt=system_prompt,
                    max_tokens=get_llm_max_tokens("characters"),
                    required_fields=["characters"],
                    max_attempts=3,
                    response_format={"type": "json_object"}
                )
                if result:
                    characters_data = result
                    print(f"   ✓ 角色生成成功 ({len(characters_data.get('characters', []))} 个角色)")
                    break
            except Exception as e:
                print(f"   ⚠️ 角色生成失败 ({attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1: raise

        characters = [Character(**c) for c in characters_data.get("characters", [])]

        # ========== Step 3: 生成修炼体系 (流式) ==========
        print("   📍 Step 3/5: 生成修炼体系（流式）...")
        power_system_data = None
        for attempt in range(max_retries):
            try:
                system_prompt = get_power_system_protocol_prompt(concept, world_building)
                result, metadata = await robust_json_generate(
                    llm_client=self.llm_client,
                    prompt="",
                    system_prompt=system_prompt,
                    max_tokens=get_llm_max_tokens("power_system"),
                    required_fields=["power_system", "cultivation_realms"],
                    max_attempts=3,
                    response_format={"type": "json_object"}
                )
                if result:
                    power_system_data = result
                    print(f"   ✓ 修炼体系生成成功")
                    break
            except Exception as e:
                print(f"   ⚠️ 修炼体系生成失败 ({attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1: raise

        world_building.power_system = power_system_data.get("power_system", "")

        # ========== Step 4: 生成情节结构 (流式) ==========
        print("   📍 Step 4/5: 生成情节结构（流式）...")
        plot_structure_data = None
        for attempt in range(max_retries):
            try:
                system_prompt = get_plot_structure_protocol_prompt(concept, world_building, characters)
                result, metadata = await robust_json_generate(
                    llm_client=self.llm_client,
                    prompt="",
                    system_prompt=system_prompt,
                    max_tokens=get_llm_max_tokens("plot_structure"),
                    required_fields=["plot_structure"],
                    max_attempts=3,
                    response_format={"type": "json_object"}
                )
                if result:
                    plot_structure_data = result
                    print(f"   ✓ 情节结构生成成功 ({len(plot_structure_data.get('plot_structure', []))} 个情节点)")
                    break
            except Exception as e:
                print(f"   ⚠️ 情节结构生成失败 ({attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1: raise

        plot_structure = [PlotPoint(**p) for p in plot_structure_data.get("plot_structure", [])]

        # ========== Step 5: 生成章节规划 (流式批量) ==========
        print("   📍 Step 5/5: 生成章节规划（流式）...")
        batch_size = 5
        all_chapter_plans = []

        if concept.total_chapters <= batch_size:
            for attempt in range(max_retries):
                try:
                    system_prompt = get_chapter_plans_protocol_prompt(
                        concept, world_building, characters, plot_structure, 1, concept.total_chapters
                    )
                    result, metadata = await robust_json_generate(
                        llm_client=self.llm_client,
                        prompt="",
                        system_prompt=system_prompt,
                        max_tokens=get_llm_max_tokens("chapter_plans"),
                        required_fields=["chapter_plans"],
                        max_attempts=3,
                        response_format={"type": "json_object"}
                    )
                    if result:
                        all_chapter_plans = result.get("chapter_plans", [])
                        print(f"   ✓ 章节规划生成成功 ({len(all_chapter_plans)} 章)")
                        break
                except Exception as e:
                    print(f"   ⚠️ 章节规划生成失败 ({attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1: raise
        else:
            print(f"   📦 章节数较多 ({concept.total_chapters})，分批生成...")
            for start_ch in range(1, concept.total_chapters + 1, batch_size):
                end_ch = min(start_ch + batch_size - 1, concept.total_chapters)
                print(f"   正在规划第 {start_ch} 到 {end_ch} 章...")

                for attempt in range(max_retries):
                    try:
                        system_prompt = get_chapter_plans_protocol_prompt(
                            concept, world_building, characters, plot_structure, start_ch, end_ch
                        )
                        result, metadata = await robust_json_generate(
                            llm_client=self.llm_client,
                            prompt="",
                            system_prompt=system_prompt,
                            max_tokens=4000,
                            required_fields=["chapter_plans"],
                            max_attempts=3,
                            response_format={"type": "json_object"}
                        )
                        if result:
                            batch_plans = result.get("chapter_plans", [])
                            all_chapter_plans.extend(batch_plans)
                            print(f"   ✓ 第 {start_ch}-{end_ch} 章规划完成")
                            break
                    except Exception as e:
                        print(f"   ⚠️ 章节规划失败 ({attempt + 1}/{max_retries}): {e}")
                        if attempt == max_retries - 1: raise

        print(f"   ✓ 总共生成 {len(all_chapter_plans)} 章规划")

        print(f"✅ 故事蓝图构建完成（流式生成）")
        print(f"   - 世界观: {len(world_building.rules)} 条规则, {len(world_building.factions)} 个势力")
        print(f"   - 角色: {len(characters)} 位")
        print(f"   - 章节规划: {len(all_chapter_plans)} 章")

        # 构建 StoryBlueprint
        blueprint = StoryBlueprint(
            title=concept.title,
            genre=concept.genre,
            world_building=world_building,
            characters=characters,
            plot_structure=plot_structure,
            chapter_plans=all_chapter_plans,
        )

        # 保存蓝图并等待用户确认
        blueprint = self._save_and_confirm_blueprint(blueprint, concept)

        return blueprint

    async def _generate_chapter_streaming(
        self,
        chapter_plan: ChapterPlan,
        blueprint: StoryBlueprint,
        concept: NovelConcept,
        context: str,
        max_retries: int = 3
    ) -> Chapter:
        """
        使用流式生成生成章节内容

        相比原版，增加了断点续传能力
        """
        print(f"   📝 正在生成第{chapter_plan.number}章（流式模式）...")

        # 构建角色信息
        characters_info = "主要角色:\n"
        main_char = blueprint.characters[0]
        characters_info += f"【主角】{main_char.name}: {main_char.description}\n"
        characters_info += f"  性格: {main_char.personality}\n"
        characters_info += f"  目标: {main_char.goals}\n"

        # 构建系统提示词
        system_prompt = generate_protocol_prompt(NOVEL_WRITER_CORE, ChapterOutput)

        task_description = (
            f"请创作第{chapter_plan.number}章《{chapter_plan.title}》\n"
            f"目标字数: {concept.target_word_count}字左右\n\n"
            f"{characters_info}\n\n{context}\n\n"
            f"本章规划:\n- 标题: {chapter_plan.title}\n- 概要: {chapter_plan.summary}\n"
            f"- 关键事件: {', '.join(chapter_plan.key_events)}\n"
        )
        if chapter_plan.shuangdian:
             task_description += f"- 爽点设计: {chapter_plan.shuangdian.description}\n"

        task_description += "\n核心要求：请展开细节，增加生动的对话、环境描写和心理描写，使内容丰满。严禁简略概括情节。"

        # 使用流式生成
        max_tokens = self._calculate_max_tokens(concept.target_word_count)

        required_fields = ["title", "content", "summary", "key_events"]

        result, metadata = await robust_json_generate(
            llm_client=self.llm_client,
            prompt=task_description,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            required_fields=required_fields,
            max_attempts=max_retries + 2,
            response_format={"type": "json_object"}
        )

        if result:
            # 成功获取结果
            chapter = Chapter(
                number=chapter_plan.number,
                title=result.get("title", chapter_plan.title),
                content=result.get("content", ""),
                word_count=len(result.get("content", "")),
                summary=result.get("summary", ""),
                key_events=result.get("key_events", []),
                character_appearances=result.get("character_appearances", []),
            )

            if metadata.get('attempt_count', 0) > 1:
                print(f"      (使用 {metadata['attempt_count']} 次尝试完成)")

            return chapter
        else:
            # 流式生成失败，使用原版的容错机制
            print(f"   ⚠️  流式生成失败，切换到基础模式...")
            return await self._generate_raw_chapter(
                chapter_plan, blueprint, concept, context
            )


# 便捷的切换函数
def create_novel_generator(llm_client=None, use_streaming: bool = True, use_local_llm: bool = False, config=None):
    """
    创建小说生成器实例

    Args:
        llm_client: LLM客户端
        use_streaming: 是否使用流式生成（默认True）
        use_local_llm: 是否使用本地模型（默认False）
        config: 配置

    Returns:
        NovelGenerator 或其子类实例
    """
    if use_streaming:
        print("🚀 使用流式JSON生成器（支持断点续传）")
        return StreamingNovelGenerator(llm_client=llm_client, use_local_llm=use_local_llm, config=config)
    else:
        print("📖 使用标准生成器")
        return NovelGenerator(llm_client=llm_client, use_local_llm=use_local_llm, config=config)
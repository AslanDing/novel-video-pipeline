"""
小说生成主控器 - 第一阶段核心
整合故事架构、章节生成和质量控制
"""
import json
import asyncio
import math
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from utils.json_helper import extract_json
from utils.streaming_json_generator import robust_json_generate

import sys
sys.path.append(str(Path(__file__).parent.parent))

from core.llm_client import NVIDIA_NIM_Client
from core.local_llm_client import get_local_llm_client
from core.base_pipeline import PipelineStage
from config.settings import NOVELS_DIR, LOCAL_LLM_CONFIG, get_llm_max_tokens, load_subsystem_config

from stages.stage1_novel.models import (
    NovelConcept, StoryBlueprint, WorldBuilding, Character,
    PlotPoint, Chapter, Novel, ChapterPlan, ScriptLine
)
from stages.stage1_novel.pydantic_models import (
    StoryBlueprintOutput, ChapterOutput, ChunkOutput, ScriptOutput,
    WorldBuildingOutput, CharactersOutput, PowerSystemOutput, PlotStructureOutput, ChapterPlansOutput
)
from stages.stage1_novel.prompts.protocol_prompts import (
    generate_protocol_prompt, STORY_ARCHITECT_CORE, NOVEL_WRITER_CORE, SCRIPT_ADAPTER_CORE,
    get_world_building_protocol_prompt, get_characters_protocol_prompt,
    get_power_system_protocol_prompt, get_plot_structure_protocol_prompt,
    get_chapter_plans_protocol_prompt
)
from stages.stage1_novel.shuangdian_system import ShuangDianSystem
from stages.stage1_novel.quality_controller import QualityController
from stages.stage1_novel.context_manager import ContextManager
from stages.stage1_novel.consistency_checker import ConsistencyChecker
from stages.stage1_novel.rhythm_controller import RhythmController


class NovelGenerator(PipelineStage):
    """
    小说生成器 - 第一阶段核心组件

    整合故事架构、章节生成和质量控制
    """

    def __init__(self, llm_client=None, use_local_llm=False, config=None):
        super().__init__("小说生成", config)
        
        # 如果未传入 client，则根据参数初始化
        if llm_client is None:
            if use_local_llm:
                provider = LOCAL_LLM_CONFIG["provider"]
                self.llm_client = get_local_llm_client(
                    provider=provider,
                    **LOCAL_LLM_CONFIG.get(provider, {}),
                    temperature=LOCAL_LLM_CONFIG.get("temperature", 0.7),
                    max_tokens=LOCAL_LLM_CONFIG.get("max_tokens", 4096)
                )
            else:
                self.llm_client = NVIDIA_NIM_Client()
        else:
            self.llm_client = llm_client
        self.output_dir = None

        # 初始化各个子系统
        self.shuangdian_system = ShuangDianSystem()
        self.quality_controller = QualityController(llm_client)
        self.context_manager = ContextManager()
        self.consistency_checker = ConsistencyChecker()
        self.rhythm_controller = RhythmController()

        # 长章节分块生成配置
        self.CHUNK_WORD_COUNT = 2000   # 每块目标字数（降低使 LLM 更容易写满）
        self.MAX_TOKENS_LIMIT = 128000  # 最大 tokens 上限
        self.MIN_TOKENS = 8000  # 最小 tokens

    def _calculate_max_tokens(self, target_word_count: int) -> int:
        """根据目标字数计算所需的 max_tokens"""
        base_tokens = target_word_count * 2
        overhead = int(base_tokens * 0.3)
        total = base_tokens + overhead
        return max(self.MIN_TOKENS, min(self.MAX_TOKENS_LIMIT, total))

    def _save_and_confirm_blueprint(self, blueprint: StoryBlueprint, concept: NovelConcept) -> StoryBlueprint:
        """保存蓝图并等待用户确认"""
        import json

        # 保存蓝图
        output_dir = NOVELS_DIR / concept.title.replace(" ", "_")
        output_dir.mkdir(parents=True, exist_ok=True)
        blueprint_path = output_dir / "story_bible.json"

        with open(blueprint_path, 'w', encoding='utf-8') as f:
            json.dump(blueprint.to_dict(), f, ensure_ascii=False, indent=2)

        print(f"\n📄 故事蓝图已保存到: {blueprint_path}")
        print(f"   请查看并修改 (如果需要)")
        print(f"   确认后继续生成章节吗? (yes/no): ", end="")

        # 等待用户确认
        user_input = input().strip().lower()
        if user_input not in ['yes', 'y', '是', '确认', 'ok']:
            print("❌ 用户取消生成")
            raise KeyboardInterrupt("用户取消生成")

        # 重新从文件读取蓝图（用户可能修改过）
        print("   ✓ 正在从文件读取蓝图...")
        with open(blueprint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 重建 StoryBlueprint 对象
        wb_data = data.get("world_building", {})
        world_building = WorldBuilding(
            setting=wb_data.get("setting", ""),
            power_system=wb_data.get("power_system", ""),
            factions=wb_data.get("factions", []),
            rules=wb_data.get("rules", []),
        )
        characters = [Character(**c) for c in data.get("characters", [])]
        plot_structure = [PlotPoint(**p) for p in data.get("plot_structure", [])]

        return StoryBlueprint(
            title=concept.title,
            genre=concept.genre,
            world_building=world_building,
            characters=characters,
            plot_structure=plot_structure,
            chapter_plans=data.get("chapter_plans", []),
        )

    def validate_input(self, input_data) -> bool:
        """验证输入"""
        if isinstance(input_data, NovelConcept):
            return True
        if isinstance(input_data, dict):
            required = ['title', 'genre', 'core_idea']
            return all(k in input_data for k in required)
        return False

    async def process(self, concept: NovelConcept) -> Novel:
        """生成完整小说"""
        print(f"📝 开始生成小说: 《{concept.title}》")
        print(f"   类型: {concept.genre} | {concept.style}")
        print(f"   章节数: {concept.total_chapters} | 每章字数: {concept.target_word_count}")

        # 步骤1: 构建故事蓝图
        blueprint = await self._create_blueprint(concept)

        # 步骤2: 规划爽点分布
        shuangdian_plan = self.shuangdian_system.plan_distribution(concept.total_chapters)
        print(f"   🎯 爽点规划完成: {len(shuangdian_plan)} 章")

        # 步骤3: 生成各章节
        chapters = []
        # 计算输出目录
        output_dir = NOVELS_DIR / concept.title.replace(" ", "_")
        
        for i in range(1, concept.total_chapters + 1):
            chapter = await self._generate_chapter_with_quality_control(
                chapter_number=i,
                blueprint=blueprint,
                concept=concept,
                previous_chapters=chapters,
                shuangdian=shuangdian_plan.get(i),
            )
            
            # --- 分镜脚本拆分 ---
            print(f"   🎬 正在为第{i}章拆分分镜脚本...")
            try:
                chapter = await self._adapt_to_script(chapter, blueprint)
            except Exception as e:
                print(f"   ⚠️ 第{i}章分镜脚本拆分失败: {e}")

            chapters.append(chapter)

            print(f"   ✅ 第{i}章完成 ({chapter.word_count}字)")
            if chapter.quality_score:
                print(f"      质量评分: {chapter.quality_score.overall}/10")

            # 每生成完一章，触发一次中间缓存保存（增量保存）
            print(f"   💾 正在缓存已生成的 {i}/{concept.total_chapters} 章...")
            partial_novel = Novel(
                metadata={
                    "title": concept.title,
                    "genre": concept.genre,
                    "style": concept.style,
                    "total_chapters": concept.total_chapters,
                    "current_chapter": i,
                    "total_word_count": sum(c.word_count for c in chapters),
                    "creation_time": datetime.now().isoformat(),
                    "status": "generating"
                },
                blueprint=blueprint,
                chapters=chapters,
            )
            partial_novel.save(output_dir)

        # 步骤4: 组装小说对象 (最终版)
        novel = Novel(
            metadata={
                "title": concept.title,
                "genre": concept.genre,
                "style": concept.style,
                "total_chapters": len(chapters),
                "total_word_count": sum(c.word_count for c in chapters),
                "creation_time": datetime.now().isoformat(),
                "status": "completed"
            },
            blueprint=blueprint,
            chapters=chapters,
        )

        # 最后再保存一次最终版
        novel.save(output_dir)
        self.output_dir = output_dir

        return novel

    async def _create_blueprint(self, concept: NovelConcept) -> StoryBlueprint:
        """分步创建故事蓝图 - 拆分生成策略"""
        print("\n🏗️  正在分步构建故事蓝图...")

        # ========== Step 1: 生成世界观 ==========
        print("   📍 Step 1/5: 生成世界观...")
        system_prompt = get_world_building_protocol_prompt(concept)
        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt="",
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("world_building"),
            required_fields=["setting", "factions", "rules"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )
        if not result:
            raise ValueError("世界观生成失败")
        world_building_data = result
        print(f"   ✓ 世界观生成成功")

        world_building = WorldBuilding(
            setting=world_building_data["setting"],
            power_system="",  # 修炼体系后续单独生成
            factions=world_building_data["factions"],
            rules=world_building_data["rules"],
        )

        # ========== Step 2: 生成角色 (基于世界观) ==========
        print("   📍 Step 2/5: 生成角色...")
        system_prompt = get_characters_protocol_prompt(concept, world_building)
        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt="",
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("characters"),
            required_fields=["characters"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )
        if not result:
            raise ValueError("角色生成失败")
        characters_data = result
        print(f"   ✓ 角色生成成功 ({len(characters_data.get('characters', []))} 个角色)")

        characters = [Character(**c) for c in characters_data.get("characters", [])]

        # ========== Step 3: 生成修炼体系 (基于世界观) ==========
        print("   📍 Step 3/5: 生成修炼体系...")
        system_prompt = get_power_system_protocol_prompt(concept, world_building)
        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt="",
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("power_system"),
            required_fields=["power_system", "cultivation_realms"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )
        if not result:
            raise ValueError("修炼体系生成失败")
        power_system_data = result
        print(f"   ✓ 修炼体系生成成功")

        # 更新 world_building 的 power_system
        world_building.power_system = power_system_data["power_system"]

        # ========== Step 4: 生成情节结构 (基于角色和世界观) ==========
        print("   📍 Step 4/5: 生成情节结构...")
        system_prompt = get_plot_structure_protocol_prompt(concept, world_building, characters)
        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt="",
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("plot_structure"),
            required_fields=["plot_structure"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )
        if not result:
            raise ValueError("情节结构生成失败")
        plot_structure_data = result
        print(f"   ✓ 情节结构生成成功 ({len(plot_structure_data.get('plot_structure', []))} 个情节点)")

        plot_structure = [PlotPoint(**p) for p in plot_structure_data.get("plot_structure", [])]

        # ========== Step 5: 生成章节规划 (批量生成) ==========
        print("   📍 Step 5/5: 生成章节规划...")
        batch_size = 5
        all_chapter_plans = []

        if concept.total_chapters <= batch_size:
            # 小于等于批量大小，一次性生成
            system_prompt = get_chapter_plans_protocol_prompt(
                concept, world_building, characters, plot_structure, 1, concept.total_chapters
            )
            result, _ = await robust_json_generate(
                llm_client=self.llm_client,
                prompt="",
                system_prompt=system_prompt,
                max_tokens=get_llm_max_tokens("chapter_plans"),
                required_fields=["chapter_plans"],
                max_attempts=3,
                response_format={"type": "json_object"}
            )
            if not result:
                raise ValueError("章节规划生成失败")
            all_chapter_plans = result.get("chapter_plans", [])
            print(f"   ✓ 章节规划生成成功 ({len(all_chapter_plans)} 章)")
        else:
            # 大于批量大小，分批生成
            print(f"   📦 章节数较多 ({concept.total_chapters})，分批生成...")
            for start_ch in range(1, concept.total_chapters + 1, batch_size):
                end_ch = min(start_ch + batch_size - 1, concept.total_chapters)
                print(f"   正在规划第 {start_ch} 到 {end_ch} 章...")

                system_prompt = get_chapter_plans_protocol_prompt(
                    concept, world_building, characters, plot_structure, start_ch, end_ch
                )
                result, _ = await robust_json_generate(
                    llm_client=self.llm_client,
                    prompt="",
                    system_prompt=system_prompt,
                    max_tokens=get_llm_max_tokens("chapter_plans"),
                    required_fields=["chapter_plans"],
                    max_attempts=3,
                    response_format={"type": "json_object"}
                )
                if result:
                    batch_plans = result.get("chapter_plans", [])
                    all_chapter_plans.extend(batch_plans)
                    print(f"   ✓ 第 {start_ch}-{end_ch} 章规划完成")
                else:
                    print(f"   ⚠️ 第 {start_ch}-{end_ch} 章规划失败")

        print(f"   ✓ 总共生成 {len(all_chapter_plans)} 章规划")

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

        return blueprint

    async def _generate_chapter_with_quality_control(
        self,
        chapter_number: int,
        blueprint: StoryBlueprint,
        concept: NovelConcept,
        previous_chapters: List[Chapter],
        shuangdian=None,
    ) -> Chapter:
        """带质量控制的章节生成（带重试机制）"""
        max_retries = 5

        for attempt in range(1, max_retries + 1):
            try:
                chapter = await self._generate_chapter_attempt(
                    chapter_number, blueprint, concept, previous_chapters, shuangdian
                )

                # 检查内容是否有效
                if chapter and chapter.content and len(chapter.content) > 100:
                    # 质量评估
                    quality_score = await self.quality_controller.evaluate_chapter(chapter, blueprint, previous_chapters)
                    chapter.quality_score = quality_score

                    # 字数明显不足（< 60% 目标），触发重写扩展
                    target = concept.target_word_count
                    if chapter.word_count < target * 0.6 and attempt < max_retries:
                        print(f"   🔧 字数不足（{chapter.word_count}/{target}字），触发扩展重写...")
                        length_issue = (
                            f"章节字数严重不足（当前约{chapter.word_count}字，目标{target}字）。"
                            f"请大幅展开内容：增加对话、心理描写、环境描写和细节，补充到{target}字左右"
                        )
                        all_issues = [length_issue] + (quality_score.issues or [])
                        rewritten = await self.quality_controller.rewrite_chapter(
                            chapter, all_issues, concept
                        )
                        if rewritten and rewritten.word_count > chapter.word_count:
                            chapter = rewritten
                            quality_score = await self.quality_controller.evaluate_chapter(
                                chapter, blueprint, previous_chapters
                            )
                            chapter.quality_score = quality_score

                    # 缓存摘要
                    self.context_manager.cache_chapter_summary(chapter)

                    if attempt > 1:
                        print(f"   ✓ 第{chapter_number}章生成成功 (尝试 {attempt}/{max_retries})")
                    return chapter
                else:
                    print(f"   ⚠️ 第{chapter_number}章生成内容无效 (尝试 {attempt}/{max_retries})")

            except Exception as e:
                print(f"   ⚠️ 第{chapter_number}章生成失败: {e} (尝试 {attempt}/{max_retries})")
                if attempt == max_retries:
                    raise

        # 所有重试都失败，返回一个降级章节
        return Chapter(
            number=chapter_number,
            title=f"第{chapter_number}章",
            content="[章节生成失败]",
            word_count=0,
            summary="生成失败",
            key_events=[],
            character_appearances=[],
        )

    async def _generate_chapter_attempt(
        self,
        chapter_number: int,
        blueprint: StoryBlueprint,
        concept: NovelConcept,
        previous_chapters: List[Chapter],
        shuangdian=None,
    ) -> Chapter:
        """单次生成章节的尝试"""
        if chapter_number - 1 < len(blueprint.chapter_plans):
            chapter_plan_dict = blueprint.chapter_plans[chapter_number - 1]
        else:
            chapter_plan_dict = {
                "title": f"第{chapter_number}章",
                "summary": "本章概要缺失",
                "key_events": []
            }
            
        chapter_plan = ChapterPlan(
            number=chapter_number,
            title=chapter_plan_dict.get("title", f"第{chapter_number}章"),
            summary=chapter_plan_dict.get("summary", ""),
            key_events=chapter_plan_dict.get("key_events", []),
        )

        plot_point = next((pp for pp in blueprint.plot_structure if pp.chapter == chapter_number), None)
        chapter_plan = self.shuangdian_system.enhance_chapter_plan(chapter_plan, plot_point)
        if shuangdian: chapter_plan.shuangdian = shuangdian
        chapter_plan.template_type = self.rhythm_controller.select_chapter_template(chapter_number, concept.total_chapters, blueprint.plot_structure)

        context = self.context_manager.build_chapter_context(chapter_number, blueprint, previous_chapters)

        # 目标字数 > 3000 时分块生成，确保每次 LLM 调用只需写 2000 字
        if concept.target_word_count > 3000:
            chapter = await self._generate_with_adaptive_chunking(chapter_plan, blueprint, concept, context)
        else:
            chapter = await self._generate_raw_chapter(chapter_plan, blueprint, concept, context)

        return chapter

    async def _generate_raw_chapter(
        self,
        chapter_plan: ChapterPlan,
        blueprint: StoryBlueprint,
        concept: NovelConcept,
        context: str,
    ) -> Chapter:
        """生成原始章节内容"""
        print(f"   📝 正在生成第{chapter_plan.number}章...")

        characters_info = "主要角色:\n"
        for c in blueprint.characters[:3]:
            characters_info += f"- {c.name}: {c.personality}\n"

        system_prompt = generate_protocol_prompt(NOVEL_WRITER_CORE, ChapterOutput)
        task_description = (
            f"请创作第{chapter_plan.number}章《{chapter_plan.title}》\n"
            f"目标字数: {concept.target_word_count}字左右\n\n"
            f"{characters_info}\n\n{context}\n\n"
            f"本章规划:\n- 概要: {chapter_plan.summary}\n"
            f"- 关键事件: {', '.join(chapter_plan.key_events)}\n"
        )
        if chapter_plan.shuangdian: 
            task_description += f"- 爽点设计: {chapter_plan.shuangdian.description}\n"
        
        task_description += "\n核心要求：请展开细节，增加生动的对话、环境描写和心理描写，使内容丰满。严禁简略概括情节。"

        max_tokens = self._calculate_max_tokens(concept.target_word_count)

        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt=task_description,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            required_fields=["title", "content", "summary", "key_events"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )

        if not result:
            return None

        try:
            validated = ChapterOutput.model_validate(result)
            return Chapter(
                number=chapter_plan.number,
                title=validated.title,
                content=validated.content,
                word_count=len(validated.content),
                summary=validated.summary,
                key_events=validated.key_events,
                character_appearances=validated.character_appearances,
            )
        except Exception as e:
            print(f"⚠️ 解析章节失败: {e}")
            return None

    async def _generate_with_adaptive_chunking(self, chapter_plan, blueprint, concept, context) -> Chapter:
        """分块生成长章节
        
        核心修复：
        - CHUNK_WORD_COUNT=2000，每块目标2000字，LLM 单次更容易写满
        - num_chunks = ceil(target / chunk_size)，公式正确计算块数
        - 每块使用带 JSON Schema 的 protocol prompt，确保输出格式和质量
        """
        num_chunks = max(2, math.ceil(concept.target_word_count / self.CHUNK_WORD_COUNT))
        print(f"   📦 分块生成第{chapter_plan.number}章（目标{concept.target_word_count}字 → {num_chunks}块 × {self.CHUNK_WORD_COUNT}字）")

        chunks = []
        all_key_events = []
        all_char_appearances = []
        current_context = context

        # 为分块生成构建携带 JSON Schema 的 system prompt
        chunk_system_prompt = generate_protocol_prompt(NOVEL_WRITER_CORE, ChunkOutput)

        for i in range(num_chunks):
            is_last = (i == num_chunks - 1)
            prev_content = "\n".join(chunks)
            prompt = self._build_chunk_prompt(chapter_plan, current_context, i, num_chunks, is_last, prev_content)

            result, _ = await robust_json_generate(
                llm_client=self.llm_client,
                prompt=prompt,
                system_prompt=chunk_system_prompt,
                max_tokens=get_llm_max_tokens("chapter_chunk"),  # 使用独立的分块 token 上限
                required_fields=["content"],
                max_attempts=3,
                response_format={"type": "json_object"}
            )

            if result:
                content = result.get("content", "")
                if content:
                    chunks.append(content)
                    current_context += f"\n[本章前文摘要]\n{content[-600:]}"
                    if result.get("key_events"):
                        all_key_events.extend(result["key_events"])
                    if result.get("character_appearances"):
                        all_char_appearances.extend(result["character_appearances"])
                    print(f"      ✓ 第{i+1}/{num_chunks}块完成（{len(content)}字）")
                else:
                    print(f"      ⚠️ 第{i+1}/{num_chunks}块内容为空")
            else:
                print(f"      ⚠️ 第{i+1}/{num_chunks}块生成失败，继续...")

        if not chunks:
            return None

        full_content = "\n\n".join(chunks)
        print(f"      ✓ 分块合并完成，总字数: {len(full_content)}字")
        return Chapter(
            number=chapter_plan.number,
            title=chapter_plan.title,
            content=full_content,
            word_count=len(full_content),
            summary=chapter_plan.summary,
            key_events=list(dict.fromkeys(all_key_events)) if all_key_events else chapter_plan.key_events,
            character_appearances=list(dict.fromkeys(all_char_appearances)),
        )

    def _build_chunk_prompt(self, chapter_plan, context, index, total, is_last, prev):
        part_desc = "开头部分" if index == 0 else ("结尾部分" if is_last else f"中间第{index+1}部分")
        prev_excerpt = prev[-800:] if prev else "（本章第一段，无前文）"
        return (
            f"请创作第{chapter_plan.number}章《{chapter_plan.title}》的{part_desc}（第{index+1}/{total}段）\n"
            f"目标字数: {self.CHUNK_WORD_COUNT}字左右\n\n"
            f"本章整体概要: {chapter_plan.summary}\n"
            f"本章关键事件: {', '.join(chapter_plan.key_events)}\n\n"
            f"上下文信息:\n{context}\n\n"
            f"前文已写内容（末尾节选）:\n{prev_excerpt}\n\n"
            f"核心要求：\n"
            f"- 继续书写{part_desc}，与前文保持自然衔接\n"
            f"- 展开细节，大量使用对话、心理描写和场景描写\n"
            f"- {'本段是最后一段，请写好反转或悬念收尾' if is_last else '本段不是结尾，不要做总结性收尾，保持叙事张力'}\n"
            f"- 严禁用概括语言跳跃情节，必须逐步展开每个场景"
        )

    async def _adapt_to_script(self, chapter: Chapter, blueprint: StoryBlueprint) -> Chapter:
        """分镜脚本拆分（增强版：支持长章节分块拆分）"""
        # 设定每块处理的字数
        chars_per_chunk = 2500
        content = chapter.content
        
        # 如果长度超过阈值，进行分块
        if len(content) <= chars_per_chunk + 500:
            chunks = [content]
        else:
            # 简单按字数切分
            chunks = []
            for i in range(0, len(content), chars_per_chunk):
                chunks.append(content[i:i + chars_per_chunk])
        
        all_script_lines = []
        scene_counter = 1
        
        for i, chunk_content in enumerate(chunks):
            if len(chunks) > 1:
                print(f"      📦 正在处理分镜分块 {i+1}/{len(chunks)}...")
            
            # 对每个分块进行重试生成
            max_retries = 3
            chunk_lines = []
            
            for attempt in range(1, max_retries + 1):
                try:
                    # 调用带有内容片段的生成函数
                    chunk_lines = await self._adapt_to_script_attempt_v2(
                        chunk_content, 
                        chapter.title, 
                        blueprint, 
                        start_scene_no=scene_counter,
                        chunk_index=i,
                        total_chunks=len(chunks)
                    )
                    if chunk_lines:
                        break
                except Exception as e:
                    print(f"      ⚠️ 分块 {i+1} 尝试 {attempt} 失败: {e}")
            
            if chunk_lines:
                all_script_lines.extend(chunk_lines)
                scene_counter += len(chunk_lines)
            else:
                print(f"      ❌ 分块 {i+1} 最终生成失败")
        
        chapter.script_lines = all_script_lines
        print(f"      ✅ 整章分镜拆解完成，共 {len(all_script_lines)} 个分镜")
        return chapter

    async def _adapt_to_script_attempt_v2(
        self, 
        content_chunk: str, 
        chapter_title: str, 
        blueprint: StoryBlueprint,
        start_scene_no: int = 1,
        chunk_index: int = 0,
        total_chunks: int = 1
    ) -> List[ScriptLine]:
        """单次分块分镜脚本拆分尝试"""
        system_prompt = generate_protocol_prompt(SCRIPT_ADAPTER_CORE, ScriptOutput)
        char_info = "\n".join([f"{c.name}: {c.appearance}" for c in blueprint.characters])

        part_desc = f"（第 {chunk_index+1}/{total_chunks} 部分）" if total_chunks > 1 else ""

        prompt = (
            f"你是顶尖的视觉艺术家和分镜编剧。请将小说章节《{chapter_title}》的文本片段{part_desc}拆分为极具画面感的【分镜脚本】。\n\n"
            f"【角色视觉参考】:\n{char_info}\n\n"
            f"【创作要求】:\n"
            f"1. 数量限制：此片段生成 5-10 个分镜行。\n"
            f"2. visual_prompt 必须是详细的英文，请按此结构撰写：\n"
            f"   (Subject: 人物及姿态), (Action: 正在发生的动作), (Setting: 环境细节), (Lighting: 光影效果, 如 cinematic lighting, golden hour), (Composition: 构图方式, 如 rule of thirds, low angle), (Mood: 氛围描述)。\n"
            f"3. 视觉质量：必须包含材质细节（如 skin texture, metallic shine）、环境特效（如 floating particles, mist）以及电影感描述。\n"
            f"4. 角色一致性：请在每个涉及角色的分镜中，根据【角色视觉参考】重复提及角色的关键外貌特征。\n"
            f"5. 镜头运动：在 motion_prompt 中精确描述摄像机如何移动，以增强动态感。\n"
            f"6. 编号提示：此片段的起始场景编号建议从 SC_{start_scene_no:03d} 开始。\n\n"
            f"【小说文本片段】:\n{content_chunk}"
        )

        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("script"),
            required_fields=["script"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )

        if not result:
            return []

        # 增加鲁棒性
        if isinstance(result, list):
            result = {"script": result}
        elif isinstance(result, dict) and "script" not in result and "scene_id" in result:
            result = {"script": [result]}

        try:
            validated = ScriptOutput.model_validate(result)
        except Exception as e:
            print(f"      ⚠️ 解析 JSON 失败: {e}")
            return []

        script_lines = []
        for i, item in enumerate(validated.script):
            if not item.visual_prompt:
                continue
            
            # 使用传入的起始编号重写 ID，防止不同块之间的 ID 冲突
            current_no = start_scene_no + i
            scene_id = f"SC_{current_no:03d}"
            shot_id = f"{scene_id}_SH01"

            script_lines.append(ScriptLine(
                scene_id=scene_id,
                shot_id=shot_id,
                role=item.role,
                speaker=item.speaker,
                text=item.text,
                emotion=item.emotion,
                visual_prompt=item.visual_prompt,
                motion_prompt=item.motion_prompt,
                camera=item.camera,
                estimated_duration=item.estimated_duration
            ))

        return script_lines

    async def _adapt_to_script_attempt(self, chapter: Chapter, blueprint: StoryBlueprint) -> Chapter:
        """单次分镜脚本拆分尝试"""
        system_prompt = generate_protocol_prompt(SCRIPT_ADAPTER_CORE, ScriptOutput)
        char_info = "\n".join([f"{c.name}: {c.appearance}" for c in blueprint.characters])

        # 限制输入正文长度，防止章节过长时 token 爆炸
        content_limit = 3000
        content_excerpt = chapter.content[:content_limit]
        if len(chapter.content) > content_limit:
            content_excerpt += f"\n\n[正文较长，以上为前{content_limit}字，后续省略]"

        # prompt = (
        #     f"请将小说章节《{chapter.title}》拆分为分镜脚本。\n"
        #     f"限制：整章最多生成 25 个分镜行，每个分镜的 visual_prompt 必须用英文填写。\n\n"
        #     f"角色参考:\n{char_info}\n\n"
        #     f"章节正文:\n{content_excerpt}"
        # )

        prompt = (
            f"你是顶尖的视觉艺术家和分镜编剧。请将小说章节《{chapter.title}》拆分为极具画面感的【分镜脚本】。\n\n"
            f"【角色视觉参考】:\n{char_info}\n\n"
            f"【创作要求】:\n"
            f"1. 数量限制：整章生成 15-25 个分镜行。\n"
            f"2. visual_prompt 必须是详细的英文，请按此结构撰写：\n"
            f"   (Subject: 人物及姿态), (Action: 正在发生的动作), (Setting: 环境细节), (Lighting: 光影效果, 如 cinematic lighting, golden hour), (Composition: 构图方式, 如 rule of thirds, low angle), (Mood: 氛围描述)。\n"
            f"3. 视觉质量：必须包含材质细节（如 skin texture, metallic shine）、环境特效（如 floating particles, mist）以及电影感描述。\n"
            f"4. 角色一致性：请在每个涉及角色的分镜中，根据【角色视觉参考】重复提及角色的关键外貌特征。\n"
            f"5. 镜头运动：在 motion_prompt 中精确描述摄像机如何移动，以增强动态感。\n\n"
            f"【本章正文】:\n{content_excerpt}"
        )

        result, _ = await robust_json_generate(
            llm_client=self.llm_client,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=get_llm_max_tokens("script"),
            required_fields=["script"],
            max_attempts=3,
            response_format={"type": "json_object"}
        )

        if not result:
            raise ValueError("分镜脚本生成失败")

        # 增加鲁棒性：如果 result 是 list，说明 LLM 直接输出了数组
        if isinstance(result, list):
            result = {"script": result}
        elif isinstance(result, dict) and "script" not in result and "scene_id" in result:
            result = {"script": [result]}

        validated = ScriptOutput.model_validate(result)

        script_lines = []
        skipped = 0
        for item in validated.script:
            # 过滤掉因截断产生的垃圾行（visual_prompt 为空代表该行不完整）
            if not item.visual_prompt:
                skipped += 1
                continue
            script_lines.append(ScriptLine(
                scene_id=item.scene_id,
                shot_id=item.shot_id,
                role=item.role,
                speaker=item.speaker,
                text=item.text,
                emotion=item.emotion,
                visual_prompt=item.visual_prompt,
                motion_prompt=item.motion_prompt,
                camera=item.camera,
                estimated_duration=item.estimated_duration
            ))

        if skipped:
            print(f"      ⚠️ 过滤掉 {skipped} 个不完整分镜行（缺少 visual_prompt）")

        if not script_lines:
            raise ValueError(f"分镜脚本全部行无效（共{len(validated.script)}行均缺少 visual_prompt）")

        chapter.script_lines = script_lines
        print(f"      ✓ 成功生成 {len(script_lines)} 个分镜")
        return chapter


class NovelGenerationPipeline(PipelineStage):
    def __init__(self, llm_client=None, config=None):
        super().__init__("小说生成", config)
        self.generator = NovelGenerator(llm_client, config)
    def validate_input(self, input_data): return self.generator.validate_input(input_data)
    async def process(self, concept): return await self.generator.process(concept)


async def quick_generate_novel(title, genre="修仙", core_idea="", total_chapters=3, llm_client=None):
    concept = NovelConcept(title=title, genre=genre, style="爽文", core_idea=core_idea, total_chapters=total_chapters, target_word_count=5000)
    if not llm_client: llm_client = NVIDIA_NIM_Client()
    generator = NovelGenerator(llm_client)
    return await generator.process(concept)


async def test_novel_generator():
    from core.llm_client import MockLLMClient
    mock_client = MockLLMClient()
    concept = NovelConcept(title="测试小说", genre="科幻", core_idea="AI统治世界", total_chapters=1, target_word_count=1000)
    generator = NovelGenerator(mock_client)
    novel = await generator.process(concept)
    print(f"测试完成: {novel.metadata['title']}")


if __name__ == "__main__":
    asyncio.run(test_novel_generator())

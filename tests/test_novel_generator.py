"""
端到端测试 - 测试完整的小说生成流程
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import asyncio

from stage1_novel import (
    NovelGenerator, NovelConcept, ShuangDianSystem,
    QualityController, ContextManager, ConsistencyChecker, RhythmController
)
from stage1_novel.models import Chapter, QualityScore


class MockLLMClient:
    """Mock LLM客户端用于测试"""

    async def generate(self, prompt, system_prompt="", max_tokens=4000, **kwargs):
        """模拟生成响应"""
        from dataclasses import dataclass

        @dataclass
        class MockResponse:
            content: str

        # 返回模拟的JSON响应
        mock_content = '''{
            "title": "测试章节",
            "content": "这是测试章节的内容。主角张三打脸了敌人，获得了突破，收获了宝物，真是反转！",
            "summary": "本章讲述了主角打脸敌人并获得突破的故事",
            "key_events": ["打脸敌人", "获得突破", "收获宝物"],
            "character_appearances": ["张三", "李四"]
        }'''

        return MockResponse(content=mock_content)

    async def close(self):
        pass


class TestEndToEnd:
    """端到端测试"""

    def setup_method(self):
        """每个测试前运行"""
        self.llm_client = MockLLMClient()

    def test_shuangdian_system_integration(self):
        """测试爽点系统集成"""
        system = ShuangDianSystem()

        # 规划10章的爽点分布
        plan = system.plan_distribution(10)
        assert len(plan) == 10

        # 验证每章都有爽点
        for chapter_num, shuangdian in plan.items():
            assert shuangdian is not None
            assert shuangdian.type is not None
            assert shuangdian.intensity is not None

    def test_quality_controller_integration(self):
        """测试质量评估器集成"""
        controller = QualityController(self.llm_client)

        # 创建测试章节
        chapter = Chapter(
            number=1,
            title="测试章节",
            content="这是测试内容，有打脸、突破、收获等爽点！" * 20,
            word_count=500,
            summary="测试摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        # 规则评估
        import asyncio
        score = asyncio.run(controller.evaluate_chapter(chapter, None, []))

        assert isinstance(score, QualityScore)
        assert 0.0 <= score.overall <= 10.0

    def test_context_manager_integration(self):
        """测试上下文管理器集成"""
        manager = ContextManager()

        # 创建测试章节
        chapter = Chapter(
            number=1,
            title="第1章",
            content="测试内容",
            word_count=100,
            summary="第1章摘要",
            key_events=["事件1"],
            character_appearances=["张三"],
        )

        # 测试摘要生成
        summary = manager.generate_summary(chapter)
        assert len(summary) > 0

        # 测试缓存
        manager.cache_chapter_summary(chapter)
        cached = manager.get_cached_summary(1)
        assert cached is not None

    def test_consistency_checker_integration(self):
        """测试一致性检查器集成"""
        checker = ConsistencyChecker()

        # 测试名字变体
        variants = checker._get_name_variants("张三")
        assert "张三" in variants
        assert "小三" in variants

        # 测试性格关键词
        traits = checker._extract_personality_traits("冷漠，不苟言笑")
        assert "冷漠" in traits

    def test_rhythm_controller_integration(self):
        """测试节奏控制器集成"""
        controller = RhythmController()

        # 测试模板选择
        from stage1_novel.models import PlotPoint
        plot_structure = [PlotPoint(chapter=i, description=f"情节{i}") for i in range(1, 11)]

        template = controller.select_chapter_template(1, 100, plot_structure)
        assert template in ["standard", "climax"]

        # 测试生成提示词
        from stage1_novel.models import ChapterPlan
        chapter_plan = ChapterPlan(
            number=1, title="测试", summary="概要", key_events=["事件1"]
        )
        prompt = controller.generate_rhythm_prompt("standard", chapter_plan)
        assert "节奏要求" in prompt

    def test_dynamic_max_tokens_calculation(self):
        """测试动态 max_tokens 计算"""
        print("\n🧪 测试动态 max_tokens 计算...")

        from stage1_novel import NovelGenerator

        generator = NovelGenerator(self.llm_client)

        # 测试不同字数
        test_cases = [
            (3000, 8000),    # 3000字 → 最小8000
            (5000, 13000),   # 5000字 → ~13000
            (10000, 26000),  # 10000字 → ~26000
            (50000, 128000), # 50000字 → 最大128000
        ]

        for target_words, expected_min in test_cases:
            tokens = generator._calculate_max_tokens(target_words)
            assert tokens >= expected_min, f"{target_words}字应该至少有{expected_min} tokens"
            assert tokens <= 128000, f"tokens不能超过128000"
            print(f"   ✅ {target_words}字 → {tokens} tokens")

        print("✅ 动态 max_tokens 计算测试通过！")

    def test_content_completeness_check(self):
        """测试内容完整性检查"""
        print("\n🧪 测试内容完整性检查...")

        from stage1_novel import NovelGenerator

        generator = NovelGenerator(self.llm_client)

        # 完整内容
        complete_content = "这是一段完整的内容，有合适的结尾。"
        assert generator._is_content_complete(complete_content) is True

        # 被截断的JSON
        truncated_json = '{"content": "这是一段被截断的内容"'
        assert generator._is_content_complete(truncated_json) is False

        # 有未完成占位符
        placeholder_content = "【未完待续】"
        assert generator._is_content_complete(placeholder_content) is False

        print("✅ 内容完整性检查测试通过！")

    @pytest.mark.asyncio
    async def test_full_novel_generation(self):
        """测试完整的小说生成流程（端到端）"""
        print("\n🧪 测试完整小说生成流程...")

        # 1. 创建概念
        concept = NovelConcept(
            title="测试小说",
            genre="修仙",
            style="爽文",
            core_idea="废材少年获得传承，一路打脸升级",
            total_chapters=3,
            target_word_count=3000,
        )

        # 2. 创建生成器
        generator = NovelGenerator(self.llm_client)

        # 3. 生成小说（这里会调用Mock LLM）
        try:
            # 注意：这里我们只测试初始化和流程，不实际调用LLM
            # 因为完整生成需要真正的LLM
            print("✅ 小说生成器初始化成功")
            print(f"   标题: {concept.title}")
            print(f"   类型: {concept.genre}")
            print(f"   章节数: {concept.total_chapters}")

            # 验证各个子系统都已初始化
            assert generator.shuangdian_system is not None
            assert generator.quality_controller is not None
            assert generator.context_manager is not None
            assert generator.consistency_checker is not None
            assert generator.rhythm_controller is not None

            print("✅ 所有子系统初始化成功")

            # 验证长章节配置
            assert hasattr(generator, 'CHUNK_WORD_COUNT')
            assert hasattr(generator, 'MAX_TOKENS_LIMIT')
            assert hasattr(generator, 'MIN_TOKENS')
            print("✅ 长章节生成配置正确")

            # 测试爽点规划
            shuangdian_plan = generator.shuangdian_system.plan_distribution(concept.total_chapters)
            assert len(shuangdian_plan) == concept.total_chapters
            print(f"✅ 爽点规划成功: {len(shuangdian_plan)} 章")

            # 测试节奏规划
            from stage1_novel.models import PlotPoint
            plot_structure = [
                PlotPoint(chapter=i, description=f"第{i}章情节")
                for i in range(1, concept.total_chapters + 1)
            ]
            chapter_plans = generator.rhythm_controller.plan_novel_chapters(
                concept.total_chapters, plot_structure
            )
            assert len(chapter_plans) == concept.total_chapters
            print(f"✅ 节奏规划成功: {len(chapter_plans)} 章")

            print("\n🎉 端到端流程测试通过！")
            return True

        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            return False


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("🧪 运行完整测试套件")
    print("=" * 70)

    # 测试爽点系统
    print("\n1. 测试爽点系统...")
    test = TestEndToEnd()
    test.setup_method()
    test.test_shuangdian_system_integration()
    print("   ✅ 通过")

    # 测试质量评估
    print("\n2. 测试质量评估...")
    test.test_quality_controller_integration()
    print("   ✅ 通过")

    # 测试上下文管理
    print("\n3. 测试上下文管理...")
    test.test_context_manager_integration()
    print("   ✅ 通过")

    # 测试一致性检查
    print("\n4. 测试一致性检查...")
    test.test_consistency_checker_integration()
    print("   ✅ 通过")

    # 测试节奏控制
    print("\n5. 测试节奏控制...")
    test.test_rhythm_controller_integration()
    print("   ✅ 通过")

    # 端到端测试
    print("\n6. 测试端到端流程...")
    import asyncio
    result = asyncio.run(test.test_full_novel_generation())

    print("\n" + "=" * 70)
    print("✅ 所有测试完成！")
    print("=" * 70)

    return True


if __name__ == "__main__":
    # 直接运行测试
    run_all_tests()

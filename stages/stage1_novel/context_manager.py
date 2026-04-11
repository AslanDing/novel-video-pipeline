"""
上下文管理器 - 管理长篇小说的上下文
"""
from typing import List, Optional

from stages.stage1_novel.models import Chapter, StoryBlueprint, NovelConcept


class ContextManager:
    """长篇小说上下文管理"""

    def __init__(self, max_context_tokens: int = 8000):
        self.max_tokens = max_context_tokens
        self.chapters_summary = {}

    def build_chapter_context(
        self,
        current_chapter: int,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> str:
        """构建生成单章所需的上下文"""
        context_parts = []

        # 1. 核心设定（始终保留）
        context_parts.append("【核心设定】")
        context_parts.append(f"世界观: {blueprint.world_building.setting[:200]}")
        context_parts.append(f"力量体系: {blueprint.world_building.power_system[:200]}")
        context_parts.append("")

        # 2. 角色档案（始终保留）
        context_parts.append("【主要角色】")
        for char in blueprint.characters[:5]:
            context_parts.append(f"- {char.name}: {char.description[:100]}")
            context_parts.append(f"  性格: {char.personality[:50]}")
        context_parts.append("")

        # 3. 整体大纲（始终保留）
        context_parts.append("【主线剧情】")
        for plot in blueprint.plot_structure[:10]:
            context_parts.append(f"第{plot.chapter}章: {plot.description[:80]}")
        context_parts.append("")

        # 4. 前文摘要（动态，最近3-5章）
        if previous_chapters:
            context_parts.append("【前文摘要】")
            recent_chapters = previous_chapters[-3:]
            for ch in recent_chapters:
                context_parts.append(f"第{ch.number}章《{ch.title}》: {ch.summary[:150]}")
            context_parts.append("")

        return "\n".join(context_parts)

    def generate_summary(self, chapter: Chapter) -> str:
        """生成章节摘要（用于后续章节的上下文）"""
        # 如果已有摘要，直接返回
        if chapter.summary and len(chapter.summary) > 20:
            return chapter.summary

        # 简单的摘要生成：取开头和结尾
        content = chapter.content
        if len(content) <= 200:
            return content

        start = content[:100]
        end = content[-100:]
        return f"{start}...{end}"

    def summarize_previous_chapters(
        self,
        chapters: List[Chapter],
        max_tokens: int = 2000
    ) -> str:
        """压缩多章内容为摘要"""
        if not chapters:
            return ""

        summaries = []
        total_length = 0

        # 从最新章节开始
        for chapter in reversed(chapters):
            summary = self.generate_summary(chapter)
            if total_length + len(summary) > max_tokens:
                break
            summaries.insert(0, f"第{chapter.number}章: {summary}")
            total_length += len(summary)

        return "\n".join(summaries)

    def cache_chapter_summary(self, chapter: Chapter):
        """缓存章节摘要"""
        self.chapters_summary[chapter.number] = self.generate_summary(chapter)

    def get_cached_summary(self, chapter_number: int) -> Optional[str]:
        """获取缓存的章节摘要"""
        return self.chapters_summary.get(chapter_number)

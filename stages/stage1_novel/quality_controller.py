"""
质量评估器 - 评估和控制章节质量
"""
import json
import re
from typing import List, Optional

from stages.stage1_novel.models import (
    Chapter, StoryBlueprint, QualityScore
)


class QualityController:
    """章节质量评估与控制"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    async def evaluate_chapter(
        self,
        chapter: Chapter,
        blueprint: Optional[StoryBlueprint] = None,
        previous_chapters: Optional[List[Chapter]] = None
    ) -> QualityScore:
        """
        评估章节质量
        返回: 评分 + 问题列表
        """
        issues = []

        # 1. 检查爽点密度
        shuangdian_score = await self.check_shuangdian(chapter)

        # 2. 检查连贯性
        coherence_score = await self.check_coherence(chapter, previous_chapters or [])

        # 3. 检查可读性
        readability_score = self.check_readability(chapter)

        # 4. 检查完整性
        completeness_score = self.check_completeness(chapter)

        # 5. 检查长度
        length_score, length_issue = self.check_length(chapter)
        if length_issue:
            issues.append(length_issue)

        # 计算总评分（加权平均）
        overall = (
            shuangdian_score * 0.25 +
            coherence_score * 0.20 +
            readability_score * 0.15 +
            completeness_score * 0.15 +
            length_score * 0.25
        )

        # 收集问题
        if shuangdian_score < 5:
            issues.append("爽点不够明显，需要增加打脸/升级/收获/反转等元素")
        if coherence_score < 6:
            issues.append("与前文连贯性需要加强")
        if readability_score < 6:
            issues.append("可读性需要提高，注意语言流畅度")
        if completeness_score < 7:
            issues.append("章节不够完整，需要有头有尾")

        return QualityScore(
            overall=round(overall, 1),
            shuangdian_score=round(shuangdian_score, 1),
            coherence_score=round(coherence_score, 1),
            readability_score=round(readability_score, 1),
            issues=issues
        )

    async def check_coherence(
        self,
        chapter: Chapter,
        previous_chapters: List[Chapter]
    ) -> float:
        """
        检查与前文的连贯性
        检测: 人名矛盾、时间线混乱、设定冲突
        """
        if not previous_chapters:
            return 8.0  # 第一章没有前文

        score = 10.0
        # 简化版连贯性检查
        # 检查角色名字是否一致
        prev_chars = set()
        for prev in previous_chapters:
            prev_chars.update(prev.character_appearances)

        current_chars = set(chapter.character_appearances)

        # 如果完全没有出现过任何前文角色，扣分
        if prev_chars and current_chars and prev_chars.isdisjoint(current_chars):
            score -= 2.0

        # 检查内容是否提到前文关键事件
        has_references = False
        for prev in previous_chapters[-2:]:
            for event in prev.key_events:
                # 简化检查：关键词匹配
                keywords = event.split()[:3]
                if any(kw in chapter.content for kw in keywords):
                    has_references = True
                    break

        if not has_references and len(previous_chapters) >= 2:
            score -= 1.5

        return max(0.0, min(10.0, score))

    async def check_shuangdian(self, chapter: Chapter) -> float:
        """
        检查爽点密度
        标准: 每章至少1个明确爽点
        """
        shuangdian_keywords = {
            "打脸": ["打脸", "震惊", "傻眼", "难以置信", "没想到", "居然"],
            "升级": ["突破", "觉醒", "升级", "进阶", "更强大", "实力大增"],
            "收获": ["获得", "得到", "发现", "宝藏", "传承", "空间", "宝物"],
            "反转": ["反转", "真相", "揭露", "原来", "竟然", "没想到"],
        }

        total_matches = 0
        for category, keywords in shuangdian_keywords.items():
            matches = sum(1 for kw in keywords if kw in chapter.content)
            total_matches += matches

        # 根据匹配数评分
        if total_matches >= 8:
            return 10.0
        elif total_matches >= 5:
            return 8.0
        elif total_matches >= 3:
            return 6.0
        elif total_matches >= 1:
            return 4.0
        else:
            return 2.0

    def check_readability(self, chapter: Chapter) -> float:
        """检查可读性"""
        score = 10.0
        content = chapter.content

        # 检查段落长度
        paragraphs = content.split('\n\n')
        avg_paragraph_len = sum(len(p) for p in paragraphs) / max(1, len(paragraphs))

        if avg_paragraph_len > 500:
            score -= 1.5  # 段落过长
        elif avg_paragraph_len < 50:
            score -= 1.0  # 段落过短

        # 检查句子长度
        sentences = re.split(r'[。！？!?]', content)
        avg_sentence_len = sum(len(s) for s in sentences) / max(1, len(sentences))

        if avg_sentence_len > 80:
            score -= 1.0

        # 检查是否有足够的对话
        dialogue_count = content.count('"') + content.count('"') + content.count('"')
        if dialogue_count < 5:
            score -= 1.0

        return max(0.0, min(10.0, score))

    def check_completeness(self, chapter: Chapter) -> float:
        """检查完整性"""
        score = 10.0
        content = chapter.content

        # 检查是否有标题
        if not chapter.title:
            score -= 2.0

        # 检查字数
        if chapter.word_count < 2000:
            score -= 4.0
        elif chapter.word_count < 3000:
            score -= 2.0

        # 检查是否有摘要
        if not chapter.summary or len(chapter.summary) < 20:
            score -= 1.0

        # 检查是否有关键事件
        if not chapter.key_events:
            score -= 1.5

        return max(0.0, min(10.0, score))

    def check_length(self, chapter: Chapter, target_words: int = 5000) -> tuple[float, Optional[str]]:
        """检查章节长度"""
        word_count = chapter.word_count
        issue = None

        # 计算得分
        if target_words * 0.8 <= word_count <= target_words * 1.2:
            score = 10.0
        elif target_words * 0.6 <= word_count <= target_words * 1.4:
            score = 8.0
        elif target_words * 0.5 <= word_count <= target_words * 1.5:
            score = 6.0
        else:
            score = 4.0
            if word_count < target_words * 0.5:
                issue = f"章节字数偏少 ({word_count}字，目标{target_words}字)"
            else:
                issue = f"章节字数偏多 ({word_count}字，目标{target_words}字)"

        return score, issue

    async def rewrite_chapter(
        self,
        chapter: Chapter,
        issues: List[str],
        concept=None
    ) -> Chapter:
        """
        重写问题章节
        针对issues中列出的问题进行修复（尤其是字数不足的扩写）
        """
        if not self.llm_client:
            return chapter

        target_words = getattr(concept, 'target_word_count', 5000) if concept else 5000
        print(f"   🔧 正在重写第{chapter.number}章（目标{target_words}字），修复: {issues[:1]}...")

        system_prompt = (
            "你是一位顶级网文大神兼专业小说编辑。你的任务是将一篇较短的章节扩展为完整、丰富的长篇内容。\n"
            "要求：\n"
            "1. 保持原有核心情节和人物设定\n"
            "2. 大幅展开每个场景，增加对话、心理活动、环境描写和动作细节\n"
            "3. 不要用总结式语言跳过情节，每个场景都要完整呈现\n"
            "4. 风格保持爽文节奏，但内容必须丰满"
        )

        prompt = (
            f"请将以下章节扩展改写，目标字数: {target_words}字左右\n\n"
            f"章节标题: {chapter.title}\n"
            f"当前内容（需要扩展）:\n{chapter.content}\n\n"
            f"需要改进的问题:\n"
            + "\n".join(f"- {issue}" for issue in issues)
            + f"\n\n请输出扩展后的完整章节（JSON格式）:\n"
            + '{"title": "章节标题", "content": "扩展后的完整正文内容", '
            + '"summary": "本章摘要", "key_events": ["关键事件1", "事件2"], '
            + '"character_appearances": ["角色1", "角色2"]}'
        )

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=target_words * 3,  # 给足 token 支持扩写
            )

            # 解析JSON
            json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response.content)

            new_content = data.get("content", chapter.content)
            print(f"   ✓ 重写完成: {chapter.word_count}字 → {len(new_content)}字")
            return Chapter(
                number=chapter.number,
                title=data.get("title", chapter.title),
                content=new_content,
                word_count=len(new_content),
                summary=data.get("summary", chapter.summary),
                key_events=data.get("key_events", chapter.key_events),
                character_appearances=data.get("character_appearances", chapter.character_appearances),
            )

        except Exception as e:
            print(f"   ⚠️  重写失败: {e}，返回原章节")
            return chapter

    async def evaluate_chapter_with_llm(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> QualityScore:
        """使用LLM进行深度质量评估"""
        if not self.llm_client:
            # 没有LLM客户端，退回到规则评估
            return await self.evaluate_chapter(chapter, blueprint, previous_chapters)

        prompt = self._build_llm_quality_prompt(chapter, blueprint, previous_chapters)

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是一位专业的小说编辑和评论家。请客观评估小说章节的质量。",
                max_tokens=2000,
            )

            return self._parse_llm_response(response.content, chapter)

        except Exception as e:
            print(f"   ⚠️  LLM评估失败: {e}，使用规则评估")
            return await self.evaluate_chapter(chapter, blueprint, previous_chapters)

    def _build_llm_quality_prompt(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        previous_chapters: List[Chapter]
    ) -> str:
        """构建LLM质量评估提示词"""
        # 构建前文摘要
        prev_summary = ""
        if previous_chapters:
            prev_summary = "前文摘要:\n"
            for ch in previous_chapters[-2:]:
                prev_summary += f"第{ch.number}章《{ch.title}》: {ch.summary[:100]}\n"

        # 构建角色信息
        chars_info = "主要角色:\n"
        for char in blueprint.characters[:3]:
            chars_info += f"- {char.name}: {char.personality[:50]}\n"

        return f"""请评估以下小说章节的质量。

            【基本信息】
            章节标题: {chapter.title}
            章节字数: {chapter.word_count}

            【故事背景】
            {chars_info}

            {prev_summary}

            【本章内容】
            {chapter.content[:5000]}...

            请从以下维度进行评估(0-10分):
            1. 爽点密度(30%): 是否有明显的爽点(打脸/升级/收获/反转)
            2. 连贯性(25%): 情节是否流畅,与前文是否一致
            3. 可读性(20%): 语言是否通顺,是否有语法错误
            4. 完整性(15%): 情节是否完整,有头有尾
            5. 长度达标(10%): 字数是否合适

            请以JSON格式输出:
            {{
                "overall": 8.5,
                "shuangdian_score": 7.0,
                "coherence_score": 9.0,
                "readability_score": 8.5,
                "completeness_score": 8.0,
                "length_score": 9.0,
                "issues": ["问题1具体描述", "问题2具体描述"]
            }}
            """

    def _parse_llm_response(self, response_content: str, chapter: Chapter) -> QualityScore:
        """解析LLM的评估响应"""
        import json
        import re

        try:
            # 提取JSON
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response_content)

            # 计算总分（加权平均）
            overall = data.get("overall", 7.0)
            shuangdian_score = data.get("shuangdian_score", 7.0)
            coherence_score = data.get("coherence_score", 7.0)
            readability_score = data.get("readability_score", 7.0)
            issues = data.get("issues", [])

            return QualityScore(
                overall=round(float(overall), 1),
                shuangdian_score=round(float(shuangdian_score), 1),
                coherence_score=round(float(coherence_score), 1),
                readability_score=round(float(readability_score), 1),
                issues=issues,
            )

        except Exception as e:
            print(f"   ⚠️  解析LLM响应失败: {e}")
            # 返回默认评分
            return QualityScore(
                overall=7.0,
                shuangdian_score=7.0,
                coherence_score=7.0,
                readability_score=7.0,
                issues=["LLM评估解析失败"],
            )

    def _build_quality_check_prompt(self, chapter: Chapter) -> str:
        """构建质量检查提示词（供LLM使用）"""
        return f"""请评估以下小说章节的质量:

                章节标题: {chapter.title}
                章节内容:
                {chapter.content}

                请从以下维度评分(0-10):
                1. 爽点密度: 是否有明显的爽点(打脸/升级/收获/反转)
                2. 连贯性: 情节是否流畅,与前文是否一致
                3. 可读性: 语言是否通顺,是否有语法错误
                4. 完整性: 情节是否完整,有头有尾

                请输出JSON格式:
                {{
                    "overall": 8.5,
                    "shuangdian_score": 7.0,
                    "coherence_score": 9.0,
                    "readability_score": 8.5,
                    "issues": ["问题1", "问题2"]
                }}
                """

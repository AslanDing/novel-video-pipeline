"""
Script Generator - 分镜脚本生成器

将章节内容拆分为分镜脚本（ScriptLine），用于后续图像生成和TTS。

Stage 1 → Stage 2/3 的关键数据桥梁。
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import asdict
import asyncio

import sys

sys.path.append(str(Path(__file__).parent.parent))

from stages.stage1_novel.models import Chapter, StoryBlueprint, Character, ScriptLine
from core.llm_client import NVIDIA_NIM_Client
from config.settings import load_prompts


class ScriptGenerator:
    """
    分镜脚本生成器

    将章节内容智能拆分为多个镜头（shot），每个镜头包含：
    - scene_id: 场景ID
    - shot_id: 镜头ID
    - role: dialogue 或 narrator
    - speaker: 说话人
    - text: 朗读文本
    - emotion: 情感标签
    - visual_prompt: 图像生成提示词
    - motion_prompt: 镜头运动
    - camera: 景别
    - estimated_duration: 预估时长
    """

    def __init__(self, llm_client=None, prompts: Dict = None):
        if llm_client is None:
            import os
            from core.llm_client import NVIDIA_NIM_Client, MockLLMClient
            if os.environ.get("NVIDIA_NIM_API_KEY"):
                self.llm_client = NVIDIA_NIM_Client()
            else:
                self.llm_client = MockLLMClient()
        else:
            self.llm_client = llm_client
        self.prompts = prompts or load_prompts().get("stage1", {})
        self.shot_counter = 0

    async def generate_script_lines(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        shots_per_chapter: int = 8,
    ) -> List[ScriptLine]:
        """
        生成章节的分镜脚本

        Args:
            chapter: 章节对象
            blueprint: 故事蓝图
            shots_per_chapter: 每章生成的镜头数

        Returns:
            分镜脚本行列表
        """
        print(f"   🎬 正在为第{chapter.number}章生成分镜脚本...")

        # 构建角色名称列表用于匹配
        character_names = [c.name for c in blueprint.characters]

        # 使用 LLM 分析章节内容，生成分镜
        shots = await self._extract_shots_with_llm(
            chapter, blueprint, shots_per_chapter
        )

        # 如果 LLM 失败，回退到简单分段
        if not shots:
            shots = self._simple_segment(chapter.content, character_names)

        # 转换为 ScriptLine 对象
        script_lines = []
        self.shot_counter = 0

        for i, shot in enumerate(shots):
            scene_id = f"SC{chapter.number:02d}"
            shot_id = f"{scene_id}_SH{i + 1:02d}"

            script_line = ScriptLine(
                scene_id=scene_id,
                shot_id=shot_id,
                role=shot.get("role", "dialogue"),
                speaker=shot.get("speaker", "narrator"),
                text=shot.get("text", ""),
                emotion=shot.get("emotion", "neutral"),
                visual_prompt=shot.get("visual_prompt", ""),
                motion_prompt=shot.get("motion_prompt", ""),
                camera=shot.get("camera", "medium shot"),
                estimated_duration=shot.get("estimated_duration", 3.0),
            )
            script_lines.append(script_line)

        print(f"      ✓ 生成了 {len(script_lines)} 个镜头")
        return script_lines

    async def _extract_shots_with_llm(
        self,
        chapter: Chapter,
        blueprint: StoryBlueprint,
        target_shots: int,
    ) -> List[Dict]:
        """使用 LLM 提取分镜"""
        # 构建角色描述用于提示
        characters_info = "\n".join(
            [f"- {c.name}: {c.description[:50]}..." for c in blueprint.characters[:5]]
        )

        prompt = f"""请分析以下小说章节内容，将其拆分为{target_shots}个分镜镜头。

章节标题: {chapter.title}
章节内容:
{chapter.content[:4000]}...

角色列表:
{characters_info}

请输出JSON格式的分镜列表，每个分镜包含:
- role: "dialogue" 或 "narrator"
- speaker: 说话人名称（旁白填 narrator）
- text: 需要朗读的文本内容（尽量完整，不要截断）
- emotion: 情感标签 (neutral, happy, sad, angry, fearful, excited, calm)
- visual_prompt: 画面描述（英文，用于AI图像生成），包含场景、人物、氛围
- motion_prompt: 镜头运动描述 (static, slow push in, pan left, tilt up 等)
- camera: 景别 (wide shot, medium shot, close-up, extreme close-up)
- estimated_duration: 预估朗读时长（秒）

输出格式:
{{"shots": [{{...}}, {{...}}, ...]}}

要求:
1. 每段对话或旁白作为一个独立镜头
2. visual_prompt 要有画面感，描述场景氛围
3. 镜头要有变化（景别、运动），不要全是静态中景
4. text 要完整保留原文对话和叙述"""

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是一个专业的小说分镜师，擅长将文字内容转化为视觉分镜脚本。",
                max_tokens=4000,
            )

            if response and response.content:
                content = response.content.strip()
                # 提取 JSON
                shots = self._extract_json(content)
                if shots and "shots" in shots:
                    return shots["shots"]

        except Exception as e:
            print(f"      ⚠️  LLM 分镜提取失败: {e}")

        return []

    def _extract_json(self, content: str) -> Optional[Dict]:
        """从文本中提取 JSON"""
        # 尝试 ```json 格式
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _simple_segment(
        self,
        content: str,
        character_names: List[str],
    ) -> List[Dict]:
        """简单分段（当 LLM 失败时使用）"""
        # 按段落分割
        paragraphs = content.split("\n\n")
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        shots = []
        current_shot = None

        for para in paragraphs:
            # 判断是对话还是旁白
            dialogue_match = re.search(r'["""](.+?)["""]', para)
            is_dialogue = dialogue_match is not None

            if is_dialogue:
                # 提取对话内容
                speaker = self._extract_speaker(para, character_names)
                text = dialogue_match.group(1) if dialogue_match else para

                current_shot = {
                    "role": "dialogue",
                    "speaker": speaker,
                    "text": text,
                    "emotion": self._detect_emotion(text),
                    "visual_prompt": self._generate_visual_prompt(speaker, "dialogue"),
                    "motion_prompt": "static",
                    "camera": "medium shot",
                    "estimated_duration": len(text) / 5.0,  # 约 5 字/秒
                }
            else:
                # 旁白
                current_shot = {
                    "role": "narrator",
                    "speaker": "narrator",
                    "text": para[:200],  # 限制长度
                    "emotion": "neutral",
                    "visual_prompt": self._generate_visual_prompt("", "narrator"),
                    "motion_prompt": "slow push in",
                    "camera": "wide shot",
                    "estimated_duration": len(para) / 5.0,
                }

            if current_shot:
                shots.append(current_shot)

            # 限制镜头数量
            if len(shots) >= 10:
                break

        return shots

    def _extract_speaker(self, para: str, character_names: List[str]) -> str:
        """提取说话人"""
        # 尝试多种模式
        patterns = [
            r'^([^""：:：\s]+)["""](.+)',
            r'["""]?(.*?)["""]?\s*(?:说道|问道|答道|喊道|笑着说|冷笑道)',
            r'^\s*([^""]+)\s+["""](.+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, para)
            if match:
                potential_speaker = match.group(1).strip()
                # 检查是否在角色列表中
                for name in character_names:
                    if name in potential_speaker:
                        return name

        # 回退：检查是否包含角色名
        for name in character_names:
            if name in para:
                return name

        return "narrator"

    def _detect_emotion(self, text: str) -> str:
        """检测情感"""
        text_lower = text.lower()

        emotion_keywords = {
            "happy": ["开心", "高兴", "快乐", "笑", "哈哈"],
            "sad": ["哭", "悲伤", "难过", "痛苦", "伤心"],
            "angry": ["怒", "气", "恨", "愤怒", "咬牙"],
            "fearful": ["怕", "恐惧", "害怕", "颤抖"],
            "excited": ["啊！", "哇！", "太棒", "激动"],
            "calm": ["平静", "淡淡", "轻声", "从容"],
        }

        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return emotion

        return "neutral"

    def _generate_visual_prompt(self, speaker: str, role: str) -> str:
        """生成简单的视觉提示词"""
        if role == "narrator":
            return "narrative scene, atmospheric, cinematic lighting, fantasy world"
        else:
            return (
                f"character {speaker}, cinematic, dramatic lighting, fantasy art style"
            )


async def generate_chapter_scripts(
    chapter: Chapter,
    blueprint: StoryBlueprint,
    output_path: str,
    llm_client=None,
) -> List[ScriptLine]:
    """
    为单章生成分镜脚本并保存

    Args:
        chapter: 章节对象
        blueprint: 故事蓝图
        output_path: 输出 JSONL 路径
        llm_client: LLM 客户端

    Returns:
        生成的 ScriptLine 列表
    """
    generator = ScriptGenerator(llm_client)
    script_lines = await generator.generate_script_lines(chapter, blueprint)

    # 保存到 JSONL
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for line in script_lines:
            f.write(json.dumps(line.to_dict(), ensure_ascii=False) + "\n")

    return script_lines


def load_script_lines_from_jsonl(jsonl_path: str) -> List[ScriptLine]:
    """从 JSONL 文件加载 ScriptLine 列表"""
    if not Path(jsonl_path).exists():
        return []

    script_lines = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                script_lines.append(ScriptLine(**json.loads(line)))

    return script_lines

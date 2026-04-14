"""
图像生成预处理模块
负责场景提取和 prompt 构建的缓存管理
"""

import json
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import asdict

import sys
sys.path.append(str(Path(__file__).parent.parent))
from core.llm_client import NVIDIA_NIM_Client
from core.local_llm_client import get_local_llm_client
from core.logger import get_logger, setup_logger
from stages.stage1_novel.models import Novel, Chapter, Character, ScriptLine
from stages.stage1_novel.pydantic_models import ScriptOutput
from stages.stage1_novel.prompts.protocol_prompts import generate_protocol_prompt
from utils.streaming_json_generator import robust_json_generate
from config.settings import LOCAL_LLM_CONFIG, load_prompts, get_llm_max_tokens

# 初始化日志
logger = get_logger("preprocessor")


class Preprocessor:
    """
    场景预处理器
    负责从章节内容提取场景并构建 prompt，支持缓存
    """

    def __init__(self, config: Dict, novel: Novel, llm_client=None):
        self.config = config
        self.novel = novel
        
        # 允许外部传入 llm_client 或根据配置自动加载本地/云端
        if llm_client is not None:
            self.llm_client = llm_client
        elif LOCAL_LLM_CONFIG.get("enabled", False):
            provider = LOCAL_LLM_CONFIG.get("provider", "vllm")
            self.llm_client = get_local_llm_client(
                provider=provider,
                **LOCAL_LLM_CONFIG.get(provider, {}),
                temperature=LOCAL_LLM_CONFIG.get("temperature", 0.7),
                max_tokens=LOCAL_LLM_CONFIG.get("max_tokens", 4096)
            )
        else:
            self.llm_client = NVIDIA_NIM_Client()
            
        # 加载提示词
        self.prompts = load_prompts()
        self.stage2_prompts = self.prompts.get("stage2", {})
            
        self.translate_to_english = config.get("translate_to_english", True)

        # 缓存目录 - 智能判断 novel_dir 是否已经是具体的小说目录
        self.novel_dir = Path(config.get("novel_dir", "outputs/novels"))
        novel_title = self.novel.metadata.get("title", "")
        
        # 如果 novel_dir 还不包含小说标题，则追加
        if novel_title and novel_title not in self.novel_dir.name:
            self.novel_dir = self.novel_dir / novel_title

        self.cache_dir = self.novel_dir / "cache"
        self.scenes_cache_dir = self.cache_dir / "scenes"
        self.prompts_cache_dir = self.cache_dir / "prompts"

        # 确保目录存在
        self.scenes_cache_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"缓存目录: {self.cache_dir}")

    def get_scene_cache_path(self, chapter_number: int) -> Path:
        """获取场景缓存文件路径"""
        return self.scenes_cache_dir / f"chapter_{chapter_number:03d}.json"

    def get_prompt_cache_path(self, chapter_number: int, scene_number: int, image_index: int) -> Path:
        """获取 prompt 缓存文件路径"""
        return self.prompts_cache_dir / f"chapter_{chapter_number:03d}_scene_{scene_number:02d}_image_{image_index:02d}.json"

    def load_cached_scenes(self, chapter_number: int) -> Optional[List[Dict]]:
        """
        加载指定章节的场景缓存

        Returns:
            场景列表，如果缓存不存在则返回 None
        """
        cache_path = self.get_scene_cache_path(chapter_number)
        if not cache_path.exists():
            logger.debug(f"场景缓存不存在: {cache_path}")
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"加载场景缓存: 第{chapter_number}章, {len(data.get('scenes', []))}个场景")
            return data.get("scenes", [])
        except Exception as e:
            logger.error(f"加载场景缓存失败: {e}")
            return None

    def save_scene_cache(self, chapter_number: int, scenes: List[Dict]):
        """保存场景到缓存"""
        cache_path = self.get_scene_cache_path(chapter_number)

        cache_data = {
            "chapter_number": chapter_number,
            "novel_title": self.novel.metadata.get("title", ""),
            "generated_at": datetime.now().isoformat(),
            "scenes": scenes
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"保存场景缓存: 第{chapter_number}章")
        except Exception as e:
            logger.error(f"保存场景缓存失败: {e}")

    def load_cached_prompt(self, chapter_number: int, scene_number: int, image_index: int) -> Optional[Dict]:
        """
        加载指定场景的 prompt 缓存

        Returns:
            prompt 缓存数据，如果缓存不存在则返回 None
        """
        cache_path = self.get_prompt_cache_path(chapter_number, scene_number, image_index)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.error(f"加载 prompt 缓存失败: {e}")
            return None

    def save_prompt_cache(self, chapter_number: int, scene_number: int, image_index: int,
                          scene_data: Dict, prompt: str):
        """保存 prompt 到缓存"""
        cache_path = self.get_prompt_cache_path(chapter_number, scene_number, image_index)

        cache_data = {
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "image_index": image_index,
            "generated_at": datetime.now().isoformat(),
            "translate_to_english": self.translate_to_english,
            "scene_data": scene_data,
            "prompt": prompt
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"保存 prompt 缓存: 第{chapter_number}章 场景{scene_number}")
        except Exception as e:
            logger.error(f"保存 prompt 缓存失败: {e}")

    async def extract_scenes(self, chapter: Chapter, num_scenes: int, force_refresh: bool = False) -> List[Dict]:
        """
        提取场景（带缓存）

        Args:
            chapter: 章节对象
            num_scenes: 默认提取的场景数量（仅在无脚本且无缓存时作为LLM提示）
            force_refresh: 是否强制刷新缓存

        Returns:
            场景列表
        """
        # 1. 优先尝试从内存中的 script_lines 加载 (如果已在 run_stage2.py 中加载)
        if hasattr(chapter, 'script_lines') and chapter.script_lines:
            from stages.stage2_visual.script_adapter import ScriptAdapter
            adapter = ScriptAdapter(self.novel.metadata.get('title', ''), self.novel_dir / "data")
            script_scenes = adapter.get_shots_as_scenes([asdict(sl) if hasattr(sl, 'to_dict') else sl for sl in chapter.script_lines])
            if script_scenes:
                logger.info(f"从内存脚本加载场景: 第{chapter.number}章, 共{len(script_scenes)}个场景")
                return script_scenes

        # 2. 尝试从 script_x.jsonl 加载 (Stage 1 分段产出)
        script_scenes = await self._get_scenes_from_script(chapter.number)
        if script_scenes:
            logger.info(f"从脚本文件加载场景: 第{chapter.number}章, 共{len(script_scenes)}个场景")
            return script_scenes

        # 3. 检查已生成的缓存
        if not force_refresh:
            cached_scenes = self.load_cached_scenes(chapter.number)
            if cached_scenes:
                # 如果缓存存在，即使数量与 num_scenes 不符，也优先使用缓存的所有场景
                # 除非缓存数量明显不足（比如只有1个而需要更多）
                if len(cached_scenes) >= num_scenes:
                    return cached_scenes
                else:
                    logger.info(f"缓存场景不足 ({len(cached_scenes)} < {num_scenes}), 将重新提取")

        # 4. 使用 LLM 提取场景 (Fallback)
        logger.info(f"正在通过LLM提取第{chapter.number}章场景 (预期数量: {num_scenes})")
        scenes = await self._extract_scenes_from_llm(chapter, num_scenes)

        # 保存缓存
        self.save_scene_cache(chapter.number, scenes)

        return scenes

    async def _get_scenes_from_script(self, chapter_number: int) -> List[Dict]:
        """从 Stage 1 产出的 script_x.jsonl 读取场景"""
        try:
            from stages.stage2_visual.script_adapter import ScriptAdapter
            
            novel_title = self.novel.metadata.get('title', '')
            if not novel_title:
                return []
                
            data_dir = self.novel_dir / "data"
            if not data_dir.exists():
                return []
            
            adapter = ScriptAdapter(novel_title, data_dir)
            script_lines = adapter.load_script_lines(chapter_number)
            
            if not script_lines:
                return []
            
            # 使用按分镜展开的逻辑，为每个 shot 生成一个独立的配图结构
            scenes = adapter.get_shots_as_scenes(script_lines)
            return scenes
        except Exception as e:
            logger.debug(f"从脚本加载场景失败: {e}")
            return []

    async def _extract_scenes_from_llm(self, chapter: Chapter, num_scenes: int) -> List[Dict]:
        """
        从 LLM 提取场景 - 现在整合了 Stage 1 的脚本分拆逻辑
        """
        logger.info(f"   🎬 正在为第{chapter.number}章生成分镜脚本...")
        
        # 角色信息
        char_info = "\n".join([f"{c.name}: {c.appearance}" for c in self.novel.blueprint.characters])
        
        # 设定分块大小
        chars_per_chunk = 2500
        content = chapter.content
        chunks = [content[i:i + chars_per_chunk] for i in range(0, len(content), chars_per_chunk)]
        
        all_script_lines = []
        scene_counter = 1
        
        script_core = self.stage2_prompts.get("script_core", "你是一位专业的分镜编剧。")
        system_prompt = generate_protocol_prompt(script_core, ScriptOutput)
        task_template = self.stage2_prompts.get("script_adapter_task", "")

        for i, chunk_content in enumerate(chunks):
            part_desc = f"（第 {i+1}/{len(chunks)} 部分）" if len(chunks) > 1 else ""
            
            if task_template:
                prompt = task_template.format(
                    title=chapter.title,
                    part_desc=part_desc,
                    char_info=char_info,
                    start_no=scene_counter,
                    content=chunk_content
                )
            else:
                prompt = (
                    f"请将小说章节《{chapter.title}》的文本片段{part_desc}拆分为分镜脚本。\n\n"
                    f"【角色视觉参考】:\n{char_info}\n\n"
                    f"【创作要求】:\n"
                    f"1. 数量限制：此片段生成 5-10 个分镜行。\n"
                    f"2. visual_prompt 必须是英文。\n\n"
                    f"【小说文本片段】:\n{chunk_content}"
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

            if result and (isinstance(result, list) or "script" in result):
                script_data = result if isinstance(result, list) else result.get("script", [])
                for j, item in enumerate(script_data):
                    # 转换回 Dict 格式，兼容现有的 get_shots_as_scenes
                    all_script_lines.append({
                        "scene_id": f"SC_{scene_counter + j:03d}",
                        "shot_id": f"SC_{scene_counter + j:03d}_SH01",
                        "visual_prompt": item.get("visual_prompt", ""),
                        "emotion": item.get("emotion", "neutral"),
                        "camera": item.get("camera", "medium"),
                        "motion_prompt": item.get("motion_prompt", ""),
                        "text": item.get("text", ""),
                        "speaker": item.get("speaker", ""),
                        "estimated_duration": item.get("estimated_duration", 3.0)
                    })
                scene_counter += len(script_data)

        if not all_script_lines:
            logger.warning("LLM 未能生成任何脚本行，使用简单提取逻辑")
            return await self._extract_scenes_simple(chapter, num_scenes)

        # 使用 ScriptAdapter 的逻辑转换为场景格式
        from stages.stage2_visual.script_adapter import ScriptAdapter
        adapter = ScriptAdapter(self.novel.metadata.get('title', ''), self.novel_dir / "data")
        scenes = adapter.get_shots_as_scenes(all_script_lines)
        
        logger.info(f"      ✅ 分镜拆解完成，共 {len(scenes)} 个分镜")
        return scenes

    async def _extract_scenes_simple(self, chapter: Chapter, num_scenes: int) -> List[Dict]:
        """简单场景提取"""
        prompt = f"""请分析以下小说章节，提取{num_scenes}个最具画面感的关键场景。

            章节标题: {chapter.title}
            章节内容:
            {chapter.content[:3000]}...（后续省略）

            请输出以下JSON格式:
            [
                {{
                    "scene_number": 1,
                    "description": "场景的文字描述（用于图像生成prompt）",
                    "key_elements": ["元素1", "元素2"],
                    "characters_present": ["角色名1", "角色2"],
                    "mood": "场景氛围（如：紧张、壮丽、温馨等）",
                    "setting": "具体场景地点"
                }}
            ]"""

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是专业的视觉场景分析师，擅长从文字中提取画面感。",
                max_tokens=4000,
            )

            scenes = self._extract_json(response.content)
            return scenes[:num_scenes]
        except Exception as e:
            logger.error(f"场景提取失败: {e}")
            # 返回默认场景
            return [
                {
                    "scene_number": i,
                    "description": f"第{i+1}个关键场景",
                    "key_elements": ["主角"],
                    "characters_present": ["主角"],
                    "mood": "紧张",
                    "setting": "未知地点",
                }
                for i in range(num_scenes)
            ]

    async def build_prompt(self, scene_data: Dict, characters: List[Character],
                           chapter_number: int, scene_number: int, image_index: int,
                           force_refresh: bool = False) -> str:
        """
        构建 prompt（带缓存）
        """
        # 检查缓存
        if not force_refresh:
            cached = self.load_cached_prompt(chapter_number, scene_number, image_index)
            if cached and cached.get("prompt"):
                logger.debug(f"使用缓存 prompt: 第{chapter_number}章 场景{scene_number}")
                return cached["prompt"]

        logger.debug(f"正在构建第{chapter_number}章 场景{scene_number} 的 prompt...")
        
        # 1. 优先使用场景数据中已有的英文 visual_prompt
        # 这是 Stage 1 脚本适配器或新版 Preprocessor 生成的
        if scene_data.get('visual_prompt'):
            prompt = scene_data['visual_prompt']
            self.save_prompt_cache(chapter_number, scene_number, image_index, scene_data, prompt)
            return prompt

        # 2. 如果只有 description，则需要翻译/构建
        description = scene_data.get("description", "")
        setting = scene_data.get("setting", "")
        mood = scene_data.get("mood", "calm")

        # 获取角色详情
        char_details = []
        for char_name in scene_data.get("characters_present", []):
            char_obj = next((c for c in characters if c.name == char_name), None)
            if char_obj:
                char_details.append(f"{char_name}({char_obj.appearance})")
            else:
                char_details.append(char_name)

        if self.translate_to_english:
            prompt = await self._translate_description(description, setting, mood, char_details)
        else:
            prompt = f"{description}, {setting}, {mood}, {', '.join(char_details)}"

        # 保存到缓存
        self.save_prompt_cache(chapter_number, scene_number, image_index, scene_data, prompt)
        return prompt

    async def _translate_description(self, description, setting, mood, characters) -> str:
        """调用 LLM 将中文描述翻译并润色为英文 Prompt"""
        template = self.stage2_prompts.get("translation_task", "")
        if template:
            prompt = template.format(
                description=description,
                setting=setting,
                mood=mood
            )
        else:
            prompt = f"""Translate the following Chinese scene description to English for AI image generation. 
                Keep it concise but detailed enough for image generation.

                Scene: {description}
                Setting: {setting}
                Mood: {mood}
                Characters: {', '.join(characters)}

                Output ONLY the translated English text."""

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are an expert at writing prompts for Stable Diffusion.",
                max_tokens=500,
            )
            return response.content.strip()
        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return f"{description}, {setting}, {mood}"


    def _extract_json(self, content: str) -> List[Dict]:
        """从文本中提取 JSON"""
        import re

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        patterns = [r'```json\s*(.*?)\s*```', r'\[.*\]']
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except:
                    continue

        raise ValueError("无法从响应中提取 JSON")

    def clear_cache(self, chapter_number: Optional[int] = None):
        """清除缓存"""
        if chapter_number:
            # 清除指定章节缓存
            scene_cache = self.get_scene_cache_path(chapter_number)
            if scene_cache.exists():
                scene_cache.unlink()
                logger.info(f"清除场景缓存: 第{chapter_number}章")

            # 清除该章节所有 prompt 缓存
            for prompt_cache in self.prompts_cache_dir.glob(f"chapter_{chapter_number:03d}_*.json"):
                prompt_cache.unlink()
                logger.info(f"清除 prompt 缓存: {prompt_cache.name}")
        else:
            # 清除所有缓存
            import shutil
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                logger.info("清除所有缓存")
            # 重建目录
            self.scenes_cache_dir.mkdir(parents=True, exist_ok=True)
            self.prompts_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_stats(self) -> Dict:
        """获取缓存统计"""
        scene_files = list(self.scenes_cache_dir.glob("*.json"))
        prompt_files = list(self.prompts_cache_dir.glob("*.json"))

        return {
            "cache_dir": str(self.cache_dir),
            "scene_cached_chapters": len(scene_files),
            "prompt_cached_count": len(prompt_files),
        }


async def preprocess_novel(novel: Novel, config: Dict, force_refresh: bool = False, llm_client=None) -> Dict:
    """
    预处理整本小说，生成所有缓存

    Args:
        novel: 小说对象
        config: 配置
        force_refresh: 是否强制刷新
        llm_client: 外部注入的 LLM 客户端

    Returns:
        预处理统计信息
    """
    preprocessor = ScenePreprocessor(config, novel, llm_client=llm_client)

    total_chapters = len(novel.chapters)
    images_per_chapter = config.get("images_per_chapter") # 默认不强制数量

    logger.info(f"开始预处理: {novel.metadata['title']}")
    count_str = f", 每章图像: {images_per_chapter}" if images_per_chapter else ""
    logger.info(f"章节数: {total_chapters}{count_str}")

    for chapter in novel.chapters:
        logger.info(f"预处理第{chapter.number}章...")

        # 提取场景
        scenes = await preprocessor.extract_scenes(chapter, images_per_chapter, force_refresh)

        # 构建每个场景的 prompt
        for i, scene in enumerate(scenes):
            prompt = await preprocessor.build_prompt(
                scene,
                novel.blueprint.characters,
                chapter.number,
                scene.get("scene_number", i + 1),
                i + 1,
                force_refresh
            )

    stats = preprocessor.get_cache_stats()
    logger.info(f"预处理完成: {stats}")

    return stats

# 为后向兼容提供别名
ScenePreprocessor = Preprocessor
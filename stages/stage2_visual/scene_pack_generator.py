"""
Scene Pack Generator - 场景包生成器

为每个场景生成全景、中景、特写、氛围参考等资产。
这些资产将用于后续的关键帧生成，保证场景一致性。

Phase 1 (预生产) 的核心组件。
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
import json
import re

import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

from stages.stage1_novel.models import Chapter
from stages.stage2_visual.image_generator import ImageGenerator
from core.storage import ProjectStorage
from config.settings import IMAGE_GENERATION


@dataclass
class ScenePack:
    """场景包"""

    scene_id: str
    scene_name: str
    wide_path: Optional[str] = None  # 全景
    medium_path: Optional[str] = None  # 中景
    closeup_path: Optional[str] = None  # 特写
    mood_ref_path: Optional[str] = None  # 氛围参考
    night_view_path: Optional[str] = None  # 夜景（可选）
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "wide_path": self.wide_path,
            "medium_path": self.medium_path,
            "closeup_path": self.closeup_path,
            "mood_ref_path": self.mood_ref_path,
            "night_view_path": self.night_view_path,
            "description": self.description,
        }


class ScenePackGenerator:
    """
    场景包生成器

    在 Phase 1 (预生产) 阶段为每个场景生成：
    - wide.png: 全景图
    - medium.png: 中景图
    - closeup.png: 特写图
    - mood_ref.png: 氛围参考
    - night_view.png: 夜景（可选）
    """

    def __init__(self, project_storage: ProjectStorage, config: Dict = None):
        self.storage = project_storage
        self.config = config or IMAGE_GENERATION.copy()
        self.image_generator = None
        self._init_image_generator()

    def _init_image_generator(self):
        """初始化图像生成器"""
        try:
            self.image_generator = ImageGenerator(self.config)
        except Exception as e:
            print(f"⚠️ 图像生成器初始化失败: {e}")
            self.image_generator = None

    async def generate_scene_pack(
        self,
        scene_id: str,
        scene_name: str,
        context: str = "",
        force_regenerate: bool = False,
    ) -> ScenePack:
        """
        为单个场景生成场景包

        Args:
            scene_id: 场景ID
            scene_name: 场景名称
            context: 场景上下文描述
            force_regenerate: 是否强制重新生成

        Returns:
            场景包
        """
        scene_dir = self.storage.get_scene_dir(scene_name)
        scene_dir.mkdir(parents=True, exist_ok=True)

        pack = ScenePack(
            scene_id=scene_id,
            scene_name=scene_name,
            description=context,
        )

        # 1. 生成全景
        wide_path = scene_dir / "wide.png"
        if force_regenerate or not wide_path.exists():
            wide_path_str = await self._generate_wide(scene_name, context)
            pack.wide_path = wide_path_str
        else:
            pack.wide_path = str(wide_path)
            print(f"      ✓ 全景已存在: {scene_name}/wide.png")

        # 2. 生成中景
        medium_path = scene_dir / "medium.png"
        if force_regenerate or not medium_path.exists():
            medium_path_str = await self._generate_medium(scene_name, context)
            pack.medium_path = medium_path_str
        else:
            pack.medium_path = str(medium_path)
            print(f"      ✓ 中景已存在: {scene_name}/medium.png")

        # 3. 生成特写
        closeup_path = scene_dir / "closeup.png"
        if force_regenerate or not closeup_path.exists():
            closeup_path_str = await self._generate_closeup(scene_name, context)
            pack.closeup_path = closeup_path_str
        else:
            pack.closeup_path = str(closeup_path)
            print(f"      ✓ 特写已存在: {scene_name}/closeup.png")

        # 4. 生成氛围参考
        mood_path = scene_dir / "mood_ref.png"
        if force_regenerate or not mood_path.exists():
            mood_path_str = await self._generate_mood_ref(scene_name, context)
            pack.mood_ref_path = mood_path_str
        else:
            pack.mood_ref_path = str(mood_path)
            print(f"      ✓ 氛围参考已存在: {scene_name}/mood_ref.png")

        # 5. 生成夜景（如果场景有夜间元素）
        if any(
            keyword in context.lower() for keyword in ["夜", "晚", "月", "星", "灯"]
        ):
            night_path = scene_dir / "night_view.png"
            if force_regenerate or not night_path.exists():
                night_path_str = await self._generate_night_view(scene_name, context)
                pack.night_view_path = night_path_str
            else:
                pack.night_view_path = str(night_path)
                print(f"      ✓ 夜景已存在: {scene_name}/night_view.png")

        # 保存场景包信息
        self._save_scene_pack_info(pack, scene_dir)

        return pack

    async def _generate_wide(self, scene_name: str, context: str) -> Optional[str]:
        """生成全景图"""
        if not self.image_generator:
            return None

        prompt = self._build_wide_prompt(scene_name, context)

        try:
            scene_dir = self.storage.get_scene_dir(scene_name)
            output_path = scene_dir / "wide.png"
            print(f"      🎨 生成全景: {scene_name}")

            if self.image_generator.local_model:
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=1024,
                    height=576,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(50),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 全景生成失败: {e}")
            return None

    async def _generate_medium(self, scene_name: str, context: str) -> Optional[str]:
        """生成中景图"""
        if not self.image_generator:
            return None

        prompt = self._build_medium_prompt(scene_name, context)

        try:
            scene_dir = self.storage.get_scene_dir(scene_name)
            output_path = scene_dir / "medium.png"
            print(f"      🎨 生成中景: {scene_name}")

            if self.image_generator.local_model:
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=768,
                    height=768,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(51),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 中景生成失败: {e}")
            return None

    async def _generate_closeup(self, scene_name: str, context: str) -> Optional[str]:
        """生成特写图"""
        if not self.image_generator:
            return None

        prompt = self._build_closeup_prompt(scene_name, context)

        try:
            scene_dir = self.storage.get_scene_dir(scene_name)
            output_path = scene_dir / "closeup.png"
            print(f"      🎨 生成特写: {scene_name}")

            if self.image_generator.local_model:
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=512,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(52),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 特写生成失败: {e}")
            return None

    async def _generate_mood_ref(self, scene_name: str, context: str) -> Optional[str]:
        """生成氛围参考图"""
        if not self.image_generator:
            return None

        prompt = self._build_mood_prompt(scene_name, context)

        try:
            scene_dir = self.storage.get_scene_dir(scene_name)
            output_path = scene_dir / "mood_ref.png"
            print(f"      🎨 生成氛围参考: {scene_name}")

            if self.image_generator.local_model:
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=512,
                    num_inference_steps=25,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(53),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 氛围参考生成失败: {e}")
            return None

    async def _generate_night_view(
        self, scene_name: str, context: str
    ) -> Optional[str]:
        """生成夜景图"""
        if not self.image_generator:
            return None

        prompt = self._build_night_prompt(scene_name, context)

        try:
            scene_dir = self.storage.get_scene_dir(scene_name)
            output_path = scene_dir / "night_view.png"
            print(f"      🎨 生成夜景: {scene_name}")

            if self.image_generator.local_model:
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=1024,
                    height=576,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(54),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 夜景生成失败: {e}")
            return None

    def _build_wide_prompt(self, scene_name: str, context: str) -> str:
        """构建全景提示词"""
        prompt = f"wide establishing shot of {scene_name}, {context}, epic scale, cinematic composition, fantasy world, dramatic lighting, high detail, 8k"
        return prompt

    def _build_medium_prompt(self, scene_name: str, context: str) -> str:
        """构建中景提示词"""
        prompt = f"medium shot of {scene_name}, {context}, atmospheric, cinematic lighting, fantasy art style, high detail"
        return prompt

    def _build_closeup_prompt(self, scene_name: str, context: str) -> str:
        """构建特写提示词"""
        prompt = f"close-up detail of {scene_name}, {context}, intricate details, cinematic lighting, fantasy art style, high detail"
        return prompt

    def _build_mood_prompt(self, scene_name: str, context: str) -> str:
        """构建氛围提示词"""
        prompt = f"mood board of {scene_name}, {context}, color palette reference, lighting atmosphere, fantasy art style, cinematic"
        return prompt

    def _build_night_prompt(self, scene_name: str, context: str) -> str:
        """构建夜景提示词"""
        prompt = f"night scene of {scene_name}, {context}, moonlight, starlight, atmospheric, cinematic lighting, fantasy art style, high detail"
        return prompt

    def _save_scene_pack_info(self, pack: ScenePack, scene_dir: Path):
        """保存场景包信息"""
        info_path = scene_dir / "scene_pack.json"
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(pack.to_dict(), f, ensure_ascii=False, indent=2)


class ScenePackManager:
    """场景包管理器 - 管理项目中所有场景包"""

    def __init__(self, project_storage: ProjectStorage):
        self.storage = project_storage
        self.generator = ScenePackGenerator(project_storage)
        self._scene_packs: Dict[str, ScenePack] = {}

    async def generate_packs_from_chapters(
        self,
        chapters: List[Chapter],
        force_regenerate: bool = False,
    ) -> Dict[str, ScenePack]:
        """从章节内容中提取场景并生成场景包"""
        print(f"\n🏠 开始生成场景包...")

        # 从章节内容中提取场景
        scenes = self._extract_scenes_from_chapters(chapters)
        print(f"   发现 {len(scenes)} 个独立场景")

        for scene_id, scene_name, context in scenes:
            print(f"\n   处理场景: {scene_name}")
            try:
                pack = await self.generator.generate_scene_pack(
                    scene_id=scene_id,
                    scene_name=scene_name,
                    context=context,
                    force_regenerate=force_regenerate,
                )
                self._scene_packs[scene_name] = pack
            except Exception as e:
                print(f"      ⚠️ 场景 {scene_name} 生成失败: {e}")

        print(f"\n🏠 场景包生成完成: {len(self._scene_packs)}/{len(scenes)}")
        return self._scene_packs

    def _extract_scenes_from_chapters(
        self,
        chapters: List[Chapter],
    ) -> List[tuple]:
        """
        从章节内容中提取场景

        Returns:
            List[(scene_id, scene_name, context)]
        """
        scenes: Set[tuple] = set()

        # 常见场景关键词
        scene_keywords = [
            "酒馆",
            "客栈",
            "山洞",
            "森林",
            "山顶",
            "悬崖",
            "大殿",
            "广场",
            "街道",
            "小巷",
            "皇宫",
            "宗门",
            "修炼场",
            "书房",
            "卧室",
            "厨房",
            "花园",
            "湖边",
            "河边",
            "海边",
            "沙漠",
        ]

        for chapter in chapters:
            content = chapter.content
            for keyword in scene_keywords:
                if keyword in content:
                    scenes.add((keyword, keyword, f"fantasy {keyword} scene"))

        # 如果没有找到场景，添加默认场景
        if not scenes:
            scenes.add(("default", "默认场景", "fantasy scene, magical atmosphere"))

        return sorted(list(scenes))

    def get_scene_pack(self, scene_name: str) -> Optional[ScenePack]:
        """获取场景包"""
        return self._scene_packs.get(scene_name)

    def list_missing_packs(self, scenes: List[tuple]) -> List[tuple]:
        """列出缺少场景包的场景"""
        missing = []
        for scene_id, scene_name, context in scenes:
            scene_dir = self.storage.get_scene_dir(scene_name)
            wide_path = scene_dir / "wide.png"
            if not wide_path.exists():
                missing.append((scene_id, scene_name, context))
        return missing

    def load_existing_packs(self) -> Dict[str, ScenePack]:
        """加载已有的场景包"""
        packs = {}
        scenes_dir = self.storage.get_scenes_dir()

        if not scenes_dir.exists():
            return packs

        for scene_dir in scenes_dir.iterdir():
            if not scene_dir.is_dir():
                continue

            info_path = scene_dir / "scene_pack.json"
            if info_path.exists():
                try:
                    with open(info_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    packs[scene_dir.name] = ScenePack(**data)
                except Exception:
                    pass

        self._scene_packs = packs
        return packs

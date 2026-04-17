"""
Character Pack Generator - 角色包生成器

为每个角色生成定妆照、脸部参考、表情组等资产。
这些资产将用于后续的关键帧生成，保证角色一致性。

Phase 1 (预生产) 的核心组件。
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json

import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

from stages.stage1_novel.models import Character
from stages.stage2_visual.image_generator import ImageGenerator
from core.storage import ProjectStorage
from config.settings import IMAGE_GENERATION


@dataclass
class CharacterPack:
    """角色包"""

    character_id: str
    character_name: str
    portrait_path: Optional[str] = None
    face_ref_path: Optional[str] = None
    outfit_ref_path: Optional[str] = None
    expressions: Dict[str, str] = None  # emotion -> image_path

    def __post_init__(self):
        if self.expressions is None:
            self.expressions = {}

    def to_dict(self) -> Dict:
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "portrait_path": self.portrait_path,
            "face_ref_path": self.face_ref_path,
            "outfit_ref_path": self.outfit_ref_path,
            "expressions": self.expressions,
        }


class CharacterPackGenerator:
    """
    角色包生成器

    在 Phase 1 (预生产) 阶段为每个角色生成：
    - portrait.png: 定妆照（正面全身/半身照）
    - face_ref.png: 脸部特写参考
    - outfit_ref.png: 服装参考
    - expressions/: 表情组（happy, sad, angry, neutral 等）
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

    async def generate_character_pack(
        self,
        character: Character,
        force_regenerate: bool = False,
    ) -> CharacterPack:
        """
        为单个角色生成角色包

        Args:
            character: 角色对象
            force_regenerate: 是否强制重新生成

        Returns:
            角色包
        """
        char_dir = self.storage.get_character_dir(character.name)
        char_dir.mkdir(parents=True, exist_ok=True)

        # 创建表情目录
        expressions_dir = char_dir / "expressions"
        expressions_dir.mkdir(exist_ok=True)

        pack = CharacterPack(
            character_id=character.id,
            character_name=character.name,
        )

        # 1. 生成定妆照
        portrait_path = char_dir / "portrait.png"
        if force_regenerate or not portrait_path.exists():
            portrait_path_str = await self._generate_portrait(character)
            pack.portrait_path = portrait_path_str
        else:
            pack.portrait_path = str(portrait_path)
            print(f"      ✓ 定妆照已存在: {character.name}/portrait.png")

        # 2. 生成脸部参考
        face_ref_path = char_dir / "face_ref.png"
        if force_regenerate or not face_ref_path.exists():
            face_ref_path_str = await self._generate_face_ref(character)
            pack.face_ref_path = face_ref_path_str
        else:
            pack.face_ref_path = str(face_ref_path)
            print(f"      ✓ 脸部参考已存在: {character.name}/face_ref.png")

        # 3. 生成服装参考
        outfit_ref_path = char_dir / "outfit_ref.png"
        if force_regenerate or not outfit_ref_path.exists():
            outfit_ref_path_str = await self._generate_outfit_ref(character)
            pack.outfit_ref_path = outfit_ref_path_str
        else:
            pack.outfit_ref_path = str(outfit_ref_path)
            print(f"      ✓ 服装参考已存在: {character.name}/outfit_ref.png")

        # 4. 生成表情组
        emotions = ["neutral", "happy", "sad", "angry", "fearful", "surprised"]
        for emotion in emotions:
            expr_path = expressions_dir / f"{emotion}.png"
            if force_regenerate or not expr_path.exists():
                expr_path_str = await self._generate_expression(character, emotion)
                if expr_path_str:
                    pack.expressions[emotion] = expr_path_str
            else:
                pack.expressions[emotion] = str(expr_path)
                print(f"      ✓ 表情 {emotion} 已存在")

        # 保存角色包信息
        self._save_character_pack_info(pack, char_dir)

        return pack

    async def _generate_portrait(self, character: Character) -> Optional[str]:
        """生成定妆照"""
        if not self.image_generator:
            return None

        prompt = await self._build_portrait_prompt(character)

        try:
            print(f"      🎨 生成定妆照: {character.name}")

            char_dir = self.storage.get_character_dir(character.name)
            output_path = char_dir / "portrait.png"

            if self.image_generator.local_model:
                from PIL import Image
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=512,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(42),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 定妆照生成失败: {e}")
            return None

    async def _generate_face_ref(self, character: Character) -> Optional[str]:
        """生成脸部参考"""
        if not self.image_generator:
            return None

        prompt = await self._build_face_ref_prompt(character)

        try:
            print(f"      🎨 生成脸部参考: {character.name}")

            char_dir = self.storage.get_character_dir(character.name)
            output_path = char_dir / "face_ref.png"

            if self.image_generator.local_model:
                from PIL import Image
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=512,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(43),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 脸部参考生成失败: {e}")
            return None

    async def _generate_outfit_ref(self, character: Character) -> Optional[str]:
        """生成服装参考"""
        if not self.image_generator:
            return None

        prompt = await self._build_outfit_prompt(character)

        try:
            print(f"      🎨 生成服装参考: {character.name}")

            char_dir = self.storage.get_character_dir(character.name)
            output_path = char_dir / "outfit_ref.png"

            if self.image_generator.local_model:
                from PIL import Image
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=768,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(44),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 服装参考生成失败: {e}")
            return None

    async def _generate_expression(
        self,
        character: Character,
        emotion: str,
    ) -> Optional[str]:
        """生成表情图"""
        if not self.image_generator:
            return None

        prompt = await self._build_expression_prompt(character, emotion)

        try:
            print(f"      🎨 生成表情 ({emotion}): {character.name}")

            char_dir = self.storage.get_character_dir(character.name)
            output_path = char_dir / "expressions" / f"{emotion}.png"

            if self.image_generator.local_model:
                from PIL import Image
                import torch

                result = self.image_generator.local_model(
                    prompt=prompt,
                    width=512,
                    height=512,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                    generator=torch.Generator(
                        device=self.image_generator.device
                    ).manual_seed(45),
                )
                image = result.images[0]
                image.save(output_path)
            else:
                return None

            return str(output_path) if output_path.exists() else None
        except Exception as e:
            print(f"      ⚠️ 表情生成失败 ({emotion}): {e}")
            return None

    async def _build_portrait_prompt(self, character: Character) -> str:
        """构建定妆照提示词"""
        # 翻译角色外貌描述为英文
        appearance = character.appearance or ""
        name = character.name

        prompt = f"portrait of {name}, {appearance}, full body, standing, fantasy art style, cinematic lighting, high detail, 8k"

        return prompt

    async def _build_face_ref_prompt(self, character: Character) -> str:
        """构建脸部参考提示词"""
        appearance = character.appearance or ""
        name = character.name

        prompt = f"close-up face portrait of {name}, {appearance}, detailed facial features, fantasy art style, cinematic lighting, high detail"

        return prompt

    async def _build_outfit_prompt(self, character: Character) -> str:
        """构建服装参考提示词"""
        appearance = character.appearance or ""
        name = character.name

        prompt = f"full body outfit view of {name}, {appearance}, detailed costume design, fantasy art style, cinematic lighting, high detail"

        return prompt

    async def _build_expression_prompt(
        self,
        character: Character,
        emotion: str,
    ) -> str:
        """构建表情提示词"""
        appearance = character.appearance or ""
        name = character.name

        emotion_map = {
            "neutral": "neutral expression, calm face",
            "happy": "happy expression, smiling, cheerful",
            "sad": "sad expression, sorrowful, melancholic",
            "angry": "angry expression, fierce, wrathful",
            "fearful": "fearful expression, scared, terrified",
            "surprised": "surprised expression, shocked, astonished",
        }

        emotion_desc = emotion_map.get(emotion, emotion)
        prompt = f"close-up face portrait of {name}, {appearance}, {emotion_desc}, fantasy art style, cinematic lighting, high detail"

        return prompt

    def _save_character_pack_info(self, pack: CharacterPack, char_dir: Path):
        """保存角色包信息"""
        info_path = char_dir / "character_pack.json"
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(pack.to_dict(), f, ensure_ascii=False, indent=2)


class CharacterPackManager:
    """角色包管理器 - 管理项目中所有角色包"""

    def __init__(self, project_storage: ProjectStorage):
        self.storage = project_storage
        self.generator = CharacterPackGenerator(project_storage)
        self._character_packs: Dict[str, CharacterPack] = {}

    async def generate_all_packs(
        self,
        characters: List[Character],
        force_regenerate: bool = False,
    ) -> Dict[str, CharacterPack]:
        """为所有角色生成角色包"""
        print(f"\n🎭 开始生成角色包 (共 {len(characters)} 个角色)...")

        for character in characters:
            print(f"\n   处理角色: {character.name}")
            try:
                pack = await self.generator.generate_character_pack(
                    character,
                    force_regenerate=force_regenerate,
                )
                self._character_packs[character.name] = pack
            except Exception as e:
                print(f"      ⚠️ 角色 {character.name} 生成失败: {e}")

        print(f"\n🎭 角色包生成完成: {len(self._character_packs)}/{len(characters)}")
        return self._character_packs

    def get_character_pack(self, character_name: str) -> Optional[CharacterPack]:
        """获取角色包"""
        return self._character_packs.get(character_name)

    def list_missing_packs(
        self,
        characters: List[Character],
    ) -> List[Character]:
        """列出缺少角色包的角色"""
        missing = []
        for character in characters:
            char_dir = self.storage.get_character_dir(character.name)
            portrait_path = char_dir / "portrait.png"
            if not portrait_path.exists():
                missing.append(character)
        return missing

    def load_existing_packs(self) -> Dict[str, CharacterPack]:
        """加载已有的角色包"""
        packs = {}
        chars_dir = self.storage.get_characters_dir()

        if not chars_dir.exists():
            return packs

        for char_dir in chars_dir.iterdir():
            if not char_dir.is_dir():
                continue

            info_path = char_dir / "character_pack.json"
            if info_path.exists():
                try:
                    with open(info_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    packs[char_dir.name] = CharacterPack(**data)
                except Exception:
                    pass

        self._character_packs = packs
        return packs

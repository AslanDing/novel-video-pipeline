"""
图像生成引擎 - 第二阶段
负责根据小说内容生成配图
"""

import os
import json
import asyncio
import traceback
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import base64
from io import BytesIO

# 图像处理相关
from PIL import Image

try:
    import torch
    from diffusers import StableDiffusionXLPipeline, StableDiffusion3Pipeline, DiffusionPipeline, StableVideoDiffusionPipeline
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch/diffusers未安装，将使用云端API模式")

import sys
sys.path.append(str(Path(__file__).parent.parent))

from core.base_pipeline import PipelineStage
from core.logger import get_logger
from stages.stage1_novel.models import Novel, Chapter, Character
from config.settings import IMAGE_GENERATION, VIDEO_GENERATION, IMAGES_DIR, VIDEOS_DIR, load_prompts

# 获取日志记录器
logger = get_logger("image_generator")


@dataclass
class GeneratedImage:
    """生成的图像信息"""
    image_id: str
    chapter_number: int
    scene_description: str
    prompt: str
    file_path: str
    width: int
    height: int
    seed: int
    generation_time: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class GeneratedVideo:
    """生成的视频信息"""
    video_id: str
    chapter_number: int
    scene_description: str
    source_image_path: str
    file_path: str
    width: int
    height: int
    frames: int
    fps: int
    generation_time: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StoryboardFrame:
    """分镜帧数据"""
    frame_id: str
    scene_description: str
    shot_type: str  # wide, medium, close-up, extreme close-up
    camera_movement: str  # static, pan, tilt, dolly, crane
    composition: str  # centered, rule of thirds, leading lines
    lighting: str  # natural, dramatic, soft
    mood: str  # tense, calm, dark, bright
    duration: float  # 视频中展示时长


@dataclass
class ChapterImages:
    """章节的图像集合"""
    chapter_number: int
    images: List[GeneratedImage]
    storyboard_frames: Optional[List[StoryboardFrame]] = None
    
    def to_dict(self) -> Dict:
        result = {
            "chapter_number": self.chapter_number,
            "images": [img.to_dict() for img in self.images],
        }
        if self.storyboard_frames:
            result["storyboard_frames"] = [asdict(f) for f in self.storyboard_frames]
        return result


@dataclass
class CharacterReference:
    """角色参考信息"""
    character_id: str
    character_name: str
    reference_image_path: Optional[str] = None
    appearance_description: Optional[str] = None


from core.llm_client import NVIDIA_NIM_Client


class IPAdapterConsistency:
    """IPAdapter 角色一致性框架（占位实现）"""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.character_embeddings: Dict[str, any] = {}
        self.enabled = False
        logger.warning("IPAdapter 框架已加载，完整功能需要额外依赖")
        logger.warning("安装依赖: pip install ipadapter insightface")

    def load_reference_image(self, character_id: str, image_path: str):
        """加载角色参考图（框架方法）"""
        logger.info(f"[IPAdapter] 加载角色参考图: {character_id}, path: {image_path}")
        self.character_embeddings[character_id] = {"reference_path": image_path}

    def generate_with_consistency(
        self,
        prompt: str,
        character_id: str,
        **kwargs
    ):
        """带角色一致性的图像生成（框架方法）"""
        if character_id in self.character_embeddings:
            logger.debug(f"[IPAdapter] 使用角色一致性: {character_id}")
        return prompt  # 框架版本返回原 prompt


class CharacterConsistencyManager:
    """角色一致性管理器"""

    def __init__(self, config: Dict):
        self.config = config
        self.consistency_type = config.get("character_consistency", {}).get("type", "ipadapter")
        self.enabled = config.get("character_consistency", {}).get("enabled", False)
        self.character_references: Dict[str, CharacterReference] = {}
        self.ipadapter = None

    def init(self, pipeline=None):
        """初始化角色一致性模块"""
        if not self.enabled:
            return

        logger.info(f"初始化角色一致性: {self.consistency_type}")

        if self.consistency_type == "ipadapter":
            self.ipadapter = IPAdapterConsistency(pipeline)
        elif self.consistency_type == "instantid":
            logger.warning("InstantID 暂未实现")

    def register_character(self, char_ref: CharacterReference):
        """注册角色参考信息"""
        self.character_references[char_ref.character_id] = char_ref
        if self.ipadapter and char_ref.reference_image_path:
            self.ipadapter.load_reference_image(
                char_ref.character_id,
                char_ref.reference_image_path
            )


class ImageGenerator(PipelineStage):
    """
    图像生成器
    
    为小说的每章生成配图
    支持：
    - 本地Stable Diffusion模型
    - 云端API（保留接口）
    - 分镜规划
    - 角色一致性框架
    - 图生视频（SVD）
    """
    
    def __init__(self, config=None):
        super().__init__("图像生成", config or IMAGE_GENERATION)
        self.local_model = None
        self.svd_model = None
        self.device = None
        self.llm_client = NVIDIA_NIM_Client()
        self.prompts = load_prompts().get("stage2", {})
        self.ipadapter = None
        self.character_consistency_enabled = False
        self.preprocessor = None  # 预处理器，用于从缓存加载 prompt
        self.character_portraits: Dict[str, Path] = {}  # 角色名 -> 定妆照路径

        # 角色一致性相关
        self.character_consistency_manager = CharacterConsistencyManager(self.config)
        self.character_references: Dict[str, CharacterReference] = {}
        
        # 初始化本地模型（如果启用）
        if self.config.get("local", {}).get("enabled", False):
            self._init_local_model()
        
        # 初始化角色一致性（如果启用）
        if self.config.get("character_consistency", {}).get("enabled", False):
            self.character_consistency_manager.init(self.local_model)
    
    def _init_local_model(self):
        """初始化本地SD模型 - 增强版，支持SVD"""
        if not TORCH_AVAILABLE:
            logger.warning("PyTorch不可用，无法加载本地模型")
            return

        try:
            # 检测GPU
            if torch.cuda.is_available():
                self.device = "cuda"
                logger.info(f"使用GPU: {torch.cuda.get_device_name(0)}")
            else:
                self.device = "cpu"
                logger.info("使用CPU（速度较慢）")
            
            # 获取模型配置
            from config.settings import IMAGE_MODELS_DIR, VIDEO_MODELS_DIR
            model_type = self.config["local"]["model_type"]
            
            # 加载主图像模型
            self._load_image_model(model_type, str(IMAGE_MODELS_DIR))
            
            # 如果是 sdxl_svd 模式，同时加载 SVD 模型
            if model_type == "sdxl_svd":
                self._load_svd_model(str(VIDEO_MODELS_DIR))
            
        except Exception as e:
            logger.error(f"加载本地模型失败", exc_info=True)
            logger.warning("将使用占位图模式。请运行: python download_models.py download")
            self.local_model = None
            self.svd_model = None
    
    def _load_image_model(self, model_type: str, cache_dir: Optional[str]):
        """加载图像生成模型"""
        logger.info(f"正在加载图像生成模型: {model_type}")

        # 根据模型类型选择模型路径
        if model_type == "sdxl" or model_type == "sdxl_svd":
            model_path = self.config["local"]["model_path"]
            if not "/" in model_path:
                model_path = "stabilityai/stable-diffusion-xl-base-1.0"
        elif model_type == "sdxl-refiner":
            model_path = self.config["local"]["model_path"]
            if not "/" in model_path:
                model_path = "stabilityai/stable-diffusion-xl-refiner-1.0"
        elif model_type == "z-image-turbo":
            model_path = self.config["local"]["model_path"]
            if not "/" in model_path:
                model_path = "Tongyi-MAI/Z-Image-Turbo"
        elif model_type == "sd3.5-medium":
            model_path = self.config["local"]["model_path"]
            if not "/" in model_path:
                model_path = "stabilityai/stable-diffusion-3.5-medium"
        else:
            model_path = self.config["local"]["model_path"]

        logger.debug(f"模型路径: {model_path}")

        # 根据模型类型选择数据类型
        if model_type in ["z-image-turbo", "sd3.5-medium"]:
            torch_dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
            logger.debug(f"使用 bfloat16 数据类型")
        else:
            torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
            logger.debug(f"使用 float16 数据类型")

        load_kwargs = {
            "torch_dtype": torch_dtype,
            "use_safetensors": True,
        }

        if cache_dir:
            load_kwargs["cache_dir"] = cache_dir
            logger.debug(f"缓存目录: {cache_dir}")

        logger.info(f"正在加载模型，这可能需要几分钟...")
        if model_type == "sdxl" or model_type == "sdxl_svd":
            self.local_model = StableDiffusionXLPipeline.from_pretrained(
                model_path,
                **load_kwargs
            )
        elif model_type == "sd3.5-medium":
            self.local_model = StableDiffusion3Pipeline.from_pretrained(
                model_path,
                **load_kwargs
            )
        else:
            self.local_model = DiffusionPipeline.from_pretrained(
                model_path,
                **load_kwargs
            )

        self.local_model = self.local_model.to(self.device)

        logger.info(f"图像模型加载完成: {model_type}")

        # SDXL 系列模型启用角色一致性（IPAdapter）
        if model_type in ["sdxl", "sdxl_svd", "sdxl-refiner", "z-image-turbo"]:
            self._enable_character_consistency()

    def _enable_character_consistency(self):
        """使用 diffusers 原生 IP-Adapter 启用角色一致性"""
        if not TORCH_AVAILABLE:
            return

        try:
            ipadapter_config = self.config.get("character_consistency", {})
            if not ipadapter_config.get("enabled", False):
                logger.info("角色一致性已禁用 (character_consistency.enabled=false)")
                return

            # IP-Adapter 常用配置
            ipadapter_repo = ipadapter_config.get("model_path", "h94/IP-Adapter")
            from config.settings import IMAGE_MODELS_DIR
            
            # 1. 自动根据模型类型加载对应的 Image Encoder (ViT-H for Plus)
            model_type = self.config.get("local", {}).get("model_type", "sdxl")
            is_sdxl = model_type in ["sdxl", "sdxl_svd", "sdxl-refiner", "z-image-turbo"]
            
            # 使用 CLIP-ViT-H-14 (IP-Adapter Plus 必备)
            image_encoder_path = "laion/CLIP-ViT-H-14-laion2B-s32B-b79K"
            
            try:
                from transformers import CLIPVisionModelWithProjection
                logger.info(f"正在加载 Image Encoder: {image_encoder_path}")
                image_encoder = CLIPVisionModelWithProjection.from_pretrained(
                    image_encoder_path,
                    torch_dtype=self.local_model.dtype,
                    cache_dir=str(IMAGE_MODELS_DIR)
                ).to(self.device)
                
                # 将 encoder 绑定到 pipeline
                self.local_model.image_encoder = image_encoder
            except Exception as e:
                logger.warning(f"加载 Image Encoder 失败: {e}，将尝试自动下载")

            # 2. 加载 IP-Adapter 权重
            if is_sdxl:
                subfolder = "sdxl_models"
                weight_name = "ip-adapter-plus_sdxl_vit-h.safetensors"
            else:
                subfolder = "models"
                weight_name = "ip-adapter-plus_sd15.safetensors"

            # 检查模型是否支持原生 IP-Adapter API (Z-Image-Turbo / ZImagePipeline 可能不支持)
            if not hasattr(self.local_model, "load_ip_adapter"):
                logger.warning(f"当前模型 ({type(self.local_model).__name__}) 不支持原生 IP-Adapter API。角色一致性已跳过。")
                self.character_consistency_enabled = False
                return

            logger.info(f"正在加载 IP-Adapter 权重: {ipadapter_repo}/{subfolder}/{weight_name}")
            
            try:
                self.local_model.load_ip_adapter(
                    ipadapter_repo,
                    subfolder=subfolder,
                    weight_name=weight_name,
                    cache_dir=str(IMAGE_MODELS_DIR),
                )
                
                # 设置 IP-Adapter 影响强度 (0.0-1.0, 越高越接近参考图)
                ip_scale = ipadapter_config.get("scale", 0.5)
                self.local_model.set_ip_adapter_scale(ip_scale)

                logger.info(f"IP-Adapter 加载完成, scale={ip_scale}, 角色一致性已启用")
                self.character_consistency_enabled = True
            except ImportError:
                logger.error("未发现 peft，无法使用 load_ip_adapter。请运行: pip install peft")
                self.character_consistency_enabled = False
            except Exception as e:
                logger.error(f"IP-Adapter 加载具体权重失败: {e}")
                self.character_consistency_enabled = False

        except Exception as e:
            logger.error(f"IP-Adapter 整体初始化过程中断: {e}", exc_info=True)
            self.character_consistency_enabled = False

    def _load_svd_model(self, cache_dir: Optional[str]):
        """加载 SVD 图生视频模型"""
        logger.info("正在加载 SVD 图生视频模型...")

        svd_model_path = self.config.get("svd", {}).get("model_path", "stabilityai/stable-video-diffusion")
        logger.debug(f"SVD 模型路径: {svd_model_path}")

        load_kwargs = {
            "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
            "use_safetensors": True,
        }

        if cache_dir:
            load_kwargs["cache_dir"] = cache_dir

        try:
            self.svd_model = StableVideoDiffusionPipeline.from_pretrained(
                svd_model_path,
                **load_kwargs
            )

            self.svd_model = self.svd_model.to(self.device)

            if self.device == "cuda":
                self.svd_model.enable_attention_slicing()

            logger.info("SVD 模型加载完成")
        except Exception as e:
            logger.error(f"SVD 模型加载失败", exc_info=True)
            raise
    
    def validate_input(self, input_data) -> bool:
        """验证输入"""
        if isinstance(input_data, Novel):
            return True
        if isinstance(input_data, dict):
            return "chapters" in input_data
        return False
    
    async def process(self, novel: Novel, preprocessor=None) -> Dict[int, ChapterImages]:
        """
        为小说生成图像（可选生成视频）

        Args:
            novel: 小说对象
            preprocessor: 可选的预处理器，用于从缓存加载 prompt

        Returns:
            章节号到图像集合的映射
        """
        model_type = self.config.get("local", {}).get("model_type", "sdxl")
        generate_video = model_type == "sdxl_svd" and self.svd_model is not None

        logger.info(f"开始为小说《{novel.metadata['title']}》生成内容")
        logger.info(f"章节数: {len(novel.chapters)}, 每章图像数: {self.config.get('images_per_chapter', 3)}")
        if generate_video:
            logger.info("模式: 图像 + 视频 (SVD)")
        else:
            logger.info("模式: 仅图像")

        # 存储 preprocessor 供后续使用
        self.preprocessor = preprocessor
        
        # 确保角色定妆照存在
        novel_title = novel.metadata.get('title', '')
        await self._ensure_character_portraits(novel, novel_title)
        
        results = {}
        
        for chapter in novel.chapters:
            logger.info(f"处理第{chapter.number}章...")
            
            # 获取小说标题用于读取 script_x.jsonl
            novel_title = novel.metadata.get('title', '')
            
            # 生成章节图像
            chapter_images = await self._generate_chapter_images(
                chapter=chapter,
                characters=novel.blueprint.characters,
                novel_title=novel_title,
            )
            
            # 如果是 sdxl_svd 模式，为每张图像生成视频
            if generate_video:
                print(f"      🎬 开始生成视频...")
                for i, image in enumerate(chapter_images.images):
                    try:
                        video_path = await self._generate_video_from_image(
                            image_path=Path(image.file_path),
                            chapter_number=chapter.number,
                            video_index=i + 1,
                            scene_description=image.scene_description,
                        )
                        print(f"      ✅ 视频 {i+1} 生成完成")
                    except Exception as e:
                        print(f"      ⚠️  视频 {i+1} 生成失败: {e}")
            
            results[chapter.number] = chapter_images
            print(f"   ✅ 第{chapter.number}章完成")
        
        total_images = sum(len(ci.images) for ci in results.values())
        logger.info(f"完成！共生成 {total_images} 张图像")
        if generate_video:
            print(f"   🎬 视频生成已完成")
        
        return results
    
    async def _generate_chapter_images(
        self,
        chapter: Chapter,
        characters: List[Character],
        novel_title: str = None,
    ) -> ChapterImages:
        """
        为单章生成图像

        策略：
        1. 优先读取 script_x.jsonl (Stage 1产出)
        2. 从缓存或 LLM 提取关键场景
        3. 为每个关键场景生成图像
        """
        images = []
        storyboard_frames = []
        num_images = self.config.get('images_per_chapter', 3)

        # 优先尝试从内存中的 script_lines 加载 (如果已在 run_stage2.py 中加载)
        scenes = []
        if hasattr(chapter, 'script_lines') and chapter.script_lines:
            from stages.stage2_visual.script_adapter import ScriptAdapter
            from dataclasses import asdict
            adapter = ScriptAdapter(novel_title or '', self.config.get('novel_dir', ''))
            scenes = adapter.get_shots_as_scenes([asdict(sl) if hasattr(sl, 'to_dict') else sl for sl in chapter.script_lines])
            if scenes:
                logger.info(f"从内存脚本加载场景: 第{chapter.number}章, 共{len(scenes)}个场景")

        # 其次尝试从 script_x.jsonl 加载
        if not scenes and novel_title:
            scenes = await self._get_scenes_from_script(novel_title, chapter.number)
        
        # 如果没有脚本文件，回退到缓存或 LLM
        if not scenes:
            scenes = await self._get_scenes_with_cache(chapter, num_images)

        # 为每个场景生成图像和分镜帧
        for i, scene in enumerate(scenes):
            try:
                image = await self._generate_single_image(
                    scene=scene,
                    chapter_number=chapter.number,
                    image_index=i + 1,
                    characters=characters,
                )
                images.append(image)
                
                # 创建分镜帧（如果有分镜信息）
                if "shot_type" in scene:
                    frame = StoryboardFrame(
                        frame_id=f"ch{chapter.number}_frame{i+1}",
                        scene_description=scene.get("description", ""),
                        shot_type=scene.get("shot_type", "medium"),
                        camera_movement=scene.get("camera_movement", "static"),
                        composition=scene.get("composition", "rule of thirds"),
                        lighting=scene.get("lighting", "dramatic"),
                        mood=scene.get("mood", "dramatic"),
                        duration=float(scene.get("duration", 8.0)),
                    )
                    storyboard_frames.append(frame)
                    
            except Exception as e:
                logger.error(f"生成图像 {i+1} 失败", exc_info=True)
                continue
        
        return ChapterImages(
            chapter_number=chapter.number,
            images=images,
            storyboard_frames=storyboard_frames if storyboard_frames else None,
        )
    
    async def _get_scenes_with_cache(self, chapter: Chapter, num_scenes: int) -> List[Dict]:
        """
        从缓存或 LLM 获取场景（带缓存支持）

        如果 preprocessor 存在，优先从缓存加载
        """
        if self.preprocessor:
            # 从预处理器的缓存加载场景
            scenes = await self.preprocessor.extract_scenes(chapter, num_scenes)
            if scenes:
                logger.debug(f"从缓存加载第{chapter.number}章场景: {len(scenes)}个")
                return scenes

        # 如果没有缓存，使用原来的方式
        return await self._extract_scenes(chapter, num_scenes)
    
    async def _get_scenes_from_script(self, novel_title: str, chapter_number: int) -> List[Dict]:
        """
        从 Stage 1 产出的 script_x.jsonl 读取场景
        
        Args:
            novel_title: 小说标题
            chapter_number: 章节号
            
        Returns:
            场景列表，每个场景包含 visual_prompt 等信息
        """
        try:
            from config.settings import NOVELS_DIR
            from stages.stage2_visual.script_adapter import ScriptAdapter
            
            # 优先从配置提供的 novel_dir 获取
            config_novel_dir = self.config.get("novel_dir")
            if config_novel_dir:
                data_dir = Path(config_novel_dir) / "data"
            else:
                # 默认回退逻辑
                data_dir = NOVELS_DIR / novel_title / "data"
                
            if not data_dir.exists():
                logger.debug(f"数据目录不存在: {data_dir}")
                return []
            
            adapter = ScriptAdapter(novel_title, data_dir)
            script_lines = adapter.load_script_lines(chapter_number)
            
            if not script_lines:
                logger.debug(f"第{chapter_number}章没有分镜脚本")
                return []
            
            # 转换为场景格式 - 每一个分镜即为一张配图
            scenes = adapter.get_shots_as_scenes(script_lines)
            
            logger.info(f"从 script_x.jsonl 加载了 {len(scenes)} 个配图分镜 (共提取自分栏的 {len(script_lines)} 次请求)")
            return scenes
            
        except Exception as e:
            logger.warning(f"从 script_x.jsonl 加载场景失败: {e}")
            return []
    
    async def _ensure_character_portraits(self, novel: Novel, novel_title: str) -> None:
        """确保角色定妆照存在，如不存在则生成；并将路径缓存到 self.character_portraits"""
        try:
            from config.settings import NOVELS_DIR
            from stages.stage2_visual.script_adapter import CharacterPortraitManager
            
            if not novel_title:
                return
            
            novel_dir = self.config.get("novel_dir")
            if novel_dir:
                novel_dir = Path(novel_dir)
            else:
                novel_dir = NOVELS_DIR / novel_title.replace(' ', '_')
            
            roles_dir = novel_dir / "assets" / "roles"
            roles_dir.mkdir(parents=True, exist_ok=True)
            
            manager = CharacterPortraitManager(novel_dir)
            
            # 获取角色列表
            characters = []
            for char in novel.blueprint.characters:
                characters.append({
                    'id': char.id,
                    'name': char.name,
                    'appearance': getattr(char, 'appearance', '') or '',
                })
            
            # 列出缺少定妆照的角色
            missing = manager.list_missing_portraits(characters)
            
            if not missing:
                logger.info(f"所有角色已有定妆照")
            else:
                logger.info(f"开始生成 {len(missing)} 个角色定妆照...")
                
                for char in missing:
                    char_name = char.get('character_name', char.get('name', ''))
                    appearance = char.get('appearance', '')
                    
                    if not appearance:
                        continue
                    
                    try:
                        portrait_path = await self._generate_character_portrait(
                            char_name, appearance, roles_dir
                        )
                        if portrait_path:
                            logger.info(f"   ✅ 角色 {char_name} 定妆照已生成")
                    except Exception as e:
                        logger.warning(f"   ⚠️ 角色 {char_name} 定妆照生成失败: {e}")
            
            # 扫描 roles_dir 下所有已有的定妆照，加载到缓存
            self.character_portraits = {}
            for portrait_file in roles_dir.glob("*.png"):
                char_name = portrait_file.stem  # 文件名就是角色名
                self.character_portraits[char_name] = portrait_file
            
            if self.character_portraits:
                logger.info(f"已加载 {len(self.character_portraits)} 个角色定妆照: {list(self.character_portraits.keys())}")
            
        except Exception as e:
            logger.warning(f"角色定妆照检查失败: {e}")
    
    async def _generate_character_portrait(
        self,
        character_name: str,
        appearance: str,
        output_dir: Path,
    ) -> Optional[Path]:
        """生成角色定妆照"""
        if not self.local_model:
            return None
        
        # 构建提示词
        translate_to_english = self.config.get("translate_to_english", True)
        translated_appearance = appearance
        if translate_to_english and self.llm_client:
            template = self.prompts.get("portrait_translation_task", "")
            if template:
                trans_prompt = template.format(appearance=appearance)
            else:
                trans_prompt = f"Translate the following character appearance to English for an image generation prompt. Output ONLY the English translation without quotes or explanations:\n{appearance}"
            
            try:
                response = await self.llm_client.generate(
                    prompt=trans_prompt,
                    system_prompt=self.prompts.get("translation_system", "You are a professional image prompt translator."),
                    max_tokens=1000
                )
                if response and response.content:
                    translated_appearance = response.content.strip()
            except Exception as e:
                logger.warning(f"翻译角色外貌失败，使用原文: {e}")

        prompt = f"portrait of {character_name}, {translated_appearance}"
        
        try:
            import torch
            from PIL import Image
            
            result = self.local_model(
                prompt=prompt,
                width=512,
                height=512,
                num_inference_steps=30,
                guidance_scale=15,
                generator=torch.Generator(device=self.device).manual_seed(42),
            )
            
            image = result.images[0]
            output_path = output_dir / f"{character_name}.png"
            image.save(output_path)
            
            return output_path
            
        except Exception as e:
            logger.warning(f"生成角色定妆照失败: {e}")
            return None

    async def _extract_scenes(self, chapter: Chapter, num_scenes: int) -> List[Dict]:
        """
        从章节内容中提取关键场景（增强版：包含分镜信息）
        
        Returns:
            场景列表，每个场景包含描述和分镜信息
        """
        # 检查是否启用分镜规划
        enable_storyboard = self.config.get("storyboard", {}).get("enabled", True)
        
        if not enable_storyboard:
            return await self._extract_scenes_simple(chapter, num_scenes)
        
        # 使用LLM分析章节内容，生成分镜
        template = self.prompts.get("scene_extraction_task", "")
        if template:
            prompt = template.format(
                num_scenes=num_scenes,
                title=chapter.title,
                content=chapter.content[:3000]
            )
        else:
            prompt = f"""请分析以下小说章节，提取{num_scenes}个分镜。
                    章节标题: {chapter.title}
                    章节内容:
                    {chapter.content[:3000]}...（后续省略）

                    每个分镜需要包含:
                    1. scene_description: 场景描述
                    2. shot_type: 镜头类型 (wide/medium/close-up/extreme close-up)
                    3. camera_movement: 镜头运动 (static/pan/tilt/dolly/crane)
                    4. composition: 构图 (centered/rule of thirds/leading lines)
                    5. lighting: 光线 (natural/dramatic/soft)
                    6. mood: 氛围 (tense/calm/dark/bright 等)
                    7. duration: 建议展示时长(秒)
                    8. key_elements: 关键元素列表
                    9. characters_present: 出现的角色列表
                    10. setting: 具体场景地点

                    输出JSON格式:
                    [
                        {{
                            "scene_number": 1,
                            "description": "场景描述",
                            "shot_type": "wide",
                            "camera_movement": "static",
                            "composition": "rule of thirds",
                            "lighting": "dramatic",
                            "mood": "tense",
                            "duration": 8.0,
                            "key_elements": ["元素1", "元素2"],
                            "characters_present": ["角色名1"],
                            "setting": "场景地点"
                        }}
                    ]"""

        response = await self.llm_client.generate(
            prompt=prompt,
            system_prompt=self.prompts.get("scene_extraction_system", "你是专业的电影分镜师和视觉场景分析师，擅长从文字中提取画面感和设计分镜。"),
            max_tokens=4000,
        )
        
        # 解析JSON
        try:
            scenes = self._extract_json(response.content)
            return scenes[:num_scenes]
        except Exception as e:
            logger.warning(f"分镜提取失败，使用简单模式: {e}")
            return await self._extract_scenes_simple(chapter, num_scenes)

    async def _extract_scenes_simple(self, chapter: Chapter, num_scenes: int) -> List[Dict]:
        """简单场景提取（无分镜信息）"""
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
                ]

                要求:
                1. 场景要有视觉冲击力，适合画成插画
                2. 描述要详细，包含环境、人物姿态、光影等
                3. 优先选择有爽点、冲突、转折的关键场景"""

        response = await self.llm_client.generate(
            prompt=prompt,
            system_prompt="你是专业的视觉场景分析师，擅长从文字中提取画面感。",
            max_tokens=4000,
        )
        
        try:
            scenes = self._extract_json(response.content)
            return scenes[:num_scenes]
        except Exception as e:
            logger.warning(f"场景提取失败，使用默认场景: {e}")
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
    
    async def _generate_single_image(
        self,
        scene: Dict,
        chapter_number: int,
        image_index: int,
        characters: List[Character],
    ) -> GeneratedImage:
        """
        生成单张图像

        支持：
        1. 本地SD模型
        2. 云端API（未来扩展）
        """
        # 尝试从缓存加载 prompt
        prompt_text = None
        scene_number = scene.get("scene_number", image_index)

        if self.preprocessor:
            cached_prompt = self.preprocessor.load_cached_prompt(chapter_number, scene_number, image_index)
            if cached_prompt and cached_prompt.get("prompt"):
                logger.debug(f"从缓存加载 prompt: 第{chapter_number}章 场景{scene_number}")
                prompt_text = cached_prompt["prompt"]

        # 如果没有缓存，则构建 prompt
        if not prompt_text:
            translate_to_english = self.config.get("translate_to_english", True)
            prompt_text = await self._build_image_prompt(scene, characters, translate_to_english)

        # 获取标识符用于命名
        shot_id = scene.get("shot_id")
        scene_id = scene.get("scene_id")

        # 生成图像
        if self.local_model and self.config.get("local", {}).get("enabled"):
            # 使用本地模型
            image_path = await self._generate_with_local_model(
                prompt=prompt_text,
                chapter_number=chapter_number,
                image_index=image_index,
                shot_id=shot_id,
                scene_id=scene_id,
                scene=scene,
            )
        else:
            # 使用模拟/占位图
            image_path = await self._generate_placeholder(
                prompt=prompt_text,
                chapter_number=chapter_number,
                image_index=image_index,
                shot_id=shot_id,
                scene_id=scene_id
            )
        
        # 创建图像记录
        return GeneratedImage(
            image_id=f"ch{chapter_number}_img{image_index}",
            chapter_number=chapter_number,
            scene_description=scene.get("description", ""),
            prompt=prompt_text,
            file_path=str(image_path),
            width=self.config.get("local", {}).get("width", 1024),
            height=self.config.get("local", {}).get("height", 1024),
            seed=42,  # 固定种子便于复现
            generation_time=0.0,
        )
    
    async def _build_image_prompt(
        self,
        scene: Dict,
        characters: List[Character],
        translate_to_english: bool = True,
    ) -> str:
        """
        构建图像生成prompt（增强版：使用分镜信息）

        Args:
            scene: 场景信息字典
            characters: 角色列表
            translate_to_english: 是否翻译为英文
        """
        # 获取场景中出现的角色
        character_names = scene.get("characters_present", [])

        # 基础场景信息
        base_description = scene.get("description", "")
        mood = scene.get("mood", "dramatic")
        setting = scene.get("setting", "")
        shot_type = scene.get("shot_type")
        camera_movement = scene.get("camera_movement")
        composition = scene.get("composition")
        lighting = scene.get("lighting")

        # 根据翻译设置处理场景描述
        if translate_to_english and base_description or setting:
            translation_prompt = f"""Translate the following Chinese scene description to English for AI image generation.
                        Keep it concise but detailed enough for image generation. Focus on visual elements, scenery, and atmosphere.

                        Scene: {base_description}
                        Setting: {setting}
                        Mood: {mood}

                        Output ONLY the translated English text, nothing else."""

            try:
                response = await self.llm_client.generate(
                    prompt=translation_prompt,
                    system_prompt="You are a professional translator specializing in visual arts and image generation prompts.",
                    max_tokens=500,
                )
                if response and response.content:
                    translated_scene = response.content.strip()
                else:
                    logger.warning("翻译返回为空，使用原文")
                    translated_scene = base_description
            except Exception as e:
                logger.warning(f"翻译场景描述失败，使用原文: {e}")
                translated_scene = base_description
        else:
            translated_scene = base_description if not translate_to_english else ""

        # 处理角色外观描述
        character_prompts = []
        for char_name in character_names:
            for char in characters:
                if char.name in char_name or char_name in char.name:
                    appearance = char.appearance

                    if translate_to_english:
                        # 翻译角色外观描述
                        char_translation_prompt = f"""Translate the following Chinese character appearance description to English.
                                Focus on visual details: clothing, hairstyle, facial features, accessories, etc.

                                Chinese: {appearance}

                                Output ONLY the translated English text."""

                        try:
                            response = await self.llm_client.generate(
                                prompt=char_translation_prompt,
                                system_prompt="You are a professional translator specializing in character appearance descriptions.",
                                max_tokens=300,
                            )
                            if response and response.content:
                                translated_appearance = response.content.strip()
                                character_prompts.append(f"{char.name}: {translated_appearance}")
                            else:
                                logger.warning(f"角色 {char.name} 翻译返回为空，使用原文")
                                character_prompts.append(f"{char.name}: {appearance}")
                        except Exception as e:
                            logger.warning(f"角色 {char.name} 描述翻译失败，使用原文: {e}")
                            character_prompts.append(f"{char.name}: {appearance}")
                    else:
                        # 不翻译，直接使用中文
                        character_prompts.append(f"{char.name}: {appearance}")
                    break

        # 构建prompt
        prompt_parts = []

        if translate_to_english:
            # 英文模式
            prompt_parts.append("masterpiece, best quality, highly detailed,")

            if translated_scene:
                prompt_parts.append(f"scene: {translated_scene}")

            if character_prompts:
                prompt_parts.append("characters: " + "; ".join(character_prompts))

            # 翻译氛围关键词
            mood_map = {
                "紧张": "tense, dramatic",
                "平静": "peaceful, calm",
                "黑暗": "dark, mysterious",
                "明亮": "bright, luminous",
                "温馨": "warm, cozy",
                "恐怖": "horror, terrifying",
                "浪漫": "romantic",
                "壮丽": "grand, majestic",
                "神秘": "mysterious, mystical",
                "热血": "action-packed, dynamic",
            }
            english_mood = mood_map.get(mood, mood)
            prompt_parts.append(f"atmosphere: {english_mood}")

            if setting:
                prompt_parts.append(f"setting: {setting}")

            # 添加分镜信息（英文）
            if shot_type:
                shot_type_map = {
                    "wide": "wide shot, full view",
                    "medium": "medium shot",
                    "close-up": "close-up shot",
                    "extreme close-up": "extreme close-up"
                }
                prompt_parts.append(shot_type_map.get(shot_type, shot_type))

            if composition:
                comp_map = {
                    "centered": "centered composition",
                    "rule of thirds": "rule of thirds composition",
                    "leading lines": "leading lines composition"
                }
                prompt_parts.append(comp_map.get(composition, composition))

            if lighting:
                light_map = {
                    "natural": "natural lighting",
                    "dramatic": "dramatic lighting, high contrast",
                    "soft": "soft lighting"
                }
                prompt_parts.append(light_map.get(lighting, lighting))

            # 艺术风格
            prompt_parts.extend([
                "fantasy art style, digital painting, cinematic lighting,",
                "sharp focus,",
            ])
        else:
            # 中文模式
            prompt_parts.append("杰作，高质量，精细画面，")

            if translated_scene:
                prompt_parts.append(f"场景: {translated_scene}")

            if character_prompts:
                prompt_parts.append("角色: " + "; ".join(character_prompts))

            prompt_parts.append(f"氛围: {mood}")

            if setting:
                prompt_parts.append(f"场景: {setting}")

            # 添加分镜信息（中文）
            if shot_type:
                shot_type_cn = {
                    "wide": "远景",
                    "medium": "中景",
                    "close-up": "近景",
                    "extreme close-up": "特写"
                }
                prompt_parts.append(shot_type_cn.get(shot_type, shot_type))

            if composition:
                comp_cn = {
                    "centered": "中心构图",
                    "rule of thirds": "三分法构图",
                    "leading lines": "引导线构图"
                }
                prompt_parts.append(comp_cn.get(composition, composition))

            if lighting:
                light_cn = {
                    "natural": "自然光",
                    "dramatic": "戏剧性光线，高对比",
                    "soft": "柔和光线"
                }
                prompt_parts.append(light_cn.get(lighting, lighting))

            # 艺术风格
            prompt_parts.extend([
                "幻想艺术风格，数字绘画，电影级光照，",
                "8K超高清，清晰焦点，",
            ])

        return ", ".join(prompt_parts)

    async def _generate_with_local_model(
        self,
        prompt: str,
        chapter_number: int,
        image_index: int,
        shot_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        scene: Optional[Dict] = None,
    ) -> Path:
        """使用本地SD模型生成图像，支持 IP-Adapter 角色一致性"""
        if not self.local_model:
            raise ValueError("本地模型未加载")
        
        logger.debug("使用本地模型生成图像...")
        
        # 生成参数
        config = self.config["local"]
        width = config.get("width", 1024)
        height = config.get("height", 1024)
        steps = config.get("steps", 30)
        cfg_scale = config.get("cfg_scale", 7.5)
        
        gen_kwargs = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": cfg_scale,
            "generator": torch.Generator(device=self.device).manual_seed(42),
        }
        
        # 如果启用了角色一致性且有可用的定妆照，注入 IP-Adapter 参考图
        if self.character_consistency_enabled and scene:
            # 获取默认权重
            default_scale = self.config.get("character_consistency", {}).get("scale", 0.5)
            
            speaker = scene.get("speaker", "")
            matched_portrait = None
            
            if speaker and speaker != "narrator" and speaker in self.character_portraits:
                matched_portrait = self.character_portraits[speaker]
            else:
                # 尝试在 visual_prompt 或 description 中匹配角色名
                text_to_search = (scene.get("visual_prompt", "") + " " + scene.get("description", "")).lower()
                for char_name, portrait_path in self.character_portraits.items():
                    if char_name.lower() in text_to_search:
                        matched_portrait = portrait_path
                        break
            
            from PIL import Image as PILImage
            if matched_portrait and matched_portrait.exists():
                try:
                    # 匹配到角色：使用权重并加载图片
                    self.local_model.set_ip_adapter_scale(default_scale)
                    portrait_img = PILImage.open(matched_portrait).convert("RGB")
                    gen_kwargs["ip_adapter_image"] = portrait_img
                    logger.info(f"   🎭 使用角色定妆照: {matched_portrait.stem} (scale={default_scale})")
                except Exception as e:
                    logger.warning(f"   ⚠️ 加载定妆照失败: {e}，将使用空占位")
                    self.local_model.set_ip_adapter_scale(0.0)
                    gen_kwargs["ip_adapter_image"] = PILImage.new("RGB", (width, height), (0, 0, 0))
            else:
                # 未匹配到角色（如旁白或背景）：将 IP-Adapter 权重设为 0
                # 注意：一旦加载了 IP-Adapter，每一帧都必须传 ip_adapter_image，否则会报错
                self.local_model.set_ip_adapter_scale(0.0)
                gen_kwargs["ip_adapter_image"] = PILImage.new("RGB", (width, height), (0, 0, 0))
                logger.debug("   🎭 未检测到角色，IP-Adapter 已静默")
        
        # 生成图像
        result = self.local_model(**gen_kwargs)
        
        image = result.images[0]
        
        # 根据小说目录或全局设置确定保存路径
        novel_dir = self.config.get("novel_dir")
        if novel_dir:
            output_dir = Path(novel_dir) / "images" / f"chapter_{chapter_number:03d}"
        else:
            output_dir = IMAGES_DIR / f"chapter_{chapter_number:03d}"
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用 scene_id + shot_id 命名
        if scene_id and shot_id:
            file_name = f"{scene_id}_{shot_id}.png"
        elif shot_id:
            file_name = f"{shot_id}.png"
        elif scene_id:
            file_name = f"{scene_id}.png"
        else:
            file_name = f"image_{image_index:02d}.png"
            
        image_path = output_dir / file_name
        image.save(image_path)
        
        logger.info(f"   📸 图像生已保存: {image_path}")
        
        return image_path
    
    async def _generate_video_from_image(
        self,
        image_path: Path,
        chapter_number: int,
        video_index: int,
        scene_description: str = "",
    ) -> Path:
        """使用 SVD 模型从图像生成视频"""
        if not self.svd_model:
            raise ValueError("SVD 模型未加载")
        
        logger.debug("使用 SVD 生成视频...")
        
        # 加载图像
        from PIL import Image
        image = Image.open(image_path).convert("RGB")
        
        # 获取 SVD 配置
        svd_config = self.config.get("svd", {})
        num_frames = svd_config.get("frames", 24)
        motion_bucket_id = svd_config.get("motion_bucket_id", 127)
        fps = svd_config.get("fps", 24)
        noise_aug_strength = svd_config.get("noise_aug_strength", 0.02)
        decode_chunk_size = svd_config.get("decode_chunk_size", 8)
        
        # 生成视频
        result = self.svd_model(
            image,
            num_frames=num_frames,
            motion_bucket_id=motion_bucket_id,
            noise_aug_strength=noise_aug_strength,
            decode_chunk_size=decode_chunk_size,
            generator=torch.Generator(device=self.device).manual_seed(42),
        )
        
        # 根据小说目录或全局设置确定保存路径
        novel_dir = self.config.get("novel_dir")
        if novel_dir:
            output_dir = Path(novel_dir) / "videos" / f"chapter_{chapter_number:03d}"
        else:
            output_dir = VIDEOS_DIR / f"chapter_{chapter_number:03d}" if 'VIDEOS_DIR' in globals() else Path("outputs/videos") / f"chapter_{chapter_number:03d}"
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        video_path = output_dir / f"video_{video_index:02d}.mp4"
        
        # 使用 imageio 保存视频
        try:
            import imageio
            import numpy as np
            
            frames = []
            for frame in result.frames[0]:
                frames.append(np.array(frame))
            
            imageio.mimwrite(video_path, frames, fps=fps, quality=8)
            print(f"      ✅ 视频已保存: {video_path}")
            
        except ImportError:
            print(f"      ⚠️  imageio 未安装，保存帧为图片")
            # 作为备选，保存每一帧为图片
            for i, frame in enumerate(result.frames[0]):
                frame_path = output_dir / f"video_{video_index:02d}_frame_{i:03d}.png"
                frame.save(frame_path)
            video_path = output_dir / f"video_{video_index:02d}_frames"
            print(f"      ✅ 视频帧已保存到: {video_path}")
        
        return video_path
    
    async def _generate_placeholder(
        self,
        prompt: str,
        chapter_number: int,
        image_index: int,
        shot_id: Optional[str] = None,
        scene_id: Optional[str] = None,
    ) -> Path:
        """生成占位图像（当没有可用模型时）"""
        logger.info("生成占位图像（无可用AI模型）...")
        
        # 创建一个简单的占位图
        width = 1024
        height = 1024
        
        # 创建渐变色背景
        from PIL import Image, ImageDraw, ImageFont
        
        img = Image.new('RGB', (width, height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)
        
        # 添加文字
        display_id = scene_id or shot_id or f"Img {image_index}"
        text = f"Chapter {chapter_number}\n{display_id}\n\n[AI Image Placeholder]"
        
        # 尝试使用默认字体
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        except:
            font = ImageFont.load_default()
        
        # 计算文字位置（居中）
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        draw.text((x, y), text, fill='#eee', font=font)
        
        # 添加提示词摘要
        prompt_summary = prompt[:100] + "..." if len(prompt) > 100 else prompt
        draw.text((50, height - 100), f"Prompt: {prompt_summary}", fill='#888', font=font)
        
        # 根据小说目录或全局设置确定保存路径
        novel_dir = self.config.get("novel_dir")
        if novel_dir:
            output_dir = Path(novel_dir) / "images" / f"chapter_{chapter_number:03d}"
        else:
            output_dir = IMAGES_DIR / f"chapter_{chapter_number:03d}"
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用 scene_id + shot_id 命名
        if scene_id and shot_id:
            file_name = f"{scene_id}_{shot_id}_placeholder.png"
        elif shot_id:
            file_name = f"{shot_id}_placeholder.png"
        elif scene_id:
            file_name = f"{scene_id}_placeholder.png"
        else:
            file_name = f"image_{image_index:02d}_placeholder.png"
            
        image_path = output_dir / file_name
        img.save(image_path)
        
        logger.info(f"   📸 [占位图] 图像已保存: {image_path}")
        
        return image_path
    
    def _extract_json(self, content: str) -> any:
        """从文本中提取JSON"""
        import json
        import re
        
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取JSON块
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'\{.*\}',
            r'\[.*\]',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        raise ValueError(f"无法从响应中提取JSON")


class ImageGenerationPipeline(PipelineStage):
    """图像生成管道"""
    
    def __init__(self, config=None):
        super().__init__("图像生成", config or IMAGE_GENERATION)
        self.generator = ImageGenerator(config)
    
    def validate_input(self, input_data) -> bool:
        return self.generator.validate_input(input_data)
    
    async def process(self, novel: Novel) -> Dict[int, ChapterImages]:
        return await self.generator.process(novel)


# ========== 便捷函数 ==========

async def quick_generate_images(
    novel: Novel,
    images_per_chapter: int = 3,
) -> Dict[int, ChapterImages]:
    """
    快速生成图像的便捷函数
    """
    config = IMAGE_GENERATION.copy()
    config["images_per_chapter"] = images_per_chapter
    
    generator = ImageGenerator(config)
    return await generator.process(novel)


# ========== 测试代码 ==========

async def test_image_generator():
    """测试图像生成器"""
    print("🧪 测试图像生成器...")
    
    # 创建测试用的Novel对象（简化版）
    from stage1_novel.novel_generator import (
        Novel, StoryBlueprint, WorldBuilding, Character, Chapter,
        NovelConcept
    )
    
    # 创建简化的测试数据
    novel = Novel(
        metadata={
            "title": "测试小说",
            "genre": "修仙",
            "total_chapters": 1,
        },
        blueprint=StoryBlueprint(
            title="测试小说",
            genre="修仙",
            world_building=WorldBuilding(
                setting="修仙世界",
                power_system="炼气-筑基-金丹",
                factions=[],
                rules=["弱肉强食"],
            ),
            characters=[
                Character(
                    id="char_001",
                    name="林云",
                    role="protagonist",
                    description="废材少年",
                    personality="坚韧",
                    goals="成为最强",
                    background="被家族抛弃",
                    appearance="黑衣少年，剑眉星目，眼神坚定，手持长剑，英姿飒爽",
                )
            ],
            plot_structure=[],
            chapter_plans=[
                {"number": 1, "title": "觉醒", "summary": "主角获得传承", "key_events": ["觉醒"], "shuangdian": "获得金手指"}
            ],
        ),
        chapters=[
            Chapter(
                number=1,
                title="觉醒",
                content="林云站在悬崖边，心中充满了不甘...",
                word_count=5000,
                summary="主角获得上古传承",
                key_events=["觉醒"],
                character_appearances=["林云"],
            )
        ],
    )
    
    # 创建生成器（使用mock模式）
    config = IMAGE_GENERATION.copy()
    config["local"]["enabled"] = False  # 不使用本地模型
    config["images_per_chapter"] = 2
    
    generator = ImageGenerator(config)
    
    # 测试生成
    try:
        results = await generator.process(novel)
        print(f"\n✅ 测试成功！生成了 {len(results)} 章的图像")
        for chapter_num, chapter_images in results.items():
            print(f"   第{chapter_num}章: {len(chapter_images.images)} 张图像")
            for img in chapter_images.images:
                print(f"      - {img.file_path}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n✅ 图像生成器测试完成!")


if __name__ == "__main__":
    asyncio.run(test_image_generator())

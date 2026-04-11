#!/usr/bin/env python3
"""
模型下载和管理工具
支持下载 Stable Diffusion XL、IPAdapter 等模型
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import PROJECT_ROOT, IMAGE_MODELS_DIR, VIDEO_MODELS_DIR, SOUND_MODELS_DIR, LLM_MODELS_DIR

try:
    import torch
    from diffusers import StableDiffusionXLPipeline, DiffusionPipeline
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("⚠️  PyTorch/diffusers 未安装")


# 模型配置
MODEL_CONFIGS = {
    "sdxl": {
        "name": "Stable Diffusion XL Base",
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "description": "主图像生成模型",
        "required": True,
    },
    "sd3.5-medium": {
        "name": "Stable Diffusion 3.5 Medium",
        "repo_id": "stabilityai/stable-diffusion-3.5-medium",
        "description": "SD 3.5 系列中型模型",
        "required": False,
    },
    "sdxl-refiner": {
        "name": "Stable Diffusion XL Refiner",
        "repo_id": "stabilityai/stable-diffusion-xl-refiner-1.0",
        "description": "图像优化模型（可选）",
        "required": False,
    },
    "svd": {
        "name": "Stable Video Diffusion",
        "repo_id": "stabilityai/stable-video-diffusion-img2vid-xt",
        "description": "图生视频模型",
        "required": False,
    },
    "z-image-turbo": {
        "name": "Z-Image-Turbo",
        "repo_id": "Tongyi-MAI/Z-Image-Turbo",
        "description": "快速图像生成模型",
        "required": False,
    },
    "ip-adapter": {
        "name": "IP-Adapter",
        "repo_id": "h94/IP-Adapter",
        "description": "角色一致性模型 (IP-Adapter Plus)",
        "required": False,
    },
    "clip-vit-h": {
        "name": "CLIP ViT-H Image Encoder",
        "repo_id": "laion/CLIP-ViT-H-14-laion2B-s32B-b79K",
        "description": "IP-Adapter Plus 必备的图像编码器",
        "required": False,
    },
}

# 默认模型目录使用图片分类目录
MODELS_DIR = IMAGE_MODELS_DIR
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def download_model(
    model_type: str = "sdxl",
    cache_dir: Optional[Path] = None,
    use_fast_load: bool = True,
) -> bool:
    """
    下载模型（支持多种模型类型）

    Args:
        model_type: 模型类型
        cache_dir: 缓存目录
        use_fast_load: 是否使用快速加载选项

    Returns:
        是否下载成功
    """
    if not TORCH_AVAILABLE:
        print("❌ 需要先安装 PyTorch 和 diffusers")
        print("   运行: pip install torch diffusers transformers accelerate pillow")
        return False

    if model_type not in MODEL_CONFIGS:
        print(f"❌ 未知模型类型: {model_type}")
        print(f"   可用类型: {', '.join(MODEL_CONFIGS.keys())}")
        return False

    config = MODEL_CONFIGS[model_type]
    
    # 自动根据类型分配目录
    if not cache_dir:
        if model_type == "svd":
            cache_dir = VIDEO_MODELS_DIR
        else:
            cache_dir = IMAGE_MODELS_DIR

    print(f"🔄 开始下载: {config['name']}")
    print(f"   来源: {config['repo_id']}")
    print(f"   缓存目录: {cache_dir}")

    try:
        # 检测设备
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 根据模型类型选择合适的数据类型
        if model_type in ["z-image-turbo", "sd3.5-medium"]:
            torch_dtype = torch.bfloat16 if device == "cuda" else torch.float32
        else:
            torch_dtype = torch.float16 if device == "cuda" else torch.float32

        print(f"   设备: {device}")
        print(f"   数据类型: {torch_dtype}")

        # 根据模型类型下载并加载模型
        if model_type == "ip-adapter":
            from huggingface_hub import snapshot_download
            snapshot_download(
                repo_id=config['repo_id'],
                allow_patterns=["*.safetensors", "sdxl_models/*", "models/*"],
                cache_dir=str(cache_dir),
                local_dir_use_symlinks=False
            )
            print(f"✅ {config['name']} 下载成功!")
            return True
        elif model_type == "clip-vit-h":
            from transformers import CLIPVisionModelWithProjection
            CLIPVisionModelWithProjection.from_pretrained(
                config['repo_id'], 
                cache_dir=str(cache_dir)
            )
            print(f"✅ {config['name']} 下载成功!")
            return True

        load_kwargs = {
            "torch_dtype": torch_dtype,
            "use_safetensors": True,
            "cache_dir": str(cache_dir),
        }

        if model_type == "sdxl":
            pipeline = StableDiffusionXLPipeline.from_pretrained(
                config["repo_id"],
                **load_kwargs
            )
        else:
            pipeline = DiffusionPipeline.from_pretrained(
                config["repo_id"],
                **load_kwargs
            )

        print(f"✅ {config['name']} 下载/加载成功!")
        return True

    except Exception as e:
        print(f"❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def download_sdxl_model(
    model_type: str = "sdxl",
    cache_dir: Optional[Path] = None,
    use_fast_load: bool = True,
) -> bool:
    """
    兼容性函数 - 调用 download_model
    """
    return download_model(model_type, cache_dir, use_fast_load)


def download_svd_model(cache_dir: Optional[Path] = None) -> bool:
    """
    下载 SVD (Stable Video Diffusion) 图生视频模型

    Args:
        cache_dir: 缓存目录

    Returns:
        是否下载成功
    """
    return download_model("svd", cache_dir)


def check_model_exists(model_type: str, cache_dir: Optional[Path] = None) -> bool:
    """
    检查模型是否已存在

    Args:
        model_type: 模型类型
        cache_dir: 缓存目录

    Returns:
        模型是否存在
    """
    cache_dir = cache_dir or MODELS_DIR

    if model_type not in MODEL_CONFIGS:
        return False

    # 检查缓存目录中是否有该模型
    repo_id = MODEL_CONFIGS[model_type]["repo_id"]
    # HuggingFace 缓存结构: models--org--name
    model_dir_name = repo_id.replace("/", "--")
    model_dir = cache_dir / f"models--{model_dir_name}"

    if model_dir.exists():
        # 检查是否有 snapshot 目录
        snapshots = list(model_dir.glob("snapshots/*"))
        if snapshots:
            return True

    return False


def list_models(cache_dir: Optional[Path] = None):
    """列出所有模型状态"""
    cache_dir = cache_dir or MODELS_DIR

    print("=" * 60)
    print("📦 模型状态")
    print("=" * 60)

    for model_type, config in MODEL_CONFIGS.items():
        exists = check_model_exists(model_type, cache_dir)
        status = "✅ 已下载" if exists else "❌ 未下载"
        required = " (必需)" if config["required"] else " (可选)"
        print(f"\n{model_type}: {config['name']}{required}")
        print(f"   状态: {status}")
        print(f"   描述: {config['description']}")


def main():
    parser = argparse.ArgumentParser(description="AI小说平台模型管理工具")
    subparsers = parser.add_subparsers(dest="command", help="命令")

    # 下载命令
    download_parser = subparsers.add_parser("download", help="下载模型")
    download_parser.add_argument(
        "--model", "-m",
        choices=list(MODEL_CONFIGS.keys()),
        default="sd3.5-medium",
        help="要下载的模型类型",
    )
    download_parser.add_argument(
        "--cache-dir", "-c",
        type=Path,
        default=MODELS_DIR,
        help="模型缓存目录",
    )

    # 检查命令
    list_parser = subparsers.add_parser("list", help="列出所有模型状态")
    list_parser.add_argument(
        "--cache-dir", "-c",
        type=Path,
        default=MODELS_DIR,
        help="模型缓存目录",
    )

    # 登录命令
    # login_parser = subparsers.add_parser("login", help="登录 Hugging Face (下载 gated 模型必需)")
    # login_parser.add_argument(
    #     "--token", "-t",
    #     help="Hugging Face API Token",default='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'
    # )

    args = parser.parse_args()

    from huggingface_hub import login
    login(token='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')
    print("✅ 登录成功!")

    
    if args.command == "download":
        success = download_model(
            model_type=args.model,
            cache_dir=args.cache_dir,
        )
        sys.exit(0 if success else 1)

    elif args.command == "list":
        list_models(args.cache_dir)

    else:
        parser.print_help()


def download():
    import torch
    from diffusers import DiffusionPipeline

    # switch to "mps" for apple devices
    pipe = DiffusionPipeline.from_pretrained("Tongyi-MAI/Z-Image-Turbo", torch_dtype=torch.bfloat16, 
        low_cpu_mem_usage=True,
        device_map="cuda", cache_dir=str(IMAGE_MODELS_DIR))

    prompt = "Astronaut in a jungle, cold color palette, muted colors, detailed, 720P"
    image = pipe(prompt).images[0]
    image.save("example.png")

def test():
    import torch
    from diffusers import ZImagePipeline

    # 1. Load the pipeline
    # Use bfloat16 for optimal performance on supported GPUs
    pipe = ZImagePipeline.from_pretrained(
        "Tongyi-MAI/Z-Image-Turbo",
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=False,
        cache_dir=str(IMAGE_MODELS_DIR)
    )
    pipe.to("cuda")

    # [Optional] Attention Backend
    # Diffusers uses SDPA by default. Switch to Flash Attention for better efficiency if supported:
    # pipe.transformer.set_attention_backend("flash")    # Enable Flash-Attention-2
    # pipe.transformer.set_attention_backend("_flash_3") # Enable Flash-Attention-3

    # [Optional] Model Compilation
    # Compiling the DiT model accelerates inference, but the first run will take longer to compile.
    # pipe.transformer.compile()

    # [Optional] CPU Offloading
    # Enable CPU offloading for memory-constrained devices.
    # pipe.enable_model_cpu_offload()

    prompt = "Young Chinese woman in red Hanfu, intricate embroidery. Impeccable makeup, red floral forehead pattern. Elaborate high bun, golden phoenix headdress, red flowers, beads. Holds round folding fan with lady, trees, bird. Neon lightning-bolt lamp (⚡️), bright yellow glow, above extended left palm. Soft-lit outdoor night background, silhouetted tiered pagoda (西安大雁塔), blurred colorful distant lights."

    # 2. Generate Image
    image = pipe(
        prompt=prompt,
        height=720,
        width=1280,
        num_inference_steps=9,  # This actually results in 8 DiT forwards
        guidance_scale=0.0,     # Guidance should be 0 for the Turbo models
        generator=torch.Generator("cuda").manual_seed(42),
    ).images[0]

    image.save("example.png")

def download_ipadpater():
    import torch
    from diffusers import DiffusionPipeline

    # switch to "mps" for apple devices
    pipe = DiffusionPipeline.from_pretrained("h94/IP-Adapter", dtype=torch.bfloat16, device_map="cuda", cache_dir=str(IMAGE_MODELS_DIR))

    prompt = "Astronaut in a jungle, cold color palette, muted colors, detailed, 720P"
    image = pipe(prompt).images[0]
    image.save("example.png")

if __name__ == "__main__":
    main()

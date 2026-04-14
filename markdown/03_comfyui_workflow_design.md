# 03_ComfyUI Workflow 设计

## 一、ComfyUI 部署架构

### 1.1 部署模式

ComfyUI 作为独立进程运行，独立占用 VRAM，不与 LLM 争抢资源：

```
┌─────────────────────────────────────────────────────┐
│  ComfyUI 独立进程 (:8188)                          │
│  模型: SDXL + SVD + InstantID                      │
│  VRAM: ~4-6GB (分时复用)                          │
└─────────────────────────────────────────────────────┘
                          ↕ HTTP/WebSocket
                          │
┌─────────────────────────────────────────────────────┐
│  API Gateway (:9000) 或 run_pipeline.py            │
└─────────────────────────────────────────────────────┘
```

### 1.2 启动命令

```bash
# 启动 ComfyUI（独立进程）
cd /path/to/ComfyUI
python main.py --listen 0.0.0.0 --port 8188 --disable-smart-memory

# 可选：指定模型路径
# python main.py --listen 0.0.0.0 --port 8188 --extra-model-paths /path/to/models
```

### 1.3 24GB VRAM 预算分配

```
系统/OS:                ~2GB
SDXL (fp16):           ~3.5GB
InstantID:             ~0.3GB
SVD (fp16):           ~3.0GB
中间激活/缓存:          ~1-2GB
────────────────────────────
总峰值:                ~9-10GB (留 14GB 给系统)
```

**策略**: SDXL 和 SVD 不同时加载，分时复用。

---

## 二、工作流设计

### 2.1 需要的 Workflow 类型

| Workflow | 用途 | 输入 | 输出 |
|----------|------|------|------|
| `t2i_flux` | 文生图 (角色/场景) | text prompt | image |
| `i2v_svd` | 图生视频 | image + motion prompt | video |
| `t2v_wan` | 文生视频 (备选) | text prompt | video |
| `character_portrait` | 角色定妆照 | character prompt + ref | consistent character image |
| `scene_generation` | 场景生成 | scene prompt + ref | consistent scene image |

### 2.2 核心 Workflow: T2I (角色定妆照)

```
┌──────────────────────────────────────────────────────────────────┐
│                    T2I: 角色定妆照生成                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐       │
│  │  Load       │    │  CLIP       │    │  CLIP        │       │
│  │  Checkpoint │───▶│  TextEncode │    │  TextEncode  │       │
│  │  (SDXL)     │    │  (Positive) │    │  (Negative)  │       │
│  └─────────────┘    └──────┬──────┘    └──────┬───────┘       │
│                             │                   │               │
│                             ▼                   ▼               │
│                      ┌─────────────────────────────┐            │
│                      │         K-Sampler           │            │
│                      │   (steps=30, cfg=7.0)        │            │
│                      └──────────────┬──────────────┘            │
│                                     │                           │
│                                     ▼                           │
│                      ┌─────────────────────────────┐            │
│                      │       VAE Decode             │            │
│                      └──────────────┬──────────────┘            │
│                                     │                           │
│                                     ▼                           │
│                      ┌─────────────────────────────┐            │
│                      │      Save Image            │            │
│                      │  (portrait_xxx.png)         │            │
│                      └─────────────────────────────┘            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**节点 ID (假设)**:
- `4`: CheckpointLoaderSimple
- `6`: CLIPTextEncode (positive)
- `7`: CLIPTextEncode (negative)
- `8`: EmptyLatentImage
- `9`: KSampler
- `10`: VAEDecode
- `11`: SaveImage

### 2.3 核心 Workflow: I2V (SVD 图生视频)

```
┌──────────────────────────────────────────────────────────────────┐
│                    I2V: SVD 图生视频                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐       │
│  │  Load       │    │  CLIP       │    │  SVD         │       │
│  │  Checkpoint │───▶│  TextEncode │    │ Img2VidCnet  │       │
│  │  (SVD model)│    │  (motion)   │    │              │       │
│  └─────────────┘    └──────┬──────┘    └──────┬───────┘       │
│                            │                   │               │
│                            │    ┌──────────────┘               │
│                            │    │                               │
│                            ▼    ▼                               │
│                      ┌─────────────────────────────┐            │
│                      │       VideoCombine           │            │
│                      │    (frames=25, fps=24)      │            │
│                      └──────────────┬──────────────┘            │
│                                     │                           │
│                                     ▼                           │
│                      ┌─────────────────────────────┐            │
│                      │      Save Video             │            │
│                      │  (shot_xxx.mp4)             │            │
│                      └─────────────────────────────┘            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.4 InstantID 人脸一致性

```
┌──────────────────────────────────────────────────────────────────┐
│              InstantID 人脸一致性 (替代 IP-Adapter)              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐                            │
│  │  Load       │    │  FaceAnaly  │                            │
│  │  Checkpoint │───▶│  sis        │                            │
│  │  (SDXL)     │    │  (InsightFace)                          │
│  └─────────────┘    └──────┬──────┘                            │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────┐    ┌──────┴──────┐    ┌──────────────┐       │
│  │  Load      │───▶│  InstantID  │───▶│  K-Sampler   │       │
│  │  Portrait  │    │  Apply     │    │              │       │
│  └─────────────┘    └────────────┘    └──────┬───────┘       │
│                                               │                │
│                                               ▼                │
│                                      ┌──────────────┐         │
│                                      │  VAE Decode  │         │
│                                      └──────┬───────┘         │
│                                             ▼                  │
│                                      ┌──────────────┐         │
│                                      │  Save Image  │         │
│                                      └──────────────┘         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、Workflow 导出规范

### 3.1 如何导出 Workflow

1. 在 ComfyUI 界面中设计完整工作流
2. 点击 "Save" 按钮导出 JSON
3. 将 JSON 文件复制到 `api_service/workflows/` 目录
4. 运行节点映射验证脚本

### 3.2 导出后必须记录的信息

导出的 workflow JSON 必须附带以下元数据：

```json
{
  "_meta": {
    "name": "T2I Flux Character Portrait",
    "version": "1.0",
    "author": "AI Novel Video",
    "created_at": "2026-04-14",
    "models": ["sd_xl_base_1.0.safetensors"],
    "description": "角色定妆照生成"
  },
  "_node_mapping": {
    "positive_prompt_node": "6",
    "negative_prompt_node": "7",
    "latent_image_node": "8",
    "ksampler_node": "9",
    "output_node": "11"
  },
  "_variable_nodes": {
    "prompt": {"node": "6", "field": "text"},
    "negative_prompt": {"node": "7", "field": "text"},
    "seed": {"node": "9", "field": "seed"},
    "steps": {"node": "9", "field": "steps"},
    "cfg": {"node": "9", "field": "cfg_scale"}
  },
  "_output_node": "11",
  "1": { ... },
  "2": { ... }
}
```

### 3.3 节点映射验证脚本

```python
#!/usr/bin/env python3
"""
验证 ComfyUI workflow 文件的节点映射是否正确
"""
import json
import sys
from pathlib import Path

def validate_workflow(workflow_path: Path) -> bool:
    with open(workflow_path, 'r') as f:
        wf = json.load(f)

    # 检查 _meta
    if "_meta" not in wf:
        print("❌ 缺少 _meta 元数据")
        return False

    # 检查 _node_mapping
    if "_node_mapping" not in wf:
        print("❌ 缺少 _node_mapping 节点映射")
        return False

    meta = wf["_meta"]
    mapping = wf["_node_mapping"]

    # 验证必需的节点
    required_nodes = ["positive_prompt_node", "negative_prompt_node",
                      "latent_image_node", "ksampler_node", "output_node"]

    for node_key in required_nodes:
        if node_key not in mapping:
            print(f"❌ 缺少节点映射: {node_key}")
            return False

        node_id = mapping[node_key]
        if node_id not in wf:
            print(f"❌ 映射的节点 ID {node_id} 不存在于 workflow 中")
            return False

    print(f"✅ Workflow 验证通过: {workflow_path.name}")
    print(f"   名称: {meta.get('name')}")
    print(f"   版本: {meta.get('version')}")
    print(f"   模型: {meta.get('models')}")
    return True

if __name__ == "__main__":
    workflow_dir = Path(__file__).parent.parent / "api_service" / "workflows"
    for wf_file in workflow_dir.glob("*.json"):
        if wf_file.stem.startswith("_"):
            continue
        print(f"\n验证: {wf_file.name}")
        validate_workflow(wf_file)
```

---

## 四、Backend 实现 (`backends/comfyui.py`)

### 4.1 节点映射注入

```python
def _patch_workflow(
    workflow: Dict,
    prompt: str,
    negative_prompt: str,
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    **kwargs
) -> Dict:
    """
    向 workflow 注入变量

    使用 _node_mapping 进行确定性节点定位，
    不依赖 _meta.title
    """
    wf = copy.deepcopy(workflow)
    mapping = wf.get("_node_mapping", {})
    var_nodes = wf.get("_variable_nodes", {})

    # 注入 positive prompt
    if "positive_prompt_node" in mapping:
        node_id = mapping["positive_prompt_node"]
        if node_id in wf and "inputs" in wf[node_id]:
            wf[node_id]["inputs"]["text"] = prompt

    # 注入 negative prompt
    if "negative_prompt_node" in mapping:
        node_id = mapping["negative_prompt_node"]
        if node_id in wf and "inputs" in wf[node_id]:
            wf[node_id]["inputs"]["text"] = negative_prompt

    # 注入 seed
    if "seed" in var_nodes:
        node_id = var_nodes["seed"]["node"]
        field = var_nodes["seed"]["field"]
        if node_id in wf and "inputs" in wf[node_id]:
            wf[node_id]["inputs"][field] = seed if seed >= 0 else random.randint(0, 2**32)

    # 注入 steps
    if "steps" in var_nodes:
        node_id = var_nodes["steps"]["node"]
        field = var_nodes["steps"]["field"]
        if node_id in wf and "inputs" in wf[node_id]:
            wf[node_id]["inputs"][field] = steps

    # 注入 cfg
    if "cfg" in var_nodes:
        node_id = var_nodes["cfg"]["node"]
        field = var_nodes["cfg"]["field"]
        if node_id in wf and "inputs" in wf[node_id]:
            wf[node_id]["inputs"][field] = cfg

    return wf
```

### 4.2 图像生成 API

```python
class ComfyUIImageBackend:
    """ComfyUI 图像生成后端"""

    def __init__(self, base_url: str = "http://localhost:8188"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300)

    async def generate(
        self,
        prompt: str,
        workflow_name: str = "t2i_flux",
        negative_prompt: str = "blurry, low quality, bad anatomy",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int = -1,
        character_refs: List[str] = [],  # InstantID 参考图
        **kwargs
    ) -> List[Path]:
        """
        生成图像

        Returns:
            List of generated image paths
        """
        # 1. 加载 workflow 模板
        workflow = self._load_workflow(workflow_name)

        # 2. 处理 InstantID 参考图
        if character_refs:
            workflow = self._apply_instantid(workflow, character_refs)

        # 3. 注入变量
        workflow = _patch_workflow(
            workflow, prompt, negative_prompt,
            seed=seed, steps=steps, cfg=cfg,
            width=width, height=height
        )

        # 4. 提交任务
        task_id = await self._submit_prompt(workflow)

        # 5. 等待完成
        result = await self._wait_for_completion(task_id)

        # 6. 下载结果
        return await self._download_results(result)
```

### 4.3 视频生成 API

```python
class ComfyUIVideoBackend:
    """ComfyUI 视频生成后端 (SVD)"""

    async def generate(
        self,
        image_path: Path,
        motion_prompt: str = "",
        num_frames: int = 25,
        fps: int = 24,
        seed: int = -1,
        workflow_name: str = "i2v_svd"
    ) -> Path:
        """
        图生视频

        Args:
            image_path: 输入关键帧
            motion_prompt: 运动描述
            num_frames: 生成帧数 (14-24 for SVD)
            fps: 输出帧率

        Returns:
            Path to generated video
        """
        workflow = self._load_workflow(workflow_name)

        # 上传图像到 ComfyUI
        image_upload = await self._upload_image(image_path)

        # 注入变量
        workflow = _patch_workflow(
            workflow,
            prompt=motion_prompt,
            negative_prompt="",
            seed=seed,
            image_path=image_upload["name"]
        )

        # 提交并等待
        task_id = await self._submit_prompt(workflow)
        result = await self._wait_for_completion(task_id)

        return await self._download_video(result)
```

---

## 五、备选方案

### 5.1 VRAM 不足时的降级策略

| VRAM 剩余 | 可用模型 | 说明 |
|-----------|----------|------|
| ≥10GB | SDXL + SVD + InstantID | 完整功能 |
| ≥6GB | SDXL + InstantID (无 SVD) | 只能用 Ken Burns 效果 |
| ≥4GB | Z-Image-Turbo + InstantID | 质量降低，速度快 |
| <4GB | 仅 CPU FFmpeg Ken Burns | 仅静态图像拼接 |

### 5.2 InstantID 备选: 固定 Seed 策略

如果 InstantID 无法使用，可以用固定 seed 策略作为降级：

```python
def build_character_prompt_with_seed(character: Character, seed: int) -> str:
    """固定 seed 保证角色一致性"""
    return f"{character.appearance}, (masterpiece:1.2), best quality, seed={seed}"
```

### 5.3 视频生成备选: Ken Burns + FFmpeg

当 VRAM 不足无法运行 SVD 时，使用 FFmpeg Ken Burns 效果：

```bash
ffmpeg -loop 1 -i keyframe.png \
  -vf "zoompan=z='min(zoom+0.001,1.5)':d=125" \
  -t 5 -c:v libx264 -preset fast shot_output.mp4
```

---

*文档版本: v1.0*
*创建时间: 2026-04-14*

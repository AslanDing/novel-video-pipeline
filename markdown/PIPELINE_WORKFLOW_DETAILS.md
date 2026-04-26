# AI Novel Video Pipeline 工作流程详解

## 目录
1. [系统架构](#1-系统架构)
2. [服务启动流程](#2-服务启动流程)
3. [Phase 1: 小说生成](#3-phase-1-小说生成)
4. [Phase 2: 媒体生成](#4-phase-2-媒体生成)
5. [Phase 3: 视频合成](#5-phase-3-视频合成)
6. [Workflow 调用详解](#6-workflow-调用详解)
7. [ComfyUI Workflow 详解](#7-comfyui-workflow-详解)
8. [API 服务网关](#8-api-服务网关)
9. [配置说明](#9-配置说明)
10. [微调参数指南](#10-微调参数指南)

---

## 1. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户请求层                                  │
│                  run_pipeline.py / main.py                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API 服务网关 (FastAPI)                        │
│                   http://localhost:9000                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │  /llm   │ │ /image   │ │ /video   │ │  /tts   │  /bgm    │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘           │
└───────┼────────────┼────────────┼────────────┼──────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ NVIDIA NIM  │ │  ComfyUI    │ │  Edge TTS   │
│ LLM API      │ │  :8188      │ │  (本地)      │
│ gpt-oss-120b│ │  + Wan2.2   │ │             │
└──────────────┘ │  + Z-Image   │ └──────────────┘
                 │  + ACE-Step  │
                 └──────────────┘
```

### 核心组件

| 组件 | 地址 | 用途 |
|------|------|------|
| API Gateway | localhost:9000 | 统一路由、任务管理 |
| ComfyUI | localhost:8188 | 图像/视频/BGM生成 |
| NVIDIA NIM | cloud API | LLM文本生成 |
| Edge TTS | 本地 | 语音合成 |

---

## 2. 服务启动流程

### 启动顺序

```bash
# 1. 启动 ComfyUI (必须先启动)
cd ~/data/comfy/ComfyUI
python3 main.py --listen 0.0.0.0 --port 8188 &

# 2. 启动 API 网关 (需要加载 .env 环境变量)
cd ai-novel-video-v2
export $(grep -v '^#' .env | xargs)
uvicorn api_service.main:app --host 0.0.0.0 --port 9000 &
```

### 环境变量要求

```bash
# .env 文件必须包含:
NVIDIA_NIM_API_KEY=your_api_key_here
NVIDIA_NIM_MODEL=openai/gpt-oss-120b  # 或其他支持的模型
```

### 健康检查

```bash
curl http://localhost:9000/health
```

返回示例:
```json
{
  "healthy": true,
  "backends": [
    {"name": "llm (nvidia_nim)", "healthy": true},
    {"name": "image (comfyui)", "healthy": true},
    {"name": "video (comfyui)", "healthy": true},
    {"name": "tts (edge_tts)", "healthy": true},
    {"name": "bgm (ace_step)", "healthy": true}
  ]
}
```

---

## 3. Phase 1: 小说生成

### 执行命令

```bash
python run_pipeline.py --project-id "my_novel" --phase 1
```

### 工作流程

```
用户请求
    │
    ▼
API Gateway /llm/generate
    │
    ▼
NVIDIA NIM API (nemotron-3-super-120b-a12b 或 gpt-oss-120b)
    │
    ▼
生成小说文本 (约2000-5000字/章)
    │
    ▼
保存至 outputs/{project_id}/novel/chapter_1.txt
```

### LLM 提示词结构

```python
# 系统提示词
SYSTEM_PROMPT = """你是一个专业的小说作家，擅长创作修仙、玄幻类型的故事。
请根据用户需求生成小说内容，要求：
1. 情节紧凑，高潮迭起
2. 角色鲜明，对话生动
3. 场景描写丰富，画面感强
4. 每章3000-5000字"""

# 用户请求模板
USER_REQUEST = f"""为项目 {project_id} 创作一个修仙小说章节。
要求：
- 主角获得神秘传承
- 有战斗场面
- 有成长和突破
- 结尾有悬念"""
```

### 输出文件

```
outputs/{project_id}/novel/
└── chapter_1.txt    # 小说文本文件
```

---

## 4. Phase 2: 媒体生成

### 执行命令

```bash
python run_pipeline.py --project-id "my_novel" --phase 2 --chapter 1
```

### 工作流程总览

```
小说文本 (chapter_1.txt)
    │
    ├──────────────────────────────────────────────────────────────┐
    │                                                              │
    ▼                                                              ▼
┌───────────────┐                                          ┌───────────────┐
│  图像生成     │                                          │  TTS音频生成  │
│  (3张关键帧)  │                                          │  (分段落合成)  │
└───────┬───────┘                                          └───────┬───────┘
        │                                                              │
        └──────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   视频生成 (I2V)       │
                        │   Wan2.2 ImageToVideo  │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        outputs/{project_id}/videos/
```

### 4.1 图像生成

#### 调用流程

```
API: POST /image/generate
    │
    ▼
ComfyUI Workflow: t2i_z_image_turbo.json
    │
    ▼
Z-Image-Turbo (640x480, 20 steps)
    │
    ▼
保存至 outputs/images/novel_img_*.png
```

#### 图像生成参数

| 参数 | 默认值 | 说明 | 可调范围 |
|------|--------|------|----------|
| width | 640 | 图像宽度 | 256-2048 |
| height | 480 | 图像高度 | 256-2048 |
| steps | 20 | 采样步数 | 1-100 |
| cfg | 7.0 | CFG强度 | 1.0-20.0 |
| seed | -1 | 随机种子(-1=随机) | 0-999999999 |

#### 提示词策略

```python
# 正面提示词模板
POSITIVE_PROMPT = """{scene_description},
masterpiece, best quality, highly detailed, cinematic lighting,
dynamic pose, vivid colors"""

# 负面提示词
NEGATIVE_PROMPT = """blurry, low quality, bad anatomy, worst quality,
low resolution, distorted face, extra fingers"""
```

#### 场景提取逻辑

```python
# 从小说文本中提取3个关键场景
SCENES = [
    "玄幻修仙场景，神秘山洞，光芒照耀，云雾缭绕",
    "战斗场景，主角施展法术，能量爆发，特效光效",
    "修炼场景，打坐冥想，灵气汇聚，星空背景"
]
```

### 4.2 TTS音频生成

#### 调用流程

```
API: POST /tts/synthesize
    │
    ▼
Edge TTS (微软)
    │
    ▼
保存至 outputs/audio/tts_tts_*.mp3
```

#### TTS参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| voice | zh-CN-XiaoxiaoNeural | 中文女声 |
| rate | +0% | 语速调整 |
| pitch | +0Hz | 音高调整 |
| format | mp3 | 音频格式 |

#### 可用声音

```python
VOICE_MAPPING = {
    "narrator": "zh-CN-XiaoxiaoNeural",    # 叙述者
    "male_1": "zh-CN-YunxiNeural",          # 男声1
    "male_2": "zh-CN-YunjianNeural",        # 男声2
    "male_3": "zh-CN-YunyangNeural",        # 男声3
    "female_1": "zh-CN-XiaoyiNeural",       # 女声1
    "female_2": "zh-CN-liaoning-XiaobeiNeural",  # 女声2
    "female_3": "zh-CN-XiaohanNeural",       # 女声3
}
```

### 4.3 视频生成 (I2V)

#### 调用流程

```
上传图像至 ComfyUI: POST /upload/image
    │
    ▼
API: POST /video/generate
    │
    ▼
ComfyUI Workflow: i2v_wan22_simple.json
    │
    ▼
Wan2.2 I2V (81帧, 24fps)
    │
    ▼
保存至 outputs/videos/novel_video_*.mp4
```

#### 视频生成参数

| 参数 | 默认值 | 说明 | 微调建议 |
|------|--------|------|----------|
| num_frames | 81 | 生成帧数 | 13-161 (必须是4的倍数+1) |
| fps | 24 | 输出帧率 | 16-60 |
| width | 640 | 视频宽度 | 256-1920 |
| height | 480 | 视频高度 | 256-1080 |

---

## 5. Phase 3: 视频合成

### 执行命令

```bash
python run_pipeline.py --project-id "my_novel" --phase 3
```

### 工作流程

```
视频文件 (novel_video_*.mp4)
    │
    ├──────────────────┐
    │                  │
    ▼                  ▼
┌──────────┐    ┌──────────┐
│ BGM生成  │    │ 读取已有  │
│ ACE-Step │    │ 视频文件  │
└────┬─────┘    └────┬─────┘
     │                │
     │                ▼
     │         ┌──────────────┐
     │         │   FFmpeg     │
     │         │ 视频合成     │
     │         │ -i video     │
     │         │ -i audio     │
     │         │ -shortest    │
     │         └──────┬───────┘
     │                │
     └────────────────┼────────────────┘
                      │
                      ▼
           outputs/videos/synth_*.mp4
```

### 5.1 BGM生成

#### 调用流程

```
API: POST /bgm/generate
    │
    ▼
ComfyUI Workflow: bgm_ace_step.json
    │
    ▼
ACE-Step 1.5 模型
    │
    ▼
保存至 outputs/audio/bgm_*.mp3
```

#### BGM参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| prompt/tags | "Epic: A powerful..." | 音乐风格描述 |
| duration | 30秒 | 音乐时长 |
| bpm | 120 | 节拍速度 |
| seed | -1 | 随机种子 |

#### 音乐风格提示词

```python
BGM_TAGS_EXAMPLES = {
    "epic": "Epic: A powerful, cinematic orchestral track with dramatic buildups",
    "rock": "Rock: A powerful, high-energy modern rock track with distorted guitars",
    "ambient": "Ambient: A calm, atmospheric background music with soft pads",
    "action": "Action: Intense, fast-paced electronic music with powerful drums"
}
```

### 5.2 FFmpeg视频合成

#### 合成命令

```bash
ffmpeg -y \
  -i input_video.mp4 \
  -i input_audio.mp3 \
  -c:v copy \
  -c:a aac \
  -shortest \
  output.mp4
```

#### 参数说明

| 参数 | 说明 |
|------|------|
| -c:v copy | 保留原视频编码，不重新压缩 |
| -c:a aac | 音频转AAC编码 |
| -shortest | 以较短的为准结束 |

---

## 6. Workflow 调用详解

### 6.1 Workflow 文件位置

```
api_service/workflows/
├── t2i_z_image_turbo.json   # 图像生成 (文生图)
├── i2v_wan22_simple.json    # 视频生成 (图生视频 Wan2.2)
├── bgm_ace_step.json       # BGM生成 (ACE-Step 1.5)
├── i2v_wan.json            # 旧版视频生成 (已废弃)
├── synthesize_video.json    # 视频合成
├── t2i_flux.json           # Flux模型文生图
└── video_ltx2_3_i2v.json   # LTX视频模型(未使用)
```

### 6.2 Workflow 加载流程

```
调用链:
API Router (routers/image.py)
    │
    ▼
backend.generate_image()
    │
    ▼
_load_workflow(wf_name)  ← 从 api_service/workflows/ 加载JSON
    │
    ▼
_patch_image_workflow()   ← 注入用户参数 (prompt, seed, steps等)
    │
    ▼
_submit_workflow()        ← POST /prompt → ComfyUI
    │
    ▼
_wait_for_prompt()        ← WebSocket 监听执行完成
    │
    ▼
_get_output_files()       ← GET /history/{prompt_id}
    │
    ▼
_download_file()          ← 下载生成的文件到本地
```

### 6.3 核心代码路径

#### 1. 加载 Workflow (`api_service/backends/comfyui.py`)

```python
# 第27行: Workflow目录定义
_WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"

# 第30-36行: 加载函数
def _load_workflow(name: str) -> Dict:
    """从 api_service/workflows/ 加载 JSON workflow 模板"""
    path = _WORKFLOW_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"ComfyUI workflow not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

#### 2. 注入参数 (`_patch_image_workflow`, `_patch_video_workflow`, `_patch_bgm_workflow`)

```python
# 参数注入逻辑 - 通过 node title 或 class_type 匹配
for node_id, node in wf.items():
    meta = node.get("_meta", {})
    title = meta.get("title", "").lower()  # 从 _meta.title 获取
    class_type = node.get("class_type", "")  # 节点类型

    # 示例: 注入正面提示词
    if "positive" in title and "text" in inputs:
        inputs["text"] = prompt

    # 示例: 注入采样参数
    elif "sampler" in title or class_type == "KSampler":
        inputs["seed"] = seed
        inputs["steps"] = steps
        inputs["cfg"] = cfg
```

#### 3. 提交到 ComfyUI

```python
# 第237-251行: 提交workflow
async def _submit_workflow(self, workflow: Dict) -> str:
    def clean_workflow(w):
        # 移除 _ 开头的键 (如 _meta, _comment)
        if isinstance(w, dict):
            return {k: clean_workflow(v) for k, v in w.items() if not k.startswith('_')}
        elif isinstance(w, list):
            return [clean_workflow(i) for i in w]
        return w

    clean_wf = clean_workflow(workflow)
    payload = {"prompt": clean_wf, "client_id": self.client_id}
    resp = await self._http.post("/prompt", json=payload)
    resp.raise_for_status()
    return resp.json()["prompt_id"]
```

#### 4. 等待执行完成

```python
# 第253-274行: WebSocket 等待
async def _wait_for_prompt(self, prompt_id: str) -> None:
    ws_url = f"{self.base_url}/ws?clientId={self.client_id}"
    async with websockets.connect(ws_url, max_size=None) as ws:
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] in ("executed", "execution_success"):
                return
            if msg["type"] == "execution_error":
                raise RuntimeError(f"ComfyUI error: {msg['data']}")
```

### 6.4 API Router 调用示例

#### 图像生成 (`routers/image.py`)

```python
@router.post("/generate")
async def generate_image(req: ImageRequest, background_tasks: BackgroundTasks):
    # 1. 创建任务
    task_id = await mgr.create_task("img")

    # 2. 后台执行 (不阻塞)
    background_tasks.add_task(_run_image_generation, task_id, req)

    # 3. 立即返回 task_id
    return ImageResponse(task_id=task_id, status=TaskStatus.queued)

async def _run_image_generation(task_id: str, req: ImageRequest):
    # 实际生成逻辑
    backend = get_image_backend()
    paths, seed = await backend.generate_image(
        prompt=req.prompt,
        width=req.width,
        height=req.height,
        steps=req.steps,
        cfg=req.cfg,
        ...
    )
    # 更新任务状态
    await mgr.set_completed(task_id, result)
```

#### 视频生成 (`routers/video.py`)

```python
@router.post("/generate")
async def generate_video(req: VideoRequest, background_tasks: BackgroundTasks):
    task_id = await mgr.create_task("vid")
    background_tasks.add_task(_run_video_generation, task_id, req)
    return VideoResponse(task_id=task_id, status=TaskStatus.queued)

async def _run_video_generation(task_id: str, req: VideoRequest):
    backend = get_video_backend()

    # 先上传图像到 ComfyUI
    image_path = _resolve_image_path(req.image_url)  # URL → 本地Path
    upload_name = await backend._upload_image(image_path)  # 上传

    # 调用生成 (使用 i2v_wan22_simple.json)
    paths, seed = await backend.generate_video(
        image_path=upload_name,  # 使用上传后的文件名
        ...
    )
```

#### BGM生成 (`routers/bgm.py`)

```python
@router.post("/generate")
async def generate_bgm_endpoint(req: BGMRequest, background_tasks: BackgroundTasks):
    task_id = await mgr.create_task("bgm")
    background_tasks.add_task(_run_bgm_generation, task_id, req)
    return BGMResponse(task_id=task_id, status=TaskStatus.queued)

async def _run_bgm_generation(task_id: str, req: BGMRequest):
    # 直接调用 (不走Backend单例)
    from api_service.backends.comfyui import generate_bgm
    paths, _ = await generate_bgm(
        tags=req.prompt,
        duration=req.duration_seconds,
        ...
    )
```

### 6.5 配置指定 Workflow

`config/api_services.json` 中指定各后端使用的默认workflow:

```json
{
  "backends": {
    "image": {
      "type": "comfyui",
      "default_workflow": "t2i_z_image_turbo"
    },
    "video": {
      "type": "comfyui",
      "default_workflow": "i2v_wan22_simple"
    },
    "bgm": {
      "type": "comfyui",
      "default_workflow": "bgm_ace_step"
    }
  }
}
```

### 6.6 自定义 Workflow 调用

如需使用其他 workflow, 可在 API 请求中指定:

```bash
# 使用自定义 workflow
curl -X POST http://localhost:9000/image/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a beautiful landscape",
    "workflow": "t2i_flux"
  }'
```

### 6.7 Workflow JSON 结构

```json
{
  "_comment": "注释信息",
  "_meta": {
    "title": "节点标题",    // 用于 _patch_* 函数的 title 匹配
    "description": "描述"
  },
  "1": {
    "inputs": {
      "param_name": "value"  // 节点输入参数
    },
    "class_type": "NodeType"  // 节点类型
  },
  "2": { ... }
}
```

**关键约定**:
- `_meta.title` 用于标识可注入参数的节点
- `_` 开头的键会在提交前被移除
- `inputs` 中使用 `[node_id, slot_index]` 格式表示节点链接

---

## 7. ComfyUI Workflow 详解

### 7.1 图像生成 Workflow (t2i_z_image_turbo.json)

```
┌─────────────────┐
│ CheckpointLoader │ → v1-5-pruned-emaonly-fp16.safetensors
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│CLIPEnc │ │CLIPEnc │ (正面/负面提示词)
│(+text) │ │(-text) │
└───┬────┘ └───┬────┘
    │           │
    └─────┬─────┘
          │
          ▼
┌─────────────────┐
│  EmptyLatent    │ → 640x480x1 latent
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    KSampler     │ → 20步, cfg=7.0, euler
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   VAEDecode     │ → latent → image
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   SaveImage     │ → outputs/images/
└─────────────────┘
```

### 7.2 视频生成 Workflow (i2v_wan22_simple.json)

```
┌─────────────┐
│  LoadImage  │ → 输入图像
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ CLIPLoader  │ → umt5_xxl_fp8_e4m3fn_scaled
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│ UNETLoader  │     │ UNETLoader  │ → high/low noise
│ (high)      │     │ (low)       │
└──────┬──────┘     └──────┬──────┘
       │                   │
       ▼                   ▼
┌─────────────┐     ┌─────────────┐
│ModelSample  │     │ModelSample  │ → shift=5.0
│SD3 (high)   │     │SD3 (low)    │
└──────┬──────┘     └──────┬──────┘
       │                   │
       └─────────┬─────────┘
                 │
                 ▼
          ┌─────────────┐
          │WanImageTo   │ → latent输出
          │Video        │
          └──────┬──────┘
                 │
                 ▼
          ┌─────────────┐
          │ KSamplerAdv  │ → 高噪声阶段
          │ (4步, cfg=3.5)│
          └──────┬──────┘
                 │
                 ▼
          ┌─────────────┐
          │ KSamplerAdv  │ → 低噪声阶段
          │ (4步, cfg=1.0)│
          └──────┬──────┘
                 │
                 ▼
          ┌─────────────┐
          │ VAEDecode   │ → video latent → images
          └──────┬──────┘
                 │
                 ▼
          ┌─────────────┐
          │ CreateVideo │ → 添加fps
          └──────┬──────┘
                 │
                 ▼
          ┌─────────────┐
          │ SaveVideo   │ → outputs/videos/
          └─────────────┘
```

### 7.3 BGM生成 Workflow (bgm_ace_step.json)

```
┌──────────────┐
│  UNETLoader  │ → acestep_v1.5_turbo.safetensors
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ DualCLIPLoader│ → qwen_0.6b + qwen_4b
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   VAELoader  │ → ace_1.5_vae.safetensors
└──────┬───────┘
       │
       ▼
┌──────────────────────────────┐
│  EmptyAceStep1.5LatentAudio  │ → 时长设置
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│   TextEncodeAceStepAudio1.5  │ → tags + lyrics
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      ConditioningZeroOut     │ → 负向条件清零
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│       ModelSamplingAuraFlow  │ → shift=3
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│         KSampler           │ → 8步, euler
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      VAEDecodeAudio         │ → latent → audio
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│       SaveAudioMP3          │ → outputs/audio/
└──────────────────────────────┘
```

---

## 8. API 服务网关

### 端点一览

| 端点 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 服务健康检查 |
| `/llm/generate` | POST | LLM文本生成 |
| `/llm/stream` | POST | LLM流式生成 |
| `/image/generate` | POST | 图像生成 |
| `/image/tasks/{id}` | GET | 查询图像任务 |
| `/video/generate` | POST | 视频生成 |
| `/video/tasks/{id}` | GET | 查询视频任务 |
| `/tts/synthesize` | POST | TTS合成 |
| `/tts/tasks/{id}` | GET | 查询TTS任务 |
| `/bgm/generate` | POST | BGM生成 |
| `/bgm/tasks/{id}` | GET | 查询BGM任务 |
| `/video/synthesize` | POST | 视频+音频合成 |
| `/files/{path}` | GET | 文件下载 |

### 任务轮询机制

```python
# 任务状态查询
async def wait_for_task(task_id, poll_interval=2.0, max_wait=300.0):
    start = time.monotonic()
    while time.monotonic() - start < max_wait:
        resp = await client.get(f"/tasks/{task_id}")
        data = resp.json()
        if data["status"] == "completed":
            return data["result"]
        elif data["status"] == "failed":
            raise RuntimeError(f"Task failed: {data.get('error')}")
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Task timed out after {max_wait}s")
```

---

## 9. 配置说明

### 9.1 API服务配置 (config/api_services.json)

```json
{
  "backends": {
    "llm": {
      "type": "nvidia_nim",
      "base_url": "https://integrate.api.nvidia.com/v1",
      "api_key": "${NVIDIA_NIM_API_KEY}",  // 从环境变量读取
      "model": "openai/gpt-oss-120b",
      "timeout_seconds": 300,
      "max_retries": 3
    },
    "image": {
      "type": "comfyui",
      "base_url": "http://localhost:8188",
      "default_workflow": "t2i_z_image_turbo",
      "timeout_seconds": 120
    },
    "video": {
      "type": "comfyui",
      "base_url": "http://localhost:8188",
      "default_workflow": "i2v_wan22_simple",
      "timeout_seconds": 600
    },
    "bgm": {
      "type": "comfyui",
      "base_url": "http://localhost:8188",
      "default_workflow": "bgm_ace_step",
      "timeout_seconds": 300
    }
  }
}
```

### 9.2 支持的LLM模型

```python
SUPPORTED_MODELS = [
    "openai/gpt-oss-120b",           # 默认
    "nvidia/nemotron-3-super-120b-a12b",
    "meta/llama3-70b-instruct",
    "meta/llama3-8b-instruct",
    "mistralai/mixtral-8x22b-instruct-v0.1",
    # 其他支持的模型...
]
```

### 9.3 模型文件路径

```
~/data/comfy/ComfyUI/models/
├── checkpoints/           # SD/视频模型
│   └── ltx-2.3-22b-dev-fp8.safetensors
├── diffusion_models/      # Wan2.2/ACE-Step
│   ├── wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
│   ├── wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
│   └── acestep_v1.5_turbo.safetensors
├── vae/
│   ├── wan_2.1_vae.safetensors
│   └── ace_1.5_vae.safetensors
├── text_encoders/
│   └── umt5_xxl_fp8_e4m3fn_scaled.safetensors
└── loras/
    ├── wan2.2_i2v_lightx2v_4steps_lora_v1_*.safetensors
    └── ltx-2.3-22b-distilled-lora-384.safetensors
```

---

## 10. 微调参数指南

### 10.1 图像质量微调

| 参数 | 影响 | 建议调整 |
|------|------|----------|
| `steps` ↑ | 更细腻，但更慢 | 20-30 最佳 |
| `cfg` ↑ | 更符合提示词，但可能过曝 | 6.0-8.0 |
| `cfg` ↓ | 更平滑，但可能模糊 | 5.0-6.0 |
| `width/height` ↑ | 更高清，但更慢 | 640x480 适合手机 |
| `seed` | 固定可复现 | 实验用固定值 |

### 10.2 视频生成微调

| 参数 | 影响 | 建议调整 |
|------|------|----------|
| `num_frames` ↑ | 视频更长，动作更丰富 | 81帧=3.4秒 |
| `fps` ↑ | 更流畅，但文件更大 | 24fps 最佳 |
| `length` | Wan2.2参数 | 81-161 |
| `motion_bucket_id` | 运动强度 | 127-255 |

**视频时长计算**: `duration = num_frames / fps`

例: 81帧 / 24fps = 3.375秒

### 10.3 TTS声音微调

| 声音角色 | 适用场景 | 参数调整 |
|----------|----------|----------|
| zh-CN-XiaoxiaoNeural | 叙述、旁白 | rate +0% |
| zh-CN-YunxiNeural | 年轻男主角 | rate +5% |
| zh-CN-YunjianNeural | 中年男性 | rate -5%, pitch -5Hz |
| zh-CN-XiaoyiNeural | 年轻女性 | rate +10% |
| zh-CN-XiaohanNeural | 儿童/可爱角色 | rate +15% |

**情感参数**:
```python
EMOTION_CONFIG = {
    "happy": {"rate": "+10%", "pitch": "+5%"},
    "sad": {"rate": "-10%", "pitch": "-5%"},
    "angry": {"rate": "+15%", "pitch": "+10%"},
    "calm": {"rate": "-5%", "pitch": "0%"}
}
```

### 10.4 BGM生成微调

| 参数 | 影响 | 建议值 |
|------|------|--------|
| `duration` | 音乐长度 | 10-120秒 |
| `bpm` | 节拍速度 | 70-180 |
| `tags` | 音乐风格 | 见下方示例 |
| `temperature` | 随机性 | 0.7-0.95 |

**BGM Tags示例**:
```python
BGM_TAGS = {
    "epic_cinematic": "Epic: A powerful, cinematic orchestral track with dramatic buildups and emotional crescendos",
    "action_rock": "Rock: High-energy rock with distorted guitars, punchy drums, intense atmosphere",
    "peaceful_ambient": "Ambient: Calm, atmospheric background with soft pads and gentle textures",
    "mysterious": "Mysterious: Dark, atmospheric with tension building elements",
    "battle_fanfare": "Fantasy: Grand orchestral battle music with brass and drums"
}
```

### 10.5 工作流程参数修改

修改 ComfyUI Workflow JSON 文件:

#### 图像生成 (api_service/workflows/t2i_z_image_turbo.json)
```json
{
  "5": {  // KSampler节点
    "inputs": {
      "seed": 42,        // 固定种子
      "steps": 30,        // 增加步数
      "cfg": 7.5,         // 调整CFG
      "sampler_name": "euler",  // 可选: euler, dpm++, etc.
      "denoise": 1.0
    }
  }
}
```

#### 视频生成 (api_service/workflows/i2v_wan22_simple.json)
```json
{
  "10": {  // WanImageToVideo节点
    "inputs": {
      "width": 1280,      // 增加分辨率
      "height": 720,
      "length": 161       // 更多帧
    }
  },
  "11": {  // KSampler high阶段
    "inputs": {
      "steps": 6,         // 增加步数
      "cfg": 4.0          // 调整CFG
    }
  }
}
```

---

## 附录: 完整Pipeline命令

```bash
# 启动服务
cd ~/data/comfy/ComfyUI && python3 main.py --listen 0.0.0.0 --port 8188 &
sleep 5
cd ai-novel-video-v2
export $(grep -v '^#' .env | xargs)
uvicorn api_service.main:app --host 0.0.0.0 --port 9000 &
sleep 3

# 完整流程
PROJECT="my_novel_$(date +%Y%m%d_%H%M%S)"

# Phase 1: 生成小说
python run_pipeline.py --project-id "$PROJECT" --phase 1

# Phase 2: 生成图像、TTS、视频
python run_pipeline.py --project-id "$PROJECT" --phase 2 --chapter 1

# Phase 3: BGM + 视频合成
python run_pipeline.py --project-id "$PROJECT" --phase 3

# 查看结果
ls -la outputs/$PROJECT/
```

---

*最后更新: 2026-04-25*

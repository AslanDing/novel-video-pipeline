# API 服务层架构设计方案

> **目标**：将 `ai-novel-video-v2` 中所有模型调用解耦，通过一套统一的 FastAPI 网关统一管理 LLM、文生图、图文生视频、文生音频服务，主应用只通过 HTTP 客户端调用这些接口。

---

## 1. 整体架构

```mermaid
graph TB
    subgraph MainApp["主应用 (ai-novel-video-v2)"]
        S1[Stage 1: 小说生成]
        S2[Stage 2: 视觉预处理 & 图像生成]
        S3[Stage 3: 音频合成]
        S4[Stage 4: 视频合并]
        S1 --> S2 --> S3 --> S4
    end

    subgraph APIGateway["api_service/ (FastAPI 统一网关)"]
        LLMRouter[/llm 路由 llama.cpp]
        ImageRouter[/image 路由 ComfyUI T2I]
        VideoRouter[/video 路由 ComfyUI I2V]
        TTSRouter[/tts 路由 Fish Audio]
        BGMRouter[/bgm 路由 ACE-Step 1.5]
    end

    subgraph Backends["后端推理引擎"]
        LlamaCpp["llama.cpp Server :8080/v1"]
        ComfyUI["ComfyUI Server :8188"]
        FishAudio["Fish Audio API Cloud/Local"]
        ACEStep["ACE-Step 1.5 Local"]
    end

    MainApp -->|HTTP| APIGateway
    LLMRouter --> LlamaCpp
    ImageRouter --> ComfyUI
    VideoRouter --> ComfyUI
    TTSRouter --> FishAudio
    BGMRouter --> ACEStep
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **解耦** | 主应用不直接 import 任何模型库（torch、diffusers 等） |
| **统一接口** | 所有服务遵循相同的请求/响应规范 |
| **可替换** | 各后端推理引擎可独立替换，不影响主应用 |
| **异步优先** | 基于 asyncio + aiohttp，支持长任务轮询 |
| **任务队列** | 耗时任务返回 task_id，客户端轮询 `/tasks/{id}` |

---

## 2. 目录结构

```
ai-novel-video-v2/
├── api_service/                    ← 新增：FastAPI 统一网关
│   ├── __init__.py
│   ├── main.py                     ← FastAPI 应用入口 & 路由挂载
│   ├── config.py                   ← 服务端口、后端地址等配置
│   ├── models.py                   ← 共享 Pydantic 请求/响应模型
│   ├── task_manager.py             ← 异步任务状态管理
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── llm.py                  ← POST /llm/generate, /llm/stream
│   │   ├── image.py                ← POST /image/generate
│   │   ├── video.py                ← POST /video/generate
│   │   ├── tts.py                  ← POST /tts/synthesize
│   │   └── bgm.py                  ← POST /bgm/generate
│   │
│   └── backends/
│       ├── __init__.py
│       ├── llama_cpp.py            ← llama.cpp OpenAI-compat 客户端
│       ├── comfyui.py              ← ComfyUI Workflow 调用封装
│       ├── fish_audio.py           ← Fish Audio TTS API 封装
│       └── ace_step.py             ← ACE-Step 1.5 本地推理封装
│
├── core/
│   ├── api_client.py               ← 新增：统一 HTTP 客户端（替代旧 LLM 客户端）
│   └── ...
│
└── config/
    ├── api_services.json           ← 新增：各服务地址配置
    └── ...
```

---

## 3. API 接口规范

### 3.1 LLM 文本生成 (`/llm`)

**后端**: llama.cpp（OpenAI 兼容协议，`/v1/chat/completions`）

```
POST /llm/generate
POST /llm/stream          ← Server-Sent Events 流式输出
GET  /llm/models          ← 列出可用模型
GET  /llm/health          ← 健康检查
```

请求：
```json
{
  "messages": [
    {"role": "system", "content": "你是一位顶级网文作家。"},
    {"role": "user",   "content": "写第一章..."}
  ],
  "max_tokens": 16000,
  "temperature": 0.7,
  "response_format": {"type": "json_object"}
}
```

响应：
```json
{
  "content": "第一章 天降奇遇\n\n...",
  "usage": {"prompt_tokens": 120, "completion_tokens": 3000},
  "model": "qwen3-14b",
  "finish_reason": "stop"
}
```

---

### 3.2 文生图 (`/image`)

**后端**: ComfyUI（Workflow API + WebSocket 轮询）

```
POST /image/generate
GET  /image/tasks/{task_id}
GET  /image/models
```

请求：
```json
{
  "prompt": "A young cultivator standing on a mountain peak, dramatic lighting, anime style",
  "negative_prompt": "blurry, low quality",
  "width": 1024,
  "height": 1024,
  "steps": 25,
  "cfg": 7.0,
  "model": "z-image-turbo",
  "seed": -1
}
```

响应：
```json
{
  "task_id": "img_abc123",
  "status": "completed",
  "images": [
    {"url": "/files/outputs/img_abc123_0.png", "width": 1024, "height": 1024, "seed": 42}
  ],
  "elapsed_seconds": 8.3
}
```

---

### 3.3 图文生视频 (`/video`)

**后端**: ComfyUI（I2V Workflow，WanVideo / CogVideoX）

```
POST /video/generate
GET  /video/tasks/{task_id}
```

请求：
```json
{
  "image_path": "/path/to/input.png",
  "prompt": "camera slowly zooms in, wind blows through trees",
  "motion_prompt": "slow zoom",
  "num_frames": 81,
  "fps": 24,
  "model": "wan_video_i2v"
}
```

响应（异步）：
```json
{
  "task_id": "vid_xyz789",
  "status": "queued",
  "estimated_seconds": 120,
  "poll_url": "/video/tasks/vid_xyz789"
}
```

---

### 3.4 文本转语音 TTS (`/tts`)

**后端**: Fish Audio（官方 API / 本地 fish-speech 部署）

```
POST /tts/synthesize
GET  /tts/voices
POST /tts/clone     ← 上传参考音频克隆音色（可选）
```

请求：
```json
{
  "text": "林凡猛地睁开双眼，一股浩然正气冲天而起！",
  "reference_id": "fish_voice_narrator",
  "speed": 1.0,
  "format": "mp3"
}
```

响应：
```json
{
  "task_id": "tts_def456",
  "status": "completed",
  "audio_url": "/files/outputs/tts_def456.mp3",
  "duration_seconds": 5.2
}
```

---

### 3.5 背景音乐/音效生成 (`/bgm`)

**后端**: ACE-Step 1.5（本地推理）

```
POST /bgm/generate
GET  /bgm/tasks/{task_id}
```

请求：
```json
{
  "prompt": "epic Chinese cultivation music, intense battle, orchestral",
  "tags": ["epic", "battle", "chinese"],
  "duration_seconds": 30,
  "format": "wav"
}
```

响应（异步）：
```json
{
  "task_id": "bgm_ghi012",
  "status": "queued",
  "poll_url": "/bgm/tasks/bgm_ghi012"
}
```

---

### 3.6 公共接口

```
GET  /health              ← 所有 backend 健康检查汇总
GET  /tasks/{task_id}     ← 通用任务状态查询
GET  /files/{path}        ← 文件下载（静态文件服务）
```

---

## 4. Backend 实现细节

### 4.1 llama.cpp

llama.cpp 原生提供 OpenAI 兼容接口，路由层做薄封装：
- 统一内部鉴权
- 日志与监控
- 错误重试（最多 3 次）
- 流式 SSE 透传

```bash
# 启动命令
llama-server \
  --model models/llm/qwen3-14b-q4_k_m.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 --n-predict 16384
```

### 4.2 ComfyUI

通过 HTTP API + WebSocket 推理：

1. `POST /prompt` → 提交 Workflow JSON，返回 `prompt_id`
2. WebSocket 连接 `/ws` → 监听 `progress` / `executing` 事件
3. `GET /history/{prompt_id}` → 获取完成结果

预先保存的 ComfyUI Workflow 文件：

| 文件 | 用途 |
|------|------|
| `api_service/workflows/t2i_flux.json` | 文生图（FLUX/SDXL） |
| `api_service/workflows/i2v_wan.json` | 图生视频（WanVideo I2V） |
| `api_service/workflows/i2v_cogvideo.json` | 图生视频（CogVideoX） |

### 4.3 Fish Audio

通过 WebSocket 流式 TTS：
- 端点：`wss://api.fish.audio/v1/tts`
- 支持：分段传输、音色克隆、多格式输出（mp3/wav/opus）
- 本地部署：参考 fish-speech 项目

### 4.4 ACE-Step 1.5

专为音乐/音效设计的扩散模型：
- 支持文字描述 + 风格 tags
- 本地 GPU 推理
- 输出 WAV，支持 30s/60s 时长

---

## 5. 主应用端改造

### 5.1 新建统一 API 客户端 `core/api_client.py`

```python
class NovelAPIClient:
    """统一服务 API 客户端，替代所有直接模型调用"""
    
    base_url: str  # 默认 http://localhost:9000
    
    async def llm_generate(prompt, system_prompt, ...) -> LLMResponse
    async def llm_stream(prompt, ...) -> AsyncGenerator[str, None]
    async def image_generate(prompt, ...) -> ImageResult
    async def video_generate(image_path, prompt, ...) -> VideoResult
    async def tts_synthesize(text, voice_id, ...) -> AudioResult
    async def bgm_generate(prompt, duration, ...) -> AudioResult
    async def wait_for_task(task_id, poll_interval=2.0) -> TaskResult
```

### 5.2 改造范围

| 模块 | 当前依赖 | 改造后 |
|------|---------|--------|
| `novel_generator.py` | `NVIDIA_NIM_Client` / `local_llm_client` | `NovelAPIClient.llm_generate()` |
| `quality_controller.py` | `llm_client.generate()` | `NovelAPIClient.llm_generate()` |
| `preprocessor.py` | `llm_client` + `robust_json_generate` | `NovelAPIClient.llm_generate()` |
| `image_generator.py` | `diffusers` Pipeline | `NovelAPIClient.image_generate()` |
| `tts_engine.py` | `edge_tts` / `ChatTTS` | `NovelAPIClient.tts_synthesize()` |
| `video_generation.py` | `HunyuanVideo` | `NovelAPIClient.video_generate()` |

---

## 6. 配置文件 `config/api_services.json`

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 9000,
    "internal_token": "change-me-in-production",
    "outputs_dir": "outputs"
  },
  "backends": {
    "llm": {
      "type": "llama_cpp",
      "base_url": "http://localhost:8080/v1",
      "model": "qwen3-14b",
      "timeout_seconds": 300
    },
    "image": {
      "type": "comfyui",
      "base_url": "http://localhost:8188",
      "default_workflow": "t2i_flux",
      "timeout_seconds": 120
    },
    "video": {
      "type": "comfyui",
      "base_url": "http://localhost:8188",
      "default_workflow": "i2v_wan",
      "timeout_seconds": 600
    },
    "tts": {
      "type": "fish_audio",
      "api_key": "${FISH_AUDIO_API_KEY}",
      "base_url": "https://api.fish.audio",
      "default_voice_id": "narrator_zh",
      "timeout_seconds": 60
    },
    "bgm": {
      "type": "ace_step",
      "model_path": "models/sound/ace-step-v1.5",
      "device": "cuda",
      "timeout_seconds": 120
    }
  }
}
```

---

## 7. 实施计划

### Phase 1：框架搭建（首要）

- [ ] `api_service/__init__.py`, `main.py`, `config.py`
- [ ] `api_service/models.py`（共享 Pydantic 模型）
- [ ] `api_service/task_manager.py`（内存任务状态 + 可选 Redis）
- [ ] `config/api_services.json`

### Phase 2：Backend 封装

- [ ] `backends/llama_cpp.py` — OpenAI compat 直连
- [ ] `backends/comfyui.py` — Workflow 提交 + WS 轮询
- [ ] `backends/fish_audio.py` — WebSocket 流式 TTS
- [ ] `backends/ace_step.py` — 本地推理封装

### Phase 3：Router 实现

- [ ] `routers/llm.py`（同步 + SSE 流式）
- [ ] `routers/image.py`（同步或异步可选）
- [ ] `routers/video.py`（异步任务）
- [ ] `routers/tts.py`
- [ ] `routers/bgm.py`
- [ ] 健康检查 & 文件服务路由

### Phase 4：主应用改造

- [ ] `core/api_client.py`（`NovelAPIClient`）
- [ ] 逐一重构各 Stage 模块
- [ ] 移除对 torch/diffusers/edge_tts 等的直接依赖

### Phase 5：测试 & 文档

- [ ] 端点集成测试（httpx + pytest-asyncio）
- [ ] `api_service/README.md`（启动方式、依赖）
- [ ] 更新 `requirements.txt`

---

## 8. 新增依赖

```
# api_service/requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
websockets>=12.0
pydantic>=2.7.0
python-multipart>=0.0.9
aiofiles>=24.1.0
```

---

> **执行顺序**：Phase 1 → Phase 2 → Phase 3 → Phase 4（可并行）→ Phase 5

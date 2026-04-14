# ai-novel-video API 服务网关

统一管理 LLM、文生图、图生视频、TTS、BGM 等 AI 推理服务的 FastAPI 网关。

---

## 架构概览

```
主应用 (run_stage*.py)
    │  HTTP
    ▼
api_service (FastAPI :9000)
    ├── /llm  → llama.cpp  (:8080)
    ├── /image → ComfyUI  (:8188)
    ├── /video → ComfyUI  (:8188)
    ├── /tts  → Fish Audio (Cloud / Local)
    └── /bgm  → ACE-Step 1.5 (Local)
```

---

## 快速启动

### 1. 安装依赖

```bash
pip install fastapi uvicorn[standard] httpx websockets aiofiles python-multipart
```

### 2. 配置

编辑 `config/api_services.json`：

```json
{
  "gateway": {"port": 9000},
  "backends": {
    "llm":   {"base_url": "http://localhost:8080/v1"},
    "image": {"base_url": "http://localhost:8188"},
    "video": {"base_url": "http://localhost:8188"},
    "tts":   {"api_key": "YOUR_FISH_AUDIO_KEY"},
    "bgm":   {"model_path": "models/sound/ace-step-v1.5"}
  }
}
```

环境变量优先级：
- `NOVEL_API_GATEWAY=http://localhost:9000`（主应用侧）
- `FISH_AUDIO_API_KEY=...`（在配置中使用 `${FISH_AUDIO_API_KEY}`）

### 3. 启动后端服务

```bash
# llama.cpp
llama-server --model models/llm/qwen3-14b-q4_k_m.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 32768

# ComfyUI
python ComfyUI/main.py --listen 0.0.0.0 --port 8188
```

### 4. 启动 API 网关

```bash
cd ai-novel-video-v2
uvicorn api_service.main:app --host 0.0.0.0 --port 9000
```

访问 API 文档：http://localhost:9000/docs

---

## 端点列表

### LLM
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/llm/generate` | 非流式文本生成 |
| POST | `/llm/stream` | SSE 流式文本生成 |
| GET  | `/llm/models` | 列出可用模型 |
| GET  | `/llm/health` | 健康检查 |

### 文生图
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/image/generate` | 提交生成任务 |
| GET  | `/image/tasks/{id}` | 查询任务状态 |
| GET  | `/image/health` | 健康检查 |

### 图生视频
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/video/generate` | 提交生成任务（异步） |
| GET  | `/video/tasks/{id}` | 查询任务状态 |
| GET  | `/video/health` | 健康检查 |

### TTS 语音
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/tts/synthesize` | 提交 TTS 任务 |
| GET  | `/tts/tasks/{id}` | 查询任务状态 |
| GET  | `/tts/voices` | 列出可用音色 |
| GET  | `/tts/health` | 健康检查 |

### BGM/音效
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/bgm/generate` | 提交生成任务（异步） |
| GET  | `/bgm/tasks/{id}` | 查询任务状态 |
| GET  | `/bgm/health` | 健康检查 |

### 通用
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/health` | 所有后端健康检查 |
| GET  | `/tasks/{id}` | 通用任务状态查询 |
| GET  | `/files/{path}` | 生成文件下载 |

---

## 主应用集成

旧代码中的 LLM 客户端可无缝替换：

```python
# 旧代码
from core.llm_client import NVIDIA_NIM_Client
llm = NVIDIA_NIM_Client()
response = await llm.generate("...", system_prompt="...")

# 新代码（直接替换）
from core.api_client import get_compat_llm_client
llm = get_compat_llm_client()
response = await llm.generate("...", system_prompt="...")

# 或使用功能更丰富的 NovelAPIClient
from core.api_client import NovelAPIClient
client = NovelAPIClient()
response = await client.llm_generate("...", system_prompt="...")
image    = await client.image_generate("epic battle scene, anime style")
audio    = await client.tts_synthesize("林凡睁开双眼...", voice_id="narrator")
```

---

## ComfyUI Workflow 配置

工作流文件位于 `api_service/workflows/`。

当前占位文件需要替换为真实 ComfyUI workflow：

1. 在 ComfyUI UI 中设计好工作流
2. 点击 **Save (API Format)**（保存为 API 格式）
3. 替换对应的 JSON 文件

节点 title 命名约定（供参数自动注入使用）：

| title 关键词 | 作用 |
|-------------|------|
| `positive` | 正向 prompt 节点 |
| `negative` | 负向 prompt 节点 |
| `sampler` | KSampler 节点（seed/steps/cfg）|
| `latent` | EmptyLatentImage（width/height）|
| `loader` | CheckpointLoaderSimple（模型名）|
| `load image` | LoadImage 节点（输入图像）|

# AI Novel Video Pipeline (AI 小说视频生成工作流)

## 📖 项目简介
本项目是一个自动化的 AI 小说推文视频生成 Pipeline。通过结合大型语言模型（LLM）、ComfyUI（图像与视频生成）、Edge TTS（语音合成）以及 ACE-Step（背景音乐生成），实现从“小说文本生成”到“图文音视频合成”的端到端全自动工作流。

## ✨ 核心特性
- **一键式全流程**：支持从一句话生成小说，到提取分镜、生成语音、图片、视频并最终合成的完整流程。
- **模块化微服务架构**：通过 FastAPI 构建统一的 API 网关，解耦 LLM、图像、视频、音频和 BGM 等服务。
- **先进模型支持**：支持 NVIDIA NIM (gpt-oss-120b)、Wan2.2 (图生视频)、Z-Image-Turbo (图像生成)、ACE-Step 1.5 (BGM生成)。
- **高度可定制**：基于 ComfyUI Workflow JSON 驱动，轻松替换或微调各个生成节点的参数。

## 🛠️ 安装与配置

### 1. 环境依赖
项目基于 Python 3.8+ 开发。首先克隆仓库并安装 Python 依赖：

```bash
# 克隆仓库
git clone <your_repo_url>
cd ai-novel-video-v2

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows 下使用 venv\Scripts\activate

# 安装核心依赖
pip install -r requirements.txt
```

### 2. 系统依赖 (视频合成必需)
需要安装 FFmpeg 用于最终的视频和音频合成：
- **Ubuntu/Debian**: `sudo apt-get install ffmpeg libsm6 libxext6`
- **macOS**: `brew install ffmpeg`
- **Windows**: 下载 [FFmpeg](https://ffmpeg.org/download.html) 并将其 bin 目录添加到系统 PATH 环境变量。

### 3. ComfyUI 部署 (核心引擎)
图像、视频和 BGM 的生成依赖于本地部署的 ComfyUI。
- 确保已在本地或服务器安装 ComfyUI，使用WAN2.2视频模型, VRAM显存要求16G以上。
- 确保所需的模型文件（如 SD 基础模型、Wan2.2 模型、ACE-Step 模型）已放置到 ComfyUI 相应的 `models/` 目录下。

### 4. 环境变量配置
复制 `.env.example` 并重命名为 `.env`，填入必需的 API Key：

```bash
cp .env.example .env
```

`.env` 必须包含以下内容（用于 LLM 文本生成）：
```env
NVIDIA_NIM_API_KEY=your_api_key_here
NVIDIA_NIM_MODEL=openai/gpt-oss-120b  # 或其他支持的模型
```

## 🚀 快速启动

启动整个系统分为两步：启动 ComfyUI 后端和启动 API 网关。

### 1. 启动 ComfyUI 后端引擎
必须首先启动 ComfyUI，因为 API 服务将依赖它的接口。
```bash
cd /path/to/ComfyUI
python main.py --listen 0.0.0.0 --port 8188 &
```

### 2. 启动 API 服务网关
```bash
cd ai-novel-video-v2
# 加载环境变量并启动 FastAPI 服务
export $(grep -v '^#' .env | xargs)
uvicorn api_service.main:app --host 0.0.0.0 --port 9000 &
```
服务启动后，可通过运行 `curl http://localhost:9000/health` 检查各节点是否健康。

## 🎯 运行 Pipeline

可以通过统一的入口脚本 `run_pipeline.py` 执行完整工作流：

```bash
# 1. 定义项目名称
PROJECT="my_novel_$(date +%Y%m%d_%H%M%S)"

# 2. Phase 1: 小说生成 (调用 LLM 生成小说文本)
python run_pipeline.py --project-id "$PROJECT" --phase 1

# 3. Phase 2: 媒体生成 (基于文本生成图像、TTS 语音，并将图像转为视频)
python run_pipeline.py --project-id "$PROJECT" --phase 2 --chapter 1

# 4. Phase 3: 视频合成 (生成 BGM 并将所有视频、语音和 BGM 合成为最终的 MP4)
python run_pipeline.py --project-id "$PROJECT" --phase 3
```

最终生成的视频文件及中间产物将保存在 `outputs/$PROJECT/` 目录下。

## 🏗️ 系统架构说明

```text
┌─────────────────────────────────────────────────────────────────┐
│                        用户请求层                               │
│                  run_pipeline.py / main.py                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API 服务网关 (FastAPI)                      │
│                   http://localhost:9000                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐    │
│  │  /llm   │ │ /image  │ │ /video  │ │  /tts   │ │  /bgm   │    │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘    │
└───────┼────────────┼────────────┼────────────┼────────────┼─────┘
        │            │            │            │            │
        ▼            ▼            ▼            ▼            ▼
┌──────────────┐ ┌────────────────────────┐ ┌───────────────┐
│ NVIDIA NIM   │ │       ComfyUI          │ │  Edge TTS     │
│ LLM API      │ │        :8188           │ │  (本地合成)   │
│ gpt-oss-120b │ │ + Wan2.2 / Z-Image     │ │               │
└──────────────┘ │ + ACE-Step 1.5         │ └───────────────┘
                 └────────────────────────┘
```

API 服务支持将工作流作为独立 JSON (`api_service/workflows/`) 载入并通过 WebSocket 进行任务分发与状态监听。你可以轻松地在配置中替换为自建的 ComfyUI 工作流。

## 🌟 进阶提升与优化方向

为了进一步提升生成视频的质量与表现力，可以通过以下方式对 Pipeline 进行增强：

### 1. 角色与画风的一致性控制 (LoRA)
目前小说分镜可能会遇到人物长相或画风前后不一致的问题。建议在 ComfyUI 工作流（如 `t2i_z_image_turbo.json`）中引入 **LoRA** 进行一致性约束：
- **角色一致性**：加载特定角色的 LoRA 模型，并在 API 网关传递的 Prompt 中固定特征词，确保多镜头的男女主角容貌统一。
- **画风一致性**：引入特定的画风 LoRA（如水墨风、赛博朋克、皮克斯3D），并调整 LoRA 权重，以保证整个视频画面的视觉风格高度一致。

### 2. TTS 语音长度与视频长度的精准对齐
默认的视频生成往往是固定帧数（如 81帧=3.4秒），而文本转语音（TTS）的朗读长度随句子长短变化，容易导致音画脱节。优化方案：
- **动态帧数计算**：先通过 `/tts/synthesize` 获取生成的音频时长，然后按照 `时长 × 目标FPS` 的公式动态计算视频生成的 `num_frames` 参数（传递给 Wan2.2），实现图生视频时长与语音时长的完美匹配。
- **视频变速与循环**：针对过长的语音段落，可在 Phase 3 的合成阶段（FFmpeg）对短视频进行慢放插帧、Ping-pong 倒放循环拼接，强制对齐音频长度。

### 3. 微调生成参数控制效果
可在 `config/api_services.json` 或在接口请求时覆盖默认参数以获取更好的效果：
- **图像质量**：调高 `steps` (如 30) 获取更细腻画质，微调 `cfg` 增强对提示词的服从度。
- **视频动态**：调高图生视频模型的 motion_bucket_id 获取更大的运动幅度。
- **配音情感**：通过在 TTS 参数中调节 `pitch` 和 `rate`，模拟不同角色的性格和情绪。
- **BGM 匹配**：通过修改生成的 `tags`（如 "Epic, action" 或 "Ambient, peaceful"）使背景音乐契合小说章节的起伏。

---
> **⚠️ 注意 / Disclaimer**
> 本项目代码及相关工作流可能存在一些 Bug 或不完善之处。作者会在有空的时候不定期进行维护和更新。欢迎提交 Issue 交流！
> 本项目仅进行学习研究，商用可能存在的任何问题，由使用者自行承担！

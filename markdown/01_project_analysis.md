# 工程分析与设计文档

## 项目：AI爽文小说创作平台 v2

---

## 一、项目现状总览

### 1.1 架构理解（已修正）

你的项目是 **Server-Client 分离架构**：

```
┌─────────────────────────────────────────────────────────────┐
│                    Server 层 (FastAPI)                       │
│                  api_service/ (:9000)                       │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐       │
│  │ /llm     │→│ /image   │→│ /video │→│ /tts   │       │
│  │          │ │          │ │        │ │        │       │
│  │ llama.cpp│ │ ComfyUI │ │ComfyUI │ │Fish API│       │
│  │ (:8080)  │ │ (:8188) │ │(:8188) │ │(Cloud) │       │
│  └──────────┘ └──────────┘ └────────┘ └────────┘       │
└─────────────────────────────────────────────────────────────┘
                           │ HTTP
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Workflow 层 (独立脚本)                     │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │Stage 1  │→│Stage 2  │→│Stage 3  │→│Stage 4  │        │
│  │Novel     │ │Image    │ │Audio    │ │Video    │        │
│  │Generator │ │Generator│ │TTS      │ │Composer │        │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │
│         │           │           │           │                 │
│         ▼           ▼           ▼           ▼                 │
│  ┌─────────────────────────────────────────────┐         │
│  │         core/api_client.py                    │         │
│  │   (统一客户端，可选调用Server API)           │         │
│  └─────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

**两种运行模式**：
1. **直调模式**: Workflow直接调用本地模型（`stages/` + `run_stage*.py`）
2. **API模式**: Workflow通过API调用Server（`core/api_client.py` → `api_service/`）

### 1.2 完成度评估

> **注意**: 原 4 Stage 流程已重构为 3 Phase 资产优先流程。

#### 新架构完成度评估

| Phase | 模块 | 完成度 | 状态 |
|-------|------|--------|------|
| **Phase 1** | 预生产 - 角色包生成 | 40% | 待实现 |
| **Phase 1** | 预生产 - 场景包生成 | 40% | 待实现 |
| **Phase 1** | LLM 章节结构生成 | 85% | 基本可用 |
| **Phase 1** | Chapter Manifest | 30% | 待实现 |
| **Phase 2** | Shot List 生成 | 30% | 待实现 |
| **Phase 2** | TTS 音频生成 | 75% | 基本可用 |
| **Phase 2** | 关键帧生成 | 50% | 部分可用 |
| **Phase 2** | 镜生视频 | 60% | 基本可用 |
| **Phase 3** | 视频合成 | 80% | 基本可用 |
| **Phase 3** | 字幕生成 | 75% | 基本可用 |
| **API层** | 运行时编排 | 0% | 待实现 |
| **API层** | 项目/章节/镜头管理 | 0% | 待实现 |
| **配置层** | Prompt 独立化 | 0% | 待实现 |
| **配置层** | 三层配置模型 | 0% | 待实现 |

#### 旧 4 Stage 遗留模块

| 遗留模块 | 完成度 | 说明 |
|----------|--------|------|
| `stages/stage1_novel/` | 85% | LLM 生成部分可直接复用 |
| `stages/stage2_visual/` | 60% | 图像/视频生成可复用 |
| `stages/stage3_audio/` | 75% | TTS 部分可直接复用 |
| `stages/stage4_merge/` | 80% | FFmpeg 合成可直接复用 |
| `api_service/backends/` | 70% | 后端代理可复用 |

### 1.3 核心问题识别（重新评估）

由于架构是Server-Client分离，GPU资源可独立使用，原有问题需要重新评估：

#### 问题1: ComfyUI工作流是占位模板 (仍为P0)
- `workflows/t2i_flux.json` 和 `i2v_wan.json` 是占位符
- 需要从实际ComfyUI导出真实workflow

#### 问题2: LLM输出格式不稳定 (仍为P1)
- `_extract_json` 使用简单正则，容易被markdown干扰
- Preprocessor中的 `_extract_json` 也有同样问题

#### 问题3: Script JSONL流程 (降为P2)
- 实际上Preprocessor已经实现了分镜脚本生成
- 但分镜脚本保存在缓存目录，未写入标准 `data/scripts/` 目录

#### 问题4: IP-Adapter实现不完整 (P2)
- 代码存在但不稳定
- 建议切换到InstantID

#### 问题5: NVIDIA NIM API Key硬编码 (P1)
- `config/settings.py` 中有硬编码的API Key
- 需要外置到环境变量

---

## 二、整体架构设计（已重构为 3 Phase）

### 2.1 新数据流设计

```
User Input: {"title": "绝世剑仙", "genre": "修仙", "core_idea": "废材逆袭", "chapters": 3}
                            ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 1: 预生产 (Pre-production)                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 1. LLM 生成故事结构 (World Building, Characters, Plot)           │   │
│  │ 2. 生成角色包 (Character Pack) → assets/characters/            │   │
│  │ 3. 生成场景包 (Scene Pack) → assets/scenes/                    │   │
│  │ 4. 固化 Chapter Manifest                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  输出: {project_preset.json, chapter_manifests/, assets/}               │
└─────────────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 2: 正式生产 (Production)                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 1. LLM 生成 Shot List (意图层数据)                              │   │
│  │ 2. TTS 先生成 (音频长度决定视频长度)                            │   │
│  │ 3. 生成关键帧 (基于角色/场景资产)                               │   │
│  │ 4. 镜生视频 (I2V / T2V)                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  输出: {keyframes/, videos/, audio/}                                    │
└─────────────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 3: 后期合成 (Post-production)                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 1. 视频拼接                                                      │   │
│  │ 2. 音频混合 (对白 + 旁白 + BGM)                                 │   │
│  │ 3. 字幕生成                                                      │   │
│  │ 4. 输出最终视频                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│  输出: {final/*.mp4}                                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 与旧 4 Stage 的关系

| 新 3 Phase | 旧 4 Stage | 说明 |
|-------------|------------|------|
| Phase 1 | Stage 1 部分 | LLM 生成部分复用，分镜生成改为 Shot List |
| Phase 2 | Stage 2 + Stage 3 | 关键帧=图像生成，TTS 提前到视频之前 |
| Phase 3 | Stage 4 | 视频合成复用 |

**核心变化**: 角色/场景资产先于镜头生成，TTS 先于视频生成

### 2.3 关键设计决策

#### 决策1: 三层配置模型
```
Layer 1: Project Preset (项目级别，稳定)
Layer 2: Chapter Manifest (章节级别，较稳定)
Layer 3: Shot Spec (镜头级别，频繁变化)
```

#### 决策2: 意图层数据
Python/FastAPI 输出创作意图，不输出技术参数：
```json
{
  "shot_id": "ch01_s003",
  "purpose": "introduce heroine close-up",
  "needs_character_consistency": true,
  "video_mode": "i2v"
}
```

#### 决策3: VRAM 分时复用
```
llama.cpp 进程:  ~8-14GB (Qwen3-14B) → Phase 1 LLM
ComfyUI 进程:    ~4-6GB (SDXL/SVD)  → Phase 2 图像/视频
TTS:             0GB (在线)           → Phase 2 TTS
FFmpeg:          0GB (CPU)           → Phase 3 合成
```

---

## 三、Server层详解

### 3.1 API Gateway架构

```
api_service (FastAPI :9000)
       │
       ├── /llm/*      → llama.cpp (:8080)
       ├── /image/*     → ComfyUI (:8188)
       ├── /video/*     → ComfyUI (:8188)
       ├── /tts/*       → Fish Audio API (Cloud)
       └── /bgm/*       → ACE-Step (Local)

配置文件: config/api_services.json
```

### 3.2 后端配置

```json
{
  "backends": {
    "llm": {
      "type": "llama_cpp",
      "base_url": "http://localhost:8080/v1",
      "model": "qwen3-14b"
    },
    "image": {
      "type": "comfyui",
      "base_url": "http://localhost:8188"
    },
    "video": {
      "type": "comfyui",
      "base_url": "http://localhost:8188"
    },
    "tts": {
      "type": "fish_audio",
      "api_key": "${FISH_AUDIO_API_KEY}"
    }
  }
}
```

### 3.3 启动顺序

```bash
# 1. 启动 llama.cpp
llama-server --model models/llm/qwen3-14b-q4_k_m.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 32768

# 2. 启动 ComfyUI
python ComfyUI/main.py --listen 0.0.0.0 --port 8188

# 3. 启动 API Gateway
uvicorn api_service.main:app --host 0.0.0.0 --port 9000

# 4. 运行 Workflow (直调或API调用)
python run_stage1.py --novel "测试"
```

---

## 四、Workflow层详解

### 4.1 独立脚本模式

每个stage都有独立的运行脚本：

```
run_stage1.py  # 小说生成
run_stage2.py  # 图像生成 + 预处理
run_stage3.py  # TTS音频生成
run_stage4.py  # 视频合成
```

### 4.2 Preprocessor - 核心预处理

Stage 2的Preprocessor负责：
1. **场景提取**: 从章节内容提取分镜场景
2. **分镜生成**: 生成每个shot的visual_prompt
3. **Prompt构建**: 构建完整的SD prompt
4. **缓存管理**: 支持断点续传

```python
# run_stage2.py 中的流程
preprocessor = ScenePreprocessor(config, novel, llm_client=llm_client)
await preprocess_novel(novel, config)  # 生成缓存
results = await generator.process(novel, preprocessor=preprocessor)  # 使用缓存生成图像
```

### 4.3 Script JSONL vs 缓存

**当前状态**:
- Preprocessor生成的"分镜脚本"保存在 `cache/scenes/` 和 `cache/prompts/`
- 并非保存在标准的 `data/scripts/script_*.jsonl`

**问题**: Stage 3需要从 `data/scripts/script_*.jsonl` 读取，但文件可能不存在

**建议**: 将Preprocessor的分镜输出统一写入 `data/scripts/script_*.jsonl`

---

## 五、备选方案与风险控制

### 5.1 LLM备选方案

| 方案 | 部署方式 | 内存/显存 | 适用场景 |
|------|----------|-----------|----------|
| NVIDIA NIM | Cloud API | 0GB | 快速原型 |
| vLLM | 本地进程 | ~8GB | 推荐主力 |
| Ollama | 本地进程 | ~8GB | 简单部署 |
| 直调API | 独立服务 | N/A | 生产环境 |

### 5.2 图像生成备选

| 方案 | 部署方式 | 显存 | 质量 |
|------|----------|------|------|
| ComfyUI SDXL | 独立进程 (:8188) | ~4GB | 高 |
| 本地diffusers | Workflow直调 | ~4GB | 高 |
| Z-Image-Turbo | ComfyUI | ~3GB | 中 |
| Flux Dev | ComfyUI | ~8GB | 极高 |

### 5.3 视频生成备选

| 方案 | 部署方式 | 显存 | 帧数 |
|------|----------|------|------|
| SVD XT | ComfyUI | ~3GB | 25 |
| Ken Burns | FFmpeg (CPU) | 0GB | N/A |
| WanVideo | ComfyUI | ~8GB | 81 |

### 5.4 TTS备选

| 方案 | 部署方式 | 费用 | 质量 |
|------|----------|------|------|
| Edge TTS | 本地 | 免费 | 中 |
| Fish Audio | Cloud API | 按量 | 高 |
| ChatTTS | 本地 | 免费 | 高 |

---

## 六、24GB VRAM约束下的最优架构

### 6.1 架构优势

由于GPU资源是分开的，24GB约束不再是问题：

```
┌─────────────────────────────────────────────┐
│  机器1: 24GB VRAM                          │
│  ┌─────────────────────────────────────┐   │
│  │  llama.cpp (独立进程)                │   │
│  │  模型: Qwen3-14B                     │   │
│  │  显存: ~8GB                         │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │  ComfyUI (独立进程)                 │   │
│  │  模型: SDXL + SVD                    │   │
│  │  显存: ~6GB (分时复用)              │   │
│  └─────────────────────────────────────┘   │
│  剩余: ~10GB 用于系统和其他              │
└─────────────────────────────────────────────┘
```

### 6.2 执行策略

```
推荐: 分时复用GPU资源

时间线:
T0-T2: Stage 1 小说生成 → LLM API调用，GPU空闲
T2-T5: Stage 2 图像生成 → ComfyUI加载SDXL
T5-T6: ComfyUI卸载SDXL，加载SVD
T6-T8: Stage 2 视频生成
T8-T10: Stage 3 TTS (CPU/云端)
T10-T12: Stage 4 合成 (CPU)
```

---

## 七、待解决问题清单

### P0 - 必须解决
1. [ ] **ComfyUI工作流模板**: 替换占位符为真实workflow

### P1 - 重要
2. [ ] **LLM输出解析**: 完善三层验证机制
3. [ ] **Script JSONL统一**: Preprocessor输出到标准位置
4. [ ] **API Key外置**: 移除硬编码

### P2 - 改进
5. [ ] **角色一致性**: IP-Adapter或切换InstantID
6. [ ] **分镜脚本流程**: 确保Stage 1→2→3数据流完整
7. [ ] **缓存目录整理**: 统一缓存位置

### P3 - 探索
8. [ ] **HunyuanVideo集成**: 更长帧数视频
9. [ ] **ACE-Step BGM**: 本地音乐生成
10. [ ] **声音克隆**: GPT-SoVITS

---

## 八、文档输出结构

| 文档 | 内容 |
|------|------|
| `01_project_analysis.md` | 项目现状、架构理解、问题识别 (本文) |
| `02_architecture_detail.md` | 各Stage详细设计、Server/Workflow关系 |
| `03_prompt_engineering.md` | Prompt工程规范、中间数据结构 |
| `04_implementation_gaps.md` | 实现差距分析、测试矩阵 |
| `05_roadmap.md` | 开发计划、里程碑 |

---

*文档版本: v2.0 (修正架构理解)*
*创建时间: 2026-04-12*

# 05_实施路线图

## 一、实施优先级

### P0 - 必须先修复（阻塞性问题）

| 优先级 | 任务 | 预计时间 | 验证标准 |
|--------|------|----------|----------|
| P0-1 | 恢复 `_adapt_to_script` 分镜脚本生成 | 1 天 | `data/scripts/script_*.jsonl` 能正确生成 |
| P0-2 | 统一使用 `robust_json_generate` | 1 天 | LLM JSON 解析成功率 > 95% |
| P0-3 | 从真实 ComfyUI 导出 workflow JSON | 1 天 | 图像生成 API 能真正执行 |

### P1 - 核心功能实现

| 优先级 | 任务 | 预计时间 | 验证标准 |
|--------|------|----------|----------|
| P1-1 | 实现 Phase 2 视频生成 (SVD) | 2 天 | 能生成视频片段 |
| P1-2 | 实现 Phase 3 视频合成 | 2 天 | 最终视频音画同步 |
| P1-3 | 统一入口为 `run_pipeline.py` | 0.5 天 | 废弃 `main.py` |
| P1-4 | 实现 InstantID 替代 IP-Adapter | 1 天 | 同一角色 10 张图一致 |

### P2 - 工程化改进

| 优先级 | 任务 | 预计时间 | 验证标准 |
|--------|------|----------|----------|
| P2-1 | API Key 外置到 `.env` | 0.5 天 | 无硬编码默认值 |
| P2-2 | Prompt 配置分离完成 | 1 天 | 所有 prompt 在 YAML 文件中 |
| P2-3 | 三层配置模型集成 | 2 天 | `project_preset.json` 正确生成和加载 |
| P2-4 | FastAPI 编排层完善 | 3 天 | `/projects/` 端点可用 |

---

## 二、详细实施步骤

### Phase 0: 基础修复 (Day 1-3)

#### Day 1: 修复 LLM JSON 解析

**任务**: 统一使用 `robust_json_generate`，消除 `_extract_json` 的脆弱正则。

**步骤**:

1. 修改 `stages/stage1_novel/novel_generator.py` 中所有 LLM 调用，改用 `robust_json_generate`
2. 添加 `required_fields` 参数确保关键字段存在
3. 测试：用各种 LLM 输出格式（纯 JSON、markdown 代码块、截断 JSON）验证

**验证**:
```bash
# 运行测试
pytest tests/test_novel_generator.py -v

# 手动测试
python run_stage1.py --novel "测试"
# 观察 JSON 解析错误日志
```

#### Day 2: 恢复分镜脚本生成

**任务**: 恢复 `novel_generator.py` 中被注释的 `_adapt_to_script` 方法。

**步骤**:

1. 实现 `generate_script_lines` 方法：
   ```python
   async def generate_script_lines(
       self,
       chapter: Chapter,
       blueprint: StoryBlueprint
   ) -> List[ScriptLine]
   ```

2. 确保输出到 `data/scripts/script_*.jsonl`

3. 在章节生成后自动调用

4. 测试：生成一本小说，检查 `script_*.jsonl` 是否存在且格式正确

**验证**:
```bash
python run_pipeline.py --project-id "test" --phase 1
# 检查 outputs/test/data/scripts/script_*.jsonl 是否存在
```

#### Day 3: 导出真实 ComfyUI Workflow

**任务**: 从真实 ComfyUI 界面导出 workflow JSON。

**步骤**:

1. 安装并启动 ComfyUI（如果未安装）
2. 设计 T2I 工作流（SDXL + InstantID）
3. 设计 I2V 工作流（SVD）
4. 导出为 JSON
5. 添加 `_meta` 和 `_node_mapping` 信息
6. 运行节点映射验证脚本

**验证**:
```bash
# 启动 ComfyUI
python /path/to/ComfyUI/main.py --listen 0.0.0.0 --port 8188

# 验证 workflow
python scripts/validate_workflow.py

# 测试图像生成 API
curl -X POST http://localhost:9000/image/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a young swordsman", "width": 1024, "height": 1024}'
```

---

### Phase 1: 核心功能 (Day 4-9)

#### Day 4-5: Phase 2 视频生成

**任务**: 实现关键帧到视频的生成。

**步骤**:

1. 实现 `generate_keyframes_for_chapter`:
   - 读取 `script_*.jsonl`
   - 调用 ComfyUI t2i 生成关键帧
   - 使用 InstantID 保持角色一致性

2. 实现 `generate_videos_for_chapter`:
   - 调用 ComfyUI i2v (SVD) 生成视频
   - 根据 timeline 设置视频时长

3. 更新 `run_pipeline.py` Phase 2 逻辑

**验证**:
```bash
python run_pipeline.py --project-id "test" --phase 2 --chapter 1
# 检查 outputs/test/images/chapter_001/ 和 videos/chapter_001/ 是否有内容
```

#### Day 6-7: Phase 3 视频合成

**任务**: 实现最终视频合成。

**步骤**:

1. 实现 `compose_final_video`:
   - 按 timeline 拼接视频片段
   - 合并音频
   - 烧录字幕

2. 实现 `generate_srt` 字幕生成

3. 更新 `run_pipeline.py` Phase 3 逻辑

**验证**:
```bash
python run_pipeline.py --project-id "test" --phase 3 --chapter 1
# 检查 outputs/test/final/chapter_001.mp4 是否存在
```

#### Day 8-9: 统一入口 + InstantID

**任务**:
1. 废弃 `main.py`，统一使用 `run_pipeline.py`
2. 用 InstantID 替换 IP-Adapter

**验证**:
```bash
# 只使用 run_pipeline.py
python run_pipeline.py --project-id "test" --all-chapters

# 检查角色一致性
# 生成同一角色的 10 张图，观察面部一致性
```

---

### Phase 2: 工程化 (Day 10-14)

#### Day 10-11: API Key + Prompt 分离

**步骤**:

1. 从 `config/settings.py` 移除 NVIDIA NIM API Key 默认值
2. 创建 `.env.example` 模板
3. 完成 `config/prompts_v2/` 中所有 YAML prompt 文件
4. 实现 `PromptLoader` 热加载机制

#### Day 12-13: 三层配置模型 + FastAPI

**步骤**:

1. 实现 `ProjectPreset.load()` / `.save()`
2. 实现 `ChapterManifest` 生成和加载
3. 完善 FastAPI `/projects/` 端点

#### Day 14: 端到端测试

**验证完整流程**:
```bash
# 1. 创建新项目
python run_pipeline.py --project-id "my_novel" --novel "逆袭剑神" --genre "修仙" --chapters 3 --all-chapters

# 2. 检查所有输出
ls outputs/my_novel/data/scripts/      # script_*.jsonl
ls outputs/my_novel/assets/characters/  # 角色资产
ls outputs/my_novel/images/            # 关键帧
ls outputs/my_novel/videos/            # 视频片段
ls outputs/my_novel/final/            # 最终视频
```

---

## 三、备选方案

### LLM 备选方案

| 方案 | 切换方式 | 注意事项 |
|------|----------|----------|
| vLLM → llama.cpp | 修改 `LOCAL_LLM_CONFIG.provider` | llama.cpp 速度较慢 |
| vLLM → NVIDIA NIM | 修改 `NVIDIA_NIM_CONFIG` | 消耗 API 配额 |
| vLLM → Ollama | 修改 `LOCAL_LLM_CONFIG.provider` | 最简单部署 |

### ComfyUI 备选方案

| 方案 | 触发条件 | 切换方式 |
|------|----------|----------|
| SVD → Ken Burns | VRAM < 4GB | 修改 `VIDEO_GENERATION.svd.enabled=False` |
| SDXL → Z-Image-Turbo | VRAM < 6GB | 修改 `IMAGE_GENERATION.local.model_type` |
| InstantID → 固定 Seed | InstantID 不可用 | 修改 `IMAGE_GENERATION.character_consistency.type` |

### TTS 备选方案

| 方案 | 触发条件 | 切换方式 |
|------|----------|----------|
| EdgeTTS → Fish Audio | EdgeTTS 不可用 | 修改 `AUDIO_GENERATION.local.backend` |
| EdgeTTS → ChatTTS | 需要本地部署 | 修改 `AUDIO_GENERATION.local.backend` |

---

## 四、风险与缓解

### 风险 1: LLM 输出 JSON 不稳定

**缓解**: `robust_json_generate` 三层防护 + 强制 `response_format={"type": "json_object"}`

### 风险 2: VRAM OOM

**缓解**: 分时复用策略，不同时运行 LLM 和 ComfyUI

### 风险 3: 角色一致性问题

**缓解**: InstantID 方案 + 固定 seed 降级策略

### 风险 4: 视频音频不同步

**缓解**: TTS 先生成，音频时长作为视频时长的锚点

---

## 五、24GB VRAM 执行计划

```
启动:
┌─────────────────────────────────────────────────────────────┐
│ T0: 启动 llama.cpp/vLLM (LLM 服务)                        │
│      - VRAM: ~8GB                                         │
└─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ T1-T3: Phase 1 (LLM 生成)                                 │
│      - 生成故事蓝图 + 章节正文 + 分镜脚本                    │
│      - VRAM: ~8GB (llama.cpp)                             │
│      - ComfyUI 空闲                                        │
└─────────────────────────────────────────────────────────────┘
                │
                ▼ (关闭 llama.cpp 释放 VRAM)
┌─────────────────────────────────────────────────────────────┐
│ T4: 启动 ComfyUI + SDXL                                   │
│      - VRAM: ~3.5GB (SDXL) + ~0.3GB (InstantID)          │
└─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ T5-T6: Phase 2 关键帧生成                                  │
│      - 角色定妆照 + 场景图 + 关键帧                         │
│      - VRAM: ~4GB (SDXL + InstantID)                      │
└─────────────────────────────────────────────────────────────┘
                │
                ▼ (卸载 SDXL，加载 SVD)
┌─────────────────────────────────────────────────────────────┐
│ T7: 加载 SVD，卸载 SDXL                                    │
│      - VRAM: ~3GB (SVD)                                   │
└─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ T8: Phase 2 视频生成                                        │
│      - SVD 图生视频                                         │
│      - VRAM: ~3GB                                          │
└─────────────────────────────────────────────────────────────┘
                │
                ▼ (关闭 ComfyUI)
┌─────────────────────────────────────────────────────────────┐
│ T9-T10: Phase 3 (FFmpeg CPU 合成)                          │
│      - 视频拼接 + 音频混合 + 字幕                           │
│      - VRAM: 0GB                                           │
└─────────────────────────────────────────────────────────────┘
```

---

*文档版本: v1.0*
*创建时间: 2026-04-14*

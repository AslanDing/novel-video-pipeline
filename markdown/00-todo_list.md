# TODO List - 按优先级排序

## P0 - 阻塞性问题（必须修复）

- [ ] **P0-1**: 恢复 `_adapt_to_script` 分镜脚本生成
  - 位置: `stages/stage1_novel/novel_generator.py` 第 177-183 行被注释
  - 影响: Stage 2/3/4 无法获得 shot-level 数据，只能降级使用章节摘要
  - 验证: 检查 `outputs/{project}/data/scripts/script_*.jsonl` 是否存在

- [ ] **P0-2**: 统一使用 `robust_json_generate` 替代脆弱的 `_extract_json`
  - 位置: 所有 LLM 调用处
  - 影响: JSON 解析失败导致流程中断
  - 验证: 多次运行 LLM 调用，解析错误率 < 5%

- [ ] **P0-3**: 从真实 ComfyUI 导出 workflow JSON
  - 位置: `api_service/workflows/t2i_flux.json`, `i2v_wan.json`
  - 影响: 图像/视频生成 API 无法真正执行
  - 验证: ComfyUI 界面设计工作流 → 导出 JSON → 添加节点映射 → 验证通过

## P1 - 核心功能实现

- [ ] **P1-1**: 实现 Phase 2 视频生成 (SVD)
  - 位置: `run_pipeline.py` 第 226-227 行 TODO
  - 验证: `videos/chapter_xxx/shot_*.mp4` 能生成

- [ ] **P1-2**: 实现 Phase 3 视频合成
  - 位置: `run_pipeline.py` 第 246-247 行 TODO
  - 验证: `final/chapter_xxx.mp4` 能生成且音画同步

- [ ] **P1-3**: 统一入口为 `run_pipeline.py`，废弃 `main.py`
  - 验证: `python run_pipeline.py --project-id "test" --all-chapters` 能完整运行

- [ ] **P1-4**: 实现 InstantID 替代 IP-Adapter
  - 位置: `stages/stage2_visual/image_generator.py`
  - 验证: 同一角色 10 张图面部一致

## P2 - 工程化改进

- [ ] **P2-1**: API Key 外置到 `.env`，移除 `config/settings.py` 默认值
  - 验证: 启动时无硬编码默认值

- [ ] **P2-2**: Prompt 配置分离完成，所有 prompt 在 YAML 中
  - 验证: `config/prompts_v2/` 包含所有需要的 prompt

- [ ] **P2-3**: 三层配置模型正确集成
  - 验证: `project_preset.json` 正确生成和加载

- [ ] **P2-4**: FastAPI 编排层完善
  - 验证: `/projects/` 端点可用

## P3 - 探索功能

- [ ] **P3-1**: HunyuanVideo 集成（更长帧数视频）
- [ ] **P3-2**: ACE-Step BGM 生成（本地音乐）
- [ ] **P3-3**: 声音克隆（GPT-SoVITS）
- [ ] **P3-4**: ChatTTS 本地集成

---

## 已完成

- [x] 三层配置模型数据类创建 (`core/config_models.py`)
- [x] ProjectStorage 存储管理器 (`core/storage.py`)
- [x] PromptLoader YAML 加载器 (`core/prompt_loader.py`)
- [x] ScriptGenerator 分镜脚本生成器 (`stages/stage1_novel/script_generator.py`)
- [x] CharacterPackManager 角色包生成器 (`stages/stage2_visual/character_pack_generator.py`)
- [x] ScenePackManager 场景包生成器 (`stages/stage2_visual/scene_pack_generator.py`)
- [x] AssetFirstPipeline 流水线框架 (`run_pipeline.py`)
- [x] FastAPI 路由基础框架 (`api_service/routers/projects.py`, `shots.py`)
- [x] YAML Prompt 模板 (`config/prompts_v2/llm_prompts/`, `image_prompts/`)
- [x] StreamingJSONGenerator JSON 修复工具 (`utils/streaming_json_generator.py`)

---

## 当前状态总结

| 类别 | 完成 | 待完成 |
|------|------|--------|
| 框架/数据类 | 10 | 0 |
| P0 阻塞 | 0 | 3 |
| P1 核心功能 | 0 | 4 |
| P2 工程化 | 0 | 4 |
| P3 探索 | 0 | 4 |

**核心问题**: 框架已搭建完毕，但实际逻辑（P0-P1）尚未实现。分镜脚本生成被注释，Phase 2/3 视频生成是 TODO。

---

*更新时间: 2026-04-14*

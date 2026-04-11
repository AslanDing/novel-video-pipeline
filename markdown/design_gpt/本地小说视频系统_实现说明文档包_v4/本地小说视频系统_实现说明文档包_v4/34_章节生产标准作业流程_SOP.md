# 34 章节生产标准作业流程 SOP

## 1. 目的

本文件把一个章节从 0 到 1 的生产过程写成标准作业流程，适合：

- 产品 demo 生产
- 内部联调
- 早期小团队手工 + 自动混合流程

---

## 2. 输入准备

### 操作人
内容策划 / 导演角色

### 输入项
- 小说构思
- 风格说明
- 主要角色表
- 参考图（可选）
- 目标时长

### 输出项
- `inputs/concept.json`
- `inputs/style_refs/*`
- `inputs/voice_refs/*`

---

## 3. SOP 步骤

### 步骤 1：创建项目

- 在 UI 中创建 project
- 填写语言、风格、目标时长
- 选择默认模型 profile

验收：project config 已持久化

### 步骤 2：生成小说圣经与章节草案

- 调用 LLM 生成 story bible
- 调用 LLM 生成 episode outline
- 调用 LLM 生成 chapter draft

验收：文本通过 schema 校验

### 步骤 3：生成 shot script

- 把 chapter draft 改写为 shot script
- 每个 shot 时长控制在 2-6 秒
- 检查 scene / shot 编号连续性

验收：`shot_count` 在目标区间，字段完整

### 步骤 4：执行脚本审核

- 编剧或导演审核 script bundle
- 必要时做 patch

验收：script status = approved

### 步骤 5：生成 voice bible

- 为 narrator 和主要角色绑定 voice profile
- 设置 style tags
- 导入参考音频或选择默认音色

验收：每个 speaker 均有可用 voice profile

### 步骤 6：生成音频

- 批量生成对白与旁白
- 跑 ASR 复核
- 修复失败片段

验收：audio coverage = 100%

### 步骤 7：生成角色立绘与关键帧

- 先固定角色 look
- 再生成剧情关键帧
- 审核关键 close-up 镜头

验收：所有必需镜头存在 approved keyframe

### 步骤 8：生成镜头视频

- 以 keyframe + motion prompt 逐镜头生成
- 失败镜头自动重试
- 不通过镜头进入人工 review

验收：所有镜头通过最低阈值

### 步骤 9：合成

- 拼接镜头
- 混音
- 生成字幕
- 导出 preview 和 master

验收：成片可播放，音视频同步

### 步骤 10：终审与发布

- 看片
- 若通过则发布章节版本
- 若不通过则定位问题镜头回退

验收：episode status = published

---

## 4. 建议角色分工

| 角色 | 职责 |
|---|---|
| 产品/导演 | 风格、镜头、终审 |
| 编剧 | 构思、脚本修订 |
| 音频负责人 | 声线、TTS、混音 |
| 视觉负责人 | 角色、关键帧、镜头风格 |
| 工程负责人 | 编排、调度、稳定性 |

---

## 5. 每日例行检查

- GPU 显存监控是否异常
- 失败队列是否堆积
- 磁盘空间是否充足
- 最近一次成片是否能正常回放
- 关键 profile 是否被误改

---

## 6. v1 生产建议

- 单章节 8-12 分钟以内
- 单镜头 2-5 秒为主
- 同时运行项目不超过 2 个
- 每章保留一次 script review 和一次 final review

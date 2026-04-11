# 30 GPU 资源管理与调度算法

## 1. 目标与约束

环境约束：
- 单机单卡
- 24GB VRAM
- 本地所有模型共用一张 GPU

设计目标：
- 避免多个重模型同时驻留
- 保持 GPU 高利用率但不爆显存
- 减少频繁加载卸载的抖动
- 让小任务不被长任务无限饿死

---

## 2. 任务分类

| 类别 | 示例 | GPU 占用级别 |
|---|---|---|
| G0 | metadata 整理、FFmpeg 清单生成 | 不占 GPU |
| G1 | TTS 小段推理、轻量 ASR | 低 |
| G2 | Qwen 14B 文本生成、关键帧生成 | 中 |
| G3 | Hunyuan I2V、长镜头生成 | 高 |

---

## 3. 资源配置文件

```yaml
profiles:
  qwen3_14b_instruct_awq:
    class: G2
    est_vram_gb: 14
    warmup_sec: 12
  fish_s2_pro:
    class: G1
    est_vram_gb: 6
    warmup_sec: 8
  sd35m_ipadapter_v1:
    class: G2
    est_vram_gb: 12
    warmup_sec: 10
  hunyuan_i2v_480p_sd_v1:
    class: G3
    est_vram_gb: 18
    warmup_sec: 25
```

---

## 4. 调度规则

### 4.1 单活模型原则

任一时刻，GPU 上只允许一个 G2/G3 任务类模型处于 active 状态。

### 4.2 轻任务插队窗口

若当前运行 G3 长任务，允许在镜头之间的空隙插入 G1 轻任务，但禁止打断 G3 正在推理中的核心过程。

### 4.3 批量同类优先

当 GPU 已经加载某模型时，优先连续执行同 profile 的任务，减少热切换。

---

## 5. 建议调度算法

采用“**分级优先队列 + 模型亲和性 + 老化机制**”：

评分函数：

```text
score = base_priority + waiting_age_bonus + same_profile_bonus - estimated_switch_cost
```

其中：
- `base_priority`：用户动作触发 > 自动后台修复
- `waiting_age_bonus`：等待越久越高
- `same_profile_bonus`：和当前已加载模型一致时加分
- `estimated_switch_cost`：模型切换开销

---

## 6. GPU 锁设计

建议实现三级锁：

1. `global_gpu_lock`
2. `profile_lock:{profile}`
3. `artifact_lock:{target_id}`

说明：
- 全局 GPU 锁保证单卡串行
- profile 锁防止同模型重复热加载
- artifact 锁防止同一镜头被重复执行

---

## 7. OOM 处理

OOM 发生时不应直接终止整个 job，而应执行降级流程：

1. 记录本次参数
2. 若是视频任务：
   - 先降 frame_count
   - 再降 resolution
   - 再启用 offload
3. 若是图像任务：
   - 先降 batch size
   - 再降 steps
4. 若仍失败，标记 `failed_retryable`

---

## 8. 预热策略

- 开机后先预热 Qwen 和 Hunyuan 两个最重 profile
- 非生产时段可定时卸载冷模型
- 热路径优先：`llm -> image -> video`

---

## 9. 监控指标

至少采集：

- 当前模型 profile
- 模型加载时间
- 推理时间
- 实际 peak VRAM
- 排队长度
- 每类任务平均等待时间
- OOM 次数
- 模型切换次数

---

## 10. 推荐运行节奏

对于一个章节生产，建议执行顺序：

1. Qwen 连续跑文本任务
2. Fish/CosyVoice 连续跑音频
3. SD3.5 连续跑关键帧
4. Hunyuan 连续跑全部镜头
5. QC 与 FFmpeg 收尾

这样可以把模型切换次数降到最低。

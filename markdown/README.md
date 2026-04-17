1) Python 业务代码：管“创作决策”

你的 Python 代码不该去管 sampler、CFG、节点 ID、ControlNet 节点怎么连。
它应该只管这些：

小说结构
章节拆解
分镜规划
角色设定
场景设定
镜头目标
哪个镜头要旁白，哪个镜头要对白
哪个镜头需要角色一致性，哪个镜头需要场景延续
最终要生成哪些资产

也就是说，Python 输出的应该是意图层数据，不是底层工作流参数。

比如 Python 产出：

{
  "chapter_id": "ch01",
  "shots": [
    {
      "shot_id": "ch01_s003",
      "purpose": "introduce heroine close-up",
      "characters": ["heroine"],
      "scene": "tavern_night",
      "shot_type": "close_up",
      "mood": "cold, restrained",
      "dialogue": "我不记得自己是谁。",
      "needs_character_consistency": true,
      "needs_scene_consistency": true,
      "video_mode": "i2v"
    }
  ]
}


2) FastAPI：管“运行时编排”

FastAPI 应该做的是把你的“意图层数据”翻译成“可执行任务”。

它负责：

参数校验
任务拆解
任务排队
资源锁
选择调用哪个下游服务
选用哪个 workflow 模板
往 workflow 里注入变量
保存中间资产
重试和失败恢复
返回统一状态

所以：

FastAPI 不是推理层。FastAPI 是控制平面。

它应该知道：

当前项目有哪些角色参考图
哪一章节已经生成过角色包
这个 shot 应该走哪个 ComfyUI workflow
当前 GPU 忙不忙
这个视频镜头要不要先做关键帧再做 I2V
这个对白要不要先做 TTS 再根据音频时长回填视频长度


3) ComfyUI：管“具体怎么生成”

ComfyUI 里保存的是：

工作流图
模型加载方式
节点连接关系
sampler
scheduler
LoRA 挂法
IP-Adapter 接法
ControlNet 接法
HunyuanVideo / 图生视频节点图
ACE-Step 1.5 音乐工作流

也就是说：

ComfyUI 负责“怎么生成”，不负责“为什么生成这张图”。

你不应该在 Python 里直接手搓一大堆 ComfyUI 原始节点 JSON。
更好的方式是：在 ComfyUI 里先手工做好少量稳定工作流模板，然后由 FastAPI 在运行时只注入变量。

这也符合 ComfyUI 官方的产品形态：它既有本地 API，也有 workflow templates 和 subgraph 这种可复用机制。




## A. Python 管“逻辑一致性”

例如：

主角本章统一用 character_pack_v2
酒馆场景统一用 scene_pack_tavern_night_v1
当前镜头继承上一个镜头的构图氛围
女主近景时角色一致性权重要高
远景动作镜头时动作优先，角色一致性权重可以稍降

这些是创作规则，应该在 Python 或 FastAPI 的业务规则里。

## B. FastAPI 管“运行时参数”

例如：

reference_images = [heroine_face_ref_01, heroine_outfit_ref_02]
ip_adapter_scale = 0.82
controlnet_pose_strength = 0.65
scene_ref_weight = 0.55
seed_mode = fixed_per_character

这些是本次任务的具体参数，应该由 FastAPI 在下发 ComfyUI 工作流前统一注入。

## C. ComfyUI 管“技术实现”

例如：

Load Image -> IPAdapter -> KSampler -> VAE Decode
OpenPose -> ControlNet -> SD3.5
Reference image + motion prompt -> HunyuanVideo I2V

这些应固定在 workflow 里，不要在上层频繁改结构。




## 三、你最该用的思路：不是“配置散落”，而是“三层配置模型”
### 第 1 层：Project Preset

项目级别，比较稳定。

比如：

{
  "project_id": "novel_a",
  "visual_style": "dark_fantasy_cinematic",
  "default_image_workflow": "character_keyframe_sd35_v1",
  "default_video_workflow": "hunyuan15_i2v_v1",
  "default_tts_voice_map": {
    "narrator": "voice_narrator_v1",
    "heroine": "voice_heroine_v2"
  },
  "consistency_policy": {
    "character_default": 0.8,
    "scene_default": 0.6,
    "seed_strategy": "fixed_per_character"
  }
}
### 第 2 层：Chapter Manifest

章节级别，决定这章要生成什么。

比如：

{
  "chapter_id": "ch01",
  "scene_order": ["tavern_night", "alley_escape"],
  "characters_involved": ["heroine", "innkeeper"],
  "required_assets": [
    "heroine_ref_pack",
    "tavern_scene_pack"
  ],
  "shots": ["ch01_s001", "ch01_s002", "ch01_s003"]
}
### 第 3 层：Shot Spec

镜头级别，最具体。

比如：

{
  "shot_id": "ch01_s003",
  "workflow": "character_closeup_i2v_v1",
  "prompt": "close-up of a pale female swordswoman in candlelight",
  "motion_prompt": "slow push-in, candle flicker, restrained anger",
  "character_refs": ["heroine_face_ref_01", "heroine_outfit_ref_01"],
  "scene_refs": ["tavern_ref_01"],
  "consistency": {
    "character_weight": 0.85,
    "scene_weight": 0.55
  },
  "tts_line_id": "tts_003"
}



## 阶段 A：预生产

这一阶段先把“稳定资产”准备好，不急着做视频。

### 第 1 步：LLM 生成章节脚本

你的 Python 先调 FastAPI 的 LLM 接口，让 llama.cpp 生成：

章节摘要
分镜草稿
旁白
对白
角色出场表
场景表

这一步不要让 LLM 直接输出“文学正文”给视频用。
要输出结构化 shot list。

llama.cpp 的 llama-server 本身就是 OpenAI 兼容 REST API，所以你把它放在 FastAPI 后面做文本规划层是合理的。

### 第 2 步：生成角色包

如果这个角色第一次出场，先不要直接做剧情镜头。
先走“角色资产生成流程”：

角色立绘
表情组
半身像
全身像
不同角度参考图
服装参考图

这些会变成后面所有镜头的 reference assets。

### 第 3 步：生成场景包

同理，重要场景先生成：

酒馆全景
酒馆中景
酒馆角落
门口夜景
光照氛围参考

这样后面镜头就不会每次“重新抽一个酒馆”。

### 第 4 步：固化章节 Manifest

到这里，FastAPI 保存一份章节运行清单：

这章有哪些 shots
每个 shot 用哪个 workflow
每个 shot 需要哪些角色参考
每个 shot 需要哪些场景参考
哪些镜头要先做音频，再做视频

这一步很重要，因为它决定你后面可以断点续跑。

## 阶段 B：正式生产
### 第 5 步：先做 TTS，不要先做最终视频

这是很多人会反过来做的地方。

对白和旁白先生成。

原因很简单：
视频最终长度要服从音频长度，而不是反过来。

Fish Audio 的本地 API 天生适合这一层，它有 TTS、参考音频克隆和批处理能力。

TTS 输出后，FastAPI 记录每句：

音频文件路径
实际时长
角色
情绪
所属 shot

### 第 6 步：生成关键帧

这一步只出静态图，不出视频。

每个 shot 先出一张或几张关键帧：

起始关键帧
可选结束关键帧
可选过渡关键帧

这里角色一致性主要靠：

固定角色 reference pack
固定角色 seed 策略
固定角色锚点描述
IP-Adapter
场景 reference

这一步是全流程成功率最高的地方，所以先把图做对，再做视频。

### 第 7 步：关键帧转视频

现在才进 ComfyUI-video。

每个 shot 的 I2V 输入应该包括：

关键帧
motion prompt
目标帧数
fps
时长目标
可选 ending frame
角色/场景 reference

HunyuanVideo 1.5 官方在 ComfyUI 的文档里明确定位为适合 24GB VRAM 的消费级 GPU，并支持高质量 T2V / I2V，典型时长是 5–10 秒，带比较好的指令跟随和镜头控制。对你这种“小说分镜短镜头”场景，非常契合。

### 第 8 步：音频和视频合成

最后再合成：

shot 视频拼接
对白音频
旁白音频
BGM
环境氛围
字幕

ACE-Step 1.5 在 ComfyUI 里原生支持，但官方定位是音乐生成，不是通用 Foley，所以它更适合做 BGM / 氛围音乐，不要拿它当所有细碎音效的唯一来源。




## 五、不同模块怎么配合：最推荐的职责链
### Python 业务代码

负责发起高层任务：

create_project
generate_chapter_plan
render_chapter
rerender_shot
regenerate_character_pack

它只和 FastAPI 说话。

### FastAPI

负责把 render_chapter(ch01) 变成一串子任务：

llm_generate_shotlist
ensure_character_assets
ensure_scene_assets
generate_tts_batch
generate_keyframes
generate_shot_videos
generate_bgm
compose_final_cut

这就是你的任务状态机。

### ComfyUI-image

只做：

角色图
场景图
分镜关键帧
图像修复
一致性图像生成

### ComfyUI-video

只做：

T2V
I2V
首尾帧动画
镜头扩展

### Fish Audio

只做：

TTS
voice cloning
多角色语音

### llama.cpp

只做：

章节拆分
分镜脚本
prompt rewrite
镜头文案
旁白文本


## 用“资产优先”，不要用“镜头优先”

你现在做小说视频，很容易犯的错误是：

“来一个 shot，就现做角色图、现做场景图、现做视频。”

这会导致一致性很差。

正确方法是：

先固化资产，再生产镜头。

也就是：

角色包
场景包
章节 shot list
shot 关键帧
shot 视频

这样角色和场景都有“主参照物”，一致性会高很多。

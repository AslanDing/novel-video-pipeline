# This file is for human

1. 重新设计一下架构
2. 将 软件与llm, 文生图等功能分离，图文生视频，音频生成等功能分离，拆分成api
3. 将prompt 从代码里面分离出来
4. 使用现有一些平台Stable Diffusion (DrawThings API)，IndexTTS2 (Voice cloning)，Aegisub / SRT，CapCut (Draft Generation) / FFmpeg
5. 模型选择：
    - LLM: Qwen3-30B-A3B-Instruct-2507/Qwen3-14B/gemma4
    - 文生图：Stable Diffusion (DrawThings API)/z-image-turbo
    - TTS: IndexTTS2 (Voice cloning)/qwen-audio
    - (文图生视频)视频生成：FFmpeg/Vidu





1. test image generation
2. test tts more people
3. video generation
4. add these features
5. reorganize the code

6. 预定角色年纪，性别，用于来生成图像和声音，一致性
7. 背景声音没有生成，没有下载本地的TTS模型
8. Qwen3-30B-A3B-Instruct-2507 本地写小说  Qwen3-14B






NovelVids (猫影短剧)

该项目的“分镜（Storyboard）”过程是其 AI 工作流中的核心第 3 步，主要通过模拟专业电影摄影指导（DP）的逻辑，将小说文本转化为结构化的视频脚本。

以下是其分镜处理的具体机制：

1. 角色与场景的“实体绑定”（Entity Binding）
在分镜开始前，系统会先结合第 1 步提取的角色（Person）、**场景（Scene）和道具（Item）**清单。

机制： 分镜脚本中不直接描述这些角色的外貌，而是使用 @{{名称}} 的占位符（例如 @{{林黛玉}}）。
目的： 确保视频生成模型在后续环节中一致性地调用第 2 步生成的“参考图”，避免角色在不同镜头中“变脸”。
2. 电影工业级的提示词架构
系统将 LLM（如 GPT-4o 或 Claude）设定为“精英摄影师与 Sora 2 提示词专家”。它不仅是翻译文字，而是进行二次创作。每个分镜（Shot）都会强制包含以下技术维度：

镜头参数（Lens）： 明确使用多少毫米的镜头（如 24mm 广角或 85mm 肖像镜）、光圈（T1.5）和滤镜。
构图与光影（Lighting）： 强制使用专业术语，如“伦勃朗光（Rembrandt）”、“丁达尔效应”、“冷暖对比（Teal & Orange）”。
动态控制（Actions）： 必须包含精确的 0.0s-2.0s 动作描述。
听觉设计（Sound）： 描述环境音质感（如“皮鞋踩在雪地的咯吱声”）。
3. 分镜的结构约束
分镜生成由 Pydantic 模型（Storyboard）严格校验，确保输出的格式符合：

固定时长： 每个镜头严格限制在 4s 或 8s（适配主流视频模型生成长度）。
分段逻辑： 如果一段故事情节过长，AI 会自动将其拆解为多个切镜（Cuts），以保持节奏感。
属性分离： 视觉描述（Visual Prose）与技术提示（Technical Prompt）分离，方便后端针对不同模型进行优化。
4. 自动化处理流程
在 services/storyboard/handler.py 中：

输入分析： 接收当前章节的文本。
上下文加载： 注入之前提取的实体视觉特征。
结构化解析： 利用 OpenAI 的 response_format 强制 LLM 直接输出 JSON。
元数据记录： 记录使用的 Token 数、模型版本等，用于成本和性能监控。
总结
该项目不是简单的“翻译”，而是通过**“实体映射 + 影视技术化重写 + 结构化约束”，将文学性的描述转化为可被视频 AI 执行的导演预备脚本**。


在当前的 ./novel-video-workflow 项目中，分镜（Storyboard）的实现逻辑主要通过 AI 导演模拟 和 时长引导提取 两个核心策略完成：

1. AI 导演角色模拟 (Persona Implementation)
系统中内置了一个名为 OllamaSystemDirector 的提示词（在 ollama_client.go 中），它将 LLM（如 Qwen/Llama）设定为“经验丰富的影视分镜师”。

指令： 明确要求 AI “将长文本分解为 3-8 个（或更多）关键视觉场景”。
维度： 每个分镜必须包含主体描述、风格限定、细节补充和氛围渲染四个要素。
2. 时长引导策略 (Duration-Guided Strategy)
这是项目的一个亮点。为了防止生成的图片与音频时长脱节，系统在分镜时会进行以下计算：

音频预估： 先预估 TTS 音频的总时长。
密度控制： 在发送给 AI 的提示词中包含一段逻辑：“文本内容估算的音频时长约为 X 秒，建议每 30-60 秒 对应一个视觉场景。”
动态调整： 让 AI 根据内容的重要性和视觉表现力，自主决定最终的分镜数量（通常建议 8-20 个）。
3. 技术实现流程
在代码层面（pkg/tools/drawthings/ollama_client.go 的 AnalyzeScenesAndGeneratePrompts 方法中）：

输入： 章节全文 + 艺术风格 + 预估时长。
结构化输出： 强制要求以 JSON 数组 格式返回，例如 ["场景1提示词", "场景2提示词", ...]。
解析与回退：
首先尝试直接解析 JSON。
如果 AI 返回了带编号的文字（如 1. xxx 2. xxx），系统会通过正则和字符串处理逻辑自动提取出每一行分镜。
关联： 生成的分镜提示词随后被送入 drawthings 模块，为每个分镜生成一张高分辨率的 .png 图片。
4. 总结
目前这里的“分镜”本质上是 “语义感知分割” —— 并不是简单的按句号切分，而是让 AI 读懂故事，找出那 10 几个最具有“画面感”的瞬间，并确保这些瞬间覆盖了整个视频的时长。

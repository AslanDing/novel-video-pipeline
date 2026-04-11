import json
from typing import Dict, Any, Type, List
from pydantic import BaseModel

def generate_field_constraints(schema: Dict[str, Any]) -> str:
    """从 JSON Schema 提取核心字段约束并格式化为文本描述"""
    constraints = []
    
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    for field, prop in properties.items():
        field_type = prop.get("type", "mixed")
        if "$ref" in prop:
            field_type = "object"
        
        is_required = "required" if field in required else "optional"
        desc = prop.get("description", "无描述")
        
        line = f"   - {field} ({field_type}, {is_required}): {desc}"
        
        # 输出长度约束（字符串类型），让 LLM 感知到长度要求
        if field_type == "string":
            if "minLength" in prop:
                line += f" | 最少 {prop['minLength']} 字符"
            if "maxLength" in prop:
                line += f" | 最多 {prop['maxLength']} 字符"
        
        # 处理枚举
        if "enum" in prop:
            line += f" | 枚举值: {', '.join(map(str, prop['enum']))}"
        
        # 处理嵌套对象
        if field_type == "object" and "properties" in prop:
             nested_constraints = generate_field_constraints(prop)
             line += f"\n     嵌套约束:\n{nested_constraints}"
             
        constraints.append(line)
        
    return "\n".join(constraints)

def generate_protocol_prompt(task_description: str, model: Type[BaseModel]) -> str:
    """生成完整的协议式提示词"""
    schema = model.model_json_schema()
    
    # 递归解析嵌套引用的 schema
    def resolve_references(schema: Dict[str, Any], full_schema: Dict[str, Any]) -> Dict[str, Any]:
        """简单的引用解析器"""
        if isinstance(schema, dict):
            if "$ref" in schema:
                ref_path = schema["$ref"].split("/")[-1]
                ref_schema = full_schema.get("$defs", {}).get(ref_path, {})
                return resolve_references(ref_schema, full_schema)
            return {k: resolve_references(v, full_schema) for k, v in schema.items()}
        elif isinstance(schema, list):
            return [resolve_references(item, full_schema) for item in schema]
        return schema

    resolved_schema = resolve_references(schema, schema)
    
    field_constraints = generate_field_constraints(resolved_schema)
    
    protocol_prompt = f"""【输出协议 - 严格遵守】

1. 输出格式:
   - 必须是合法的 JSON 对象
   - 禁止 Markdown code fence (```json 等)
   - 禁止注释 // 或 /* */
   - 禁止尾随逗号
   - 禁止单引号，所有字符串必须是双引号
   - 禁止未定义的字段 (additionalProperties: false)
   - 禁止 "..." 或 "等" 占位符

2. 字段约束:
{field_constraints}

3. 禁止项 (严格禁止):
   - 禁止输出任何非JSON内容
   - 禁止使用 Markdown 格式
   - 禁止使用代码块
   - 禁止添加任何解释性文字
   - 禁止使用省略号或占位符
   - 禁止添加 Schema 中未定义的字段

【JSON Schema】
{json.dumps(resolved_schema, ensure_ascii=False, indent=2)}

【任务描述】
{task_description}

请严格按照上述协议和 Schema 进行输出。
"""
    return protocol_prompt

# 预定义系统提示词片段
STORY_ARCHITECT_CORE = "你是一位资深爽文小说架构师，擅长构筑庞大且逻辑自洽的仙侠、修仙世界观，并精准把握读者的情绪起伏。"
NOVEL_WRITER_CORE = "你是一位顶级的网文大神，擅长创作宏大的修仙/都市世界。你的文字细腻，善于通过丰富的对白、心理活动和环境描写来铺展情节。你拒绝平铺直叙，擅长在细节中埋下伏笔，让每一章都充满张力和画面感。你生成的内容必须详实、具体，严禁通过总结式语言跳过故事情节。"
SCRIPT_ADAPTER_CORE = "你是一位专业的影视短视频分镜编剧，擅长将文字正文转化为极具张力和视觉感的镜头脚本。"


# ========== 拆分蓝图生成用的 Prompt 模板 ==========

def generate_world_building_prompt(concept) -> str:
    """生成世界观提示词"""
    return f"""根据以下小说概念，设计一个引人入胜的世界观。

小说概念:
- 标题: {concept.title}
- 类型: {concept.genre}
- 风格: {concept.style}
- 核心创意: {concept.core_idea}

请设计:
1. 世界背景设定 (setting) - 涵盖历史、地理和当前局势，200字以上
2. 主要势力列表 (factions) - 每方势力包含 name, description, type (正/邪/中)
3. 世界运行的核心规则或禁忌 (rules)

注意：只输出世界观相关的内容，不要包含角色或情节。"""


def generate_characters_prompt(concept, world_building) -> str:
    """生成角色提示词"""
    return f"""根据以下小说概念和世界观，设计核心角色。

小说概念:
- 标题: {concept.title}
- 类型: {concept.genre}
- 核心创意: {concept.core_idea}

世界观设定:
{world_building.setting}

势力分布:
{chr(10).join([f"- {f['name']}: {f['description']}" for f in world_building.factions])}

请设计 1-10 个核心角色，包括:
- 主角 (protagonist) 至少1个
- 反派 (antagonist) 至少1个
- 配角 (supporting) 若干

每个角色需包含: id, name, role, description, personality, goals, background, appearance

注意：appearance 字段要详细，便于后续 AI 绘画生成角色形象。"""


def generate_power_system_prompt(concept, world_building) -> str:
    """生成修炼体系提示词"""
    return f"""根据以下小说概念和世界观，设计修炼体系。

小说概念:
- 标题: {concept.title}
- 类型: {concept.genre}
- 核心创意: {concept.core_idea}

世界观设定:
{world_building.setting}

请设计:
1. 修炼体系描述 (power_system) - 力量等级划分及其核心逻辑
2. 修炼境界列表 (cultivation_realms) - 每境包含 name, description, level

注意：体系设计要新颖独特，与世界观相契合。"""


def generate_plot_structure_prompt(concept, world_building, characters) -> str:
    """生成情节结构提示词"""
    chars_info = "\n".join([f"- {c.name} ({c.role}): {c.description}" for c in characters[:5]])
    return f"""根据以下小说概念、世界观和角色，设计主线剧情结构。

小说概念:
- 标题: {concept.title}
- 类型: {concept.genre}
- 计划总章节数: {concept.total_chapters}

世界观设定:
{world_building.setting}

修炼体系:
{world_building.power_system}

核心角色:
{chars_info}

请设计主线剧情结构 (plot_structure)，包含 {max(5, concept.total_chapters // 5)} 个情节点:
- 每个情节点需指定对应的起始章节号 (chapter)
- 描述核心冲突和情节发展 (description)
- 指定主要的爽点类型 (shuangdian_type): 如打脸、升级、奇遇、反转
- 指定情感强度 (intensity): low, medium, high, extreme

情节点要覆盖从开头到结尾的完整故事弧线。"""


def generate_chapter_plans_prompt(concept, world_building, characters, plot_structure, start_chapter: int, end_chapter: int) -> str:
    """生成章节规划提示词"""
    chars_info = "\n".join([f"- {c.name}: {c.goals}" for c in characters[:5]])
    return f"""请详细规划第 {start_chapter} 到 {end_chapter} 章的章节规划。

小说标题: {concept.title}
计划总章节数: {concept.total_chapters}

世界观设定:
{world_building.setting}

修炼体系:
{world_building.power_system}

主要角色:
{chars_info}

主线情节点:
{chr(10).join([f"- 第{p.chapter}章: {p.description} (爽点: {p.shuangdian_type}, 强度: {p.intensity})" for p in plot_structure[:5]])}

请为第 {start_chapter} 到 {end_chapter} 章每章设计:
- 章节号 (number)
- 章节标题 (title)
- 本章内容概要 (summary)
- 本章必须发生的关键事件列表 (key_events)
- 本章的具体爽点设计 (shuangdian)，如果适用

确保章节规划连贯且有节奏感。"""


# 预生成的协议式提示词（带 Output 模型）
def get_world_building_protocol_prompt(concept) -> str:
    """获取世界观生成的协议式提示词"""
    from stages.stage1_novel.pydantic_models import WorldBuildingOutput
    task_desc = generate_world_building_prompt(concept)
    return generate_protocol_prompt(STORY_ARCHITECT_CORE + "\n\n" + task_desc, WorldBuildingOutput)


def get_characters_protocol_prompt(concept, world_building) -> str:
    """获取角色生成的协议式提示词"""
    from stages.stage1_novel.pydantic_models import CharactersOutput
    task_desc = generate_characters_prompt(concept, world_building)
    return generate_protocol_prompt(STORY_ARCHITECT_CORE + "\n\n" + task_desc, CharactersOutput)


def get_power_system_protocol_prompt(concept, world_building) -> str:
    """获取修炼体系生成的协议式提示词"""
    from stages.stage1_novel.pydantic_models import PowerSystemOutput
    task_desc = generate_power_system_prompt(concept, world_building)
    return generate_protocol_prompt(STORY_ARCHITECT_CORE + "\n\n" + task_desc, PowerSystemOutput)


def get_plot_structure_protocol_prompt(concept, world_building, characters) -> str:
    """获取情节结构生成的协议式提示词"""
    from stages.stage1_novel.pydantic_models import PlotStructureOutput
    task_desc = generate_plot_structure_prompt(concept, world_building, characters)
    return generate_protocol_prompt(STORY_ARCHITECT_CORE + "\n\n" + task_desc, PlotStructureOutput)


def get_chapter_plans_protocol_prompt(concept, world_building, characters, plot_structure, start_chapter: int, end_chapter: int) -> str:
    """获取章节规划生成的协议式提示词"""
    from stages.stage1_novel.pydantic_models import ChapterPlansOutput
    task_desc = generate_chapter_plans_prompt(concept, world_building, characters, plot_structure, start_chapter, end_chapter)
    return generate_protocol_prompt(STORY_ARCHITECT_CORE + "\n\n" + task_desc, ChapterPlansOutput)

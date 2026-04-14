import json
from typing import Dict, Any, Type, List
from pydantic import BaseModel
from config.settings import load_prompts

# 加载提示词配置
PROMPTS = load_prompts()
STAGE1_PROMPTS = PROMPTS.get("stage1", {})

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
STORY_ARCHITECT_CORE = STAGE1_PROMPTS.get("architect_core", "你是一位资深爽文小说架构师。")
NOVEL_WRITER_CORE = STAGE1_PROMPTS.get("writer_core", "你是一位顶级的网文大神。")
SCRIPT_ADAPTER_CORE = PROMPTS.get("stage2", {}).get("script_core", "你是一位专业的分镜编剧。")


# ========== 拆分蓝图生成用的 Prompt 模板 ==========

def generate_world_building_prompt(concept) -> str:
    """生成世界观提示词"""
    template = STAGE1_PROMPTS.get("world_building", "")
    if not template:
        return f"根据以下小说概念，设计一个引人入胜的世界观。\n\n小说概念: {concept.title}"
    
    return template.format(
        title=concept.title,
        genre=concept.genre,
        style=concept.style,
        core_idea=concept.core_idea
    )


def generate_characters_prompt(concept, world_building) -> str:
    """生成角色提示词"""
    template = STAGE1_PROMPTS.get("characters", "")
    if not template:
        return f"根据以下小说概念和世界观，设计核心角色。"

    return template.format(
        title=concept.title,
        genre=concept.genre,
        core_idea=concept.core_idea,
        setting=world_building.setting,
        factions=chr(10).join([f"- {f['name']}: {f['description']}" for f in world_building.factions])
    )


def generate_power_system_prompt(concept, world_building) -> str:
    """生成修炼体系提示词"""
    template = STAGE1_PROMPTS.get("power_system", "")
    if not template:
        return f"根据以下小说概念和世界观，设计修炼体系。"

    return template.format(
        title=concept.title,
        genre=concept.genre,
        core_idea=concept.core_idea,
        setting=world_building.setting
    )


def generate_plot_structure_prompt(concept, world_building, characters) -> str:
    """生成情节结构提示词"""
    template = STAGE1_PROMPTS.get("plot_structure", "")
    if not template:
        return f"根据以下小说概念、世界观和角色，设计主线剧情结构。"

    chars_info = "\n".join([f"- {c.name} ({c.role}): {c.description}" for c in characters[:5]])
    return template.format(
        title=concept.title,
        genre=concept.genre,
        total_chapters=concept.total_chapters,
        setting=world_building.setting,
        power_system=world_building.power_system,
        characters=chars_info,
        plot_count=max(5, concept.total_chapters // 5)
    )


def generate_chapter_plans_prompt(concept, world_building, characters, plot_structure, start_chapter: int, end_chapter: int) -> str:
    """生成章节规划提示词"""
    template = STAGE1_PROMPTS.get("chapter_plans", "")
    if not template:
        return f"请详细规划第 {start_chapter} 到 {end_chapter} 章的章节规划。"

    chars_info = "\n".join([f"- {c.name}: {c.goals}" for c in characters[:5]])
    plot_info = chr(10).join([f"- 第{p.chapter}章: {p.description} (爽点: {p.shuangdian_type}, 强度: {p.intensity})" for p in plot_structure[:5]])
    
    return template.format(
        start=start_chapter,
        end=end_chapter,
        title=concept.title,
        total_chapters=concept.total_chapters,
        setting=world_building.setting,
        power_system=world_building.power_system,
        characters=chars_info,
        plot_structure=plot_info
    )


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

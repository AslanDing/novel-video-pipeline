"""
Prompt Loader - YAML提示词加载器

支持热加载的提示词管理，从 YAML 文件读取提示词模板。
提示词文件位于 config/prompts_v2/ 目录。

目录结构:
config/prompts_v2/
├── llm_prompts/
│   ├── world_building.yaml
│   ├── characters.yaml
│   ├── power_system.yaml
│   ├── plot_structure.yaml
│   ├── chapter_plans.yaml
│   └── shot_list.yaml
├── image_prompts/
│   ├── character_portrait.yaml
│   ├── character_consistency.yaml
│   └── scene_generation.yaml
├── tts_prompts/
│   └── emotion_detection.yaml
└── workflows/
    └── intent_to_workflow_mapping.yaml
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
import hashlib

import sys
sys.path.append(str(Path(__file__).parent.parent))


# 全局缓存
_prompt_cache: Dict[str, Dict[str, str]] = {}
_cache_mtime: Dict[str, float] = {}


class PromptLoader:
    """
    YAML 提示词加载器

    支持：
    - 热加载：检测文件修改自动重新加载
    - 模板变量：{variable} 格式的变量替换
    - 分类管理：按类别组织提示词
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        初始化提示词加载器

        Args:
            base_dir: 提示词文件目录，默认为 config/prompts_v2/
        """
        if base_dir is None:
            # 尝试导入项目根目录
            try:
                from config.settings import PROJECT_ROOT
                base_dir = PROJECT_ROOT / "config" / "prompts_v2"
            except ImportError:
                base_dir = Path("config/prompts_v2")

        self.base_dir = Path(base_dir)
        self._ensure_directory_structure()

    def _ensure_directory_structure(self):
        """确保目录结构存在"""
        dirs = [
            self.base_dir / "llm_prompts",
            self.base_dir / "image_prompts",
            self.base_dir / "tts_prompts",
            self.base_dir / "workflows",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, category: str, name: str) -> str:
        """获取缓存键"""
        return f"{category}/{name}"

    def _get_file_path(self, category: str, name: str) -> Path:
        """获取文件路径"""
        return self.base_dir / category / f"{name}.yaml"

    def _load_yaml_file(self, file_path: Path) -> Optional[Dict]:
        """加载 YAML 文件"""
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"⚠️  加载提示词文件失败: {file_path}, error: {e}")
            return None

    def _should_reload(self, category: str, name: str) -> bool:
        """检查是否需要重新加载"""
        cache_key = self._get_cache_key(category, name)
        file_path = self._get_file_path(category, name)

        if not file_path.exists():
            return False

        current_mtime = file_path.stat().st_mtime

        # 如果缓存不存在或文件已修改，需要重新加载
        if cache_key not in _cache_mtime:
            return True

        return current_mtime > _cache_mtime[cache_key]

    def load_prompt(self, category: str, name: str, use_cache: bool = True) -> Optional[str]:
        """
        加载单个提示词

        Args:
            category: 类别 (如 "llm_prompts", "image_prompts")
            name: 提示词名称 (不含 .yaml 扩展名)
            use_cache: 是否使用缓存

        Returns:
            提示词内容，如果不存在返回 None
        """
        cache_key = self._get_cache_key(category, name)

        # 检查缓存
        if use_cache and not self._should_reload(category, name):
            if cache_key in _prompt_cache:
                return _prompt_cache[cache_key]

        # 加载文件
        file_path = self._get_file_path(category, name)
        data = self._load_yaml_file(file_path)

        if data is None:
            return None

        # 提取 prompt 字段
        prompt = data.get("prompt") or data.get("template") or data.get("content")

        if prompt:
            # 更新缓存
            _prompt_cache[cache_key] = prompt
            _cache_mtime[cache_key] = file_path.stat().st_mtime

        return prompt

    def load_prompts_by_category(self, category: str) -> Dict[str, str]:
        """
        加载某个类别的所有提示词

        Args:
            category: 类别名称

        Returns:
            {name: prompt} 字典
        """
        category_dir = self.base_dir / category
        if not category_dir.exists():
            return {}

        prompts = {}
        for yaml_file in category_dir.glob("*.yaml"):
            name = yaml_file.stem
            prompt = self.load_prompt(category, name)
            if prompt:
                prompts[name] = prompt

        return prompts

    def render_template(
        self,
        template: str,
        variables: Dict[str, Any],
    ) -> str:
        """
        渲染模板，替换变量

        Args:
            template: 模板字符串
            variables: 变量字典

        Returns:
            渲染后的字符串
        """
        result = template
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result

    def get_prompt(
        self,
        category: str,
        name: str,
        variables: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        获取提示词（支持模板渲染）

        Args:
            category: 类别
            name: 名称
            variables: 模板变量
            use_cache: 是否使用缓存

        Returns:
            渲染后的提示词
        """
        prompt = self.load_prompt(category, name, use_cache)

        if prompt and variables:
            prompt = self.render_template(prompt, variables)

        return prompt

    def reload(self, category: Optional[str] = None, name: Optional[str] = None):
        """
        重新加载提示词

        Args:
            category: 类别，为 None 则重新加载所有
            name: 名称，为 None 则重新加载所有
        """
        if category and name:
            # 重新加载单个
            cache_key = self._get_cache_key(category, name)
            _prompt_cache.pop(cache_key, None)
            _cache_mtime.pop(cache_key, None)
            self.load_prompt(category, name, use_cache=False)
        else:
            # 重新加载所有
            global _prompt_cache, _cache_mtime
            _prompt_cache = {}
            _cache_mtime = {}
            for cat in ["llm_prompts", "image_prompts", "tts_prompts", "workflows"]:
                self.load_prompts_by_category(cat)


# ─── 便捷函数 ────────────────────────────────────────────────────────────────

_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """获取全局提示词加载器（单例）"""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader


def load_prompt(
    category: str,
    name: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    便捷函数：加载提示词

    用法:
        prompt = load_prompt("llm_prompts", "world_building", {"genre": "修仙"})
    """
    loader = get_prompt_loader()
    return loader.get_prompt(category, name, variables)


def reload_prompts():
    """便捷函数：重新加载所有提示词"""
    loader = get_prompt_loader()
    loader.reload()


# ─── 默认提示词模板 ──────────────────────────────────────────────────────────

DEFAULT_PROMPTS = {
    "llm_prompts/world_building": {
        "prompt": """请为以下小说类型设计一个完整的世界观设定。

小说类型: {genre}
核心创意: {core_idea}

请输出以下JSON格式:
{{
    "setting": "世界描述，涵盖历史、地理和当前局势",
    "factions": [
        {{"name": "势力名称", "description": "势力描述", "type": "正/邪/中"}}
    ],
    "rules": ["世界运行的核心规则或禁忌"]
}}""",
    },
    "llm_prompts/characters": {
        "prompt": """请为以下小说生成{n}个核心角色。

小说类型: {genre}
世界设定: {world_building}

请输出以下JSON格式:
{{
    "characters": [
        {{
            "id": "char_001",
            "name": "角色姓名",
            "role": "protagonist/antagonist/supporting",
            "description": "核心特质、性格和简短生平",
            "personality": "详细性格描写",
            "goals": "角色的长期和短期目标",
            "background": "背景故事",
            "appearance": "外貌细节描述，用于AI绘画",
            "age": "young/middle/old",
            "gender": "male/female"
        }}
    ]
}}""",
    },
    "llm_prompts/shot_list": {
        "prompt": """请分析以下章节内容，生成分镜列表。

章节标题: {chapter_title}
章节内容:
{chapter_content}

角色列表:
{characters}

请将内容拆分为多个镜头，每个镜头包含:
- role: "dialogue" 或 "narrator"
- speaker: 说话人名称
- text: 需要朗读的文本
- emotion: 情感标签 (neutral, happy, sad, angry, fearful, excited, calm)
- visual_prompt: 英文画面描述
- motion_prompt: 镜头运动描述
- camera: 景别描述
- estimated_duration: 预估时长（秒）

输出JSON格式:
{{"shots": [...]}}""",
    },
}


def create_default_prompt_files():
    """创建默认提示词文件（如果不存在）"""
    loader = get_prompt_loader()

    for full_name, data in DEFAULT_PROMPTS.items():
        parts = full_name.split("/")
        category = parts[0]
        name = parts[1]

        file_path = loader._get_file_path(category, name)
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            print(f"✅ 创建默认提示词: {file_path}")

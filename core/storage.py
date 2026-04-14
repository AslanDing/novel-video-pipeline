"""
Storage Management for Asset-First Workflow

处理项目目录结构的创建和管理。
遵循三层配置模型的目录规范。

目录结构:
outputs/{project_id}/
├── project_preset.json              # Layer 1: Project Preset
├── data/
│   ├── story_bible.json            # 故事蓝图
│   ├── chapters/
│   │   ├── chapter_001.md
│   │   └── chapter_001_summary.json
│   ├── scripts/
│   │   └── script_001.jsonl
│   └── chapter_manifests/
│       └── ch01_manifest.json
├── assets/
│   ├── characters/
│   │   └── {char_name}/
│   │       ├── portrait.png
│   │       ├── face_ref.png
│   │       └── expressions/
│   └── scenes/
│       └── {scene_name}/
│           ├── wide.png
│           ├── medium.png
│           └── mood_ref.png
├── images/chapter_001/
├── videos/chapter_001/
├── audio/chapter_001/
└── final/
    └── chapter_001.mp4
"""

from pathlib import Path
from typing import Optional, Dict, List
import json


class ProjectStorage:
    """项目存储管理器"""

    def __init__(self, project_id: str, base_dir: Optional[Path] = None):
        """
        初始化项目存储管理器

        Args:
            project_id: 项目ID
            base_dir: 基础目录，默认为 outputs/
        """
        if base_dir is None:
            # 尝试导入配置
            try:
                from config.settings import OUTPUTS_DIR
                base_dir = OUTPUTS_DIR
            except ImportError:
                base_dir = Path("outputs")

        self.base_dir = Path(base_dir)
        self.project_id = project_id
        self.project_dir = self.base_dir / project_id

    def get_project_dir(self) -> Path:
        """获取项目根目录"""
        return self.project_dir

    def get_data_dir(self) -> Path:
        """获取数据目录"""
        return self.project_dir / "data"

    def get_chapters_dir(self) -> Path:
        """获取章节目录"""
        return self.get_data_dir() / "chapters"

    def get_scripts_dir(self) -> Path:
        """获取脚本目录"""
        return self.get_data_dir() / "scripts"

    def get_chapter_manifests_dir(self) -> Path:
        """获取章节清单目录"""
        return self.get_data_dir() / "chapter_manifests"

    def get_assets_dir(self) -> Path:
        """获取资产目录"""
        return self.project_dir / "assets"

    def get_characters_dir(self) -> Path:
        """获取角色资产目录"""
        return self.get_assets_dir() / "characters"

    def get_scenes_dir(self) -> Path:
        """获取场景资产目录"""
        return self.get_assets_dir() / "scenes"

    def get_character_dir(self, character_name: str) -> Path:
        """获取单个角色目录"""
        # 角色名做 sanitize
        safe_name = self._sanitize_name(character_name)
        return self.get_characters_dir() / safe_name

    def get_scene_dir(self, scene_name: str) -> Path:
        """获取单个场景目录"""
        safe_name = self._sanitize_name(scene_name)
        return self.get_scenes_dir() / safe_name

    def get_images_dir(self, chapter_number: Optional[int] = None) -> Path:
        """获取图像目录"""
        if chapter_number is not None:
            return self.project_dir / "images" / f"chapter_{chapter_number:03d}"
        return self.project_dir / "images"

    def get_videos_dir(self, chapter_number: Optional[int] = None) -> Path:
        """获取视频目录"""
        if chapter_number is not None:
            return self.project_dir / "videos" / f"chapter_{chapter_number:03d}"
        return self.project_dir / "videos"

    def get_audio_dir(self, chapter_number: Optional[int] = None) -> Path:
        """获取音频目录"""
        if chapter_number is not None:
            return self.project_dir / "audio" / f"chapter_{chapter_number:03d}"
        return self.project_dir / "audio"

    def get_final_dir(self) -> Path:
        """获取最终输出目录"""
        return self.project_dir / "final"

    def ensure_directories(self):
        """确保所有必要目录存在"""
        dirs = [
            self.project_dir,
            self.get_data_dir(),
            self.get_chapters_dir(),
            self.get_scripts_dir(),
            self.get_chapter_manifests_dir(),
            self.get_assets_dir(),
            self.get_characters_dir(),
            self.get_scenes_dir(),
            self.get_images_dir(),
            self.get_videos_dir(),
            self.get_audio_dir(),
            self.get_final_dir(),
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return self

    def _sanitize_name(self, name: str) -> str:
        """清理名称，移除非法字符"""
        import re
        # 只保留字母、数字、中文、下划线
        return re.sub(r'[^\w\u4e00-\u9fff]', '_', name)

    # ========== 文件路径便捷方法 ==========

    def get_chapter_path(self, chapter_number: int) -> Path:
        """获取章节 Markdown 文件路径"""
        return self.get_chapters_dir() / f"chapter_{chapter_number:03d}.md"

    def get_chapter_summary_path(self, chapter_number: int) -> Path:
        """获取章节摘要 JSON 路径"""
        return self.get_chapters_dir() / f"chapter_{chapter_number:03d}_summary.json"

    def get_script_path(self, chapter_number: int) -> Path:
        """获取脚本 JSONL 路径"""
        return self.get_scripts_dir() / f"script_{chapter_number:03d}.jsonl"

    def get_chapter_manifest_path(self, chapter_id: str) -> Path:
        """获取章节清单路径"""
        return self.get_chapter_manifests_dir() / f"{chapter_id}_manifest.json"

    def get_project_preset_path(self) -> Path:
        """获取项目预设文件路径"""
        return self.project_dir / "project_preset.json"

    def get_story_bible_path(self) -> Path:
        """获取故事圣经路径"""
        return self.get_data_dir() / "story_bible.json"

    # ========== 资产文件便捷方法 ==========

    def get_character_portrait_path(self, character_name: str) -> Path:
        """获取角色定妆照路径"""
        char_dir = self.get_character_dir(character_name)
        return char_dir / "portrait.png"

    def get_character_face_ref_path(self, character_name: str) -> Path:
        """获取角色脸部参考路径"""
        char_dir = self.get_character_dir(character_name)
        return char_dir / "face_ref.png"

    def get_character_expressions_dir(self, character_name: str) -> Path:
        """获取角色表情目录"""
        char_dir = self.get_character_dir(character_name)
        return char_dir / "expressions"

    def get_scene_wide_path(self, scene_name: str) -> Path:
        """获取场景宽视图路径"""
        scene_dir = self.get_scene_dir(scene_name)
        return scene_dir / "wide.png"

    def get_scene_medium_path(self, scene_name: str) -> Path:
        """获取场景中视图路径"""
        scene_dir = self.get_scene_dir(scene_name)
        return scene_dir / "medium.png"

    def get_scene_mood_ref_path(self, scene_name: str) -> Path:
        """获取场景氛围参考路径"""
        scene_dir = self.get_scene_dir(scene_name)
        return scene_dir / "mood_ref.png"

    def get_final_video_path(self, chapter_number: int) -> Path:
        """获取最终视频路径"""
        return self.get_final_dir() / f"chapter_{chapter_number:03d}.mp4"

    # ========== 读取/保存方法 ==========

    def load_chapter_summary(self, chapter_number: int) -> Dict:
        """加载章节摘要"""
        path = self.get_chapter_summary_path(chapter_number)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def load_chapter_content(self, chapter_number: int) -> str:
        """加载章节内容"""
        path = self.get_chapter_path(chapter_number)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def load_script_lines(self, chapter_number: int) -> List[Dict]:
        """加载脚本行"""
        path = self.get_script_path(chapter_number)
        if not path.exists():
            return []

        lines = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        return lines

    def save_script_lines(self, chapter_number: int, script_lines: List[Dict]):
        """保存脚本行到 JSONL"""
        path = self.get_script_path(chapter_number)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            for line in script_lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def exists(self) -> bool:
        """检查项目目录是否存在"""
        return self.project_dir.exists() and self.project_dir.is_dir()

    def list_chapters(self) -> List[int]:
        """列出所有章节号"""
        if not self.get_chapters_dir().exists():
            return []

        chapters = []
        for f in self.get_chapters_dir().glob("chapter_*.md"):
            try:
                num = int(f.stem.split("_")[1])
                chapters.append(num)
            except (IndexError, ValueError):
                pass
        return sorted(chapters)

    def list_characters(self) -> List[str]:
        """列出所有角色"""
        if not self.get_characters_dir().exists():
            return []

        characters = []
        for d in self.get_characters_dir().iterdir():
            if d.is_dir():
                characters.append(d.name)
        return sorted(characters)

    def list_scenes(self) -> List[str]:
        """列出所有场景"""
        if not self.get_scenes_dir().exists():
            return []

        scenes = []
        for d in self.get_scenes_dir().iterdir():
            if d.is_dir():
                scenes.append(d.name)
        return sorted(scenes)


def get_project_storage(project_id: str, base_dir: Optional[Path] = None) -> ProjectStorage:
    """获取项目存储管理器（便捷函数）"""
    return ProjectStorage(project_id, base_dir)


def create_project_storage(project_id: str, title: str, genre: str, base_dir: Optional[Path] = None) -> ProjectStorage:
    """创建新项目存储（便捷函数）"""
    storage = ProjectStorage(project_id, base_dir)
    storage.ensure_directories()
    return storage

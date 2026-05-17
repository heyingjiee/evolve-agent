import re
from pathlib import Path
from typing import TypedDict, cast

from evolve.config import global_config

#### 目录结构 ####
# memory/
#   ├── MEMORY.md          # 索引
#   ├── prefer_tabs.md     # 用户偏好
#   ├── feedback_tests.md  # 用户反馈问题（做什么对/不对）
#   └── ....md             # 更多记忆文件


#### MEMORY.md 是索引文件 ####
"""
# Memory Index
  - prefer_tabs: User prefers tabs for indentation [user]
  - avoid_mock_heavy_tests: User dislikes mock-heavy tests [feedback]
"""

#### 记忆文件采用frontmatter格式 ####
# name 记忆名字
# description 描述记忆是干啥的
# type = user用户偏好 、 feedback用户纠正过的问题 、project 项目约定/规则 、reference 外部资源（文档、监控面板、bug追踪面板）
# content 正文
"""
---
name: prefer_tabs
description: User prefers tabs for indentation
type: user
---
The user explicitly prefers tabs over spaces when editing source files.
"""

MEMORY_DIR = global_config.WORKDIR / ".evolve/memory"


class Memory(TypedDict):
    type: str
    name: str
    description: str
    content: str


# 记忆类型，也就是文件的type字段
MEMORY_TYPES = ("user", "feedback", "project", "reference")


class MemoryManager:
    def __init__(self, memory_dir: Path | None = None):
        # memory 文件所在目录
        self.memory_dir = memory_dir or MEMORY_DIR
        # 存储配置文件， 格式
        self.memories: dict[str, Memory] = {}

    def load_all(self):
        """除去MEMORY.md 索引文件的其他记忆文件，读入 self.memories"""
        self.memories = {}
        if not self.memory_dir.exists():
            return

        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(path.read_text())
            if parsed:
                name = parsed["name"]
                self.memories[name] = parsed

        print(f"[Memory loaded: {len(self.memories)} memories from ${self.memory_dir}]")

    def load_memory_prompt(self) -> str:
        """
        把 self.memories 中的记忆生成 prompt 的一部分，作为系统提示词注入到LLM
        self.memories 格式：
            {
                name1: {name, description, type, content}
                name2: {name, description, type, content}
            }

        生成 prompt格式
          # Memories (persistent across sessions)
          ## [类型]
          ### name1: 描述1
          正文1
          ### name2: 描述2
          正文2

          ## [其他类型]
          ...
        """

        # 处理成这个 type -> [{ "name", "type", "description", "content" }]
        mem_map: dict[str, list] = {}
        for name, mem in self.memories.items():
            mem_type = mem["type"]
            if mem_type not in mem_map:
                mem_map[mem_type] = []
            mem_map[mem_type].append(mem)

        sections = ["# Memories (persistent across sessions)"]
        if mem_map.keys():
            for mem_type in mem_map.keys():
                sections.append(f"## [{mem_type}]")
                for mem in mem_map.get(mem_type, []):
                    sections.append(f"### {mem['name']}: {mem['description']}")
                    sections.append(f"{mem['content']}")
        else:
            sections.append("(no memories)")

        return "\n".join(sections)

    def save_memory(self, memory: Memory) -> str:
        """
        1、保存到 memory 文件
        2、更新内存中的 memory 数据
        """
        # 判断传入数据是否符合规范
        name = memory.get("name")
        mem_type = memory.get("type")
        description = memory.get("description")
        content = memory.get("content", "")  # 可以为空

        pattern = r"^[a-z0-9]+_[a-z0-9]+$"
        if not name or not re.fullmatch(pattern, name):
            return "Error: invalid memory name, name must be like `xxx_yyy` "

        if not mem_type or mem_type not in MEMORY_TYPES:
            return f"Error: invalid type, type must be one of {MEMORY_TYPES}"

        if not description:
            return "Error: invalid memory description"

        # 写入文件
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mem_type}\n"
            f"---\n"
            f"{memory['content']}\n"
        )
        file_path = self.memory_dir / f"{name}.md"
        file_path.write_text(frontmatter)

        # 更新内存数据
        self.memories[name] = {
            "name": name,
            "description": description,
            "content": content,
            "type": mem_type,
        }

        # 更新索引文件
        self._rebuild_index()

        return f"Saved memory '{name}' [{mem_type}] to {file_path}"

    def _rebuild_index(self):
        """
        更新索引文件， 格式：
            - name1: description [type]
            - name2: description [type]
        """
        sections = ["# Memory Index"]
        for mem in self.memories.values():
            sections.append(f"{mem['name']}: {mem['description']} [{mem['type']}]")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        memory_index_path = self.memory_dir / "MEMORY.md"
        memory_index_path.write_text("\n".join(sections) + "\n")

    def _parse_frontmatter(self, text: str) -> Memory | None:
        """从记忆文件中提取 frontmatter 格式"""
        match = re.match(r"---\n(.*)\n---(.*)", text, re.DOTALL)
        if not match:
            return None
        # 头部
        header = match.group(1)
        # 正文
        content = match.group(2).strip()
        # 拼接结果
        mem_map = {}
        for line in header.splitlines():
            key, value = line.split(":", 1)
            mem_map[key.strip()] = value.strip()

        result = {}
        for mem_type in ("type", "name", "description", "content"):
            # 防止读入其他无效字段
            result[mem_type] = mem_map.get(mem_type, "")
        result["content"] = content

        return cast(Memory, cast(object, result))  # 类型转换成 Memory


memory_schema = {
    "name": "save_memory",
    "description": "Save a persistent memory that survives across sessions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short identifier (e.g. prefer_tabs, db_schema)",
            },
            "description": {
                "type": "string",
                "description": "One-line summary of what this memory captures",
            },
            "type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": "user=preferences, feedback=corrections, project=non-obvious project conventions or decision reasons, reference=external resource pointers",
            },
            "content": {
                "type": "string",
                "description": "Full memory content (multi-line OK)",
            },
        },
        "required": ["name", "description", "type", "content"],
    },
}



# 单例
memory_mgr = MemoryManager()

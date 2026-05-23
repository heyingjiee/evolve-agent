import re
from pathlib import Path
from typing import TypedDict, cast


class Memory(TypedDict):
    type: str
    name: str
    description: str
    content: str


MEMORY_TYPES = ("user", "feedback", "project", "reference")


class MemoryManager:
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memories: dict[str, Memory] = {}

    @classmethod
    def from_workspace(cls, workspace: Path) -> "MemoryManager":
        return cls(workspace / ".evolve" / "memory")

    def load_all(self) -> None:
        self.memories = {}
        if not self.memory_dir.exists():
            return

        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(path.read_text())
            if parsed:
                self.memories[parsed["name"]] = parsed

        print(f"[Memory loaded: {len(self.memories)} memories from ${self.memory_dir}]")

    def load_memory_prompt(self) -> str:
        mem_map: dict[str, list[Memory]] = {}
        for mem in self.memories.values():
            mem_map.setdefault(mem["type"], []).append(mem)

        sections = ["# Memories (persistent across sessions)"]
        if mem_map:
            for mem_type, items in mem_map.items():
                sections.append(f"## [{mem_type}]")
                for mem in items:
                    sections.append(f"### {mem['name']}: {mem['description']}")
                    sections.append(mem["content"])
        else:
            sections.append("(no memories)")

        return "\n".join(sections)

    def save_memory(self, memory: Memory) -> str:
        name = memory.get("name")
        mem_type = memory.get("type")
        description = memory.get("description")
        content = memory.get("content", "")

        pattern = r"^[a-z0-9]+_[a-z0-9]+$"
        if not name or not re.fullmatch(pattern, name):
            return "Error: invalid memory name, name must be like `xxx_yyy` "
        if not mem_type or mem_type not in MEMORY_TYPES:
            return f"Error: invalid type, type must be one of {MEMORY_TYPES}"
        if not description:
            return "Error: invalid memory description"

        self.memory_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mem_type}\n"
            f"---\n"
            f"{content}\n"
        )
        file_path = self.memory_dir / f"{name}.md"
        file_path.write_text(frontmatter)

        self.memories[name] = {
            "name": name,
            "description": description,
            "content": content,
            "type": mem_type,
        }
        self._rebuild_index()
        return f"Saved memory '{name}' [{mem_type}] to {file_path}"

    def _rebuild_index(self) -> None:
        sections = ["# Memory Index"]
        for mem in self.memories.values():
            sections.append(f"{mem['name']}: {mem['description']} [{mem['type']}]")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.memory_dir / "MEMORY.md").write_text("\n".join(sections) + "\n")

    def _parse_frontmatter(self, text: str) -> Memory | None:
        match = re.match(r"---\n(.*)\n---(.*)", text, re.DOTALL)
        if not match:
            return None
        header = match.group(1)
        content = match.group(2).strip()
        mem_map: dict[str, str] = {}
        for line in header.splitlines():
            key, value = line.split(":", 1)
            mem_map[key.strip()] = value.strip()

        result = {}
        for key in ("type", "name", "description", "content"):
            result[key] = mem_map.get(key, "")
        result["content"] = content
        return cast(Memory, cast(object, result))


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


memory_mgr = MemoryManager.from_workspace(Path.cwd().resolve())

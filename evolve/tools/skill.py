import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillManifest:
    name: str
    description: str
    path: Path


@dataclass
class SkillDocument:
    manifest: SkillManifest
    body: str


class SkillRegistry:
    def __init__(self, skill_path: Path):
        self.skill_path = skill_path
        self.documents: dict[str, SkillDocument] = {}
        self.load_all()

    @classmethod
    def from_workspace(cls, workspace: Path) -> "SkillRegistry":
        return cls(workspace / "src" / "skills")

    def load_all(self) -> None:
        self.documents = {}
        if not self.skill_path.exists():
            return
        for path in sorted(self.skill_path.rglob("SKILL.md")):
            meta, body = self._parse_frontmatter(path.read_text())
            name = meta.get("name", path.parent.name)
            description = meta.get("description", "No description")
            manifest = SkillManifest(name, description, path)
            self.documents[name] = SkillDocument(manifest, body)
        print(f"\n[available skills: {','.join(self.documents.keys())}]")

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, match.group(2)

    def describe_available(self) -> str:
        if not self.documents:
            return "(no skills available)"
        lines = []
        for name in sorted(self.documents):
            manifest = self.documents[name].manifest
            lines.append(f"- {manifest.name}:{manifest.description}")
        return "\n".join(lines)

    def load_full_text(self, name: str) -> str:
        if name not in self.documents:
            known = ",".join(sorted(self.documents)) or "(none)"
            return f"Error: Unknown skill '{name}'. Available skill {known}"
        document = self.documents[name]
        return (
            f"<skill name=\"{document.manifest.name}\">\n"
            f"{document.body}\n"
            "</skill>"
        )


SKILL_REGISTRY = SkillRegistry.from_workspace(Path.cwd().resolve())

skill_schema = {
    "name": "load_skill",
    "description": "Load the full body of a named skill into the current context.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}

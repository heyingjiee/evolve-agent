import datetime
import sys
from pathlib import Path

from evolve.tools.memory import MemoryManager
from evolve.tools.skill import SkillRegistry


MEMORY_GUIDANCE = """
When to save memories:
- User states a preference ("I like tabs", "always use pytest") -> type: user
- User corrects you ("don't do X", "that was wrong because...") -> type: feedback
- You learn a project fact that is not easy to infer from current code alone
  (for example: a rule exists because of compliance, or a legacy module must
  stay untouched for business reasons) -> type: project
- You learn where an external resource lives (ticket board, dashboard, docs URL)
  -> type: reference
When NOT to save:
- Anything easily derivable from code (function signatures, file structure, directory layout)
- Temporary task state (current branch, open PR numbers, current TODOs)
- Secrets or credentials (API keys, passwords)
"""


class SystemPromptBuilder:
    def __init__(
        self,
        workdir: Path,
        tools_list: list | None = None,
        *,
        skill_registry: SkillRegistry | None = None,
        memory_manager: MemoryManager | None = None,
        model: str | None = None,
    ):
        self.workdir = workdir
        self.tools = tools_list or []
        self.skill_registry = skill_registry
        self.memory_manager = memory_manager
        self.model = model or ""

    def build(self) -> str:
        sections = []
        for part in (
            self._build_core(),
            self._build_tool_listing(),
            self._build_skill_listing(),
            self._build_memory_section(),
            self._build_agent_md(),
        ):
            if part:
                sections.append(part)
        sections.append("=== DYNAMIC_BOUNDARY ===")
        dynamic = self._build_dynamic_context()
        if dynamic:
            sections.append(dynamic)
        return "\n\n".join(sections)

    def _build_core(self) -> str:
        return (
            f"You are a coding agent operating in {self.workdir}. \n"
            "Use the provide tools to explore, read, write, and edit files.\n"
            "Always verify before assuming. Prefer reading files over guessing."
        )

    def _build_tool_listing(self) -> str:
        if not self.tools:
            return ""
        lines = ["# Available tools"]
        for tool in self.tools:
            props = tool.get("input_schema", {}).get("properties", {})
            params = ", ".join(props.keys())
            lines.append(f"- {tool['name']}({params}): {tool['description']}")
        return "\n".join(lines)

    def _build_skill_listing(self) -> str:
        if self.skill_registry is None:
            return ""
        skills = self.skill_registry.describe_available()
        if not skills or skills == "(no skills available)":
            return ""
        return "# Available skills\n" + skills

    def _build_memory_section(self) -> str:
        if self.memory_manager is None:
            return ""
        return f"{self.memory_manager.load_memory_prompt()}\n{MEMORY_GUIDANCE}"

    def _build_agent_md(self) -> str:
        root_agent_md_path = self.workdir / "AGENT.md"
        if not root_agent_md_path.exists():
            return ""
        lines = root_agent_md_path.read_text().splitlines()
        quoted = "\n".join(f">  {line}" for line in lines)
        return (
            "# AGENT.md instructions\n"
            "## From project root (AGENT.md)\n"
            f"{quoted}"
        )

    def _build_dynamic_context(self) -> str:
        return (
            "# Dynamic context\n"
            f"Current date: {datetime.date.today().isoformat()}\n"
            f"Working directory: {self.workdir}\n"
            f"Model: {self.model}\n"
            f"Platform: {sys.platform}"
        )

import datetime
import os
import sys
from pathlib import Path

from evolve import tools
from evolve.tools.memory import memory_mgr


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
    def __init__(self, workdir: Path, tools_list: list = None):
        self.workdir = workdir
        self.tools = tools_list or []
        self.skills_dir = self.workdir / ".evolve" / "skills"
        self.memory_dir = self.workdir / ".evolve" / ".memory"

    def build(self):
        """
            组装System Prompt
        """
        sections = []
        core = self._build_core()
        if core:
            sections.append(core)
        tools_text = self._build_tool_listing()
        if tools_text:
            sections.append(tools_text)
        skills = self._build_skill_listing()
        if skills:
            sections.append(skills)
        memory = self._build_memory_section()
        if memory:
            sections.append(memory)
        agent_md = self._build_agent_md()
        if agent_md:
            sections.append(agent_md)
        # 分界标识，上面是静态部分，下面是动态部分
        # 大模型支持"提示词缓存"机制，静态部分会被缓存起来每次调用共享，节省成本提高响应速度
        sections.append("=== DYNAMIC_BOUNDARY ===")
        dynamic = self._build_dynamic_context()
        if dynamic:
            sections.append(dynamic)
        return "\n\n".join(sections)

    def _build_core(self):
        """固定prompt文案"""
        return (
            f"You are a coding agent operating in {self.workdir}. \n"
            "Use the provide tools to explore, read, write, and edit files.\n"
            "Always verify before assuming. Prefer reading files over guessing."
        )

    def _build_tool_listing(self):
        """
            工具提示词，格式：
            # Available tools
            - 工具名1(参数): 描述
            - 工具名2(参数): 描述
        """
        if not self.tools:
            return ""
        lines = ["# Available tools"]
        for tool in self.tools:
            props = tool.get("input_schema", {}).get("properties", {})
            params = ", ".join(props.keys())
            lines.append(f"- {tool["name"]}({params}): {tool["description"]}")
        return "\n".join(lines)

    def _build_skill_listing(self):
        """
            Skill提示词，格式：
            # Available skills
            - 名字: 描述
            - 名字: 描述
        """
        skills = tools.SKILL_REGISTRY.describe_available()
        if not skills:
            return ""
        else:
            return (
                "# Available skills\n"
                f"{tools.SKILL_REGISTRY.describe_available()}"
            )

    def _build_memory_section(self):
        """
            Memory提示词，格式： 参考load_memory_prompt注释
        """
        # TODO: 记忆会膨胀，需要定期处理。09提到的 DreamConsolidator
        # TODO: subAgent 支持读memory，不能写
        memory_section = memory_mgr.load_memory_prompt()
        return (
            f"{memory_section}\n"
            f"{MEMORY_GUIDANCE}"
        )

    def _build_agent_md(self):
        """ 读取根目录下 AGENT.md 构建提示词
            格式：
                # AGENT.md instructions
                ## From project root (AGENT.md)
                xxxx文件正文
                ## From subdir (xx/xx/AGENT.md)
                xxxx文件正文
            注意： 分成两集级，项目根目录的AGENT.md 和 子目录的AGENT.md
        """
        # TODO  递归读取子目录的AGENT.md逻辑待考虑
        root_agent_md_path = self.workdir / "AGENT.md"
        if root_agent_md_path.exists():
            lines = root_agent_md_path.read_text().splitlines()
            return (
                "# AGENT.md instructions\n"
                "## From project root (AGENT.md)\n"
                
                f"{"\n".join(f">  {line}" for line in lines)}"
            )
        return ""

    def _build_dynamic_context(self):
        """ 动态信息 """
        MODEL = os.environ["MODEL_ID"]
        return (
            "# Dynamic context\n"
            f"Current date: {datetime.date.today().isoformat()}"
            f"Working directory: {self.workdir}\n"
            f"Model: {MODEL}\n"
            f"Platform: {sys.platform}"
        )



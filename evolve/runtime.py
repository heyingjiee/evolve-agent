import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evolve import tools
from evolve.agents.task import run_task_subagent, task_schema
from evolve.config import Config
from evolve.hooks import Context, HookManager
from evolve.permission.manager import PermissionManager
from evolve.prompt import SystemPromptBuilder
from evolve.tools.background import BackgroundManager
from evolve.tools.memory import MemoryManager
from evolve.tools.skill import SkillRegistry


TOOLS = [
    tools.bash_schema,
    tools.read_schema,
    tools.write_schema,
    tools.edit_schema,
    tools.plan_schema,
    tools.skill_schema,
    task_schema,
    tools.compact_schema,
    tools.memory_schema,
    tools.run_background_schema,
    tools.check_background_schema,
]


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.runtime_dir = self.root / ".evolve"
        self.session_dir = self.runtime_dir / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)


class Evolve:
    def __init__(self, config: Config, history: list[dict[str, Any]] | None = None):
        self.config = config
        self.workspace = Workspace(config.workspace)
        self.client = config.build_client()
        self.history = history or []
        self.compact_state = tools.CompactState()
        self.permissions = PermissionManager(mode="default")
        self.memory_manager = MemoryManager.from_workspace(self.workspace.root)
        self.memory_manager.load_all()
        self.background_manager = BackgroundManager.from_workspace(self.workspace.root)
        self.skill_registry = SkillRegistry.from_workspace(self.workspace.root)
        self.hooks = HookManager(self.workspace.root)
        self.plan_manager = tools.PlanManager(reminder_interval=3)
        self.prompt_builder = SystemPromptBuilder(
            self.workspace.root,
            TOOLS,
            skill_registry=self.skill_registry,
            memory_manager=self.memory_manager,
            model=self.config.model,
        )
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_path = self.workspace.session_dir / f"{self.session_id}.json"

    @classmethod
    def from_session(cls, config: Config, session_id: str | None = None) -> "Evolve":
        workspace = Workspace(config.workspace)
        resolved_session_id = session_id or "latest"
        session_path = cls._resolve_session_path(workspace, resolved_session_id)
        if session_path is None or not session_path.exists():
            raise ValueError(f"Session not found: {resolved_session_id}")
        payload = json.loads(session_path.read_text())
        agent = cls(config=config, history=payload.get("history", []))
        agent.session_id = payload.get("session_id", session_path.stem)
        agent.session_path = session_path
        return agent

    def ask(self, user_input: str, config: Config | None = None) -> str:
        if config is not None:
            self.config = config
            self.client = config.build_client()

        self.history.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": user_input}],
            }
        )
        self._agent_loop()
        final_text = self._extract_last_text()
        self._save_session()
        if final_text:
            print(f"{'-' * 50}\n{final_text}\n{'-' * 50}")
        return final_text

    def reset(self) -> None:
        self.history = []
        self.compact_state = tools.CompactState()
        self.plan_manager = tools.PlanManager(reminder_interval=3)
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_path = self.workspace.session_dir / f"{self.session_id}.json"

    def memory_text(self) -> str:
        return self.memory_manager.load_memory_prompt()

    def prompt_text(self) -> str:
        return self.prompt_builder.build()

    @staticmethod
    def _resolve_session_path(workspace: Workspace, session_id: str) -> Path | None:
        if session_id == "latest":
            candidates = sorted(workspace.session_dir.glob("*.json"))
            return candidates[-1] if candidates else None
        path = workspace.session_dir / f"{session_id}.json"
        return path

    def _save_session(self) -> None:
        payload = {
            "session_id": self.session_id,
            "workspace": str(self.workspace.root),
            "history": self.history,
        }
        self.session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def _execute_tool(self, block: dict[str, Any]) -> str:
        tool_name = block.get("name")
        argv = block.get("input") or {}
        tool_use_id = block.get("id", "")
        if tool_name == "bash":
            return tools.run_bash(argv["command"], tool_use_id, self.workspace.root)
        if tool_name == "read_file":
            return tools.run_read(argv["path"], tool_use_id, self.compact_state, self.workspace.root, argv.get("limit"))
        if tool_name == "write_file":
            return tools.run_write(argv["path"], argv["content"], self.workspace.root)
        if tool_name == "edit_file":
            return tools.run_edit(argv["path"], argv["old_text"], argv["new_text"], self.workspace.root)
        if tool_name == "plan":
            return self.plan_manager.update(argv["items"])
        if tool_name == "task":
            return run_task_subagent(
                argv.get("prompt", ""),
                workspace=self.workspace.root,
                client=self.client,
                model=self.config.model,
                skill_registry=self.skill_registry,
            )
        if tool_name == "load_skill":
            return self.skill_registry.load_full_text(argv["name"])
        if tool_name == "compact":
            return "Compacting conversation..."
        if tool_name == "save_memory":
            return self.memory_manager.save_memory(argv)
        if tool_name == "run_background":
            return self.background_manager.run(argv["command"])
        if tool_name == "check_background":
            return self.background_manager.check(argv.get("task_id"))
        return f"Unknown tool: {tool_name}"

    def _normalize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return []

        has_tool_result_ids = set()
        for msg in messages:
            if msg["role"] != "user":
                continue
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    has_tool_result_ids.add(block["tool_use_id"])

        normalized = list(messages)
        for msg in list(messages):
            if msg["role"] != "assistant":
                continue
            for block in msg["content"]:
                if block["type"] == "tool_use" and block["id"] not in has_tool_result_ids:
                    normalized.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block["id"],
                                    "content": "(cancelled)",
                                }
                            ],
                        }
                    )

        merged = [normalized[0]]
        for msg in normalized[1:]:
            if msg["role"] == merged[-1]["role"]:
                merged[-1]["content"] = merged[-1]["content"] + msg["content"]
            else:
                merged.append(msg)
        return merged

    def _extract_last_text(self) -> str:
        for msg in reversed(self.history):
            if msg["role"] != "assistant":
                continue
            return "".join(
                block.get("text", "")
                for block in msg["content"]
                if block.get("type") == "text"
            )
        return ""

    def _agent_loop(self) -> None:
        while True:
            notifs = self.background_manager.clear_notifications()
            if notifs and self.history:
                notif_text = "\n".join(
                    f"[bg:{item['task_id']}] {item['status']}: {item['result_preview']} "
                    f"(output_file={item['output_file']})"
                    for item in notifs
                )
                self.history.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"<background-results>\n{notif_text}\n</background-results>",
                            }
                        ],
                    }
                )

            self.history = self._normalize_messages(self.history)
            self.history = tools.micro_compact(self.history)
            system = self.prompt_builder.build()

            response = self.client.messages.create(
                model=self.config.model,
                system=system,
                messages=self.history,
                tools=TOOLS,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            contents = [block.to_dict() for block in response.content]
            self.history.append({"role": "assistant", "content": contents})

            if response.stop_reason != "tool_use":
                return

            tool_contents: list[dict[str, Any]] = []
            used_plan = False
            manual_compact = False
            compact_focus = None

            for block in contents:
                if block.get("type") != "tool_use":
                    continue

                tool_name = block["name"]
                tool_input = block.get("input") or {}
                ctx: Context = {"tool_name": tool_name, "tool_input": tool_input}

                decision = self.permissions.check(tool_name, tool_input)
                if decision["behavior"] == "deny":
                    output = f"Permission denied: {decision['reason']}"
                elif decision["behavior"] == "ask" and not self.permissions.ask_user(tool_name, tool_input):
                    output = f"Permission denied by user for: {tool_name}"
                else:
                    pre_hook = self.hooks.run_hook("PreToolUse", ctx)
                    if pre_hook.get("blocked"):
                        reason = pre_hook.get("block_reason", "Blocked by hook")
                        output = f"Tool blocked by PreToolUse hook: {reason}"
                    else:
                        if ctx.get("tool_input") is not None:
                            block["input"] = ctx["tool_input"]
                        output = self._execute_tool(block)
                        ctx["tool_output"] = output
                        post_hook = self.hooks.run_hook("PostToolUse", ctx)
                        notes = [f"[Hook note]: {msg}" for msg in post_hook.get("messages", [])]
                        if notes:
                            output = "\n".join([output, *notes])

                tool_contents.append(
                    {
                        "type": "tool_result",
                        "content": output,
                        "tool_use_id": block["id"],
                    }
                )

                if tool_name == "plan":
                    used_plan = True
                if tool_name == "compact":
                    manual_compact = True
                    compact_focus = (tool_input or {}).get("focus")

            if used_plan:
                self.plan_manager.state.rounds_since_update = 0
            else:
                self.plan_manager.note_round_without_update()
                reminder = self.plan_manager.reminder()
                if reminder:
                    tool_contents.insert(0, {"type": "text", "text": reminder})

            if manual_compact:
                self.history = tools.compact_history(
                    self.history,
                    self.compact_state,
                    self.workspace.root,
                    self.client,
                    self.config.model,
                    focus=compact_focus,
                )

            self.history.append({"role": "user", "content": tool_contents})

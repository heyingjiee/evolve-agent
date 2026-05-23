import json
import os
import subprocess
from pathlib import Path
from typing import NotRequired, TypedDict


HOOK_TIMEOUT = 30


class Context(TypedDict):
    tool_name: str
    tool_input: NotRequired[str | dict | None]
    tool_output: NotRequired[str | None]


class HookResult(TypedDict):
    blocked: bool
    block_reason: NotRequired[str]
    messages: list[str]


class HookManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.hooks = {"PreToolUse": [], "PostToolUse": [], "SessionStart": []}
        settings_path = self.workspace / ".evolve" / "settings.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            hooks_config = settings.get("hooks", {})
            for event in ("PreToolUse", "PostToolUse", "SessionStart"):
                self.hooks[event] = hooks_config.get(event, [])
            if hooks_config:
                print(f"[Hooks loaded from {settings_path}]")

    def run_hook(self, event: str, context: Context) -> HookResult:
        result: HookResult = {"blocked": False, "messages": []}

        for hook in self.hooks[event]:
            matcher = hook["matcher"]
            command = hook["command"]
            if matcher != "*" and matcher != context["tool_name"]:
                continue

            env = dict(os.environ)
            env["tool_name"] = context["tool_name"]
            env["tool_input"] = json.dumps(context.get("tool_input", "{}"), ensure_ascii=False)[:10000]
            env["tool_output"] = (context.get("tool_output") or "")[:10000]

            try:
                run_result = subprocess.run(
                    command,
                    cwd=self.workspace,
                    env=env,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=HOOK_TIMEOUT,
                )
                stdout_preview = run_result.stdout.strip()[:100] if run_result.stdout else "(no stdout)"
                print(f"[hook:{event}]\n{stdout_preview}")
                if run_result.returncode == 0:
                    try:
                        hook_output = json.loads(run_result.stdout.strip())
                        if "updatedInput" in hook_output:
                            context["tool_input"] = hook_output["updatedInput"]
                        if hook_output.get("additionalContext"):
                            result["messages"].append(hook_output["additionalContext"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif run_result.returncode == 1:
                    reason = run_result.stderr.strip() or "Blocked by hook"
                    result["blocked"] = True
                    result["block_reason"] = reason
                    print(f"  [hook:{event}] BLOCKED: {reason[:200]}")
                elif run_result.returncode == 2:
                    msg = run_result.stderr.strip()
                    if msg:
                        result["messages"].append(msg)
                        print(f"  [hook:{event}] INJECT: {msg[:200]}")
            except subprocess.TimeoutExpired as e:
                print(f"  [hook:{event}] Timeout: {e}")
            except Exception as e:
                print(f"[hook:{event}] Error: {e}")
        return result

from pathlib import Path

from evolve import tools
from evolve.tools.skill import SkillRegistry


task_schema = {
    "name": "task",
    "description": "Run a subtask in a clean context and return a summary",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "description": {"type": "string", "description": "Short description of the task"},
        },
        "required": ["prompt"],
    },
}


CHILD_TOOLS = [tools.bash_schema, tools.read_schema, tools.write_schema, tools.edit_schema, tools.skill_schema]


def execute_tool(block, state: tools.CompactState, workspace: Path, skill_registry: SkillRegistry) -> str:
    tool_name = block.get("name")
    argv = block.get("input") or {}
    tool_use_id = block.get("id")
    if tool_name == "bash":
        return tools.run_bash(argv["command"], tool_use_id, workspace)
    if tool_name == "read_file":
        return tools.run_read(argv["path"], tool_use_id, state, workspace, argv.get("limit"))
    if tool_name == "write_file":
        return tools.run_write(argv["path"], argv["content"], workspace)
    if tool_name == "edit_file":
        return tools.run_edit(argv["path"], argv["old_text"], argv["new_text"], workspace)
    if tool_name == "load_skill":
        return skill_registry.load_full_text(argv["name"])
    if tool_name == "compact":
        return "Compacting conversation..."
    return f"Unknown tool: {tool_name}"


def run_task_subagent(prompt: str, *, workspace: Path, client, model: str, skill_registry: SkillRegistry) -> str:
    sub_system = f"You are a coding subagent at {workspace}. Complete the given task, then summarize your findings"
    sub_message: list = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    compact_state = tools.CompactState()

    for _ in range(30):
        resp = client.messages.create(
            model=model,
            system=sub_system,
            messages=sub_message,
            tools=CHILD_TOOLS,
            max_tokens=8000,
        )
        contents = [block.to_dict() for block in resp.content]
        sub_message.append({"role": "assistant", "content": contents})
        if resp.stop_reason != "tool_use":
            break

        results = []
        for block in contents:
            if block["type"] != "tool_use":
                continue
            output = execute_tool(block, compact_state, workspace, skill_registry)
            results.append({"type": "tool_result", "content": output, "tool_use_id": block["id"]})
        sub_message.append({"role": "user", "content": results})

    return "".join(block["text"] for block in contents if block["type"] == "text") or "(no summary)"

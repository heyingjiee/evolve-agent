from pathlib import Path

from evolve.shared.utils import safe_path
from evolve.tools.compact import CompactState, persist_large_output


def run_read(path: str, tool_use_id: str, state: CompactState, workspace: Path, limit: int = None) -> str:
    """
        读取文件内容。
        当返回内容过大时，先持久化到本地，避免挤占上下文窗口。
    """
    if path in state.recent_files:
        state.recent_files.remove(path)
    state.recent_files.append(path)

    if len(state.recent_files) > 5:
        state.recent_files = state.recent_files[-5:]

    try:
        text = safe_path(path, work_dir=workspace).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"...({len(lines) - limit} more lines)"]
        return persist_large_output(tool_use_id, "\n".join(lines), workspace)
    except Exception as e:
        return f"Error: {e}"


read_schema = {
    "name": "read_file",
    "description": "Read file contents",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["path"],
    },
}

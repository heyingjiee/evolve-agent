from evolve.tools.compact import persist_large_output
from evolve.shared.utils import safe_path
from evolve.tools.compact import CompactState
from evolve.config import global_config


def run_read(path: str, tool_use_id: str, state: CompactState, limit: int = None) -> str:
    """
        read工具，防止读取的内容很大，挤占上下文窗口，所以需要持久化化到本地
    """
    # 如果存在，则移除，然后追加到最后
    if path in state.recent_files:
        state.recent_files.remove(path)
    state.recent_files.append(path)

    # 超过5条，截取最后5条
    if len(state.recent_files) > 5:
        state.recent_files = state.recent_files[:-5]
    # 读取文件
    try:
        text = safe_path(path, work_dir=global_config.WORKDIR).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"...({len(lines) - limit} more lines)"]
        return persist_large_output(tool_use_id, '\n'.join(lines))  # 持久化
    except Exception as e:
        return f"Error: {e}"


read_schema = {
    "name": "read_file",
    "description": "Read file contents",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["path"]
    }
}

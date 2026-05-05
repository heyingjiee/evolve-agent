from pathlib import Path

from shared.utils import safe_path


def run_read(path: str, limit: int = None) -> str:
    """ read工具 """
    try:
        text = safe_path(path, work_dir = Path.cwd()).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"...({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:5000]
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
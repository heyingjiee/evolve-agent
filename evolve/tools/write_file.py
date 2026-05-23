from pathlib import Path

from evolve.shared.utils import safe_path


def run_write(path: str, content: str, workspace: Path) -> str:
    """ write工具 """
    try:
        fp = safe_path(path, work_dir=workspace)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


write_schema = {
    "name": "write_file",
    "description": "Write contents to file ",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}

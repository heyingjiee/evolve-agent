from pathlib import Path

from evolve.shared.utils import safe_path


def run_edit(path: str, old_text: str, new_text: str, workspace: Path) -> str:
    """ 编辑文件"""
    try:
        fp = safe_path(path, work_dir=workspace)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


edit_schema = {
    "name": "edit_file",
    "description": "Replace exact content in file",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        "required": ["path", "old_text", "new_text"],
    },
}

from .bash import bash_schema, run_bash
from .edit_file import edit_schema, run_edit
from .read_file import read_schema, run_read
from .write_file import write_schema, run_write
from .todo import todo_schema, TodoManager

TODO = TodoManager(3)

# 工具映射
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),  # limit是可选参数，需要用get
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"])
}

__all__ = ["TOOL_HANDLERS", "TODO", "bash_schema", "edit_schema", "read_schema", "write_schema", "todo_schema"]
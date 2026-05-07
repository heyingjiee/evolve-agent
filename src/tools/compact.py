import os
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class CompactState:
    has_compacted: bool = False,  # 是否被压缩过
    last_summary: str = "",
    recent_files: list[str] = field(default_factory=list),


def persist_large_output(tool_use_id: str, output: str) -> str:
    """ 持久化到文件,返回Preview概览 """
    if len(output) <= int(os.getenv("PERSIST_THRESHOLD", "30000")):
        return output

    preview_chars = int(os.getenv("PREVIEW_CHARS", "2000"))
    tool_result_dir = Path.cwd() / os.getenv("TOOL_RESULTS_DIR", "./task_outputs/tool-results")

    tool_result_dir.mkdir(parents=True, exist_ok=True)
    stored_path = tool_result_dir / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output)
    preview = output[:preview_chars]
    relative_path = stored_path.relative_to(Path.cwd())
    return (
        "<persisted-output>"
        f"Full output saved to: {relative_path}"
        "Preview:\n"
        f"{preview}\n"
        "</persisted-output>"
    )
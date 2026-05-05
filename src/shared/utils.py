from pathlib import Path

def safe_path(p: str, *,work_dir: Path) -> Path:
    """ 安全路径, 防止路径跑出 WORKDIR 以外 """
    path = (work_dir / p).resolve()
    if not path.is_relative_to(work_dir):
        raise ValueError(f"Path escapes workspace: {path}")
    return path


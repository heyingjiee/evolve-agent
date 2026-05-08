import sys
from pathlib import Path

# 将 src 目录添加到 Python 路径
root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "src"))

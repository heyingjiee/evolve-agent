import os
import re
from pathlib import Path

def main():
    text = """---
name: xxx
description: yyyy
---"""
    print(re.match(r"^---\n(.*)\n(.*)\n---",text).group(1))

if __name__ == "__main__":
    main()

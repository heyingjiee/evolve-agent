import os
from pathlib import Path
from anthropic import Anthropic


class GlobalConfig:
    def __init__(self):
        # 运行目录
        self.WORKDIR = Path.cwd()

        # 客户端
        self.client = Anthropic(
            base_url=os.getenv("ANTHROPIC_BASE_URL"),
            api_key=os.getenv("ANTHROPIC_API_KEY"),  # This is the default and can be omitted
        )


# 实例化全局单例配置
global_config = GlobalConfig()
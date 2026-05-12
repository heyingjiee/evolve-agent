import json

from hooks import HookManager

try:
    import readline

    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
    # readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass

# 加载环境变量后
from dotenv import load_dotenv

load_dotenv(override=True)

# 加载环境变量后，再执行
import os
from pathlib import Path
from config import global_config
from agents import main_agent
from permission.manager import PermissionManager, MODES
import tools

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# TODO 工具是否支持同步，目前工具调用不能同步
CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}


# TODO 加入到入口，没有就input要求用户确认，确认后新建配置文件，取消直接结束
def is_workspace_trusted(workspace: Path) -> bool:
    """ 检查是否是受信人工作区 """
    ws = workspace or global_config.WORKDIR
    setting_path = (ws / ".evolve/setting.json")
    if not setting_path.exists():
        return False
    else:
        return json.loads(setting_path.read_text()).get("trust", False)


def main():
    # 先询问是否信任工作区，信任放行，否则退出
    if not is_workspace_trusted(global_config.WORKDIR):
        is_trusted = input("> do you trust the current workspace? Allow? (y/n):")
        if is_trusted == "y":
            setting_file = global_config.WORKDIR / ".evolve/setting.json"
            setting_config = {}
            if setting_file.exists():
                # 存在读取历史配置
                setting_config = json.loads(setting_file.read_text())
            else:
                # 不存在保证父级目录存在，后面write才不会报错
                setting_file.parent.mkdir(parents=True, exist_ok=True)
            # 设置配置
            setting_config["trust"] = "true"
            setting_file.write_text(json.dumps(setting_config, indent=4, ensure_ascii=False))
        else:
            return

    # 对话历史
    history = []
    # 压缩历史
    compact_state = tools.CompactState()
    # 钩子
    hooks = HookManager()

    # 启动设置权限模式
    print("Permission modes: default,plan,auto")
    mode_input = input("Mode (default): ").strip().lower() or "default"
    perms = PermissionManager(mode=mode_input)

    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (KeyboardInterrupt, EOFError):
            break

        # 退出
        if query.strip().lower() in ("exit", "q"):
            break

        # /mode <mode> 切换权限模式
        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2:
                perms.mode = parts[1]
                print(f"[Switched to {parts[1]} mode]")
            else:
                print(f"Usage: /mode <{"|".join(MODES)}>")
            continue

        # /rules 展示当前规则集合
        if query == "/rules":
            for index, rule in enumerate(perms.rules):
                print(f"{index}: {rule}")
            continue

        history.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": query,
            }]
        })
        main_agent.agent_loop(history, state=compact_state, perms=perms, hooks=hooks)

        final_text = "".join([block["text"] for block in history[-1]["content"] if block["type"] == "text"])
        print(final_text)


if __name__ == "__main__":
    main()

# 计划测试: 帮我规划五一推荐景点、以及景点的热门项目、美食推荐

# subAgent测试: 两个子agent分别统计四川、山东的菜系特征、名菜、文化与饮食习惯的关系，主Agent汇总生成 food.md

# 压缩read_file、bash返回值、自动压缩上下文： 读取 /Users/heyingjie/Downloads/简历.pdf 分析如何改进来提高简历初筛率

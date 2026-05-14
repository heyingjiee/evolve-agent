import json
import os
import subprocess
from typing import NotRequired, TypedDict

from evolve.config import global_config

# hook执行超时时间
HOOK_TIMEOUT = 30  # 秒


class Context(TypedDict):
    tool_name: str
    tool_input: NotRequired[str | None]
    tool_output: NotRequired[str | None]  # PostToolUse钩子会有工具输出


class HookResult(TypedDict):
    blocked: bool  # 是否阻止
    block_reason: NotRequired[str]  # 阻止原因（可选）
    messages: list[str]  # 提示信息 （可选）


class HookManager:
    """"
        1、init：
        从 hooks.json中加载钩子逻辑 ， 结构如下:
            {
              "hooks": {
                "PreToolUse": [
                  {
                    "matcher": "Bash",  # 匹配当 Bash工具调用才执行 command
                    "command": "node scripts/check_safety.js"
                  },
                  {
                    "matcher": "*",
                    "command": "echo 'Checking permissions...'"
                  }
                ],
                "PostToolUse": [
                  {
                    "matcher": "Write",
                    "command": "git add ."
                  }
                ],
                # TODO 这个需要实现
                "SessionStart": [
                  {
                    "matcher": "*",
                    "command": "echo 'Session started!'"
                  }
                ]
              }
            }

        2、run_hook: 运行钩子
    """

    def __init__(self):
        self.hooks = {"PreToolUse": [], "PostToolUse": [], "SessionStart": []}
        hooks_config_path = global_config.WORKDIR / ".evolve" / "hooks.json"
        hooks_config = {}
        if hooks_config_path.exists():
            hooks_config = json.loads(hooks_config_path.read_text())["hooks"]
            for event in ("PreToolUse", "PostToolUse", "SessionStart"):
                self.hooks[event] = hooks_config.get(event, [])
            print(f"[Hooks loaded from {hooks_config_path}]")

    def run_hook(self, event: str, context: Context) -> HookResult:
        """
            event = PreToolUse"|"PostToolUse"|"SessionStart
            1、运行指定 event 的所有钩子
            2、可能有多个工具调用，每个都触发 run_hook ，所以 context 记录了是哪个工具，入参、返参
            3、只有matcher匹配上的工具才执行command。 将 context 数据注入到command的环境变量，command就可以访问这些信息

               command入参：把上下文注入env，传入command
               command返参：
                    returncode 退出码： 0放行，1拒绝,3补充
                    stdout 标准输出：有2种情况
                        字符串：'xxxx'
                        JSON字符串： 下面约定3个字段来控制python的逻辑
                        {
                          "updatedInput": "xxx"  # 调用工具的入参
                          "permissionDecision": "DENY", # 权限
                          "additionalContext": "禁止删除 /tmp/important 目录！" # 信息
                        }
              处理command结果，拼接返参
                    result = {
                        "blocked": False,   # 是否阻止
                        "block_reason": "xxx" # 阻止原因（可选）
                        "messages": [],  # 提示信息 （可选）
                    }
        """
        # 默认返回结果
        result: HookResult = {"blocked": False, "messages": []}

        for hook in self.hooks[event]:
            matcher = hook["matcher"]
            command = hook["command"]
            if matcher == "*" or matcher == context["tool_name"]:
                # `*` 是所有工具都触发，或者精确匹配到context["tool_input"]触发
                # 把上下文信息注入到环境变量
                env = dict(os.environ)  # 浅拷贝环境变量，不能直接修改环境变量否则会影响主程序
                env["tool_name"] = context["tool_name"]
                env["tool_input"] = json.dumps(context.get("tool_input", "{}"), ensure_ascii=False)[:10000]
                env["tool_output"] = (context.get("tool_output") or "")[:10000]

                # 执行命令
                try:
                    r = subprocess.run(
                        command,
                        cwd=global_config.WORKDIR,
                        env=env,
                        shell=True,
                        capture_output=True,
                        text=True, timeout=HOOK_TIMEOUT)
                    print(f"[hook:{event}]\n{r.stdout.strip()[:100] if r.stdout else "(no stdout)})"}")
                    # 放行
                    if r.returncode == 0:
                        try:
                            # 返回JSON
                            hook_output = json.loads(r.stdout.strip())
                            # 更新上下文工具入参
                            if "updatedInput" in hook_output:
                                context["tool_input"] = hook_output["updatedInput"]
                            # 拼接返回结果
                            # 不改变 blocked 结果
                            # 有信息追加信息
                            if hook_output.get("additionalContext"):
                                result["messages"].append(hook_output.get("additionalContext"))
                        except (json.JSONDecodeError, TypeError):
                            # 返回字符串
                            pass

                    # 拒绝
                    elif r.returncode == 1:
                        reason = r.stderr.strip() or "Blocked by hook"
                        result["blocked"] = True
                        result["block_reason"] = reason
                        print(f"  [hook:{event}] BLOCKED: {reason[:200]}")

                    # 放行 + 注入信息
                    elif r.returncode == 2:
                        msg = r.stderr.strip()
                        if msg:
                            result["messages"].append(msg)
                            print(f"  [hook:{event}] INJECT: {msg[:200]}")

                except subprocess.TimeoutExpired as e:
                    print(f"  [hook:{event}] Timeout: {e}")
                except Exception as e:
                    print(f"[hook:{event}] Error: {e}")
        return result


from dotenv import load_dotenv

# 加载环境变量 - 必须在其他导入之前
load_dotenv(override=True)

import json
import os
from pathlib import Path
from typing import cast

from evolve import tools
from evolve.config import global_config
from evolve.hooks import HookManager, Context
from evolve.permission.manager import MODES, PermissionManager
from evolve.agents.task import task_schema, run_task_subagent
from evolve.prompt import SystemPromptBuilder

try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
    # readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# TODO 工具是否支持同步，目前工具调用不能同步
CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}

# TODO 加入到入口，没有就input要求用户确认，确认后新建配置文件，取消直接结束
def is_workspace_trusted(workspace: Path) -> bool:
    """检查是否是受信人工作区"""
    ws = workspace or global_config.WORKDIR
    setting_path = ws / ".evolve/settings.json"
    if not setting_path.exists():
        return False
    else:
        return json.loads(setting_path.read_text()).get("trust", False)


# 任务管理器
reminder_interval = int(os.getenv("REMINDER_INTERVAL", "3"))
planManager = tools.PlanManager(reminder_interval)


# 工具Schema
TOOLS = [
    tools.bash_schema,
    tools.read_schema,
    tools.write_schema,
    tools.edit_schema,
    tools.plan_schema,
    tools.skill_schema,
    task_schema,
    tools.compact_schema,
    tools.memory_schema,
    tools.run_background_schema,
    tools.check_background_schema
]

# 调用工具
def execute_tool(block, compact_state: tools.CompactState) -> str:
    tool_name = block.get("name")
    argv = block.get("input") or {}
    tool_use_id = block.get("id")
    if tool_name == "bash":
        return tools.run_bash(argv["command"], tool_use_id)
    if tool_name == "read_file":
        return tools.run_read(argv["path"], tool_use_id, compact_state, argv.get("limit"))
    if tool_name == "write_file":
        return tools.run_write(argv["path"], argv["content"])
    if tool_name == "edit_file":
        return tools.run_edit(argv["path"], argv["old_text"], argv["new_text"])
    if tool_name == "plan":
        return planManager.update(argv["items"])
    if tool_name == "task":
        desc = cast(str, argv.get("description", "subtask"))
        prompt = cast(str, argv.get("prompt", ""))
        print(f"[Subagent Prompt]\n{desc}: {prompt[:80]}")
        return run_task_subagent(prompt)
    if tool_name == "load_skill":
        return tools.SKILL_REGISTRY.load_full_text(argv["name"])
    if tool_name == "compact":
        return "Compacting conversation..."  # 真正的压缩不在这里，在agent loop
    if tool_name == "save_memory":
        tools.memory_mgr.save_memory(argv)
    if tool_name == "run_background":
        tools.bg_task_mgr.run(argv["command"])
    if tool_name == "check_background":
        tools.bg_task_mgr.check(argv.get("task_id") or None)
    return f"Unknown tool: {tool_name}"

# 统一处理下规范化参数
def normalize_messages(messages: list) -> list:
    """
    messages = [
       {"role": "user", "content": [ { "type": "text", "text": "你好"} ]},
       {
            "role": "assistant",
            "content": [
                "type": "text", "text": "答案",  # 返回答案
                "type": "tool_use", "id": "xxxxx" # 返回工具调用
            ]
       },
       {
            "role": "user",
            "content": [
                "type": "tool_result", "tool_use_id": "调用id", content": "调用结果"

            ]
       }
     ]

    注意：
     1、Agent调用工具，如果工具没调用成功/没有对应工具的情况，这种也需要补一条tool_result结果，content: "(cancelled)"
     2、user、assistant 需要交通，如果出现连续的同一角色，合并到 content 列表汇总
      {
         "role": "user", content: [
            "type": "tool_result", "tool_use_id":"xxxxx", "content": "(cancelled)"
            "type": "tool_result", "tool_use_id":"yyyyy", "content": "工具结果"
      ]},
    """
    # 给没有调用结果的工具，补一条 tool_resul
    has_tool_result_ids = set()
    for msg in messages:
        if msg["role"] == "user":
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    has_tool_result_ids.add(block["tool_use_id"])

    for msg in messages:
        if msg["role"] == "assistant":
            for block in msg["content"]:
                if (
                    block["type"] == "tool_use"
                    and block["id"] not in has_tool_result_ids
                ):
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block["id"],
                                    "content": "(cancelled)",
                                }
                            ],
                        }
                    )
    # 连续message是同一角色要合并
    merged = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev = merged[-1]
            prev["content"] = prev["content"] + msg["content"]
        else:
            merged.append(msg)
    return merged

# # 异常恢复器
# def choose_recovery(stop_reason: str | None, e: Exception | None) -> dict:
#     """
#         参数:
#             stop_reason 是每轮LLM返回的信息
#             error_text 是 try...except 捕获的错误
#         核心逻辑：
#            1、 stop_reason == "max_tokens" 大模型调用超tokens了
#            2、 e 错误
#                  except APIError as e:
#                    str(e) = overlong_prompt、(long+prompt) prompt超过上下文了 => 压缩
#                    str(e) = 其他错误 => 重试
#                  except (Ne):
#     """
#     ...

# 动态构建系统提示词
prompt_builder = SystemPromptBuilder(global_config.WORKDIR, TOOLS)

# 核心Agent Loop
def agent_loop(
    messages: list,
    *,
    compact_state: tools.CompactState,
    perms: PermissionManager,
    hooks: HookManager,
):
    """单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:

        # 组装系统提示词
        system = prompt_builder.build()

        # 取出所有已完成的后台任务
        notifs = tools.bg_task_mgr.clear_notifications()
        if notifs and messages:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['preview']} "
                f"(output_file={n['output_file']})"
                for n in notifs
            )
            messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})

        # 规范化参数
        messages[:] = normalize_messages(messages)  # 这是原地修改

        # 压缩工具返回结果
        messages[:] = tools.micro_compact(messages)

        # 超过上限压缩上下文
        if len(str(messages)) > int(os.getenv("CONTEXT_LIMIT", "50000")):
            print("[auto compact conversation history]")
            messages[:] = tools.compact_history(messages, compact_state)

        # 调用模型
        resp = global_config.client.messages.create(
            model=os.getenv("MODEL_ID", "claude-opus-4-6"),
            system=system,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        """
         resp.content格式: [{TinkingBlock()}, TextBlock(), ToolUseBlock(),...] 是 [ContentBlock] 类型
         把这些对象，转成字典
         注意：
            * type字段是公共的 thinking、text、tool_use 表示其类型，block["type"],其他字段建议get获取
            * type = tool_use 表示工具调用，其有 name: 工具名，input: 入参 , id：调用id
            * type = text 表示文本，其有 text: 返回的文本
        """
        contents = [block.to_dict() for block in resp.content]

        messages.append({"role": "assistant", "content": contents})

        # 不是工具调用，结束
        if resp.stop_reason != "tool_use":
            return

        # 工具调用
        tool_contents = []
        used_plan = False  # 存储本轮对话中，是否调用了计划工具
        manual_compact = False  # 存储本轮对话中，是否调用了压缩工具
        compact_focus = None  # LLM 返回是否压缩上下文

        for block in contents:
            if block["type"] == "tool_use":
                tool_name = block["name"]
                tool_input = block["input"]

                # 注入 Hook 的上下文
                ctx: Context = {"tool_name": tool_name, "tool_input": tool_input}
                print(f"{'-' * 50}")
                print(f"[Name] {tool_name}")
                print(f"[Input]\n{tool_input}")

                # TODO 这里之后需要调整下，关于 鉴权、Hook先后的逻辑，Hook应该有强大的能力去控制默认鉴权逻辑
                # 权限检查
                behavior, reason = perms.check(tool_name, tool_input).values()
                if behavior == "deny":
                    # 拒绝
                    output = f"Permission denied: {reason}"
                    print(f"  [DENIED] {block.get('name', 'unknown')}: {reason}")
                elif behavior == "ask" and not perms.ask_user(tool_name, tool_input):
                    # 询问用户，用户拒绝
                    output = f"Permission denied by user for: {tool_name}"
                    print(f"  [USER DENIED] {block.get('name', 'unknown')}")
                else:
                    # 允许 / 询问用户同意
                    # 执行前钩子
                    pre_hook_results = hooks.run_hook("PreToolUse", ctx)
                    for msg in pre_hook_results.get("messages", []):
                        tool_contents.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block["id"],
                                "content": f"[Hook message]: {msg}",
                            }
                        )
                    if pre_hook_results.get("blocked"):
                        reason = pre_hook_results.get("block_reason", "Blocked by hook")
                        output = f"Tool blocked by PreToolUse hook: {reason}"
                        tool_contents.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block["id"],
                                "content": output,
                            }
                        )
                        continue

                    output = execute_tool(block, compact_state)
                    print(f"[Output]\n{output[:200]}")

                    # 执行后钩子
                    ctx["tool_output"] = output
                    post_hook_result = hooks.run_hook("PostToolUse", ctx)
                    for msg in post_hook_result.get("messages", []):
                        output += f"\n[Hook note]: {msg}"
                    tool_contents.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": str(output),  # 这里覆盖了执行结果
                        }
                    )


                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                tool_contents.append(
                    {
                        "type": "tool_result",
                        "content": output,
                        "tool_use_id": block["id"],
                    }
                )

                # 记录调用过计划工具
                if tool_name == "plan":
                    used_plan = True
                # 记录调用过压缩工具
                if tool_name == "compact":
                    manual_compact = True
                    compact_focus = (tool_input or {}).get("focus")

        # 调用了计划工具
        if used_plan:
            planManager.state.rounds_since_update = 0
        else:
            # 没有调用就计数，然后触发reminder
            planManager.note_round_without_update()
            reminder = planManager.reminder()
            if reminder:
                # 注意力机制对开头和结尾的信息最敏感，而对中间的信息关注度最低。开头内容更不容易被噪音干扰
                tool_contents.insert(0, {"type": "text", "text": reminder})
                print(f"[Reminder plan]")

        # 调用了压缩工具
        if manual_compact:
            print("[manual compact]")
            messages[:] = tools.compact_history(messages, compact_state, focus=compact_focus)

        messages.append({"role": "user", "content": tool_contents})


def app():
    # 先询问是否信任工作区，信任放行，否则退出
    if not is_workspace_trusted(global_config.WORKDIR):
        is_trusted = input("> do you trust the current workspace? Allow? (y/n):")
        if is_trusted == "y":
            setting_file = global_config.WORKDIR / ".evolve/settings.json"
            setting_config = {}
            if setting_file.exists():
                # 存在读取历史配置
                setting_config = json.loads(setting_file.read_text())
            else:
                # 不存在保证父级目录存在，后面write才不会报错
                setting_file.parent.mkdir(parents=True, exist_ok=True)
            # 设置配置
            setting_config["trust"] = "true"
            setting_file.write_text(
                json.dumps(setting_config, indent=4, ensure_ascii=False)
            )
        else:
            return

    # 对话历史
    history = []
    # 压缩状态
    compact_state = tools.CompactState()
    # 钩子
    hooks = HookManager()
    # 加载 .evolve/.memory 下的记忆文件
    tools.memory_mgr.load_all()
    # 构建好的提示词
    full_prompt = prompt_builder.build()
    section_count = full_prompt.count("\n# ")
    print(f"[System prompt assembled: {len(full_prompt)} chars, ~{section_count} sections]")

    # 启动设置权限模式
    # mode_input = input("choose mode (default/plan/auto): ").strip().lower() or "default"
    # print(f"[Using {mode_input} mode]")
    perms = PermissionManager(mode="default")

    while True:
        try:
            query = input("evolve> ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        # 退出
        if query.lower() in ("exit", "q"):
            break

        # /mode <mode> 切换权限模式
        if query.startswith("/mode"):
            parts = query.split()
            if len(parts) == 2:
                perms.mode = parts[1]
                print(f"[Switched to {parts[1]} mode]")
            else:
                print(f"Usage: /mode <{'|'.join(MODES)}>")
            continue

        # /rules 展示当前规则集合
        if query == "/rules":
            for index, rule in enumerate(perms.rules):
                print(f"{index}: {rule}")
            continue

        # /memories 列出当前记忆文件
        if query == "/memories":
            if tools.memory_mgr.memories:
                for mem in tools.memory_mgr.memories.values():
                    print(f"  [{mem['type']}] {mem['name']} {mem['description']}")
            else:
                print("  (no memories)")
            continue

        if query == "/prompt":
            print(prompt_builder.build())
            continue

        if query.strip() == "/sections":
            prompt = prompt_builder.build()
            for line in prompt.splitlines():
                if line.startswith("# ") or line == "=== DYNAMIC_BOUNDARY ===":
                    print(f"  {line}")
            continue

        history.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": query,
                    }
                ],
            }
        )
        agent_loop(
            history,
            compact_state=compact_state,
            perms=perms,
            hooks=hooks,
        )

        final_text = "".join(
            [
                block["text"]
                for block in history[-1]["content"]
                if block["type"] == "text"
            ]
        )
        print(f"{'-' * 50}\n{final_text}\n{'-' * 50}")


if __name__ == "__main__":
    app()

# 计划测试: 调研中华饮食文化变化，按照 搜集、汇总、输出文档 这三部完成

# subAgent测试: 两个子agent分别统计四川、山东的菜系特征、名菜、文化与饮食习惯的关系，主Agent汇总生成 food.md

# 压缩read_file、bash返回值、自动压缩上下文： 读取 /Users/heyingjie/Downloads/简历.pdf 分析如何改进来提高简历初筛率

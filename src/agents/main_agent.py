import os
from typing import cast

import tools
from agents.task import run_task_subagent, task_schema
from config import global_config
from hooks import Context, HookManager
from permission.manager import PermissionManager
from tools import memory_mgr

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
]


# 调用工具
def execute_tool(block, state: tools.CompactState) -> str:
    tool_name = block.get("name")
    argv = block.get("input")
    tool_use_id = block.get("id")
    if tool_name == "bash":
        return tools.run_bash(argv["command"], tool_use_id)
    if tool_name == "read_file":
        return tools.run_read(argv["path"], tool_use_id, state, argv.get("limit"))
    if tool_name == "write_file":
        return tools.run_write(argv["path"], argv["content"])
    if tool_name == "edit_file":
        return tools.run_edit(argv["path"], argv["old_text"], argv["new_text"])
    if tool_name == "plan":
        return planManager.update(argv["items"])
    if tool_name == "task":
        desc = cast(str, argv.get("description", "subtask"))
        prompt = cast(str, argv.get("prompt", ""))
        print(f"[Subagent]: {desc}: {prompt[:80]}")
        return run_task_subagent(prompt)
    if tool_name == "load_skill":
        return tools.SKILL_REGISTRY.load_full_text(argv["name"])
    if tool_name == "compact":
        return "Compacting conversation..."  # 真正的压缩不在这里，在agent loop
    if tool_name == "save_memory":
        memory_mgr.save_memory(argv)
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


MEMORY_GUIDANCE = """
When to save memories:
- User states a preference ("I like tabs", "always use pytest") -> type: user
- User corrects you ("don't do X", "that was wrong because...") -> type: feedback
- You learn a project fact that is not easy to infer from current code alone
  (for example: a rule exists because of compliance, or a legacy module must
  stay untouched for business reasons) -> type: project
- You learn where an external resource lives (ticket board, dashboard, docs URL)
  -> type: reference
When NOT to save:
- Anything easily derivable from code (function signatures, file structure, directory layout)
- Temporary task state (current branch, open PR numbers, current TODOs)
- Secrets or credentials (API keys, passwords)
"""


# 系统提示词
def build_system_prompt():
    parts = [
        f"You are a coding agent at {global_config.WORKDIR}. Use tools to solve tasks"
    ]

    # 加载存储的记忆 ，如何使用记忆
    # TODO: 记忆会膨胀，需要定期处理。09提到的DreamConsolidator
    # TODO: subAgent 支持读memory，不能写
    memory_section = memory_mgr.load_memory_prompt()
    if memory_section:
        parts.append(memory_section)
    parts.append(MEMORY_GUIDANCE)

    # Skill
    parts.append(f"Skills available: {tools.SKILL_REGISTRY.describe_available()}")

    return "\n\n".join(parts)


# 核心Agent Loop
def agent_loop(
    messages: list,
    *,
    state: tools.CompactState,
    perms: PermissionManager,
    hooks: HookManager,
):
    """单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:
        # 组装系统提示词
        system = build_system_prompt()

        # 规范化参数
        messages[:] = normalize_messages(messages)  # 这是原地修改

        # 压缩工具返回结果
        messages[:] = tools.micro_compact(messages)

        # 超过上限压缩上下文
        if len(str(messages)) > int(os.getenv("CONTEXT_LIMIT", "50000")):
            print("[auto compact conversation history]")
            messages[:] = tools.compact_history(messages, state)

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
        used_todo = False  # 存储本轮对话中，是否调用了计划工具
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
                    print(f"  [DENIED] {block.name}: {reason}")
                elif behavior == "ask" and not perms.ask_user(tool_name, tool_input):
                    # 询问用户，用户拒绝
                    output = f"Permission denied by user for: {tool_name}"
                    print(f"  [USER DENIED] {block.name}")
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

                    output = execute_tool(block, state)

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
                    print(f"[Output]\n{output[:200]}")
                    print(f"{'-' * 50}")

                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                tool_contents.append(
                    {
                        "type": "tool_result",
                        "content": output,
                        "tool_use_id": block["id"],
                    }
                )

                # 记录调用过计划工具
                if tool_name == "todo":
                    used_todo = True
                # 记录调用过压缩工具
                if tool_name == "compact":
                    manual_compact = True
                    compact_focus = (tool_input or {}).get("focus")

        # 调用了计划工具
        if used_todo:
            planManager.state.rounds_since_update = 0
        else:
            # 没有调用就计数，然后触发reminder
            planManager.note_round_without_update()
            reminder = planManager.reminder()
            if reminder:
                # 注意力机制对开头和结尾的信息最敏感，而对中间的信息关注度最低。开头内容更不容易被噪音干扰
                tool_contents.insert(0, {"type": "text", "text": reminder})

        # 调用了压缩工具
        if manual_compact:
            print("[manual compact]")
            messages[:] = tools.compact_history(messages, state, focus=compact_focus)

        messages.append({"role": "user", "content": tool_contents})

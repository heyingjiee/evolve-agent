import os
from typing import cast
import tools
from config import global_config
from permission.manager import PermissionManager
from agents.task import task_schema, run_task_subagent


# 任务管理器
reminder_interval = int(os.getenv('REMINDER_INTERVAL', "3"))
planManager = tools.PlanManager(reminder_interval)


# 系统提示词
SYSTEM = f"""You are a coding agent at {global_config.WORKDIR}.
Use bash to inspect and change the workspace. Act first, then report clearly.
Skills available:
{tools.SKILL_REGISTRY.describe_available()}
"""

# 工具Schema
TOOLS = [tools.bash_schema, tools.read_schema, tools.write_schema, tools.edit_schema, tools.plan_schema, tools.skill_schema, task_schema, tools.compact_schema]

# 调用工具
def execute_tool(block, state: tools.CompactState) -> str:
    tool_name = block.get("name")
    argv = block.get("input")
    tool_use_id = block.get("id")
    if tool_name == 'bash':
        return tools.run_bash(argv["command"], tool_use_id)
    if tool_name == 'read_file':
        return tools.run_read(argv["path"], tool_use_id, state, argv.get("limit"))
    if tool_name == 'write_file':
        return tools.run_write(argv["path"], argv["content"])
    if tool_name == 'edit_file':
        return tools.run_edit(argv["path"], argv["old_text"], argv["new_text"])
    if tool_name == 'plan':
       return planManager.update(argv["items"])
    if tool_name == 'task':
       desc = cast(str, argv.get("description", "subtask"))
       prompt = cast(str, argv.get("prompt", ""))
       print(f"[Subagent]: {desc}: {prompt[:80]}")
       return run_task_subagent(prompt)
    if tool_name == 'load_skill':
       return tools.SKILL_REGISTRY.load_full_text(argv["name"])
    if tool_name == 'compact':
       return "Compacting conversation..." # 真正的压缩不在这里，在agent loop
    return f"Unknown tool: {tool_name}"

# 统一处理下
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
                if block["type"] == "tool_use" and block["id"] not in has_tool_result_ids:
                   messages.append({
                       "role": "user",
                       "content": [{
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": "(cancelled)"
                        }]
                   })
    # 连续message是同一角色要合并
    merged = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev = merged[-1]
            prev["content"] = prev["content"] + msg["content"]
        else:
            merged.append(msg)
    return merged

# 核心Agent Loop
def agent_loop(messages: list, state: tools.CompactState, perms: PermissionManager):
    """ 单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:
        # 规范化参数
        messages[:] = normalize_messages(messages) # 这是原地修改

        # 压缩工具返回结果
        messages[:] = tools.micro_compact(messages)

        # 超过上限压缩上下文
        if len(str(messages)) > int(os.getenv("CONTEXT_LIMIT", "50000")):
            print("[auto compact conversation history]")
            messages[:] = tools.compact_history(messages, state)

        # 调用模型
        resp = global_config.client.messages.create(
            model=os.getenv('MODEL_ID', 'claude-opus-4-6'),
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
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
        used_todo = False # 存储本轮对话中，是否调用了计划工具
        manual_compact = False # 存储本轮对话中，是否调用了压缩工具
        compact_focus = None # LLM 返回是否压缩上下文

        for block in contents:
            if block["type"] == "tool_use":
                tool_name = block["name"]
                tool_input = block["input"]
                print(f"[Tool] {tool_name}: {tool_input}")
                # 权限检查
                behavior, reason = perms.check(tool_name, tool_input).values()
                if behavior == "deny":
                    # 拒绝
                    output = f"Permission denied: {reason}"
                    print(f"  [DENIED] {block.name}: {reason}")
                elif behavior == "ask":
                    # 询问用户
                    if perms.ask_user(tool_name, tool_input):
                        output = execute_tool(block, state)  # 执行工具
                        print(f"[Tool Result]\n{output[:200]}")
                    else:
                        output = f"Permission denied by user for: {tool_name}"
                        print(f"  [USER DENIED] {block.name}")
                else:
                    # 允许
                    output = execute_tool(block, state) # 执行工具
                    print(f"[Tool Result]\n{output[:200]}")

                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                tool_contents.append({"type": "tool_result", "content": output, "tool_use_id": block["id"]})

                # 记录调用过计划工具
                if tool_name == 'todo':
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

import os
import tools
from config import global_config
from tools.skill import SKILL_REGISTRY

# schema
task_schema = {
    "name": "task",
    "description": "Run a subtask in a clean context and return a summary",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "description":  {"type": "string", "description": "Short description of the task"}
        },
        "required": ["prompt"]
    }
}

# 系统提示词
SUB_SYSTEM = f"You are a coding subagent at {global_config.WORKDIR}. Complete the given task, then summarize your findings"

# 工具集
CHILD_TOOLS = [tools.bash_schema, tools.read_schema, tools.write_schema, tools.edit_schema, tools.skill_schema]

# 工具调用
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
    if tool_name == 'load_skill':
       return SKILL_REGISTRY.load_full_text(argv["name"])
    if tool_name == 'compact':
       return "Compacting conversation..." # 真正的压缩不在这里，在agent loop
    return f"Unknown tool: {tool_name}"

# 子Agent
def run_task_subagent(prompt: str) -> str:
    # message
    sub_message:list = [{"role": "user", "content": [{ "type": "text", "text": prompt}]}]

    compact_state = tools.CompactState()
    # 最大30轮循环
    for _ in range(30):
        resp = global_config.client.messages.create(
            model=os.getenv('MODEL_ID', 'claude-opus-4-6'),
            system=SUB_SYSTEM,
            messages=sub_message,
            tools=CHILD_TOOLS,
            max_tokens=8000
        )

        # 把大模型返回的对象转化为 dict
        contents = [block.to_dict() for block in resp.content]

        sub_message.append({"role": "assistant", "content": contents})

        # 不是工具调用，结束
        if resp.stop_reason != "tool_use":
            break

        # 工具调用
        results = []
        for block in contents:
            if block["type"] == 'tool_use':
                tool_name = block["name"]
                tool_use_id = block["id"]
                tool_argv = block["input"]
                output = execute_tool(block, compact_state)
                print(f"[Tool]\n{tool_name}: {tool_argv}")
                print(f"[Tool Result]\n{output[:200]}")
                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                results.append({"type": "tool_result", "content": output, "tool_use_id": tool_use_id})

        sub_message.append({"role": "user", "content": results})
    # 最后一轮是摘要, LLM返回的content是 [ContentBlock] ，需要用 getattr，取 type
    return "".join(block["text"] for block in contents if block["type"] == "text") or "(no summary)"

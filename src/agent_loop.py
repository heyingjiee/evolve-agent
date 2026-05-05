import os

try:
    import readline

    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
    readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass


from tools import TOOL_HANDLERS, bash_schema, read_schema, write_schema, edit_schema, TODO, todo_schema
from typing import cast
from anthropic import Anthropic
from anthropic.types import ThinkingBlock, ToolUseBlock, TextBlock
from dotenv import load_dotenv


load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),  # This is the default and can be omitted
)

# 模型
MODEL = os.getenv('MODEL_ID', 'claude-opus-4-6')

# 系统提示词
SYSTEM = """
    f"You are a coding agent at {os.getcwd()}"
    "Use bash to inspect and change the workspace. Act first, then report clearly."
"""

# 子Agent系统提示词
SUB_SYSTEM = f"You are a coding subagent at {os.getcwd()}. Complete the given task, then summarize your findings"


# 计划经过多少轮触发提醒
PLAN_REMINDER_INTERVAL = 3

def extract_text(content: list[ThinkingBlock] | str):
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts)


CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}

task_schema = [{
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
}]

TOOLS = [bash_schema, read_schema, write_schema, edit_schema, todo_schema] + task_schema
CHILD_TOOLS = [bash_schema, read_schema, write_schema, edit_schema]

# 子Agent
def run_subagent(prompt: str) -> str:
    sub_message:list = [{"role": "user", "content": prompt}]
    # 最大30轮循环
    for _ in range(30):
        resp = client.messages.create(
            model=MODEL,
            system=SUB_SYSTEM,
            messages=sub_message,
            tools=CHILD_TOOLS,
            max_tokens=8000
        )

        sub_message.append({"role": "assistant", "content": resp.content})

        # 不是工具调用，结束
        if resp.stop_reason != "tool_use":
            break

        # 工具调用
        results = []
        for block in resp.content:
            if block.type == 'tool_use':
                block = cast(ToolUseBlock, block)  # 重新断言
                try:
                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        output = handler(**block.input)
                    else:
                        output = f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                print(f"[Tool] {block.name}: {block.input}")
                print(f"[Tool Result] {output[:200]}")
                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                results.append({"type": "tool_result", "content": output, "tool_use_id": block.id})

        sub_message.append({"role": "user", "content": results})
    # 最后一轮是摘要, LLM返回的content是 [ContentBlock] ，需要用 getattr，取 type
    return "".join(cast(TextBlock, content).text for content in resp.content if getattr(content, "type") == "text") or "(no summary)"

# 统一处理下
def normalize_messages(messages: list) -> list:
    """
        # messages = [
        #   {"role": "user", "content": "你好"},
        #   {"role": "assistant", "content": [ThinkingBlock(), TextBlock("type": "text", "text": "答案")] } # 返回回答
        #   {"role": "assistant", "content": [ThinkingBlock(), ThinkingBlock("type": "tool_use", "id": "xxxxx")] } # 返回工具调用
        # ]
        # AI返回的每条消息的content不是字符串，是list[ContentBlock]，我们必须转成字符串再传给大模型
        #
        # 调用工具的结构：
        # 1、AI返回的信息 content需要处理
        # 2、Agent调用工具，返回信息需要处理为：{"role": "user", "type": "tool_result", "tool_use_id":"xxxxx", "content": "工具结果"},
        #    注意：存在工具没调用成功/没有对应工具的情况，这种也需要补一条tool_result结果，content: "(cancelled)"
        # 3、user、assistant 需要交通，如果出现连续的同一角色，合并到 content 列表汇总
    """

    cleaned = []
    for msg in messages:
        clean = {"role": msg["role"]}
        if isinstance(msg.get("content"), str):
            clean["content"] = msg["content"]
        elif isinstance(msg.get("content"), list):
            content = []
            for block in msg["content"]:
                if getattr(block, "type", None):  # sdk 返回的不是字典，而是ContentBlock类型，需要格外处理
                    temp = {"type": block.type}
                    for attr in ("id", "name", "input", "text", "thinking"):
                        temp[attr] = getattr(block, attr, None)
                    content.append(temp)
                else:
                    content.append(block)

            clean["content"] = content
        else:
            clean["content"] = msg.get("content", "")
        cleaned.append(clean)
    # Collect existing tool_result IDs
    existing_results = set()
    for msg in cleaned:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    existing_results.add(block.get("tool_use_id"))
    # Find orphaned tool_use blocks and insert placeholder results
    for msg in cleaned:
        if msg["role"] != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id") not in existing_results:
                cleaned.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": "(cancelled)"
                }]})
    # Merge consecutive same-role messages
    if not cleaned:
        return cleaned
    merged = [cleaned[0]]
    for msg in cleaned[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev = merged[-1]
            prev_c = prev["content"] if isinstance(prev["content"], list) \
                else [{"type": "text", "text": str(prev["content"])}]
            curr_c = msg["content"] if isinstance(msg["content"], list) \
                else [{"type": "text", "text": str(msg["content"])}]
            prev["content"] = prev_c + curr_c
        else:
            merged.append(msg)
    return merged

# 核心Agent Loop
def agent_loop(messages: list):
    """ 单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:

        resp = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=normalize_messages(messages),
            tools=TOOLS,
            max_tokens=8000
        )

        messages.append({"role": "assistant", "content": resp.content})

        # 不是工具调用，结束
        if resp.stop_reason != "tool_use":
            return

        # 工具调用
        results = []
        used_todo = False
        for block in resp.content:
            if block.type == "tool_use":
                block = cast(ToolUseBlock, block)  # 重新断言
                if block.name == "task":
                    # task 工具
                    desc = cast(str, block.input.get("description", "subtask"))
                    prompt = cast(str, block.input.get("prompt", ""))
                    print(f"> task: {desc}: {prompt[:80]}")
                    output = run_subagent(prompt)
                else:
                    # 其他工具
                    handler = TOOL_HANDLERS.get(block.name)
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"

                print(f"[Tool] {block.name}: {block.input}")
                print(f"[Tool Result] {output[:200]}")
                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                results.append({"type": "tool_result", "content": output, "tool_use_id": block.id})

                # 记录调用过计划工具
                if block.name == 'todo':
                    used_todo = True


        if used_todo:
            # 调用了todo工具
            TODO.state.rounds_since_update = 0
        else:
            # 没有调用就计数，然后触发reminder
            TODO.note_round_without_update()
            reminder = TODO.reminder()
            if reminder:
                # 注意力机制对开头和结尾的信息最敏感，而对中间的信息关注度最低。开头内容更不容易被噪音干扰
                results.insert(0, {"type": "text", "text": reminder})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []

    while True:
        query = input("\033[36ms01 >> \033[0m")
        if query == "exit":
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        final_text = extract_text(history[-1]["content"])
        print(final_text)


# plan测试 ：帮我规划五一推荐景点、以及景点的热门项目、美食推荐

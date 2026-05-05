import os
import subprocess
from dataclasses import dataclass

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


from pathlib import Path
from typing import cast
import anthropic
from anthropic import Anthropic
from anthropic.types import ThinkingBlock, ToolUseBlock
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),  # This is the default and can be omitted
)

MODEL = os.getenv('MODEL_ID', 'claude-opus-4-6')

# 系统提示词
SYSTEM = """
    f"You are a coding agent at {os.getcwd()}"
    "Use bash to inspect and change the workspace. Act first, then report clearly."
"""


# @dataclass
# class LoopState:
#     # 对话上下文
#     message: list
#     # agent Loop循环次数
#     turn_count: int
#     # 当次循环的原因
#     transition_reason: str|None = None


def extract_text(content: list[ThinkingBlock]|str):
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts)

# 安全路径, 防止路径跑出 WORKDIR 以外
def safe_path(p: str) -> Path:
    path = (WORKDIR/p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    return path

# bash工具
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command block"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

    output = (result.stdout + result.stderr).strip()
    return output[:5000] if output else "(no output)"

# read工具
def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"...({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:5000]
    except Exception as e:
        return f"Error: {e}"

# write工具
def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text,1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


CONCURRENCY_SAFE = {"read_file"}
CONCURRENCY_UNSAFE = {"write_file", "edit_file"}



TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")), # limit是可选参数，需要用get
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
}

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the current workspace",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
{
        "name": "read_file",
        "description": "Read file contents",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"]
        }
    },
{
        "name": "write_file",
        "description": "Write contents to file ",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }
    },
{
        "name": "edit_file",
        "description": "Replace exact content in file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"]
        }
    },

]

# 统一处理下
def normalize_messages(messages: list) -> list:
    """
        # messages = [
        #   {"role": "user", "content": "你好"},
        #   {"role": "assistant", "content": [ThinkingBlock(), TextBlock()] } # 返回回答
        #   {"role": "assistant", "content": [ThinkingBlock(), ThinkingBlock("type": "tool_use", "id": "xxxxx")] } # 返回工具调用
        # ]
        # AI返回的每条消息的content不是字符串，是list[ContentBlock]，我们必须转成字符串再传给大模型
        #
        # 调用工具的结构：
        # 1、AI返回的信息 content需要处理
        # 2、Agent调用工具，返回信息需要处理为：{"role": "user", "type": "tool_result", "tool_use_id":"xxxxx", "content": "工具结果"},
        #    注意：存在工具没调用成功/没有对应工具的情况，这种也需要补一条tool_result结果，content: "(cancelled)"
        # 3、
    """
    # results = []
    # for message in messages:
    #     item = { "role": message["role"] }
    #     if isinstance(message.get("content"), str):
    #         item["content"] = message["content"]
    #     elif isinstance(message["content"], list):
    #         item["content"] = []
    #         for block in message["content"]:
    #             if isinstance(block, dict):
    #                 item["content"].append({k:v for k,v in block.items() if not k.startswith('_') })
    #
    #     else:
    #         item["content"] = ""
    #
    #     results.append(item)
    #
    # # 如果出现LLM调用的工具不存在，这种需要补一个空的 tool_result 结果
    # existing_tool_use_id = set()
    # for message in results:
    #     if isinstance(message["content"], list):
    #         for block in message["content"]:
    #             if block.get("type") == "tool_use":
    #                 existing_tool_use_id.add(block.get("id"))
    #
    # for message in results:
    #     if isinstance(message["content"], list):
    #         for block in message["content"]:
    #             if block.get("type") == "tool_result" and block.get("id") not in existing_tool_use_id:
    #                 results.append({"role": "user", "type": "tool_result", "tool_use_id": block.get("id"), "content": "(cancelled)"})
    #
    # # 用户、大模型的信息必须交替，如果出现连续的同角色的content需要合并在一个列表里
    # merged = [results[0]] if results else []
    # for message in results[1:]:
    #     if message["role"] == merged[-1]["role"]:
    #         # 最后一个message
    #         pre = merged[-1]["content"]
    #         pre_content = pre["content"] if isinstance(pre["content"], list) else [{"type": "text", "text": pre["content"]}]
    #         cur_content = message["content"] if isinstance(message["content"], list) else [{"type": "text", "text": message["content"]}]
    #         pre["content"] = pre_content + cur_content
    #     else :
    #         merged.append(message)
    #
    # return merged
    cleaned = []
    for msg in messages:
        clean = {"role": msg["role"]}
        if isinstance(msg.get("content"), str):
            clean["content"] = msg["content"]
        elif isinstance(msg.get("content"), list):
            clean["content"] = [
                {k: v for k, v in block.items()
                 if not k.startswith("_")}
                for block in msg["content"]
                if isinstance(block, dict)
            ]
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
                cleaned.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block["id"],
                     "content": "(cancelled)"}
                ]})
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

def agent_loop(messages: list):
    """ 单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:
        handledMsg = normalize_messages(messages)
        print("[format message]",handledMsg)
        resp = cast(anthropic.types.Message, client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=handledMsg,
            tools=TOOLS,
            max_tokens=8000
        ))

        messages.append({"role": "assistant", "content": resp.content})

        # 不是工具调用，结束
        if resp.stop_reason != "tool_use":
            return

        # 工具调用
        results = []
        for block in resp.content:
            if block.type == 'tool_use':
                block = cast(ToolUseBlock, block) # 重新断言
                print(f"[Tool] {block.name}")
                handler = TOOL_HANDLERS.get(block.name)
                if handler:
                    output = handler(**block.input)
                else:
                    output =f"Unknown tool: {block.name}"
                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                results.append({"type": "tool_result", "content": output, "tool_use_id": block.id})

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

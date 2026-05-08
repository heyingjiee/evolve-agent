import re
from fnmatch import fnmatch
import json
import os
import time
from importlib.resources import read_text
from pathlib import Path
from tools import CompactState

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


import tools
from typing import cast
from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),  # This is the default and can be omitted
)

# 运行目录
WORKDIR = Path.cwd()

# 模型
MODEL = os.getenv('MODEL_ID', 'claude-opus-4-6')

# Skill目录
SKILLS_DIR = WORKDIR / "skills"

# Skill仓库
SKILL_REGISTRY = tools.SkillRegistry(SKILLS_DIR)

# 系统提示词
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use bash to inspect and change the workspace. Act first, then report clearly.
Skills available:
{SKILL_REGISTRY.describe_available()}
"""

# 子Agent系统提示词
SUB_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings"

# 任务管理器
reminder_interval = int(os.getenv('REMINDER_INTERVAL', "3"))
TODO = tools.TodoManager(reminder_interval)

def collect_tool_result_blocks(messages: list):
    """ 从message中过滤提取工具返回信息 """
    blocks = []
    for msg in messages:
        if msg["role"] == "user":
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    blocks.append(block)
    return blocks

def micro_compact(messages: list) -> list:
    """
        压缩工具返回内容
        1. 提取工具返回的信息 collect_tool_result_blocks

     """
    tool_results = collect_tool_result_blocks(messages)
    keep_recent_tool_results = int(os.getenv("KEEP_RECENT_TOOL_RESULTS", "3"))
    if len(tool_results) < keep_recent_tool_results:
        # 不压缩工具返回结果
        return messages

    # 压缩
    for block in tool_results[:keep_recent_tool_results]:
        content = block.get("content", "")
        if not isinstance(content, str) or len(content) <= 120:
            continue
        block["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
    return messages


def write_transcript(messages: list) -> Path:
    """ 把message信息写入文件，返回文件路径 """
    transcript_dir = Path.cwd() / os.getenv("TRANSCRIPT_DIR", "./transcripts")
    transcript_dir.mkdir(parents=True, exist_ok=True)  # 保证目录一定有，后面才能写入
    store_path = transcript_dir / f"transcript_{int(time.time())}.json"

    # 没有一口气写入 messages，是出于内存考虑，防止内存溢出
    with store_path.open("w") as handler:
        for message in messages:
            handler.write(json.dumps(message, default=str))
    return store_path

def summarize_history(messages: list) -> str:
    """调用大模型总结摘要"""
    conversation = json.dumps(messages, default=str)
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. The current goal\n"
        "2. Important findings and decisions\n"
        "3. Files read or changed\n"
        "4. Remaining work\n"
        "5. User constraints and preferences\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )
    messages: list = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt}
        ]
    }]
    resp = client.messages.create(
        model = MODEL,
        messages = messages,
        max_tokens = 2000
    )

    return resp.content[0].text.strip()

def compact_history(messages: list, state: CompactState, focus: str | None = None, ):
    """
        压缩历史记录
        1、把messages写入文件  write_transcript
        2、生成摘要 summarize_history
        3、更新state状态信息
        4、返回压缩后的一条message
     """
    # 历史写入文件
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages)
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    else:
        recent_lines = "\n".join(f"- {path}" for path in state.recent_files)
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"

    state.has_compacted = True
    state.last_summary =summary
    return [{
        "role": "user",
        "content": [{
            "type": "text",
            "text":  (
                    "This conversation was compacted so work can continue.\n"
                    f"{summary}"
                )
            }]
    }]

compact_schema = [{
    "name": "compact",
    "description": "Summarize earlier conversation so work can continue in a smaller context",
    "input_schema": {
        "type": "object",
        "properties": {
            "focus": {"type": "string"}
        }
    }
}]

# TODO 工具是否支持同步，目前工具调用不能同步
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


# 权限模式
MODES = ["default", "plan", "auto"]
# 默认规则
DEFAULT_RULES = [
    # 拒绝执行的规则
    {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
    {"tool": "bash", "content": "sudo *", "behavior": "deny"},
    # 允许执行的规则
    {"tool": "read_file", "path": "*", "behavior": "allow"},
]
# plan模式：允许读，拒绝写
# 读工具
READ_ONLY_TOOL = ['read_file', 'bash_readonly'] # TODO 这个bash_readonly怎么实现？
# 写工具
WRITE_TOOLS = ['write_file', 'edit_file', 'bash']



class BashSecurityValidator:
    # 攻击bash脚本的正则
    VALIDATORS = [
        ("shell_metachar", r"[;&|`$]"),  # shell metacharacters
        ("sudo", r"\bsudo\b"),  # privilege escalation
        ("rm_rf", r"\brm\s+(-[a-zA-Z]*)?r"),  # recursive delete
        ("cmd_substitution", r"\$\("),  # command substitution
        ("ifs_injection", r"\bIFS\s*="),  # IFS manipulation
    ]

    def validate(self, command: str) -> list:
        """ 检查 bash命令 是否命中危险命令正则 """
        failures = []
        for name, pattern in self.VALIDATORS:
            if re.search(pattern, command):
                failures.append((name, pattern))
        return failures

    def is_safe(self, command: str) -> bool:
        """ 命令是否安全 """
        return len(self.validate(command)) == 0
    def describe_failures(self, command: str) -> str:
        """ 失败信息 """
        failures = self.validate(command)
        if not failures:
            return "No issues detected"
        parts = [f"{name} (pattern: {pattern})" for name, pattern in failures]
        return "Security flags:" + ",".join(parts)

bash_validator = BashSecurityValidator()

class PermissionManager:
    def __init__(self, mode: str = "default", rules: list = None):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}. Choose from {MODES}")
        self.mode = mode
        # 初始化内部规则，ask 权限如果用户选择 always 则会追加进去
        self.rules = rules or DEFAULT_RULES
        # 连续拒绝次数
        self.consecutive_denials = 0
        # 最大拒绝次数
        self.max_consecutive_denials = 3

    def check(self, tool_name: str, tool_input: dict) -> dict:
        """
            检查工具+入参是否有执行权限
            返参格式： {"behavior": "deny", "reason": "xxx"}
                     {"behavior": "allow", "reason": "xxx"}
                     {"behavior": "ask", "reason": "xxx"}
            这个reason是用来加到上下文对话中，作为工具返回的结果
        """
        # bash 权限太大，需要单独处理
        if tool_name == "bash":
            command = tool_input.get("command", "")
            failures = bash_validator.validate(command)
            if failures:
                # 如果是 "sudo", "rm_rf" 拒绝
                server_hit = [f for f in failures if f[0] in {"sudo", "rm_rf"}]
                if server_hit:
                    desc = bash_validator.describe_failures(command)
                    return {"behavior": "deny", "reason": f"Bash validator: {desc}"}
            # 其他清空询问
            desc = bash_validator.describe_failures(command)
            return {"behavior": "ask","reason": f"Bash validator flagged: {desc}"}

        # 查下内部规则如果允许，就放行
        for rule in self.rules:
            if rule["behavior"] == "allow" and self._matches(rule, tool_name, tool_input):
                self.consecutive_denials = 0
                return {"behavior": "allow", "reason": f"Matched allow rule: {rule}"}

        # mode=plan 的校验规则： 允许读操作，但是拒绝所有写操作
        if self.mode == "plan":
            if tool_name in WRITE_TOOLS:
                return {"behavior": "deny", "reason":"Plan mode: write operations are blocked"}
            return {"behavior": "allow", "reason":"Plan mode: read-only allowed"}

        # mode=auto 的校验规则：在rules中只查找如果允许，就允许
        if self.mode == "auto":
            for rule in self.rules:
                if self._matches(rule, tool_name, tool_input):
                    self.consecutive_denials = 0
                    return {"behavior": "allow", "reason": f"Matched allow rule: {rule}"}

        # 询问用户
        return {"behavior": "ask", "reason": f"No rule matched for {tool_name}, asking user"}

    def ask_user(self, tool_name: str, tool_input: dict) -> bool:
        """ 询问用户是否授权，授权返回True """
        preview = json.dumps(tool_input, ensure_ascii=False)[:200]
        print(f"\n [Permission] {tool_name}: {preview}")
        try:
            answer = input(" Allow? (y/n/always): ").strip().lower()
        except (KeyboardInterrupt,EOFError):
            return False

        # 永久允许，追加到内部规则
        if answer == "always":
            self.rules.append({"tool": tool_name, "content": "*", "behavior": "allow"},)
            self.consecutive_denials = 0
            return True
        # 允许
        if answer in ("y", "yes"):
            self.consecutive_denials = 0
            return True

        # 拒绝
        self.consecutive_denials += 1
        if self.consecutive_denials >= self.max_consecutive_denials:
            print(f" [{self.consecutive_denials}] consecutive denials -- consider switch to plan mode")
        return False

    def _matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
        """
            工具+参数是否符合规则
            rule:
                {"tool": "bash", "content": "rm -rf /", "behavior": "deny"},
                {"tool": "bash", "path": "*", "behavior": "deny"},
            rule有两种形式 content、path
        """
        if rule.get("tool") == "*":
            return True

        if rule.get("tool") == tool_name:
            # path
            if "path" in rule:
                return fnmatch(tool_input.get("path",""), rule["path"])
             # content
            if "content" in rule:
                return fnmatch(tool_input.get("command",""), rule["content"])
        return False

# TODO 加入到入口，没有就input要求用户确认，确认后新建配置文件，取消直接结束
def is_workspace_trusted(workspace: Path) -> bool:
    """ 检查是否是受信人工作区 """
    ws = workspace or WORKDIR
    return (ws / ".claude/.claude_trusted").exists()

# 工具Schema
TOOLS = [tools.bash_schema, tools.read_schema, tools.write_schema, tools.edit_schema, tools.todo_schema] + task_schema + compact_schema
CHILD_TOOLS = [tools.bash_schema, tools.read_schema, tools.write_schema, tools.edit_schema]

# TDOO: 这里是全量的工具，没有做Agent、SubAgent的区别。目前只是在传入的Schema上做了区分，建议后续增加判断
def execute_tool(block, state: CompactState) -> str:
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
    if tool_name == 'todo':
       return TODO.update(argv["items"])
    if tool_name == 'task':
       desc = cast(str, argv.get("description", "subtask"))
       prompt = cast(str, argv.get("prompt", ""))
       print(f"[Subagent]: {desc}: {prompt[:80]}")
       return run_subagent(prompt)
    if tool_name == 'load_skill':
       return SKILL_REGISTRY.load_full_text(argv["name"])
    if tool_name == 'compact':
       return "Compacting conversation..." # 真正的压缩不在这里，在agent loop
    return f"Unknown tool: {tool_name}"

# 子Agent
def run_subagent(prompt: str) -> str:
    sub_message:list = [{"role": "user", "content": [{ "type": "text", "text": prompt}]}]
    compact_state = CompactState()
    # 最大30轮循环
    for _ in range(30):
        resp = client.messages.create(
            model=MODEL,
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
                print(f"[Tool] {tool_name}: {tool_argv}")
                print(f"[Tool Result] {output[:200]}")
                # 工具的调用结果，要和tool_use_id关联上，llm才知道结果是哪次工具调用返回的
                results.append({"type": "tool_result", "content": output, "tool_use_id": tool_use_id})

        sub_message.append({"role": "user", "content": results})
    # 最后一轮是摘要, LLM返回的content是 [ContentBlock] ，需要用 getattr，取 type
    return "".join(block["text"] for block in contents if block["type"] == "text") or "(no summary)"


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
def agent_loop(messages: list, state: CompactState, perms: PermissionManager):
    """ 单词循环， True会进入下一轮循环 ，False结束循环"""
    while True:
        # 规范化参数
        messages[:] = normalize_messages(messages) # 这是原地修改

        # 压缩工具返回结果
        messages[:] = micro_compact(messages)

        # 超过上限压缩上下文
        if len(str(messages)) > int(os.getenv("CONTEXT_LIMIT", "50000")):
            print("[auto compact conversation history]")
            messages[:] = compact_history(messages, state)

        # 调用模型
        resp = client.messages.create(
            model=MODEL,
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
                        print(f"[Tool Result] {output[:200]}")
                    else:
                        output = f"Permission denied by user for: {tool_name}"
                        print(f"  [USER DENIED] {block.name}")
                else:
                    # 允许
                    output = execute_tool(block, state) # 执行工具
                    print(f"[Tool Result] {output[:200]}")

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
            TODO.state.rounds_since_update = 0
        else:
            # 没有调用就计数，然后触发reminder
            TODO.note_round_without_update()
            reminder = TODO.reminder()
            if reminder:
                # 注意力机制对开头和结尾的信息最敏感，而对中间的信息关注度最低。开头内容更不容易被噪音干扰
                tool_contents.insert(0, {"type": "text", "text": reminder})

        # 调用了压缩工具
        if manual_compact:
            print("[manual compact]")
            messages[:] = compact_history(messages, state, focus=compact_focus)

        messages.append({"role": "user", "content": tool_contents})


if __name__ == "__main__":
    # 对话历史
    history = []
    # 压缩历史
    compact_state = CompactState()


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
        if query.strip().lower() in ("exit", "q") :
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
        agent_loop(history, compact_state, perms)

        final_text = "".join([block["text"] for block in history[-1]["content"] if block["type"] == "text"])
        print(final_text)



# 计划测试: 帮我规划五一推荐景点、以及景点的热门项目、美食推荐

# subAgent测试: 两个子agent分别统计四川、山东的菜系特征、名菜、文化与饮食习惯的关系，主Agent汇总生成 food.md

# 压缩read_file、bash返回值、自动压缩上下文： 读取 /Users/heyingjie/Downloads/简历.pdf 分析如何改进来提高简历初筛率
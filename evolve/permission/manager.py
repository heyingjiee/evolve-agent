import json
import re
from fnmatch import fnmatch

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
READ_ONLY_TOOL = ['read_file']
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
        print(f"[Permission]\n{tool_name}: {preview}")
        try:
            answer = input("Allow? (y/n/always): ").strip().lower()
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

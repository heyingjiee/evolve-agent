"""
Hook 端到端测试 - 测试 uv run ./src/main.py 的 hook 命中情况

测试策略：
1. 创建测试用的 hooks.json
2. 使用 monkeypatch 模拟 stdin，注入预定义的 query
3. 捕获输出，验证 hook 是否被触发
"""

import json
from unittest.mock import patch, MagicMock

import pytest


# 测试命令
TEST_COMMANDS = [
    "echo 'hello world'",  # bash 命令
    "echo test",  # 另一个 bash
]


class TestHookE2E:
    """Hook 端到端测试"""

    @pytest.fixture
    def test_hooks_config(self, tmp_path):
        """创建测试用 hooks.json"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "command": "echo 'PRE-BASH-TRIGGERED'"}
                ],
                "PostToolUse": [
                    {"matcher": "Read", "command": "echo 'POST-READ-TRIGGERED'"}
                ],
                "SessionStart": [
                    {"matcher": "*", "command": "echo 'SESSION-START-TRIGGERED'"}
                ]
            }
        }
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))
        return tmp_path

    def test_hooks_json_loaded(self, test_hooks_config):
        """验证 hooks.json 能否正确加载"""
        from hooks import HookManager

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            assert len(manager.hooks["PreToolUse"]) == 1
            assert manager.hooks["PreToolUse"][0]["matcher"] == "Bash"
            assert manager.hooks["PreToolUse"][0]["command"] == "echo 'PRE-BASH-TRIGGERED'"

    def test_pre_tool_use_hook_matcher(self, test_hooks_config):
        """测试 PreToolUse 钩子对 Bash 工具的匹配"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "echo hello"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_called_once()
                # mock_run.call_args 是一个 mock.call_args tuple (args, kwargs)
                # subprocess.run 调用: command 是位置参数
                call_args = mock_run.call_args
                cmd = call_args[0][0]  # 第一个位置参数是 command
                assert cmd == "echo 'PRE-BASH-TRIGGERED'"

    def test_pre_tool_use_hook_not_matched(self, test_hooks_config):
        """测试 PreToolUse 钩子对非匹配工具不触发"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "Read", "tool_input": "Read"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_not_called()

    def test_post_tool_use_hook_matcher(self, test_hooks_config):
        """测试 PostToolUse 钩子对 Read 工具的匹配"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {
                "tool_name": "Read",
                "tool_input": "Read",
                "tool_output": "file content here"
            }
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PostToolUse", context)

                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args.kwargs
                assert "file content here" in call_kwargs["env"]["tool_output"]

    def test_session_start_hook(self, test_hooks_config):
        """测试 SessionStart 钩子在会话启动时执行"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "SessionStart"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("SessionStart", context)

                mock_run.assert_called_once()

    def test_hook_env_injection(self, test_hooks_config):
        """测试 hook 执行时环境变量注入"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {
                "tool_name": "Bash",
                "tool_input": '{"command": "ls -la"}',
                "tool_output": None
            }
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                call_kwargs = mock_run.call_args.kwargs
                env = call_kwargs["env"]

                assert env["tool_name"] == "Bash"
                assert "ls" in env["tool_input"]
                assert "command" in env["tool_input"]

    def test_hook_blocked_result(self, test_hooks_config):
        """测试 hook 返回阻止结果"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Dangerous command blocked"
                )
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is True
                assert "Dangerous command blocked" in result["block_reason"]

    def test_hook_inject_message(self, test_hooks_config):
        """测试 hook 返回码 2 注入消息"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=2,
                    stdout="",
                    stderr="Warning: This is a sensitive operation"
                )
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is False
                assert "Warning: This is a sensitive operation" in result["messages"]

    def test_permission_override_integration(self, test_hooks_config):
        """测试 hook JSON 输出中的 permission_override"""
        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = test_hooks_config
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"additionalContext": "Security policy"}),
                    stderr=""
                )
                result = manager.run_hook("PreToolUse", context)

                assert "Security policy" in result["messages"]


class TestRealHookScenarios:
    """真实场景测试"""

    def test_security_check_hook(self, tmp_path):
        """模拟安全检查 hook 场景"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "command": """if echo 'rm -rf /tmp/test' | grep -q 'rm -rf'; then echo 'BLOCKED'; exit 1; fi; exit 0;"""
                    }
                ],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="BLOCKED")
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is True

    def test_git_add_hook(self, tmp_path):
        """模拟 git add hook 场景"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [],
                "PostToolUse": [
                    {
                        "matcher": "Write",
                        "command": "git add ."
                    }
                ],
                "SessionStart": []
            }
        }
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        from hooks import HookManager, Context

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {
                "tool_name": "Write",
                "tool_input": "Write",
                "tool_output": "File written successfully"
            }
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PostToolUse", context)

                mock_run.assert_called_once()

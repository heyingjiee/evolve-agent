import json
from unittest.mock import MagicMock, patch

from hooks import HookManager, Context


class TestHookManagerInit:
    """HookManager 初始化测试"""

    def test_load_hooks_from_file(self, tmp_path):
        """测试从 hooks.json 加载钩子配置"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "command": "echo pre"}
                ],
                "PostToolUse": [
                    {"matcher": "Write", "command": "git add ."}
                ],
                "SessionStart": [
                    {"matcher": "*", "command": "echo start"}
                ]
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            assert len(manager.hooks["PreToolUse"]) == 1
            assert len(manager.hooks["PostToolUse"]) == 1
            assert len(manager.hooks["SessionStart"]) == 1

    def test_no_hooks_file(self, tmp_path):
        """测试没有 hooks.json 文件时初始化成功"""
        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            assert manager.hooks["PreToolUse"] == []
            assert manager.hooks["PostToolUse"] == []
            assert manager.hooks["SessionStart"] == []

    def test_empty_hooks_config(self, tmp_path):
        """测试空的 hooks 配置"""
        hooks_config = {"hooks": {}}
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            assert manager.hooks["PreToolUse"] == []
            assert manager.hooks["PostToolUse"] == []
            assert manager.hooks["SessionStart"] == []


class TestRunHook:
    """run_hook 方法测试"""

    def test_no_matching_hooks(self, tmp_path):
        """测试没有匹配的钩子时返回默认结果"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "command": "echo pre"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Write"}
            result = manager.run_hook("PreToolUse", context)

            assert result["blocked"] is False
            assert result["messages"] == []

    def test_wildcard_matcher_runs_for_all_tools(self, tmp_path):
        """测试通配符 matcher 匹配所有工具"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "echo wildcard"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Write", "tool_input": "test input"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_called_once()

    def test_exact_matcher_only_runs_for_matched_tool(self, tmp_path):
        """测试精确 matcher 只对匹配的工具生效"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "command": "echo bash_only"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Write", "tool_input": "Write"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_not_called()

    def test_tool_name_matcher_runs_for_matched_tool(self, tmp_path):
        """测试 tool_name 匹配时执行钩子"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "command": "echo bash"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_called_once()


class TestHookResultProcessing:
    """钩子执行结果处理测试"""

    def test_returncode_0_allows_execution(self, tmp_path):
        """测试返回码 0 放行"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "echo ok"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is False

    def test_returncode_1_blocks_execution(self, tmp_path):
        """测试返回码 1 阻止执行"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "exit 1"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Blocked by hook")
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is True
                assert result["block_reason"] == "Blocked by hook"

    def test_returncode_2_injects_message(self, tmp_path):
        """测试返回码 2 注入信息"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "exit 2"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="Warning: sensitive operation")
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is False
                assert "Warning: sensitive operation" in result["messages"]

    def test_json_output_with_updated_input(self, tmp_path):
        """测试 JSON 输出更新工具入参"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "echo json"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "original input"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"updatedInput": "modified input"}),
                    stderr=""
                )
                manager.run_hook("PreToolUse", context)

                assert context["tool_input"] == "modified input"

    def test_json_output_with_additional_context(self, tmp_path):
        """测试 JSON 输出添加额外上下文信息"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "echo json"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"additionalContext": "注意：这是一个危险操作"}),
                    stderr=""
                )
                result = manager.run_hook("PreToolUse", context)

                assert "注意：这是一个危险操作" in result["messages"]

    def test_string_output_no_json_decode(self, tmp_path):
        """测试字符串输出不进行 JSON 解析"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "echo plain text"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "original"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="plain text output", stderr="")
                result = manager.run_hook("PreToolUse", context)

                assert context["tool_input"] == "original"
                assert result["messages"] == []


class TestContextInjection:
    """上下文注入环境变量测试"""

    def test_env_variables_injected(self, tmp_path):
        """测试上下文注入到环境变量"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "command": "echo $tool_name"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": '{"command": "ls"}', "tool_output": "file1\nfile2"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PreToolUse", context)

                mock_run.assert_called()
                call_kwargs = mock_run.call_args.kwargs
                env = call_kwargs["env"]

                assert env["tool_name"] == "Bash"
                assert "command" in env["tool_input"]
                assert "ls" in env["tool_input"]
                assert "file1" in env["tool_output"]


class TestTimeout:
    """超时处理测试"""

    def test_timeout_handling(self, tmp_path):
        """测试命令执行超时处理"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [{"matcher": "*", "command": "sleep 100"}],
                "PostToolUse": [],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "Bash", "tool_input": "Bash"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.side_effect = Exception("Timeout")
                result = manager.run_hook("PreToolUse", context)

                assert result["blocked"] is False


class TestToolOutputContext:
    """PostToolUse 工具输出上下文测试"""

    def test_post_tool_use_has_tool_output(self, tmp_path):
        """测试 PostToolUse 钩子可以访问工具输出"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [],
                "PostToolUse": [{"matcher": "*", "command": "echo output"}],
                "SessionStart": []
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {
                "tool_name": "Read",
                "tool_input": "Read",
                "tool_output": "file content here"
            }
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("PostToolUse", context)

                mock_run.assert_called()
                call_kwargs = mock_run.call_args.kwargs
                env = call_kwargs["env"]
                assert "file content here" in env["tool_output"]


class TestSessionStartHook:
    """SessionStart 钩子测试"""

    def test_session_start_hook_executes(self, tmp_path):
        """测试 SessionStart 钩子执行"""
        hooks_config = {
            "hooks": {
                "PreToolUse": [],
                "PostToolUse": [],
                "SessionStart": [{"matcher": "*", "command": "echo session started"}]
            }
        }
        evolve_dir = tmp_path / ".evolve"
        evolve_dir.mkdir()
        hooks_file = evolve_dir / "hooks.json"
        hooks_file.write_text(json.dumps(hooks_config))

        with patch("hooks.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            manager = HookManager()

            context: Context = {"tool_name": "SessionStart"}
            with patch("hooks.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                manager.run_hook("SessionStart", context)

                mock_run.assert_called_once()
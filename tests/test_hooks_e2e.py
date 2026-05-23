import json
from unittest.mock import MagicMock, patch

import pytest

from evolve.hooks import Context, HookManager


@pytest.fixture
def workspace_with_hooks(tmp_path):
    """创建带有 hooks 配置的临时工作区。"""
    evolve_dir = tmp_path / ".evolve"
    evolve_dir.mkdir()
    (evolve_dir / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "command": "echo 'PRE-BASH-TRIGGERED'"}],
                    "PostToolUse": [{"matcher": "Read", "command": "echo 'POST-READ-TRIGGERED'"}],
                    "SessionStart": [{"matcher": "*", "command": "echo 'SESSION-START-TRIGGERED'"}],
                }
            }
        )
    )
    return tmp_path


class TestHookE2E:
    def test_settings_json_loaded(self, workspace_with_hooks):
        """测试 settings.json 中的 hooks 能被正确加载。"""
        manager = HookManager(workspace_with_hooks)
        assert manager.hooks["PreToolUse"][0]["matcher"] == "Bash"
        assert manager.hooks["PostToolUse"][0]["matcher"] == "Read"

    def test_pre_tool_use_hook_matcher(self, workspace_with_hooks):
        """测试 PreToolUse 的匹配和执行。"""
        manager = HookManager(workspace_with_hooks)
        context: Context = {"tool_name": "Bash", "tool_input": "echo hello"}

        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            manager.run_hook("PreToolUse", context)

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == "echo 'PRE-BASH-TRIGGERED'"

    def test_post_tool_use_hook_receives_tool_output(self, workspace_with_hooks):
        """测试 PostToolUse 能拿到工具输出。"""
        manager = HookManager(workspace_with_hooks)
        context: Context = {"tool_name": "Read", "tool_input": "Read", "tool_output": "file content here"}

        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            manager.run_hook("PostToolUse", context)

        assert "file content here" in mock_run.call_args.kwargs["env"]["tool_output"]

    def test_session_start_hook_runs(self, workspace_with_hooks):
        """测试 SessionStart hook 可以正常执行。"""
        manager = HookManager(workspace_with_hooks)
        context: Context = {"tool_name": "SessionStart"}

        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            manager.run_hook("SessionStart", context)

        mock_run.assert_called_once()

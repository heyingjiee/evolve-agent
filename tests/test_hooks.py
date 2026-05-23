import json
from unittest.mock import MagicMock, patch

from evolve.hooks import Context, HookManager


def write_settings(tmp_path, hooks: dict) -> None:
    """写入测试用的 settings.json。"""
    evolve_dir = tmp_path / ".evolve"
    evolve_dir.mkdir()
    (evolve_dir / "settings.json").write_text(json.dumps({"hooks": hooks}))


class TestHookManagerInit:
    def test_load_hooks_from_settings(self, tmp_path):
        """测试从 settings.json 读取 hooks 配置。"""
        write_settings(
            tmp_path,
            {
                "PreToolUse": [{"matcher": "Bash", "command": "echo pre"}],
                "PostToolUse": [{"matcher": "Write", "command": "git add ."}],
                "SessionStart": [{"matcher": "*", "command": "echo start"}],
            },
        )

        manager = HookManager(tmp_path)

        assert len(manager.hooks["PreToolUse"]) == 1
        assert len(manager.hooks["PostToolUse"]) == 1
        assert len(manager.hooks["SessionStart"]) == 1

    def test_missing_settings_file_defaults_to_empty_hooks(self, tmp_path):
        """测试缺少 settings.json 时返回空 hooks。"""
        manager = HookManager(tmp_path)
        assert manager.hooks["PreToolUse"] == []
        assert manager.hooks["PostToolUse"] == []
        assert manager.hooks["SessionStart"] == []


class TestRunHook:
    def test_non_matching_hook_is_skipped(self, tmp_path):
        """测试未匹配的 hook 会被跳过。"""
        write_settings(tmp_path, {"PreToolUse": [{"matcher": "Bash", "command": "echo pre"}]})
        manager = HookManager(tmp_path)

        context: Context = {"tool_name": "Write"}
        result = manager.run_hook("PreToolUse", context)

        assert result["blocked"] is False
        assert result["messages"] == []

    def test_matching_hook_runs_subprocess(self, tmp_path):
        """测试匹配成功时会调用子进程执行 hook。"""
        write_settings(tmp_path, {"PreToolUse": [{"matcher": "*", "command": "echo pre"}]})
        manager = HookManager(tmp_path)

        context: Context = {"tool_name": "Write", "tool_input": {"path": "a.txt"}}
        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            manager.run_hook("PreToolUse", context)

        mock_run.assert_called_once()

    def test_returncode_1_blocks(self, tmp_path):
        """测试返回码 1 会阻止工具继续执行。"""
        write_settings(tmp_path, {"PreToolUse": [{"matcher": "*", "command": "exit 1"}]})
        manager = HookManager(tmp_path)

        context: Context = {"tool_name": "Bash", "tool_input": "echo test"}
        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Blocked by hook")
            result = manager.run_hook("PreToolUse", context)

        assert result["blocked"] is True
        assert result["block_reason"] == "Blocked by hook"

    def test_returncode_2_injects_message(self, tmp_path):
        """测试返回码 2 会注入提示信息。"""
        write_settings(tmp_path, {"PreToolUse": [{"matcher": "*", "command": "warn"}]})
        manager = HookManager(tmp_path)

        context: Context = {"tool_name": "Bash", "tool_input": "echo test"}
        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="Careful")
            result = manager.run_hook("PreToolUse", context)

        assert result["blocked"] is False
        assert result["messages"] == ["Careful"]

    def test_json_stdout_can_update_input_and_messages(self, tmp_path):
        """测试 hook 的 JSON 输出可以改写输入并追加提示。"""
        write_settings(tmp_path, {"PreToolUse": [{"matcher": "*", "command": "rewrite"}]})
        manager = HookManager(tmp_path)

        context: Context = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        with patch("evolve.hooks.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "updatedInput": {"command": "pwd"},
                        "additionalContext": "Use pwd instead",
                    }
                ),
                stderr="",
            )
            result = manager.run_hook("PreToolUse", context)

        assert context["tool_input"] == {"command": "pwd"}
        assert result["messages"] == ["Use pwd instead"]

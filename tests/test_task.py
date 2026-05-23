from pathlib import Path
from unittest.mock import MagicMock, patch


class TestExecuteTool:
    def test_execute_bash(self, tmp_path):
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_bash.return_value = "output"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {"name": "bash", "input": {"command": "echo hello"}, "id": "tool_1"}
            execute_tool(block, CompactState(), tmp_path, MagicMock())
            mock_tools.run_bash.assert_called_once_with("echo hello", "tool_1", tmp_path)

    def test_execute_read_file(self, tmp_path):
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_read.return_value = "file content"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {"name": "read_file", "input": {"path": "a.txt"}, "id": "tool_2"}
            execute_tool(block, CompactState(), tmp_path, MagicMock())
            mock_tools.run_read.assert_called_once()

    def test_execute_write_file(self, tmp_path):
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_write.return_value = "OK"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {"name": "write_file", "input": {"path": "a.txt", "content": "hello"}, "id": "tool_3"}
            execute_tool(block, CompactState(), tmp_path, MagicMock())
            mock_tools.run_write.assert_called_once_with("a.txt", "hello", tmp_path)

    def test_execute_edit_file(self, tmp_path):
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_edit.return_value = "OK"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {"name": "edit_file", "input": {"path": "a.txt", "old_text": "a", "new_text": "b"}, "id": "tool_4"}
            execute_tool(block, CompactState(), tmp_path, MagicMock())
            mock_tools.run_edit.assert_called_once_with("a.txt", "a", "b", tmp_path)

    def test_execute_load_skill(self, tmp_path):
        from evolve.agents.task import execute_tool
        from evolve.tools import CompactState

        registry = MagicMock()
        registry.load_full_text.return_value = "<skill>test</skill>"
        block = {"name": "load_skill", "input": {"name": "test_skill"}, "id": "tool_5"}
        result = execute_tool(block, CompactState(), tmp_path, registry)
        registry.load_full_text.assert_called_once_with("test_skill")
        assert result == "<skill>test</skill>"

    def test_execute_compact(self, tmp_path):
        from evolve.agents.task import execute_tool
        from evolve.tools import CompactState

        result = execute_tool({"name": "compact", "input": {}, "id": "tool_6"}, CompactState(), tmp_path, MagicMock())
        assert "Compacting" in result

    def test_execute_unknown_tool(self, tmp_path):
        from evolve.agents.task import execute_tool
        from evolve.tools import CompactState

        result = execute_tool({"name": "unknown_tool", "input": {}, "id": "tool_7"}, CompactState(), tmp_path, MagicMock())
        assert "Unknown tool" in result


class TestRunTaskSubagent:
    def test_subagent_no_tool_call(self, tmp_path):
        from evolve.agents.task import run_task_subagent

        mock_text_block = MagicMock()
        mock_text_block.to_dict.return_value = {"type": "text", "text": "这是摘要内容"}
        client = MagicMock()
        client.messages.create.return_value = MagicMock(stop_reason="end_turn", content=[mock_text_block])
        result = run_task_subagent("帮我完成任务", workspace=tmp_path, client=client, model="test-model", skill_registry=MagicMock())
        assert result == "这是摘要内容"

    def test_subagent_single_tool_call(self, tmp_path):
        from evolve.agents.task import run_task_subagent

        mock_tool_block = MagicMock()
        mock_tool_block.to_dict.return_value = {"type": "tool_use", "name": "bash", "input": {"command": "ls"}, "id": "call_1"}
        tool_response = MagicMock(stop_reason="tool_use", content=[mock_tool_block])
        mock_text_block = MagicMock()
        mock_text_block.to_dict.return_value = {"type": "text", "text": "任务完成"}
        summary_response = MagicMock(stop_reason="end_turn", content=[mock_text_block])
        client = MagicMock()
        client.messages.create.side_effect = [tool_response, summary_response]

        with patch("evolve.agents.task.execute_tool") as mock_exec:
            mock_exec.return_value = "ls output"
            result = run_task_subagent("查看文件", workspace=tmp_path, client=client, model="test-model", skill_registry=MagicMock())
            assert result == "任务完成"
            mock_exec.assert_called_once()

    def test_subagent_no_text_block(self, tmp_path):
        from evolve.agents.task import run_task_subagent

        mock_block = MagicMock()
        mock_block.to_dict.return_value = {"type": "image"}
        client = MagicMock()
        client.messages.create.return_value = MagicMock(stop_reason="end_turn", content=[mock_block])
        result = run_task_subagent("任务", workspace=tmp_path, client=client, model="test-model", skill_registry=MagicMock())
        assert "(no summary)" in result

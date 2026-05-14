from unittest.mock import MagicMock, patch


class TestExecuteTool:
    """execute_tool 工具执行测试 - 完全确定"""

    def test_execute_bash(self):
        """测试 bash 工具执行"""
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_bash.return_value = "output"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {
                "name": "bash",
                "input": {"command": "echo hello"},
                "id": "tool_1"
            }
            state = CompactState()
            execute_tool(block, state)

            mock_tools.run_bash.assert_called_once_with("echo hello", "tool_1")

    def test_execute_read_file(self, tmp_path):
        """测试 read_file 工具执行"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")

        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_read.return_value = "file content"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {
                "name": "read_file",
                "input": {"path": str(test_file)},
                "id": "tool_2"
            }
            state = CompactState()
            execute_tool(block, state)

            mock_tools.run_read.assert_called_once()

    def test_execute_write_file(self):
        """测试 write_file 工具执行"""
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_write.return_value = "OK"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {
                "name": "write_file",
                "input": {"path": "/tmp/test.txt", "content": "hello"},
                "id": "tool_3"
            }
            state = CompactState()
            execute_tool(block, state)

            mock_tools.run_write.assert_called_once_with("/tmp/test.txt", "hello")

    def test_execute_edit_file(self):
        """测试 edit_file 工具执行"""
        with patch("evolve.agents.task.tools") as mock_tools:
            mock_tools.run_edit.return_value = "OK"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {
                "name": "edit_file",
                "input": {"path": "/tmp/test.txt", "old_text": "a", "new_text": "b"},
                "id": "tool_4"
            }
            state = CompactState()
            execute_tool(block, state)

            mock_tools.run_edit.assert_called_once_with("/tmp/test.txt", "a", "b")

    def test_execute_load_skill(self):
        """测试 load_skill 工具执行"""
        with patch("evolve.agents.task.SKILL_REGISTRY") as mock_registry:
            mock_registry.load_full_text.return_value = "<skill>test</skill>"
            from evolve.agents.task import execute_tool
            from evolve.tools import CompactState

            block = {
                "name": "load_skill",
                "input": {"name": "test_skill"},
                "id": "tool_5"
            }
            state = CompactState()
            result = execute_tool(block, state)

            mock_registry.load_full_text.assert_called_once_with("test_skill")
            assert result == "<skill>test</skill>"

    def test_execute_compact(self):
        """测试 compact 工具执行"""
        from evolve.agents.task import execute_tool
        from evolve.tools import CompactState

        block = {
            "name": "compact",
            "input": {},
            "id": "tool_6"
        }
        state = CompactState()
        result = execute_tool(block, state)

        assert "Compacting" in result

    def test_execute_unknown_tool(self):
        """测试未知工具"""
        from evolve.agents.task import execute_tool
        from evolve.tools import CompactState

        block = {
            "name": "unknown_tool",
            "input": {},
            "id": "tool_7"
        }
        state = CompactState()
        result = execute_tool(block, state)

        assert "Unknown tool" in result


class TestRunTaskSubagent:
    """run_task_subagent 集成测试 - 用 Mock LLM"""

    def test_subagent_no_tool_call(self):
        """测试 LLM 不调用工具，直接返回文本"""
        from evolve.agents.task import run_task_subagent

        mock_text_block = MagicMock()
        mock_text_block.to_dict.return_value = {"type": "text", "text": "这是摘要内容"}
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.return_value = mock_response

            result = run_task_subagent("帮我完成任务")

            assert result == "这是摘要内容"
            assert mock_config.client.messages.create.call_count == 1

    def test_subagent_single_tool_call(self):
        """测试 LLM 调用一次工具后返回"""
        from evolve.agents.task import run_task_subagent

        # Mock 一个可以 to_dict() 的 tool_use block
        mock_tool_block = MagicMock()
        mock_tool_block.to_dict.return_value = {
            "type": "tool_use",
            "name": "bash",
            "input": {"command": "ls"},
            "id": "call_1"
        }
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [mock_tool_block]

        mock_text_block = MagicMock()
        mock_text_block.to_dict.return_value = {"type": "text", "text": "任务完成"}
        mock_summary_response = MagicMock()
        mock_summary_response.stop_reason = "end_turn"
        mock_summary_response.content = [mock_text_block]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.side_effect = [mock_tool_response, mock_summary_response]

            with patch("evolve.agents.task.execute_tool") as mock_exec:
                mock_exec.return_value = "ls output"

                result = run_task_subagent("查看文件")

                assert result == "任务完成"
                assert mock_config.client.messages.create.call_count == 2
                mock_exec.assert_called_once()

    def test_subagent_multiple_tool_calls(self):
        """测试 LLM 多次调用工具"""
        from evolve.agents.task import run_task_subagent

        mock_tool_block = MagicMock()
        mock_tool_block.to_dict.return_value = {
            "type": "tool_use",
            "name": "bash",
            "input": {"command": "pwd"},
            "id": "call_1"
        }
        mock_tool_response = MagicMock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.content = [mock_tool_block]

        mock_text_block = MagicMock()
        mock_text_block.to_dict.return_value = {"type": "text", "text": "摘要"}
        mock_summary_response = MagicMock()
        mock_summary_response.stop_reason = "end_turn"
        mock_summary_response.content = [mock_text_block]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.side_effect = [mock_tool_response, mock_summary_response]

            with patch("evolve.agents.task.execute_tool") as mock_exec:
                mock_exec.return_value = "result"

                result = run_task_subagent("任务")

                assert result == "摘要"
                assert mock_config.client.messages.create.call_count == 2

    def test_subagent_max_iterations(self):
        """测试达到最大迭代次数（30轮）"""
        from evolve.agents.task import run_task_subagent

        mock_tool_block = MagicMock()
        mock_tool_block.to_dict.return_value = {
            "type": "tool_use",
            "name": "bash",
            "input": {"command": "ls"},
            "id": "call_1"
        }
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [mock_tool_block]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.return_value = mock_response

            with patch("evolve.agents.task.execute_tool") as mock_exec:
                mock_exec.return_value = "result"

                run_task_subagent("任务")

                assert mock_config.client.messages.create.call_count == 30

    def test_subagent_empty_response(self):
        """测试 LLM 返回空内容"""
        from evolve.agents.task import run_task_subagent

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="text", text="")]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.return_value = mock_response

            result = run_task_subagent("任务")

            assert "(no summary)" in result

    def test_subagent_no_text_block(self):
        """测试 LLM 返回没有 text 块"""
        from evolve.agents.task import run_task_subagent

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="image", source=MagicMock())]

        with patch("evolve.agents.task.global_config") as mock_config:
            mock_config.client.messages.create.return_value = mock_response

            result = run_task_subagent("任务")

            assert "(no summary)" in result


class TestTaskSchema:
    """task_schema 格式测试"""

    def test_task_schema_structure(self):
        """验证 task_schema 结构正确"""
        from evolve.agents.task import task_schema

        assert task_schema["name"] == "task"
        assert "description" in task_schema
        assert "input_schema" in task_schema
        assert task_schema["input_schema"]["type"] == "object"
        assert "prompt" in task_schema["input_schema"]["properties"]
        assert "description" in task_schema["input_schema"]["properties"]
        assert "prompt" in task_schema["input_schema"]["required"]


class TestChildTools:
    """子 Agent 工具集测试"""

    def test_child_tools_include_skill(self):
        """验证子 Agent 工具集包含 skill"""
        from evolve.agents.task import CHILD_TOOLS

        tool_names = [t["name"] for t in CHILD_TOOLS]
        assert "bash" in tool_names
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
        assert "load_skill" in tool_names

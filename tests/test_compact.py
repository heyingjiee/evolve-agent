import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestPersistLargeOutput:
    """工具返回结果超限制抛弃测试"""

    def test_small_output_not_persisted(self, tmp_path):
        """测试小输出不持久化"""
        from tools.compact import persist_large_output

        small_output = "hello world"
        result = persist_large_output("tool_1", small_output)

        assert result == small_output
        assert not (tmp_path / "task_outputs" / "tool-results" / "tool_1.txt").exists()

    def test_large_output_persisted_and_preview_returned(self, tmp_path):
        """测试大输出持久化到文件并返回预览"""
        from tools.compact import persist_large_output

        # 创建一个超过 30000 字符的输出
        large_output = "x" * 50000

        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            result = persist_large_output("tool_big", large_output)

            # 验证返回了预览
            assert "<persisted-output>" in result
            assert "tool_big.txt" in result
            assert "Preview:" in result
            assert len(result) < len(large_output)

            # 验证文件被写入
            stored_file = tmp_path / "tool_outputs" / "tool-results" / "tool_big.txt"
            assert stored_file.exists()
            assert stored_file.read_text() == large_output

    def test_output_exactly_at_threshold_not_persisted(self, tmp_path):
        """测试刚好在阈值不持久化"""
        from tools.compact import persist_large_output

        # 阈值是 30000，刚好等于时不持久化
        output = "y" * 30000
        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            result = persist_large_output("tool_threshold", output)

            assert result == output

    def test_output_slightly_over_threshold_persisted(self, tmp_path):
        """测试稍微超过阈值就持久化"""
        from tools.compact import persist_large_output

        output = "z" * 30001
        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            result = persist_large_output("tool_over", output)

            assert "<persisted-output>" in result
            assert "tool_over.txt" in result

    def test_read_file_large_content_persisted(self, tmp_path):
        """测试 read_file 读取大文件时持久化"""
        from tools.read_file import run_read
        from tools.compact import CompactState

        # 创建一个大于阈值的大文件
        large_file = tmp_path / "large_file.txt"
        large_file.write_text("a" * 50000)

        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            with patch("tools.read_file.global_config", mock_config):
                with patch("tools.read_file.safe_path") as mock_safe:
                    mock_safe.return_value = large_file
                    state = CompactState()
                    result = run_read(str(large_file), "read_tool", state)

                    assert "<persisted-output>" in result or len(result) < 50000

    def test_bash_large_output_persisted(self, tmp_path):
        """测试 bash 执行返回大输出时持久化"""
        from tools.bash import run_bash

        long_output = "b" * 50000

        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.stdout = long_output
                mock_result.stderr = ""
                mock_run.return_value = mock_result

                result = run_bash("echo test", "bash_tool")

                assert "<persisted-output>" in result or len(result) < len(long_output)


class TestMicroCompact:
    """上下文对话超限制压缩工具返回结果测试"""

    def test_few_tool_results_no_compaction(self):
        """测试工具返回结果少时不压缩"""
        from tools.compact import micro_compact

        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "content": "result1", "tool_use_id": "t1"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "result2", "tool_use_id": "t2"}
            ]}
        ]

        with patch.dict(os.environ, {"KEEP_RECENT_TOOL_RESULTS": "3"}):
            result = micro_compact(messages)

            assert result[0]["content"][0]["content"] == "result1"

    def test_many_tool_results_compacted(self):
        """测试工具返回结果多时压缩"""
        from tools.compact import micro_compact

        # 创建超过 KEEP_RECENT_TOOL_RESULTS 的工具结果
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tool result 0", "tool_use_id": "t0"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tool result 1", "tool_use_id": "t1"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tool result 2", "tool_use_id": "t2"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tool result 3", "tool_use_id": "t3"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tool result 4", "tool_use_id": "t4"}
            ]},
        ]

        with patch.dict(os.environ, {"KEEP_RECENT_TOOL_RESULTS": "3"}):
            result = micro_compact(messages)

            # 前面的长内容应该被压缩
            assert "[Earlier tool result compacted" in result[0]["content"][0]["content"]

    def test_short_tool_results_not_compacted(self):
        """测试短内容工具结果不被压缩"""
        from tools.compact import micro_compact

        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "content": "short", "tool_use_id": "t0"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "tiny", "tool_use_id": "t1"}
            ]},
        ]

        with patch.dict(os.environ, {"KEEP_RECENT_TOOL_RESULTS": "2"}):
            result = micro_compact(messages)

            assert "short" in result[0]["content"][0]["content"]
            assert "tiny" in result[1]["content"][0]["content"]

    def test_tool_result_120_chars_threshold(self):
        """测试 120 字符阈值"""
        from tools.compact import micro_compact

        # 创建刚好超过 120 字符的内容
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "content": "a" * 121, "tool_use_id": "t0"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "a" * 120, "tool_use_id": "t1"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "a" * 119, "tool_use_id": "t2"}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "a" * 118, "tool_use_id": "t3"}
            ]},
        ]

        with patch.dict(os.environ, {"KEEP_RECENT_TOOL_RESULTS": "2"}):
            result = micro_compact(messages)

            # 超过 120 字符的会被压缩
            assert "[Earlier tool result compacted" in result[0]["content"][0]["content"]


class TestCompactHistory:
    """完整对话历史压缩测试"""

    def test_compact_history_returns_single_message(self):
        """测试压缩后返回单条消息"""
        from tools.compact import compact_history, CompactState

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "task 1"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "response 1"}]},
            {"role": "user", "content": [{"type": "text", "text": "task 2"}]},
        ]

        with patch("tools.compact.write_transcript") as mock_write:
            mock_write.return_value = Path("/tmp/test.json")
            with patch("tools.compact.summarize_history") as mock_summarize:
                mock_summarize.return_value = "Summary of conversation"

                state = CompactState()
                result = compact_history(messages, state)

                assert len(result) == 1
                assert result[0]["role"] == "user"
                assert "compacted" in result[0]["content"][0]["text"].lower()

    def test_compact_history_updates_state(self):
        """测试压缩后状态更新"""
        from tools.compact import compact_history, CompactState

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "task"}]},
        ]

        with patch("tools.compact.write_transcript") as mock_write:
            mock_write.return_value = Path("/tmp/test.json")
            with patch("tools.compact.summarize_history") as mock_summarize:
                mock_summarize.return_value = "Conversation summary"

                state = CompactState()
                result = compact_history(messages, state)

                assert state.has_compacted is True
                assert state.last_summary == "Conversation summary"

    def test_compact_history_with_focus(self):
        """测试带 focus 参数的压缩"""
        from tools.compact import compact_history, CompactState

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "task"}]},
        ]

        with patch("tools.compact.write_transcript") as mock_write:
            mock_write.return_value = Path("/tmp/test.json")
            with patch("tools.compact.summarize_history") as mock_summarize:
                mock_summarize.return_value = "Summary"

                state = CompactState()
                result = compact_history(messages, state, focus="important file")

                assert "Focus to preserve next: important file" in result[0]["content"][0]["text"]

    def test_compact_history_without_focus_uses_recent_files(self):
        """测试不带 focus 时使用 recent_files"""
        from tools.compact import compact_history, CompactState

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "task"}]},
        ]

        with patch("tools.compact.write_transcript") as mock_write:
            mock_write.return_value = Path("/tmp/test.json")
            with patch("tools.compact.summarize_history") as mock_summarize:
                mock_summarize.return_value = "Summary"

                state = CompactState()
                state.recent_files = ["file1.txt", "file2.txt"]
                result = compact_history(messages, state)

                assert "file1.txt" in result[0]["content"][0]["text"]
                assert "file2.txt" in result[0]["content"][0]["text"]


class TestWriteTranscript:
    """对话历史写入文件测试"""

    def test_write_transcript_creates_directory(self, tmp_path):
        """测试写入 transcript 创建目录"""
        from tools.compact import write_transcript

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "test"}]},
        ]

        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            with patch.dict(os.environ, {"TRANSCRIPT_DIR": "transcripts"}):
                path = write_transcript(messages)

                assert path.exists()
                assert "transcript_" in path.name
                assert path.suffix == ".json"

    def test_write_transcript_content(self, tmp_path):
        """测试写入内容正确"""
        from tools.compact import write_transcript

        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ]

        with patch("tools.compact.global_config") as mock_config:
            mock_config.WORKDIR = tmp_path
            with patch.dict(os.environ, {"TRANSCRIPT_DIR": "transcripts"}):
                path = write_transcript(messages)

                content = path.read_text()
                assert "hello" in content


class TestCollectToolResultBlocks:
    """收集工具返回结果测试"""

    def test_collect_from_user_messages(self):
        """测试从 user 消息收集工具结果"""
        from tools.compact import collect_tool_result_blocks

        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "response"}]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": "result1", "tool_use_id": "t1"},
                {"type": "tool_result", "content": "result2", "tool_use_id": "t2"}
            ]},
        ]

        blocks = collect_tool_result_blocks(messages)
        assert len(blocks) == 2
        assert blocks[0]["content"] == "result1"
        assert blocks[1]["content"] == "result2"

    def test_ignore_non_tool_result_blocks(self):
        """测试忽略非工具结果块"""
        from tools.compact import collect_tool_result_blocks

        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "just text"},
                {"type": "tool_result", "content": "tool result", "tool_use_id": "t1"}
            ]},
        ]

        blocks = collect_tool_result_blocks(messages)
        assert len(blocks) == 1


class TestCompactState:
    """CompactState 测试"""

    def test_default_values(self):
        """测试默认值"""
        from tools.compact import CompactState

        state = CompactState()
        assert state.has_compacted is False
        assert state.last_summary == ""
        assert state.recent_files == []

    def test_recent_files_tracking(self):
        """测试 recent_files 追踪"""
        from tools.compact import CompactState

        state = CompactState()
        state.recent_files.append("file1.txt")
        state.recent_files.append("file2.txt")

        assert len(state.recent_files) == 2
        assert "file1.txt" in state.recent_files

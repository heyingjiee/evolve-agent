import os
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestPersistLargeOutput:
    def test_small_output_not_persisted(self, tmp_path):
        from evolve.tools import persist_large_output

        small_output = "hello world"
        result = persist_large_output("tool_1", small_output, tmp_path)
        assert result == small_output

    def test_large_output_persisted_and_preview_returned(self, tmp_path):
        from evolve.tools import persist_large_output

        large_output = "x" * 50000
        result = persist_large_output("tool_big", large_output, tmp_path)
        assert "<persisted-output>" in result
        assert (tmp_path / ".evolve/compact/tool-outputs/tool_big.txt").exists()

    def test_read_file_large_content_persisted(self, tmp_path):
        from evolve.tools import CompactState
        from evolve.tools.read_file import run_read

        large_file = tmp_path / "large_file.txt"
        large_file.write_text("a" * 50000)
        state = CompactState()
        result = run_read("large_file.txt", "read_tool", state, tmp_path)
        assert "<persisted-output>" in result

    def test_bash_large_output_persisted(self, tmp_path):
        from evolve.tools import run_bash

        long_output = "b" * 50000
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=long_output, stderr="")
            result = run_bash("echo test", "bash_tool", tmp_path)
        assert "<persisted-output>" in result


class TestMicroCompact:
    def test_many_tool_results_compacted(self):
        from evolve.tools import micro_compact

        messages = [
            {"role": "user", "content": [{"type": "tool_result", "content": "tool result 0" * 100, "tool_use_id": "t0"}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "tool result 1", "tool_use_id": "t1"}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "tool result 2", "tool_use_id": "t2"}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "tool result 3", "tool_use_id": "t3"}]},
        ]
        with patch.dict(os.environ, {"KEEP_RECENT_TOOL_RESULTS": "2"}):
            result = micro_compact(messages)
        assert "[Earlier tool result compacted." in result[0]["content"][0]["content"]


class TestCompactHistory:
    def test_compact_history_returns_single_message(self, tmp_path):
        from evolve.tools import CompactState, compact_history

        messages = [{"role": "user", "content": [{"type": "text", "text": "task 1"}]}]
        with patch("evolve.tools.compact.write_transcript") as mock_write, patch("evolve.tools.compact.summarize_history") as mock_summary:
            mock_write.return_value = Path("/tmp/test.json")
            mock_summary.return_value = "Summary of conversation"
            result = compact_history(messages, CompactState(), tmp_path, MagicMock(), "test-model")
        assert len(result) == 1
        assert "compacted" in result[0]["content"][0]["text"].lower()

    def test_compact_history_with_focus(self, tmp_path):
        from evolve.tools import CompactState, compact_history

        with patch("evolve.tools.compact.write_transcript") as mock_write, patch("evolve.tools.compact.summarize_history") as mock_summary:
            mock_write.return_value = Path("/tmp/test.json")
            mock_summary.return_value = "Summary"
            result = compact_history([{"role": "user", "content": [{"type": "text", "text": "task"}]}], CompactState(), tmp_path, MagicMock(), "test-model", focus="important file")
        assert "important file" in result[0]["content"][0]["text"]

    def test_write_transcript_content(self, tmp_path):
        from evolve.tools import write_transcript

        messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
        path = write_transcript(messages, tmp_path)
        assert path.exists()
        assert "hello" in path.read_text()


class TestCollectToolResultBlocks:
    def test_collect_from_user_messages(self):
        from evolve.tools import collect_tool_result_blocks

        messages = [{"role": "user", "content": [{"type": "tool_result", "content": "result1", "tool_use_id": "t1"}]}]
        blocks = collect_tool_result_blocks(messages)
        assert len(blocks) == 1
        assert blocks[0]["content"] == "result1"

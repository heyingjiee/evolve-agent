import json
from unittest.mock import MagicMock, patch

import pytest

from evolve.tools import BackgroundManager, check_background_schema, run_background_schema


class TestBackgroundManager:
    @pytest.fixture
    def bg_mgr(self, tmp_path):
        mgr = BackgroundManager(tmp_path)
        mgr.dir = tmp_path / ".evolve" / "background-tasks"
        mgr.dir.mkdir(parents=True, exist_ok=True)
        return mgr

    def test_run_returns_task_id(self, bg_mgr):
        result = bg_mgr.run("echo hello")
        assert "Background task" in result
        assert "output_file=" in result

    def test_run_creates_task_state_file(self, bg_mgr):
        bg_mgr.run("echo hello")
        task_id = list(bg_mgr.tasks.keys())[0]
        state_file = bg_mgr.dir / f"{task_id}.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["status"] == "running"
        assert data["command"] == "echo hello"

    def test_check_with_task_id(self, bg_mgr):
        bg_mgr.run("echo hello")
        task_id = list(bg_mgr.tasks.keys())[0]
        data = json.loads(bg_mgr.check(task_id))
        assert data["task_id"] == task_id
        assert data["command"] == "echo hello"

    def test_check_unknown_task(self, bg_mgr):
        assert "Unknown task" in bg_mgr.check("missing")

    def test_check_all_tasks(self, bg_mgr):
        bg_mgr.run("echo a")
        bg_mgr.run("echo b")
        result = bg_mgr.check(None)
        assert len(result.splitlines()) == 2

    def test_clear_notifications(self, bg_mgr):
        bg_mgr._notification_queue.extend(["a", "b"])
        assert bg_mgr.clear_notifications() == ["a", "b"]
        assert bg_mgr.clear_notifications() == []


class TestBackgroundExecute:
    @pytest.fixture
    def bg_mgr(self, tmp_path):
        mgr = BackgroundManager(tmp_path)
        mgr.dir = tmp_path / ".evolve" / "background-tasks"
        mgr.dir.mkdir(parents=True, exist_ok=True)
        return mgr

    def _create_task(self, bg_mgr, task_id: str, command: str):
        import time

        bg_mgr.tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "command": command,
            "result": None,
            "result_preview": "",
            "output_file": f".evolve/background-tasks/{task_id}.log",
            "started_at": time.time(),
            "finish_at": None,
        }

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_success(self, mock_run, bg_mgr):
        mock_run.return_value = MagicMock(stdout="test output", stderr="", returncode=0)
        self._create_task(bg_mgr, "test_task", "echo test")
        bg_mgr._execute("test_task", "echo test")
        assert bg_mgr.tasks["test_task"]["status"] == "completed"
        assert bg_mgr.tasks["test_task"]["result"] == "test output"

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_timeout(self, mock_run, bg_mgr):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 0)
        self._create_task(bg_mgr, "test_task", "sleep 100")
        bg_mgr._execute("test_task", "sleep 100")
        assert bg_mgr.tasks["test_task"]["status"] == "timeout"

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_exception(self, mock_run, bg_mgr):
        mock_run.side_effect = Exception("unexpected error")
        self._create_task(bg_mgr, "test_task", "bad")
        bg_mgr._execute("test_task", "bad")
        assert bg_mgr.tasks["test_task"]["status"] == "error"


class TestBackgroundSchemas:
    def test_run_background_schema_structure(self):
        assert run_background_schema["name"] == "run_background"
        assert run_background_schema["input_schema"]["properties"]["command"]["type"] == "string"

    def test_check_background_schema_structure(self):
        assert check_background_schema["name"] == "check_background"
        assert check_background_schema["input_schema"]["properties"]["task_id"]["type"] == "string"

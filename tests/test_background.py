import json

import pytest
from unittest.mock import patch, MagicMock

from evolve.tools import BackgroundManager


class TestBackgroundManager:
    """BackgroundManager 测试 - 直接测试 run/check"""

    @pytest.fixture
    def bg_mgr(self, tmp_path, monkeypatch):
        """创建带有临时目录的 BackgroundManager"""
        from evolve import config
        monkeypatch.setattr(config.global_config, "WORKDIR", tmp_path)

        mgr = BackgroundManager()
        mgr.dir = tmp_path / ".evolve" / "background-tasks"
        mgr.dir.mkdir(parents=True, exist_ok=True)
        return mgr

    def test_run_returns_task_id(self, bg_mgr):
        """测试 run 返回 task_id"""
        result = bg_mgr.run("echo hello")
        assert "Background task" in result
        assert "started:" in result
        assert "output_file=" in result

    def test_run_creates_task_state_file(self, bg_mgr):
        """测试 run 会在文件中创建任务状态"""
        bg_mgr.run("echo hello")

        task_id = list(bg_mgr.tasks.keys())[0]

        state_file = bg_mgr.dir / f"{task_id}.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text())
        assert data["status"] == "running"
        assert data["command"] == "echo hello"
        assert data["task_id"] == task_id

    def test_check_with_task_id(self, bg_mgr):
        """测试 check 单个任务"""
        bg_mgr.run("echo hello")

        task_id = list(bg_mgr.tasks.keys())[0]
        result = bg_mgr.check(task_id)

        data = json.loads(result)
        assert data["task_id"] == task_id
        assert "status" in data
        assert "command" in data
        assert "output_file" in data

    def test_check_unknown_task_id(self, bg_mgr):
        """测试 check 不存在的任务"""
        result = bg_mgr.check("unknown_id")
        assert "Error" in result
        assert "Unknown task" in result

    def test_check_all_tasks(self, bg_mgr):
        """测试 check 不传参数返回所有任务"""
        bg_mgr.run("echo task1")
        bg_mgr.run("echo task2")

        result = bg_mgr.check(None)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "running" in lines[0]
        assert "running" in lines[1]

    def test_check_empty_when_no_tasks(self, bg_mgr):
        """测试 check 无任务时返回空"""
        result = bg_mgr.check(None)
        assert result == ""

    def test_task_timeout(self, bg_mgr):
        """测试任务超时状态"""
        import time
        bg_mgr.tasks["timeout_test"] = {
            "task_id": "timeout_test",
            "status": "timeout",
            "command": "sleep 10",
            "result": None,
            "result_preview": "",
            "output_file": "test.log",
            "started_at": time.time(),
            "finish_at": None,
        }

        assert bg_mgr.tasks["timeout_test"]["status"] == "timeout"

    def test_notification_queue(self, bg_mgr):
        """测试通知队列"""
        bg_mgr._notification_queue.append("test_task_1")
        bg_mgr._notification_queue.append("test_task_2")

        notifications = bg_mgr.clear_notifications()
        assert len(notifications) == 2

        notifications_after_clear = bg_mgr.clear_notifications()
        assert len(notifications_after_clear) == 0

    def test_run_multiple_commands(self, bg_mgr):
        """测试多个后台任务"""
        bg_mgr.run("echo first")
        bg_mgr.run("echo second")
        bg_mgr.run("echo third")

        assert len(bg_mgr.tasks) == 3
        result = bg_mgr.check(None)
        lines = result.split("\n")
        assert len(lines) == 3


class TestBackgroundExecute:
    """测试 _execute 方法 - 需要先创建任务"""

    @pytest.fixture
    def bg_mgr(self, tmp_path, monkeypatch):
        """创建带有临时目录的 BackgroundManager"""
        from evolve import config
        monkeypatch.setattr(config.global_config, "WORKDIR", tmp_path)

        mgr = BackgroundManager()
        mgr.dir = tmp_path / ".evolve" / "background-tasks"
        mgr.dir.mkdir(parents=True, exist_ok=True)
        return mgr

    def _create_task(self, bg_mgr, task_id: str, command: str):
        """辅助方法：创建任务"""
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
        """测试 _execute 成功执行"""
        mock_run.return_value = MagicMock(stdout="test output", stderr="", returncode=0)
        self._create_task(bg_mgr, "test_task", "echo test")

        bg_mgr._execute("test_task", "echo test")

        assert bg_mgr.tasks["test_task"]["status"] == "completed"
        assert bg_mgr.tasks["test_task"]["result"] == "test output"

        log_file = bg_mgr.dir / "test_task.log"
        assert log_file.exists()
        assert log_file.read_text() == "test output"

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_with_stderr(self, mock_run, bg_mgr):
        """测试 _execute 处理 stderr"""
        mock_run.return_value = MagicMock(stdout="out", stderr="error msg", returncode=0)
        self._create_task(bg_mgr, "test_task", "echo test")

        bg_mgr._execute("test_task", "echo test")

        assert bg_mgr.tasks["test_task"]["status"] == "completed"
        assert "error msg" in bg_mgr.tasks["test_task"]["result"]

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_timeout(self, mock_run, bg_mgr):
        """测试 _execute 超时处理"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 0)
        self._create_task(bg_mgr, "test_task", "sleep 100")

        bg_mgr._execute("test_task", "sleep 100")

        assert bg_mgr.tasks["test_task"]["status"] == "timeout"
        assert "Timeout Expired" in bg_mgr.tasks["test_task"]["result"]

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_exception(self, mock_run, bg_mgr):
        """测试 _execute 异常处理"""
        mock_run.side_effect = Exception("unexpected error")
        self._create_task(bg_mgr, "test_task", "some command")

        bg_mgr._execute("test_task", "some command")

        assert bg_mgr.tasks["test_task"]["status"] == "error"
        assert "unexpected error" in bg_mgr.tasks["test_task"]["result"]

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_large_output_truncated(self, mock_run, bg_mgr):
        """测试 _execute 大输出被截断"""
        large_output = "x" * 60000
        mock_run.return_value = MagicMock(stdout=large_output, stderr="", returncode=0)
        self._create_task(bg_mgr, "test_task", "echo large")

        bg_mgr._execute("test_task", "echo large")

        result = bg_mgr.tasks["test_task"]["result"]
        assert len(result) <= 50000

    @patch("evolve.tools.background.subprocess.run")
    def test_execute_no_output(self, mock_run, bg_mgr):
        """测试 _execute 无输出情况"""
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        self._create_task(bg_mgr, "test_task", "echo")

        bg_mgr._execute("test_task", "echo")

        assert bg_mgr.tasks["test_task"]["result"] == "(no output)"


class TestBackgroundSchemas:
    """后台任务 schema 测试"""

    def test_run_background_schema_structure(self):
        """测试 run_background_schema 结构"""
        from evolve.tools import run_background_schema

        assert run_background_schema["name"] == "run_background"
        assert "description" in run_background_schema
        assert "input_schema" in run_background_schema

        props = run_background_schema["input_schema"]["properties"]
        assert "command" in props
        assert props["command"]["type"] == "string"

        required = run_background_schema["input_schema"]["required"]
        assert "command" in required

    def test_check_background_schema_structure(self):
        """测试 check_background_schema 结构"""
        from evolve.tools import check_background_schema

        assert check_background_schema["name"] == "check_background"
        assert "description" in check_background_schema
        assert "input_schema" in check_background_schema

        props = check_background_schema["input_schema"]["properties"]
        assert "task_id" in props
        assert props["task_id"]["type"] == "string"

        required = check_background_schema["input_schema"]["required"]
        assert "task_id" in required
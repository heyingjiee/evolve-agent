import json
import subprocess
import threading
import time
import uuid
from pathlib import Path


class BackgroundManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.dir = self.workspace / ".evolve" / "background-tasks"
        self.tasks = {}
        self._notification_queue = []
        self._lock = threading.Lock()

    @classmethod
    def from_workspace(cls, workspace: Path) -> "BackgroundManager":
        return cls(workspace)

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def run(self, command: str) -> str:
        self._ensure_dir()
        task_id = str(uuid.uuid4())[:8]
        log_file_path = self.dir / f"{task_id}.log"
        task_state_path = self.dir / f"{task_id}.json"
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "command": command,
            "result": None,
            "result_preview": "",
            "output_file": str(log_file_path.relative_to(self.workspace)),
            "started_at": time.time(),
            "finish_at": None,
        }
        task_state_path.write_text(json.dumps(dict(self.tasks[task_id]), indent=2, ensure_ascii=False))

        thread = threading.Thread(target=self._execute, args=(task_id, command), daemon=True)
        thread.start()
        return (
            f"Background task {task_id} started: {command[:80]}"
            f"(output_file={log_file_path.relative_to(self.workspace)})"
        )

    def check(self, task_id: str | None) -> str:
        if task_id:
            if task_id not in self.tasks:
                return f"Error: Unknown task {task_id}"
            task = self.tasks[task_id]
            check_result = {
                "task_id": task["task_id"],
                "status": task["status"],
                "command": task["command"],
                "result_preview": task["result_preview"],
                "output_file": task["output_file"],
                "started_at": task["started_at"],
                "finish_at": task["finish_at"],
            }
            return json.dumps(check_result, indent=2, ensure_ascii=False)

        lines = []
        for task in self.tasks.values():
            lines.append(
                f"{task['task_id']}: {task['status']}: {task['command'][:60]}"
                f"-> {task.get('result_preview') or 'running'}"
            )
        return "\n".join(lines)

    def clear_notifications(self):
        with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs

    def _execute(self, task_id: str, command: str) -> None:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=300,
            )
            std_str = (result.stdout + result.stderr).strip()
            output = std_str[:50000] if std_str else "(no output)"
            status = "completed"
        except subprocess.TimeoutExpired:
            output = "Error: Timeout Expired"
            status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "error"

        self._ensure_dir()
        log_file_path = self.dir / f"{task_id}.log"
        log_file_path.write_text(output)

        started_at = self.tasks[task_id]["started_at"]
        result_preview = (" ".join(output.split()))[:500]
        try:
            output_file = str(log_file_path.relative_to(self.workspace))
        except ValueError:
            output_file = str(log_file_path)

        notification_task = {
            "task_id": task_id,
            "status": status,
            "command": command,
            "result_preview": result_preview,
            "output_file": output_file,
            "started_at": started_at,
            "finish_at": time.time(),
        }
        self.tasks[task_id] = notification_task | {"result": output}
        (self.dir / f"{task_id}.json").write_text(json.dumps(dict(self.tasks[task_id]), indent=2, ensure_ascii=False))

        with self._lock:
            self._notification_queue.append(notification_task)


bg_task_mgr = BackgroundManager.from_workspace(Path.cwd().resolve())

run_background_schema = {
    "name": "run_background",
    "description": "run command in background thread. Return task_id immediately",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

check_background_schema = {
    "name": "check_background",
    "description": "Check background task status. Omit task_id to list all",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
}

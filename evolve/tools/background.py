import json
import subprocess
import threading
import time
import uuid

from evolve.config import global_config

# LLM委托后台任务 -> 任务完成后写入文件 -> 把结果预览推入通知列表
# Agent Loop 每轮会检查通知列表
class BackgroundManager:
    def __init__(self):
        # 存储后台任务结果的文件夹
        self.dir = global_config.WORKDIR / ".evolve" / "background-tasks"
        self.dir.mkdir(parents=True, exist_ok=True)
        # 任务列表
        # task_id 任务id
        # status  状态 running、completed、timeout、error
        # command  任务命令
        # result  任务结果（存到文件中）
        # result_preview  任务结果预览（预览放回prompt上下文，防止原始结果太大超出上下文）
        # output_file  任务结果存储文件路径 存储路径：.evolve/background-task/{task_id}.log
        # started_at  任务创建时间
        # finish_at  任务完成时间
        self.tasks = {} # task_id -> {task_id, status, command, result, result_preview, started_at, finish_at, result }

        # 通知列表（后台任务完成后推入）
        self._notification_queue = []
        # 锁
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        """
            tool: 启动后台任务，返回 task_id
            log 文件写执行完整命令结果
            json 文件写完整数据对象（删除了result字段，即完整命令结果）

            output_file 字段存的是log，是为了让LLM查到原始的结果

        """
        task_id = str(uuid.uuid4())[:8]
        log_file_path = self.dir / f"{task_id}.log"
        task_state_path = self.dir / f"{task_id}.json"
        # 初始化数据
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": "running",
            "command": command,
            "result": None,
            "result_preview": "",
            # 这个是命令结果，不是完整的task对象
            "output_file": str(log_file_path.relative_to(global_config.WORKDIR)),
            "started_at": time.time(),
            "finish_at": None,
        }
        # 任务状态写入文件
        task_state_path.write_text(json.dumps(dict(self.tasks[task_id]), indent=2, ensure_ascii=False)) # 这里浅拷贝dict因为多线程运行run，可能会误改数据

        # 多线程执行
        thread = threading.Thread(
            target=self._execute,
            args=(task_id, command),
            daemon=True, # 守护线程，主进程退出会被直接kill
        )
        thread.start()
        return (
            f"Background task {task_id} started: {command[:80]}"
            f"(output_file={log_file_path.relative_to(global_config.WORKDIR)})"
        )

    def check(self, task_id: str|None) -> str:
        """tool：检查是否有后台任务task_id/ 不传参数就是全部任务"""
        if task_id:
            if task_id not in self.tasks:
                return f"Error: Unknown task {task_id}"
            t = self.tasks[task_id]
            # 去掉了 result 返回结果，只保留路由
            check_result = {
                "task_id": t["task_id"],
                "status": t["status"],
                "command": t["command"],
                "result_preview": t["result_preview"],
                "output_file": t["output_file"],
                "started_at":  t["started_at"],
                "finish_at":  t["finish_at"],
            }
            return json.dumps(check_result, indent=2, ensure_ascii=False)

        else:
            lines = []
            for task in self.tasks.values():
                lines.append(
                    f"{task["task_id"]}: {task['status']}: {task['command'][:60]}"
                    f"-> {task.get('result_preview') or "running"}"
                )
            return "\n".join(lines)

    def clear_notifications(self):
        """ 返回通知列表后，清空列表"""
        with self._lock:
           notifs = list(self._notification_queue)
           self._notification_queue.clear()
        return notifs

    def _execute(self, task_id: str, command: str):
        """ 执行 """
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=global_config.WORKDIR,
                capture_output=True,
                text=True,
                timeout=300,
            )
            std_str = (r.stdout + r.stderr).strip()
            result = std_str[:50000] if std_str else "(no output)"
            status= "completed"
        except subprocess.TimeoutExpired:
            result = "Error: Timeout Expired"
            status = "timeout"
        except Exception as e:
            result = f"Error: {e}"
            status = "error"

        # 命令结果写入文件
        log_file_path = self.dir / f"{task_id}.log"
        log_file_path.write_text(result)

        # 任务状态写入文件
        started_at = self.tasks[task_id]["started_at"]
        result_preview = (" ".join(result.split()))[:500]
        try:
            output_file = str(log_file_path.relative_to(global_config.WORKDIR))
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
        # 写入文件多个 result，携带完整命令
        self.tasks[task_id] = notification_task | {"result": result,}
        task_state_path = self.dir / f"{task_id}.json"
        task_state_path.write_text(json.dumps(dict(self.tasks[task_id]), indent=2, ensure_ascii=False))

        # 结束
        with self._lock:
            self._notification_queue.append(notification_task)


bg_task_mgr = BackgroundManager()

# 运行后台任务
run_background_schema = {
    "name" : "run_background",
    "description" : "run command in background thread. Return task_id immediately",
     "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
    }
}

# 检查后台任务执行结果
check_background_schema = {
    "name": "check_background",
    "description": "Check background task status. Omit task_id to list all",
    "input_schema": {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"]
    }
}
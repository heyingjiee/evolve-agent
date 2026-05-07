import subprocess
import os

from tools.compact import persist_large_output


def run_bash(command: str, tool_use_id: str) -> str:
    """" bash 工具 """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command block"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

    output = (result.stdout + result.stderr).strip()
    return persist_large_output(output if output else "(no output)", tool_use_id)

bash_schema =  {
    "name": "bash",
    "description": "Run a shell command in the current workspace",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
    }
}
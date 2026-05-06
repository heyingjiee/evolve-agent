# 单条计划
from dataclasses import dataclass, field


@dataclass
class PlanItem:
    content: str = ""
    status: str = "pending"
    active_form: str = ""


# 计划列表
@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)  # 全部计划
    rounds_since_update: int = 0  # 执行多少轮


# 计划管理器
class TodoManager:
    def __init__(self, reminder_interval):
        self.state = PlanningState()
        self.reminder_interval =  reminder_interval

    def update(self, items: list):
        if len(items) > 12:
            raise ValueError("Keep the session plan short (max 12 items)")

        normalized = []
        in_progress_count = 0

        for index, raw_item in enumerate(items):
            content =  str(raw_item.get("content", "")).strip()
            status = str(raw_item.get("status", "pending")).lower()
            active_form = str(raw_item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {index}: content required")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"Item {index}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            normalized.append(PlanItem(
                content=content,
                status=status,
                active_form=active_form,
            ))

        if in_progress_count > 1:
            raise ValueError("Only one plan item can be in_progress")

        self.state.items = normalized
        self.state.rounds_since_update = 0
        return self.render()

    def render(self):
        """ 根据任务状态返回不同的样式 """
        if not self.state.items:
            return "No session plan yet"

        lines = []
        for item in self.state.items:
            marker = {
                "pending": "[]",
                "in_progress": "[>]",
                "completed": "[x]",
            }
            line = f"{marker[item.status]} {item.content}"
            if item.status == "in_progress":
                line += f" {item.active_form}"
            lines.append(line)
        completed = sum(1 for item in self.state.items if item.status == "completed")
        lines.append(f"\n({completed}/{len(self.state.items)} completed)")
        return "\n".join(lines)


    def reminder(self) -> str|None:
        if self.state.items and self.state.rounds_since_update >= self.reminder_interval:
            return "<reminder>Refresh your current plan before continue</reminder>"
        return None


    def note_round_without_update(self) -> None:
        self.state.rounds_since_update += 1


todo_schema = {
    "name": "todo",
    "description": "Rewrite the current session plan for multi-step work",
    "input_schema": {
        "type": "object",
        "properties": {"items": {
            "type": "array",
            "items": {
                "content": "string",
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"]
                },
                "activeForm": {
                    "type": "string",
                    "description": "Optional present-continuous label.",
                }
            }
        }},
        "required": ["items"]
    }
}

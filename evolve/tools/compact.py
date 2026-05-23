import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)


def collect_tool_result_blocks(messages: list):
    blocks = []
    for msg in messages:
        if msg["role"] == "user":
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    blocks.append(block)
    return blocks


def micro_compact(messages: list) -> list:
    tool_results = collect_tool_result_blocks(messages)
    keep_recent_tool_results = int(os.getenv("KEEP_RECENT_TOOL_RESULTS", "3"))
    if len(tool_results) < keep_recent_tool_results:
        return messages

    for block in tool_results[:-keep_recent_tool_results]:
        content = block.get("content", "")
        if not isinstance(content, str) or len(content) <= 120:
            continue
        block["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
    return messages


def write_transcript(messages: list, workspace: Path) -> Path:
    transcript_dir = workspace / os.getenv("TRANSCRIPT_DIR", ".evolve/compact/transcripts")
    transcript_dir.mkdir(parents=True, exist_ok=True)
    store_path = transcript_dir / f"transcript_{int(time.time())}.json"
    with store_path.open("w") as handler:
        for message in messages:
            handler.write(json.dumps(message, default=str, ensure_ascii=False) + "\n")
    return store_path


def summarize_history(messages: list, client, model: str) -> str:
    conversation = json.dumps(messages, default=str, ensure_ascii=False)
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. The current goal\n"
        "2. Important findings and decisions\n"
        "3. Files read or changed\n"
        "4. Remaining work\n"
        "5. User constraints and preferences\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )
    request_messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]

    try:
        resp = client.messages.create(model=model, messages=request_messages, max_tokens=2000)
        summary = resp.content[-1].text.strip()
    except Exception as e:
        summary = f"(compact failed: {e}). Previous context lost."

    return (
        "This session continues from a previous conversation that was compacted. "
        f"Summary of prior context:\n\n{summary}\n\n"
        "Continue from where we left off without re-asking the user."
    )


def compact_history(
    messages: list,
    state: CompactState,
    workspace: Path,
    client,
    model: str,
    focus: str | None = None,
):
    transcript_path = write_transcript(messages, workspace)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages, client, model)
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    else:
        recent_lines = "\n".join(f"- {path}" for path in state.recent_files)
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"

    state.has_compacted = True
    state.last_summary = summary
    return [{
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "This conversation was compacted so work can continue.\n"
                f"{summary}"
            ),
        }],
    }]


def persist_large_output(tool_use_id: str, output: str, workspace: Path) -> str:
    if len(output) <= int(os.getenv("PERSIST_THRESHOLD", "30000")):
        return output

    preview_chars = int(os.getenv("PREVIEW_CHARS", "2000"))
    tool_result_dir = workspace / os.getenv("TOOL_RESULTS_DIR", ".evolve/compact/tool-outputs")
    tool_result_dir.mkdir(parents=True, exist_ok=True)
    stored_path = tool_result_dir / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output)
    preview = output[:preview_chars]
    relative_path = stored_path.relative_to(workspace)
    return (
        "<persisted-output>"
        f"Full output saved to: {relative_path}"
        "Preview:\n"
        f"{preview}\n"
        "</persisted-output>"
    )


compact_schema = {
    "name": "compact",
    "description": "Summarize earlier conversation so work can continue in a smaller context",
    "input_schema": {
        "type": "object",
        "properties": {
            "focus": {"type": "string"},
        },
    },
}

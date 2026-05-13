import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from config import global_config


@dataclass
class CompactState:
    has_compacted: bool = False  # history是否被压缩过
    last_summary: str = ""  # history压缩的摘要
    recent_files: list[str] = field(default_factory=list)  # read_file工具最近读入文件的路径


def collect_tool_result_blocks(messages: list):
    """ 从message中过滤提取工具返回信息 """
    blocks = []
    for msg in messages:
        if msg["role"] == "user":
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    blocks.append(block)
    return blocks


def micro_compact(messages: list) -> list:
    """
        压缩工具返回内容
     """
    tool_results = collect_tool_result_blocks(messages)
    keep_recent_tool_results = int(os.getenv("KEEP_RECENT_TOOL_RESULTS", "3"))
    if len(tool_results) < keep_recent_tool_results:
        # 不压缩工具返回结果
        return messages

    # 压缩
    for block in tool_results[:-keep_recent_tool_results]:
        content = block.get("content", "")
        if not isinstance(content, str) or len(content) <= 120:
            continue
        block["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
    return messages


def write_transcript(messages: list) -> Path:
    """ 把message信息写入文件，返回文件路径 """
    transcript_dir = global_config.WORKDIR / os.getenv("TRANSCRIPT_DIR", ".evolve/compact/transcripts")
    transcript_dir.mkdir(parents=True, exist_ok=True)  # 保证目录一定有，后面才能写入
    store_path = transcript_dir / f"transcript_{int(time.time())}.json"

    # 没有一口气写入 messages，是出于内存考虑，防止内存溢出
    with store_path.open("w") as handler:
        for message in messages:
            handler.write(json.dumps(message, default=str, ensure_ascii=False) + "\n")
    return store_path


def summarize_history(messages: list) -> str:
    """调用大模型总结摘要"""
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
    messages: list = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt}
        ]
    }]
    resp = global_config.client.messages.create(
        model=os.getenv('MODEL_ID', 'claude-opus-4-6'),
        messages=messages,
        max_tokens=2000
    )

    return resp.content[-1].text.strip()


def compact_history(messages: list, state: CompactState, focus: str | None = None, ):
    """
        压缩历史记录
        1、把messages写入文件  write_transcript
        2、生成摘要 summarize_history
        3、更新state状态信息
        4、返回压缩后的一条message
     """
    # 历史写入文件
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages)
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
            )
        }]
    }]


def persist_large_output(tool_use_id: str, output: str) -> str:
    """ 持久化到文件,返回Preview概览 """
    if len(output) <= int(os.getenv("PERSIST_THRESHOLD", "30000")):
        return output

    preview_chars = int(os.getenv("PREVIEW_CHARS", "2000"))
    tool_result_dir = global_config.WORKDIR / os.getenv("TOOL_RESULTS_DIR", ".evolve/compact/tool-outputs")

    tool_result_dir.mkdir(parents=True, exist_ok=True)
    stored_path = tool_result_dir / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output)
    preview = output[:preview_chars]
    relative_path = stored_path.relative_to(global_config.WORKDIR)
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
            "focus": {"type": "string"}
        }
    }
}

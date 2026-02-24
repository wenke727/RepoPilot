from __future__ import annotations

import json
from typing import Any, Literal

DisplayGroup = Literal["command", "output", "result", "timeout", "artifact", "protocol"]

_DISPLAY_LABELS: dict[DisplayGroup, str] = {
    "command": "命令",
    "output": "输出",
    "result": "结果",
    "timeout": "超时",
    "artifact": "产物",
    "protocol": "协议",
}

_PREVIEW_LIMIT = 600


def enrich_event_for_display(event: dict[str, Any]) -> dict[str, Any]:
    view = dict(event)
    view["display"] = build_event_display(event)
    return view


def build_event_display(event: dict[str, Any]) -> dict[str, str]:
    event_type = _as_str(event.get("type"))

    if event_type == "command":
        return _build_display(
            group="command",
            text=_as_str(event.get("cmd")) or "(无命令内容)",
            merge_suffix="command",
            raw=_event_raw_without_seq(event),
        )

    if event_type == "stream":
        group, text, merge_suffix, raw = _build_stream_display(event)
        return _build_display(group=group, text=text, merge_suffix=merge_suffix, raw=raw)

    if event_type == "assistant_text":
        return _build_display(
            group="result",
            text=_as_str(event.get("text")) or "(无文本结果)",
            merge_suffix="assistant_text",
            raw=_event_raw_without_seq(event),
        )

    if event_type == "timeout":
        return _build_display(
            group="timeout",
            text=_as_str(event.get("message")) or "任务超时",
            merge_suffix="timeout",
            raw=_event_raw_without_seq(event),
        )

    if event_type == "artifact":
        return _build_display(
            group="artifact",
            text=_as_str(event.get("path")) or "(无产物路径)",
            merge_suffix="artifact",
            raw=_event_raw_without_seq(event),
        )

    fallback = _as_str(event.get("message")) or f"事件类型: {event_type or 'unknown'}"
    return _build_display(
        group="protocol",
        text=fallback,
        merge_suffix=event_type or "other",
        raw=_event_raw_without_seq(event),
    )


def _build_stream_display(event: dict[str, Any]) -> tuple[DisplayGroup, str, str, str]:
    line = _as_str(event.get("line"))
    raw = line or _event_raw_without_seq(event)
    if not line:
        return "protocol", "(空输出)", "empty", raw

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return "protocol", line, "unparsed", raw

    if not isinstance(payload, dict):
        return "protocol", line, "non_object", raw

    stream_type = _as_str(payload.get("type"))
    stream_subtype = _as_str(payload.get("subtype"))
    merge_suffix = stream_subtype or stream_type or "unknown"

    if stream_type == "assistant":
        texts = _extract_assistant_text(payload)
        if texts:
            return "output", "\n".join(texts), merge_suffix, raw
        return "protocol", _describe_stream_protocol(payload), merge_suffix, raw

    if stream_type == "result" and stream_subtype == "success":
        result = _as_str(payload.get("result")) or "执行完成"
        return "result", result, "success", raw

    return "protocol", _describe_stream_protocol(payload), merge_suffix, raw


def _extract_assistant_text(payload: dict[str, Any]) -> list[str]:
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return chunks


def _describe_stream_protocol(payload: dict[str, Any]) -> str:
    stream_type = _as_str(payload.get("type"))
    stream_subtype = _as_str(payload.get("subtype"))

    if stream_type == "assistant":
        tool_names = _extract_assistant_tool_names(payload)
        if tool_names:
            return f"助手调用工具: {', '.join(tool_names)}"
        return "助手协议消息"

    if stream_type == "user":
        if _contains_user_tool_result(payload):
            return "工具返回结果"
        return "用户协议消息"

    if stream_type == "system":
        return f"系统事件: {stream_subtype or 'event'}"

    if stream_type == "result":
        return f"结果事件: {stream_subtype or 'event'}"

    if stream_type:
        return f"协议事件: {stream_type}"

    return "协议事件"


def _extract_assistant_tool_names(payload: dict[str, Any]) -> list[str]:
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    names: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if _as_str(item.get("type")) != "tool_use":
            continue
        name = _as_str(item.get("name"))
        if name:
            names.append(name)
    return names


def _contains_user_tool_result(payload: dict[str, Any]) -> bool:
    message = payload.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if isinstance(item, dict) and _as_str(item.get("type")) == "tool_result":
            return True
    return False


def _build_display(group: DisplayGroup, text: str, merge_suffix: str, raw: str) -> dict[str, str]:
    cleaned = text.strip() if text else ""
    preview = _truncate_preview(cleaned or "(空输出)")
    suffix = merge_suffix or "event"
    return {
        "group": group,
        "label": _DISPLAY_LABELS[group],
        "text": preview,
        "merge_key": f"{group}:{suffix}",
        "raw": raw,
    }


def _event_raw_without_seq(event: dict[str, Any]) -> str:
    view = {key: value for key, value in event.items() if key != "seq"}
    return json.dumps(view, ensure_ascii=False)


def _truncate_preview(text: str) -> str:
    if len(text) <= _PREVIEW_LIMIT:
        return text
    return text[:_PREVIEW_LIMIT] + "…"


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""

"""Local BigApple Desktop Gateway discovery and task transport."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


_LOOPBACK_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost):(\d{2,5})")


class BigAppleGatewayError(RuntimeError):
    pass


def _json_request(base_url: str, path: str, *, method: str = "GET",
                  payload: dict | None = None, timeout: float = 5) -> dict:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(
        base_url.rstrip("/") + path, data=body, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise BigAppleGatewayError(
            f"BigApple Gateway HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise BigAppleGatewayError(f"BigApple Gateway request failed: {exc}") from exc
    try:
        result = json.loads(content or "{}")
    except json.JSONDecodeError as exc:
        raise BigAppleGatewayError("BigApple Gateway returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise BigAppleGatewayError("BigApple Gateway returned a non-object response")
    return result


def _log_candidates(log_path: str | None = None) -> list[str]:
    path = log_path or os.path.expanduser("~/.bigapple/logs/app.log")
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4 * 1024 * 1024))
            text = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    ports = _LOOPBACK_RE.findall(text)
    candidates = []
    for port in reversed(ports):
        base = f"http://127.0.0.1:{port}"
        if base not in candidates:
            candidates.append(base)
    return candidates


def discover_gateway() -> str:
    override = (os.environ.get("COMMA_REVIEW_BIGAPPLE_GATEWAY") or "").strip().rstrip("/")
    candidates = [override] if override else []
    candidates.extend(base for base in _log_candidates() if base not in candidates)
    for base in candidates:
        try:
            health = _json_request(base, "/api/health", timeout=0.75)
        except BigAppleGatewayError:
            continue
        if str(health.get("status") or "").lower() == "ok":
            return base
    return ""


def gateway_status() -> dict:
    base = discover_gateway()
    return {
        "available": bool(base),
        "ready": bool(base),
        "auth_state": "ready" if base else "not_running",
        "version": "BigApple Desktop Gateway" if base else "",
        "detail": base or "未发现正在运行的 BigApple Desktop Gateway",
        "gateway_url": base,
    }


def _message_text(content: Any) -> str:
    if not isinstance(content, str):
        return ""
    try:
        blocks = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    if not isinstance(blocks, list):
        return content.strip()
    preferred = []
    fallback = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if block_type in {"text", "final", "answer"}:
            preferred.append(text.strip())
        elif block_type == "commentary":
            fallback.append(text.strip())
    return "\n\n".join(preferred or fallback).strip()


def _event_text(event: Any) -> str:
    if isinstance(event, str):
        return event.strip()
    if isinstance(event, list):
        return "\n\n".join(text for text in (_event_text(item) for item in event) if text).strip()
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "").lower()
    if event_type in {"result", "done", "usage", "metadata", "meta"}:
        return ""
    if event_type in {"text", "delta", "content_delta", "message_delta"}:
        data = event.get("data")
        if isinstance(data, str):
            return data
        return str(event.get("text") or event.get("delta") or "")
    if event_type in {"final_text", "final", "answer"}:
        for key in ("data", "content", "text", "output"):
            value = event.get(key)
            text = _message_text(value) if key == "content" else str(value or "").strip()
            if text:
                return text
    if event.get("role") == "assistant":
        return _message_text(event.get("content")) or str(event.get("text") or "").strip()
    for key in ("message", "delta", "data", "event"):
        text = _event_text(event.get(key))
        if text:
            return text
    if any(token in event_type for token in ("final", "answer", "complete", "message")):
        for key in ("content", "text", "output"):
            text = _message_text(event.get(key)) if key == "content" else str(event.get(key) or "").strip()
            if text:
                return text
    return ""


def _result_payload(event: dict) -> dict:
    if str((event or {}).get("type") or "").lower() != "result":
        return {}
    data = event.get("data")
    if isinstance(data, dict):
        return data
    if not isinstance(data, str) or not data.strip():
        return {}
    try:
        loaded = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _sse_error(events: list[dict]) -> str:
    for event in reversed(events):
        payload = _result_payload(event)
        if not payload or not payload.get("is_error"):
            continue
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:2000]
        provider_debug = payload.get("provider_debug")
        if isinstance(provider_debug, dict):
            for key in ("error", "message", "detail"):
                value = provider_debug.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:2000]
        return "BigApple task failed"
    return ""


def _assistant_text_from_events(events: list[dict]) -> str:
    final_text = ""
    deltas = []
    for event in events:
        event_type = str((event or {}).get("type") or "").lower()
        text = _event_text(event)
        if not text:
            continue
        if event_type in {"final_text", "final", "answer"}:
            final_text = text
        else:
            deltas.append(text)
    return (final_text or "".join(deltas)).strip()


def _read_sse_response(response) -> tuple[str, list[dict]]:
    events: list[dict] = []
    data_lines: list[str] = []
    for raw in response:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                _append_sse_event(events, data_lines)
                data_lines = []
            continue
        if line.startswith(":") or not line.startswith("data:"):
            continue
        data_lines.append(line[5:].strip())
    if data_lines:
        _append_sse_event(events, data_lines)
    error = _sse_error(events)
    if error:
        raise BigAppleGatewayError(error)
    return _assistant_text_from_events(events), events


def _append_sse_event(events: list[dict], data_lines: list[str]) -> None:
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        parsed = {"type": "text", "text": data}
    if isinstance(parsed, dict):
        events.append(parsed)
    else:
        events.append({"type": "data", "data": parsed})


def submit_task(prompt: str, *, working_directory: str, timeout: int,
                schema: dict | None = None, base_url: str = "") -> dict:
    base = (base_url or "").strip().rstrip("/") or discover_gateway()
    if not base:
        raise BigAppleGatewayError("未发现正在运行的 BigApple Desktop Gateway")
    provider_id = (os.environ.get("COMMA_REVIEW_BIGAPPLE_PROVIDER_ID") or "").strip()
    model = (os.environ.get("COMMA_REVIEW_BIGAPPLE_MODEL") or "").strip()
    session_payload = {
        "title": "Comma Review Studio",
        "working_directory": os.path.realpath(working_directory),
        "mode": "ask",
    }
    if provider_id:
        session_payload["provider_id"] = provider_id
    if model:
        session_payload["model"] = model
    started = time.monotonic()
    created = _json_request(
        base, "/api/chat/sessions", method="POST",
        payload=session_payload, timeout=min(timeout, 30),
    )
    session = created.get("session") or {}
    session_id = str(session.get("id") or "")
    if not session_id:
        raise BigAppleGatewayError("BigApple Gateway did not return a session id")
    request_id = uuid.uuid4().hex
    task_prompt = prompt
    if schema:
        task_prompt += (
            "\n\nReturn only one JSON object matching this JSON Schema exactly; "
            "do not wrap it in a Markdown fence:\n" +
            json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
    request = urllib.request.Request(
        base + "/api/chat",
        data=json.dumps({
            "session_id": session_id,
            "request_id": request_id,
            "content": task_prompt,
            "model_content": task_prompt,
            "mode": "ask",
            "client_persists_messages": False,
        }, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            output, events = _read_sse_response(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise BigAppleGatewayError(
            f"BigApple task failed with HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise BigAppleGatewayError(f"BigApple task request failed: {exc}") from exc
    if not output:
        messages = _json_request(
            base,
            f"/api/chat/sessions/{urllib.parse.quote(session_id)}/messages?limit=20",
            timeout=min(timeout, 15),
        ).get("messages") or []
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                output = _message_text(message.get("content"))
                if output:
                    break
    if not output:
        raise BigAppleGatewayError("BigApple task completed without assistant text")
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "output": output,
        "elapsed_ms": elapsed_ms,
        "gateway_url": base,
        "session_id": session_id,
        "request_id": request_id,
        "provider_id": provider_id or session.get("provider_id") or "",
        "model": model or session.get("model") or "",
        "events": events,
    }

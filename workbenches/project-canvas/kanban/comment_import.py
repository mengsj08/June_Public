"""Durable import and projection for comments created outside the kanban.

External comments are append-only facts in the existing per-task comments
ledger.  They are deliberately not AI queue messages: importing a review must
never create or resume a model run, and it must never mutate the task Markdown.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA = "kanban.comments/v1"
EVENT = "external_comment_imported"
EDIT_EVENT = "external_comment_edited"
PROJECTABLE_EVENTS = {EVENT, EDIT_EVENT}
MAX_BATCH_COMMENTS = 500
MAX_COMMENT_BYTES = 64 * 1024
MAX_QUOTE_BYTES = 16 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_CHARS = 500


def _text(value: Any, limit: int | None = None) -> str:
    text = str(value or "").strip()
    return text[:limit] if limit is not None else text


def _digest(*parts: Any, size: int = 24) -> str:
    raw = "\0".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:size]


def _task_id(task_rel_path: str, task_file: dict[str, Any]) -> str:
    fm = task_file.get("frontmatter") if isinstance(task_file.get("frontmatter"), dict) else {}
    value = _text(fm.get("task_id"))
    if value:
        return value
    stem = Path(task_rel_path).stem
    return stem.split("_", 1)[0] or stem


def _ledger_path(repo_root: Path, task_rel_path: str, task_id: str) -> Path:
    task_path = Path(task_rel_path)
    safe_id = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in task_id).strip("-._")
    safe_id = safe_id or task_path.stem
    path = (repo_root / task_path.parent / ".comments" / safe_id / "ledger.jsonl").resolve()
    path.relative_to(repo_root.resolve())
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _resolve_task(deps: dict[str, Any], path_value: Any):
    candidate, rel_path, error, status = deps["resolve_active_task_card_path"](_text(path_value))
    if error:
        return None, "", None, {"ok": False, "error": error}, status
    task_file, read_error = deps["read_task_file"](rel_path)
    if not task_file:
        status = 404 if read_error == "文件不存在" else 400
        return None, rel_path, None, {"ok": False, "error": read_error or "任务卡不可读"}, status
    return candidate, rel_path, task_file, None, 200


def _source(value: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(value, dict):
        return None, "source 必须是对象"
    provider = _text(value.get("provider"), 40).lower()
    doc_token = _text(value.get("doc_token"), 256)
    if not provider:
        return None, "source.provider 不能为空"
    if not doc_token:
        return None, "source.doc_token 不能为空"
    url = _text(value.get("url"), 2048)
    if url and not url.startswith("https://"):
        return None, "source.url 只允许 https"
    return {
        "provider": provider,
        "url": url,
        "doc_token": doc_token,
        "revision": _text(value.get("revision"), 128),
    }, ""


def _normalized_with_indexes(value: str) -> tuple[str, list[int]]:
    output: list[str] = []
    indexes: list[int] = []
    in_whitespace = False
    for index, char in enumerate(str(value or "")):
        if char in {"*", "`"}:
            continue
        if char.isspace() or char in {"\u00a0", "\u2007", "\u202f"}:
            if not in_whitespace:
                output.append(" ")
                indexes.append(index)
                in_whitespace = True
            continue
        output.append(char)
        indexes.append(index)
        in_whitespace = False
    return "".join(output), indexes


def _all_indexes(body: str, quote: str) -> list[int]:
    matches: list[int] = []
    cursor = 0
    while quote and cursor <= len(body) - len(quote):
        found = body.find(quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + max(1, len(quote))
    return matches


def _choose_anchor_index(
    body: str, quote: str, prefix: str, suffix: str,
    recorded_index: int = -1, occurrence_index: int = -1,
) -> tuple[int, str]:
    matches = _all_indexes(body, quote)
    if matches and 0 <= occurrence_index < len(matches):
        return matches[occurrence_index], "exact"
    if not matches:
        normalized_body, body_indexes = _normalized_with_indexes(body)
        normalized_quote, _quote_indexes = _normalized_with_indexes(quote)
        normalized_matches = _all_indexes(normalized_body, normalized_quote)
        raw_matches = [body_indexes[index] for index in normalized_matches if index < len(body_indexes)]
        if raw_matches:
            if 0 <= occurrence_index < len(raw_matches):
                return raw_matches[occurrence_index], "normalized"
            if recorded_index in raw_matches:
                return recorded_index, "normalized"
            if len(raw_matches) == 1:
                return raw_matches[0], "normalized"
            return -1, "ambiguous"
        return -1, "missing"
    if len(matches) == 1:
        return matches[0], "exact"
    if recorded_index in matches:
        return recorded_index, "exact"
    scored: list[tuple[int, int]] = []
    for index in matches:
        score = 0
        if prefix and body[max(0, index - len(prefix)):index] == prefix:
            score += 2
        if suffix and body[index + len(quote):index + len(quote) + len(suffix)] == suffix:
            score += 2
        scored.append((score, index))
    scored.sort(reverse=True)
    if scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], "exact"
    return -1, "ambiguous"


def _normalize_source_quote(value: Any, rel_path: str, task_file: dict[str, Any]):
    if value in (None, ""):
        return None, "unanchored", ""
    if not isinstance(value, dict):
        return None, "unanchored", "source_quote 必须是对象"
    quote_text = _text(value.get("quote_text"))
    if not quote_text:
        return None, "unanchored", "source_quote.quote_text 不能为空"
    if len(quote_text.encode("utf-8")) > MAX_QUOTE_BYTES:
        return None, "unanchored", f"source_quote.quote_text 超过 {MAX_QUOTE_BYTES} bytes"
    context = value.get("context") if isinstance(value.get("context"), dict) else {}
    locator = value.get("source_locator") if isinstance(value.get("source_locator"), dict) else {}
    locator_path = _text(locator.get("task_path") or rel_path)
    if locator_path != rel_path:
        return None, "unanchored", "source_quote 不属于当前任务卡"
    prefix = str(locator.get("prefix") or context.get("prefix") or "")[-MAX_CONTEXT_CHARS:]
    suffix = str(locator.get("suffix") or context.get("suffix") or "")[:MAX_CONTEXT_CHARS]
    body = str(task_file.get("body") or "")
    try:
        recorded_index = int(locator.get("text_index", -1))
    except (TypeError, ValueError):
        recorded_index = -1
    try:
        occurrence_index = int(locator.get("occurrence_index", -1))
    except (TypeError, ValueError):
        occurrence_index = -1
    index, anchor_status = _choose_anchor_index(
        body, quote_text, prefix, suffix,
        recorded_index=recorded_index,
        occurrence_index=occurrence_index,
    )
    try:
        block_index = max(-1, int(locator.get("block_index", -1)))
    except (TypeError, ValueError):
        block_index = -1
    normalized = {
        "quote_text": quote_text,
        "section": _text(value.get("section"), 512),
        "context": {"prefix": prefix, "suffix": suffix},
        "source_locator": {
            "task_path": rel_path,
            "body_rev": _text(task_file.get("rev"), 128),
            "text_index": index,
            "prefix": prefix,
            "suffix": suffix,
            "block_index": block_index,
            "occurrence_index": occurrence_index,
            "feishu_block_id": _text(locator.get("feishu_block_id"), 256),
            "accuracy": _text(locator.get("accuracy"), 80) or anchor_status,
        },
        "anchor_status": anchor_status,
    }
    return normalized, anchor_status, ""


def _flatten_comments(comments: list[Any]) -> tuple[list[dict[str, Any]] | None, str]:
    flat: list[dict[str, Any]] = []
    for root in comments:
        if not isinstance(root, dict):
            return None, "comments 中每项必须是对象"
        root_copy = dict(root)
        replies = root_copy.pop("replies", [])
        flat.append({"item": root_copy, "root": root_copy, "is_reply": False, "parent_item": None})
        if replies in (None, ""):
            replies = []
        if not isinstance(replies, list):
            return None, "replies 必须是数组"
        reply_by_external_id: dict[str, dict[str, Any]] = {}
        pending: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for reply in replies:
            if not isinstance(reply, dict):
                return None, "replies 中每项必须是对象"
            reply_copy = dict(reply)
            reply_id = _text(reply_copy.get("reply_id") or reply_copy.get("comment_id"))
            if reply_id:
                reply_by_external_id[reply_id] = reply_copy
            pending.append((reply_copy, None))
        for reply_copy, _ in pending:
            parent_external = _text(reply_copy.get("parent_id"))
            parent_item = reply_by_external_id.get(parent_external) if parent_external else root_copy
            flat.append({"item": reply_copy, "root": root_copy, "is_reply": True, "parent_item": parent_item or root_copy})
    if len(flat) > MAX_BATCH_COMMENTS:
        return None, f"批注总数超过上限 {MAX_BATCH_COMMENTS}"
    return flat, ""


def _external_id(item: dict[str, Any], is_reply: bool) -> str:
    if is_reply:
        return _text(item.get("reply_id") or item.get("comment_id"), 512)
    return _text(item.get("comment_id"), 512)


def _entry_id(source: dict[str, Any], external_id: str, kind: str) -> str:
    return "ext-" + _digest(source["provider"], source["doc_token"], kind, external_id)


def _build_events(
    flat: list[dict[str, Any]], source: dict[str, Any], rel_path: str,
    task_file: dict[str, Any], task_id: str,
) -> tuple[list[dict[str, Any]] | None, dict[str, int], str]:
    events: list[dict[str, Any]] = []
    anchor_counts = {"exact": 0, "ambiguous": 0, "missing": 0, "unanchored": 0}
    total_bytes = 0
    root_entry_by_object: dict[int, str] = {}
    item_entry_by_object: dict[int, str] = {}
    for row in flat:
        item = row["item"]
        external_id = _external_id(item, row["is_reply"])
        if not external_id:
            return None, anchor_counts, "comment_id/reply_id 不能为空"
        content = _text(item.get("content"))
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > MAX_COMMENT_BYTES:
            return None, anchor_counts, f"批注 {external_id} 超过 {MAX_COMMENT_BYTES} bytes"
        total_bytes += content_bytes
        if total_bytes > MAX_TOTAL_BYTES:
            return None, anchor_counts, f"批注总内容超过 {MAX_TOTAL_BYTES} bytes"
        kind = "reply" if row["is_reply"] else "comment"
        entry_id = _entry_id(source, external_id, kind)
        item_entry_by_object[id(item)] = entry_id
        root = row["root"]
        root_external_id = _external_id(root, False)
        thread_id = "ext-thread-" + _digest(source["provider"], source["doc_token"], root_external_id)
        if not row["is_reply"]:
            root_entry_by_object[id(root)] = entry_id
    for row in flat:
        item = row["item"]
        root = row["root"]
        is_reply = row["is_reply"]
        external_id = _external_id(item, is_reply)
        entry_id = item_entry_by_object[id(item)]
        root_external_id = _external_id(root, False)
        thread_id = "ext-thread-" + _digest(source["provider"], source["doc_token"], root_external_id)
        if is_reply:
            parent_item = row.get("parent_item") or root
            parent = item_entry_by_object.get(id(parent_item)) or root_entry_by_object[id(root)]
            source_quote = None
            anchor_status = "inherited"
        else:
            parent = None
            source_quote, anchor_status, quote_error = _normalize_source_quote(
                item.get("source_quote"), rel_path, task_file,
            )
            if quote_error:
                return None, anchor_counts, f"批注 {external_id}: {quote_error}"
            anchor_counts[anchor_status] = anchor_counts.get(anchor_status, 0) + 1
        origin = dict(source)
        origin["comment_id"] = root_external_id
        if is_reply:
            origin["reply_id"] = external_id
        content = _text(item.get("content"))
        ts = _text(item.get("ts") or item.get("created_at"), 128)
        updated_at = _text(item.get("updated_at") or ts, 128)
        event = {
            "v": 1,
            "schema": SCHEMA,
            "event": EVENT,
            "entry_id": entry_id,
            "thread_id": thread_id,
            "parent": parent,
            "role": "human",
            "author": _text(item.get("author"), 256) or "未知作者",
            "ts": ts,
            "updated_at": updated_at,
            "content": content,
            "content_len": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
            "resolved": bool(item.get("resolved", root.get("resolved", False))),
            "origin": origin,
            "path": rel_path,
            "task_id": task_id,
            "anchor_status": anchor_status,
            "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if source_quote:
            event["source_quote"] = source_quote
        event["event_id"] = "ext-event-" + _digest(
            entry_id, updated_at, content, event["resolved"],
            json.dumps(source_quote or {}, ensure_ascii=False, sort_keys=True),
        )
        events.append(event)
    return events, anchor_counts, ""


def _project_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": _text(row.get("thread_id")),
        "entry_id": _text(row.get("entry_id")),
        "parent": row.get("parent"),
        "author": _text(row.get("author")),
        "ts": _text(row.get("ts")),
        "updated_at": _text(row.get("updated_at")),
        "content": str(row.get("content") or ""),
        "resolved": bool(row.get("resolved", False)),
        "origin": dict(row.get("origin") or {}),
        "source_quote": dict(row.get("source_quote") or {}),
        "anchor_status": _text(row.get("anchor_status")),
        "edited_at": _text(row.get("edited_at")),
        "edited_by": _text(row.get("edited_by")),
    }


def project_threads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("event") not in PROJECTABLE_EVENTS or not row.get("entry_id"):
            continue
        latest[str(row["entry_id"])] = (ordinal, row)
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for ordinal, row in latest.values():
        thread_id = _text(row.get("thread_id"))
        if thread_id:
            grouped.setdefault(thread_id, []).append((ordinal, row))
    threads: list[tuple[int, dict[str, Any]]] = []
    for thread_id, entries in grouped.items():
        entries.sort(key=lambda pair: (pair[1].get("ts") or "", pair[0]))
        roots = [pair for pair in entries if not pair[1].get("parent")]
        if not roots:
            continue
        root_ordinal, root_row = roots[-1]
        thread = _project_event(root_row)
        thread["thread_id"] = thread_id
        thread["replies"] = [
            _project_event(row) for _ordinal, row in entries if row.get("parent")
        ]
        threads.append((root_ordinal, thread))
    threads.sort(key=lambda pair: (pair[1].get("ts") or "", pair[0]))
    return [thread for _ordinal, thread in threads]


def get_task_comments(deps: dict[str, Any], path_value: Any):
    _candidate, rel_path, task_file, error, status = _resolve_task(deps, path_value)
    if error:
        return error, status
    task_id = _task_id(rel_path, task_file)
    ledger = _ledger_path(Path(deps["repo_root"]), rel_path, task_id)
    comments = project_threads(_read_jsonl(ledger))
    return {
        "ok": True,
        "path": rel_path,
        "task_id": task_id,
        "comments": comments,
        "count": len(comments),
        "ledger_ref": str(ledger.relative_to(Path(deps["repo_root"]).resolve())),
    }, 200


def import_comments(deps: dict[str, Any], request: Any):
    if not isinstance(request, dict):
        return {"ok": False, "error": "请求体必须是对象"}, 400
    _candidate, rel_path, task_file, error, status = _resolve_task(deps, request.get("path"))
    if error:
        return error, status
    source, source_error = _source(request.get("source"))
    if source_error:
        return {"ok": False, "error": source_error}, 400
    comments = request.get("comments")
    if not isinstance(comments, list) or not comments:
        return {"ok": False, "error": "comments 必须是非空数组"}, 400
    flat, flat_error = _flatten_comments(comments)
    if flat_error:
        return {"ok": False, "error": flat_error}, 400
    expected_rev = _text(request.get("expected_task_rev"))
    if expected_rev and expected_rev != _text(task_file.get("rev")):
        return {
            "ok": False,
            "error": "任务正文版本已变化",
            "current_task_rev": task_file.get("rev") or "",
        }, 409
    task_id = _task_id(rel_path, task_file)
    events, anchor_counts, build_error = _build_events(flat or [], source or {}, rel_path, task_file, task_id)
    if build_error:
        return {"ok": False, "error": build_error}, 400
    repo_root = Path(deps["repo_root"]).resolve()
    ledger = _ledger_path(repo_root, rel_path, task_id)
    dry_run = request.get("dry_run") is not False
    lock = deps.get("ledger_lock")

    def inspect_and_maybe_write():
        existing = _read_jsonl(ledger)
        existing_ids = {str(row.get("event_id")) for row in existing if row.get("event_id")}
        pending = [event for event in (events or []) if event["event_id"] not in existing_ids]
        if not dry_run and pending:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            payload = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in pending)
            with ledger.open("a", encoding="utf-8") as handle:
                handle.write(payload)
        projected = project_threads(existing + pending)
        return existing, pending, projected

    if lock is None:
        existing, pending, projected = inspect_and_maybe_write()
    else:
        with lock:
            existing, pending, projected = inspect_and_maybe_write()
    return {
        "ok": True,
        "dry_run": dry_run,
        "path": rel_path,
        "task_id": task_id,
        "task_rev": task_file.get("rev") or "",
        "received": len(events or []),
        "would_import": len(pending),
        "imported": 0 if dry_run else len(pending),
        "skipped": len(events or []) - len(pending),
        "anchor_counts": anchor_counts,
        "comments": projected,
        "ledger_ref": str(ledger.relative_to(repo_root)),
    }, 200


def edit_comment(deps: dict[str, Any], request: Any, actor: str = ""):
    if not isinstance(request, dict):
        return {"ok": False, "error": "请求体必须是对象"}, 400
    _candidate, rel_path, task_file, error, status = _resolve_task(deps, request.get("path"))
    if error:
        return error, status
    entry_id = _text(request.get("entry_id"), 256)
    if not entry_id:
        return {"ok": False, "error": "entry_id 不能为空"}, 400
    content = str(request.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "批注内容不能为空"}, 400
    if len(content.encode("utf-8")) > MAX_COMMENT_BYTES:
        return {"ok": False, "error": f"批注内容超过 {MAX_COMMENT_BYTES} bytes"}, 400

    task_id = _task_id(rel_path, task_file)
    repo_root = Path(deps["repo_root"]).resolve()
    ledger = _ledger_path(repo_root, rel_path, task_id)
    expected_updated_at = _text(request.get("expected_updated_at"), 128)
    editor = _text(actor, 256) or "用户"
    lock = deps.get("ledger_lock")

    def inspect_and_edit():
        rows = _read_jsonl(ledger)
        matches = [
            row for row in rows
            if row.get("event") in PROJECTABLE_EVENTS and str(row.get("entry_id") or "") == entry_id
        ]
        if not matches:
            return None, rows, "批注不存在", 404, False
        current = matches[-1]
        current_updated_at = _text(current.get("updated_at"), 128)
        if expected_updated_at and expected_updated_at != current_updated_at:
            return None, rows, "批注已被其他修改更新", 409, False
        if content == str(current.get("content") or ""):
            return current, rows, "", 200, False
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        event = dict(current)
        event.update({
            "event": EDIT_EVENT,
            "content": content,
            "content_len": len(content),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
            "updated_at": now,
            "edited_at": now,
            "edited_by": editor,
            "previous_event_id": current.get("event_id") or "",
        })
        event["event_id"] = "ext-edit-" + _digest(
            entry_id, now, content, event.get("previous_event_id"), editor,
        )
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event, rows + [event], "", 200, True

    if lock is None:
        changed, rows, edit_error, edit_status, did_change = inspect_and_edit()
    else:
        with lock:
            changed, rows, edit_error, edit_status, did_change = inspect_and_edit()
    if edit_error:
        payload = {"ok": False, "error": edit_error}
        if edit_status == 409:
            latest = next((row for row in reversed(rows) if str(row.get("entry_id") or "") == entry_id), {})
            payload["current_updated_at"] = latest.get("updated_at") or ""
            payload["current_content"] = str(latest.get("content") or "")
        return payload, edit_status
    comments = project_threads(rows)
    projected = next(
        (
            item for thread in comments
            for item in [thread, *(thread.get("replies") or [])]
            if item.get("entry_id") == entry_id
        ),
        None,
    )
    return {
        "ok": True,
        "changed": did_change,
        "path": rel_path,
        "task_id": task_id,
        "comment": projected,
        "comments": comments,
        "ledger_ref": str(ledger.relative_to(repo_root)),
    }, 200

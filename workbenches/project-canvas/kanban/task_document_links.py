"""Task-linked Markdown document access.

The task card is the allowlist.  Only Markdown files explicitly named in its
``related_paths`` frontmatter may be written, and every write carries a
machine-readable selection anchor.  This module does not edit task cards and
does not discover arbitrary documents on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


SCHEMA = "task-document-links/v1"
ANCHOR_SCHEMA = "selection-anchor/v1"
MAX_QUOTE_BYTES = 8 * 1024


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed(path: Path, roots) -> bool:
    return any(_is_relative_to(path, Path(root).resolve()) for root in roots)


def _list_values(task_file, deps, key: str):
    fm = task_file.get("frontmatter") or {}
    value = fm.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    reader = deps.get("frontmatter_block_list_values")
    if callable(reader):
        return [
            str(item).strip()
            for item in reader(task_file.get("frontmatter_block"), key)
            if str(item).strip()
        ]
    return []


def _relative_base(task_file):
    fm = task_file.get("frontmatter") or {}
    workdir = str(fm.get("workdir") or "").strip()
    if workdir:
        candidate = Path(os.path.expanduser(workdir))
        if candidate.is_file():
            return candidate.parent
        return candidate
    return Path(task_file["path"]).parent


def _resolve_document(raw_path: str, task_file):
    expanded = Path(os.path.expanduser(str(raw_path or "").strip()))
    if expanded.is_absolute():
        return expanded.resolve()
    return (_relative_base(task_file) / expanded).resolve()


def _document_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def _linked_document_rows(task_file, deps):
    roots = [Path(root).resolve() for root in deps.get("allowed_roots") or []]
    default_raw = str((task_file.get("frontmatter") or {}).get("default_context_doc") or "").strip()
    default_path = _resolve_document(default_raw, task_file) if default_raw else None
    rows = []
    seen = set()
    for raw in _list_values(task_file, deps, "related_paths"):
        if Path(raw).suffix.lower() not in {".md", ".markdown"}:
            continue
        resolved = _resolve_document(raw, task_file)
        canonical = str(resolved)
        if canonical in seen:
            continue
        seen.add(canonical)
        allowed = _allowed(resolved, roots)
        exists = resolved.is_file()
        reason = ""
        if not allowed:
            reason = "文档不在允许根目录内"
        elif not exists:
            reason = "文档不存在"
        rows.append({
            "id": _document_id(resolved),
            "path": canonical,
            "label": resolved.name,
            "is_default": bool(default_path and resolved == default_path),
            "exists": exists,
            "writable": bool(allowed and exists and os.access(resolved, os.W_OK)),
            "reason": reason,
        })
    rows.sort(key=lambda row: (not row["is_default"], row["label"].lower(), row["path"]))
    return rows


def list_linked_documents(deps, task_path: str):
    if not task_path or ".." in task_path or str(task_path).startswith("/"):
        return {"ok": False, "error": "非法任务路径"}, 400
    task_file, error = deps["read_task_file"](task_path)
    if not task_file:
        return {"ok": False, "error": error or "任务卡不存在"}, 404
    documents = _linked_document_rows(task_file, deps)
    return {
        "ok": True,
        "schema": SCHEMA,
        "task_path": task_path,
        "task_id": str((task_file.get("frontmatter") or {}).get("task_id") or ""),
        "documents": documents,
    }, 200


def _selection_anchor(task_file, task_path: str, source_quote, payload):
    locator = source_quote.get("source_locator") or {}
    context = source_quote.get("context") or {}
    selector = {
        "exact": str(source_quote.get("quote_text") or "").strip(),
        "prefix": str(locator.get("prefix") or context.get("prefix") or "")[-500:],
        "suffix": str(locator.get("suffix") or context.get("suffix") or "")[:500],
        "text_index": int(locator.get("text_index", -1)),
        "block_index": int(locator.get("block_index", -1)),
        "body_rev": str(locator.get("body_rev") or "")[:128],
    }
    fm = task_file.get("frontmatter") or {}
    return {
        "schema": ANCHOR_SCHEMA,
        "source_type": "task_body",
        "task_id": str(fm.get("task_id") or ""),
        "task_path": task_path,
        "session_id": str(payload.get("session_id") or "")[:256] or None,
        "branch_id": str(payload.get("branch_id") or "")[:256] or None,
        "section": str(source_quote.get("section") or "")[:512] or None,
        "selector": selector,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "captured_by": str(payload.get("actor") or "human_action")[:80],
    }


def _render_append_block(anchor):
    quote = str((anchor.get("selector") or {}).get("exact") or "").strip()
    quoted = "\n".join("> " + line if line else ">" for line in quote.splitlines())
    metadata = json.dumps(anchor, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"{quoted}\n\n"
        "<details>\n"
        f"<summary>来源 · {anchor.get('task_id') or '任务卡'}</summary>\n\n"
        "```json\n"
        f"{metadata}\n"
        "```\n\n"
        "</details>"
    )


def _atomic_append(path: Path, block: str):
    current = path.read_text(encoding="utf-8")
    separator = "\n\n" if current and not current.endswith("\n\n") else ""
    content = current + separator + block + "\n"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def append_selection(deps, payload):
    task_path = str(payload.get("path") or "").strip()
    target_path = str(payload.get("document_path") or "").strip()
    source_quote = payload.get("source_quote")
    if not task_path or ".." in task_path or task_path.startswith("/"):
        return {"ok": False, "error": "非法任务路径"}, 400
    if not isinstance(source_quote, dict):
        return {"ok": False, "error": "缺少选区来源"}, 400
    quote = str(source_quote.get("quote_text") or "").strip()
    if not quote:
        return {"ok": False, "error": "选中文字为空"}, 400
    if len(quote.encode("utf-8")) > MAX_QUOTE_BYTES:
        return {"ok": False, "error": "选中文字超过大小限制"}, 400

    task_file, error = deps["read_task_file"](task_path)
    if not task_file:
        return {"ok": False, "error": error or "任务卡不存在"}, 404
    documents = _linked_document_rows(task_file, deps)
    target = next((row for row in documents if row["path"] == str(Path(os.path.expanduser(target_path)).resolve())), None)
    if not target:
        return {"ok": False, "error": "目标文档没有关联到当前任务卡"}, 403
    if not target["writable"]:
        return {"ok": False, "error": target["reason"] or "目标文档不可写"}, 400

    anchor = _selection_anchor(task_file, task_path, source_quote, payload)
    block = _render_append_block(anchor)
    lock = deps.get("write_lock")
    try:
        if lock:
            with lock:
                _atomic_append(Path(target["path"]), block)
        else:
            _atomic_append(Path(target["path"]), block)
    except (OSError, UnicodeError) as exc:
        return {"ok": False, "error": f"写入关联文档失败: {exc}"}, 500
    return {
        "ok": True,
        "schema": SCHEMA,
        "task_path": task_path,
        "document": target,
        "anchor": anchor,
    }, 200

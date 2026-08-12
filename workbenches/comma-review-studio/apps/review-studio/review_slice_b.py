"""Deterministic Scientific Review v1.1 Slice B helpers.

This module belongs to the Review Studio host.  It deliberately has no model,
filesystem, or editor-core dependencies: callers provide authorized Markdown
and normalized comment records, and receive hashes, locators, and routing
metadata.
"""
from __future__ import annotations

import difflib
import hashlib
import re


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_LIST_RE = re.compile(r"^\s{0,3}(?:[-+*]|\d+[.)])\s+")
_QUOTE_RE = re.compile(r"^\s{0,3}>")
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_PROTECTED_SECTIONS = (
    ("abstract", re.compile(r"(?:^|\b)abstract(?:\b|$)|摘要", re.I)),
    ("methods", re.compile(
        r"(?:^|\b)(?:methods?|methodology|materials?\s+and\s+methods?|"
        r"statistical\s+analysis|statistics?|participants?|study\s+design|"
        r"sample\s+size|outcome\s+measures?|outcomes?|cohorts?|eligibility|"
        r"inclusion\s+and\s+exclusion|inclusion\s+criteria|exclusion\s+criteria)(?:\b|$)|"
        r"材料与方法|研究方法|实验方法|方法学|方法|统计学分析|统计分析|统计|"
        r"研究对象|受试者|参与者|研究设计|样本量|结局指标|结局|队列|"
        r"纳入与排除标准|纳入排除|纳入标准|排除标准",
        re.I,
    )),
    ("results", re.compile(r"(?:^|\b)(?:results?|findings?)(?:\b|$)|研究结果|结果|研究发现|发现", re.I)),
    ("conclusion", re.compile(r"(?:^|\b)conclusions?(?:\b|$)|结论", re.I)),
    ("references", re.compile(
        r"(?:^|\b)(?:references?|bibliography|works\s+cited)(?:\b|$)|参考文献|引用文献",
        re.I,
    )),
    ("figures-tables", re.compile(
        r"(?:^|\b)(?:figures?|figs?\.?|tables?)(?:\b|$)|图表|图例|表格|附图|附表",
        re.I,
    )),
)
_LOW_RISK_SECTIONS = re.compile(
    r"(?:^|\b)(?:discussion|acknowledg(?:e)?ments?)(?:\b|$)|讨论|致谢",
    re.I,
)
_WORDING_LEVEL_SECTIONS = re.compile(
    r"(?:^|\b)(?:introduction|background|discussion|acknowledg(?:e)?ments?)(?:\b|$)|"
    r"引言|背景|讨论|致谢",
    re.I,
)
_FIGURE_TABLE_BODY_RE = re.compile(
    r"!\[[^\]]*\]\([^\n)]+\)|<\s*(?:img|figure|table)\b|"
    r"(?:^|\b)(?:figure|fig\.?|table)\s*[A-Za-z0-9IVX.-]+|"
    r"(?:^|\s)(?:图|表)\s*[A-Za-z0-9一二三四五六七八九十.-]+",
    re.I | re.M,
)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _heading_title(line: str) -> str:
    match = _HEADING_RE.match(line.rstrip("\r\n"))
    if not match:
        return ""
    return re.sub(r"\s+#+$", "", match.group(2)).strip()


def _is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index]
    stripped = line.rstrip("\r\n")
    if not stripped.strip():
        return True
    if (_HEADING_RE.match(stripped) or _FENCE_RE.match(stripped)
            or _LIST_RE.match(stripped) or _QUOTE_RE.match(stripped)):
        return True
    if re.match(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$", stripped):
        return True
    return bool(index + 1 < len(lines) and "|" in stripped
                and _TABLE_SEPARATOR_RE.match(lines[index + 1].rstrip("\r\n")))


def segment_markdown(source: str, *, body_rev: str, task_path: str) -> list[dict]:
    """Rebuild source blocks with the same source-range contract as blocks.js.

    ``src/core/blocks.js`` delegates token boundaries to a Markdown lexer and
    then records raw source ranges while dropping whitespace tokens.  The host
    mirrors that contract here with a deterministic CommonMark-oriented lexer;
    rendered HTML is never involved.
    """
    body = str(source or "")
    if not body:
        return []
    lines = body.splitlines(keepends=True)
    offsets = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    blocks = []
    heading_stack = []
    index = 0
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        stripped = line.rstrip("\r\n")
        if not stripped.strip():
            line_index += 1
            continue
        start_line = line_index
        block_type = "paragraph"
        heading = _heading_title(line)
        if heading:
            block_type = "heading"
            level = len(_HEADING_RE.match(stripped).group(1))
            heading_stack = heading_stack[:level - 1]
            heading_stack.append(heading)
            line_index += 1
        elif _FENCE_RE.match(stripped):
            block_type = "code"
            marker = _FENCE_RE.match(stripped).group(1)
            line_index += 1
            closing = re.compile(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$")
            while line_index < len(lines):
                candidate = lines[line_index].rstrip("\r\n")
                line_index += 1
                if closing.match(candidate):
                    break
        elif _LIST_RE.match(stripped):
            block_type = "list"
            line_index += 1
            while line_index < len(lines):
                candidate = lines[line_index].rstrip("\r\n")
                if not candidate.strip():
                    if line_index + 1 < len(lines) and (
                            _LIST_RE.match(lines[line_index + 1].rstrip("\r\n"))
                            or re.match(r"^\s{2,}\S", lines[line_index + 1])):
                        line_index += 1
                        continue
                    break
                if _LIST_RE.match(candidate) or re.match(r"^\s{2,}\S", candidate):
                    line_index += 1
                    continue
                break
        elif _QUOTE_RE.match(stripped):
            block_type = "blockquote"
            line_index += 1
            while line_index < len(lines) and _QUOTE_RE.match(lines[line_index].rstrip("\r\n")):
                line_index += 1
        elif (line_index + 1 < len(lines) and "|" in stripped
              and _TABLE_SEPARATOR_RE.match(lines[line_index + 1].rstrip("\r\n"))):
            block_type = "table"
            line_index += 2
            while line_index < len(lines):
                candidate = lines[line_index].rstrip("\r\n")
                if not candidate.strip() or "|" not in candidate:
                    break
                line_index += 1
        elif re.match(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$", stripped):
            block_type = "hr"
            line_index += 1
        else:
            line_index += 1
            while line_index < len(lines) and not _is_block_start(lines, line_index):
                line_index += 1
        start = offsets[start_line]
        end = offsets[line_index] if line_index < len(lines) else len(body)
        raw = body[start:end]
        block = {
            "id": f"block-{index}",
            "index": index,
            "start": start,
            "end": end,
            "type": block_type,
            "section": heading_stack[-1] if heading_stack else "",
            "section_path": list(heading_stack),
            "raw": raw,
            "hash": _digest(raw),
            "source_locator": {
                "task_path": task_path,
                "body_rev": body_rev,
                "block_index": index,
                "start": start,
                "end": end,
                "type": block_type,
            },
        }
        blocks.append(block)
        index += 1
    return blocks


def _public_change(block: dict, change: str, *, baseline_hash: str = "",
                   wording_only: bool = False) -> dict:
    return {
        "id": block["id"],
        "change": change,
        "section": block.get("section") or "",
        "section_path": list(block.get("section_path") or []),
        "type": block.get("type") or "unknown",
        "wording_only": bool(wording_only),
        "hash": block.get("hash") or "",
        "baseline_hash": baseline_hash,
        "source_locator": dict(block.get("source_locator") or {}),
    }


def compare_blocks(baseline_blocks: list[dict], current_blocks: list[dict]) -> list[dict]:
    """Return changed block locators and hashes without Markdown body text."""
    before = [block["hash"] for block in baseline_blocks]
    after = [block["hash"] for block in current_blocks]
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changed = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            paired = min(a1 - a0, b1 - b0)
            for offset in range(paired):
                baseline_block = baseline_blocks[a0 + offset]
                current_block = current_blocks[b0 + offset]
                wording_only = (
                    baseline_block.get("type") == current_block.get("type") == "paragraph"
                    and difflib.SequenceMatcher(
                        a=baseline_block.get("raw") or "",
                        b=current_block.get("raw") or "",
                        autojunk=False,
                    ).ratio() >= 0.8
                )
                changed.append(_public_change(
                    current_block, "modified",
                    baseline_hash=baseline_block["hash"],
                    wording_only=wording_only,
                ))
            for offset in range(paired, b1 - b0):
                changed.append(_public_change(current_blocks[b0 + offset], "added"))
            for offset in range(paired, a1 - a0):
                old = dict(baseline_blocks[a0 + offset])
                old["id"] = f"removed-{old['index']}-{old['hash'][7:19]}"
                changed.append(_public_change(old, "removed", baseline_hash=old["hash"]))
        elif tag == "insert":
            changed.extend(_public_change(block, "added") for block in current_blocks[b0:b1])
        elif tag == "delete":
            for block in baseline_blocks[a0:a1]:
                old = dict(block)
                old["id"] = f"removed-{old['index']}-{old['hash'][7:19]}"
                changed.append(_public_change(old, "removed", baseline_hash=old["hash"]))
    return changed


def protected_sections(changed_blocks: list[dict], block_lookup: dict[str, dict]) -> list[str]:
    touched = []
    for change in changed_blocks:
        block = block_lookup.get(change["id"], {})
        section_path = list(change.get("section_path") or block.get("section_path") or [])
        section = str(change.get("section") or block.get("section") or "")
        if not section_path and section:
            section_path = [section]
        raw = str(block.get("raw") or "")
        block_type = str(change.get("type") or block.get("type") or "")
        categories = [
            name for name, pattern in _PROTECTED_SECTIONS
            if any(pattern.search(title) for title in section_path)
        ]
        if block_type == "table" or _FIGURE_TABLE_BODY_RE.search(raw):
            categories.append("figures-tables")
        explicitly_low_risk = any(_LOW_RISK_SECTIONS.search(title) for title in section_path)
        recognized_wording_change = bool(
            change.get("wording_only")
            and any(_WORDING_LEVEL_SECTIONS.search(title) for title in section_path)
        )
        if not categories and not (explicitly_low_risk or recognized_wording_change):
            categories.append("unclassified")
        for category in categories:
            if category not in touched:
                touched.append(category)
    return touched


def comment_snapshot(comments: list[dict]) -> dict[str, dict]:
    snapshot = {}
    for comment in comments:
        comment_id = str(comment.get("id") or "")
        if not comment_id:
            continue
        replies = {}
        for reply in comment.get("replies") or []:
            reply_id = str(reply.get("id") or "")
            if not reply_id:
                continue
            replies[reply_id] = {
                "content_hash": _digest(str(reply.get("content") or "")),
                "state": str(reply.get("state") or "active"),
                "updated_at": str(reply.get("updated_at") or ""),
            }
        snapshot[comment_id] = {
            "comment_version": int(comment.get("comment_version") or 1),
            "content_hash": _digest(str(comment.get("content") or "")),
            "lifecycle_state": str(comment.get("lifecycle_state") or "active"),
            "finding_state": str(comment.get("finding_state") or ""),
            "human_edited": bool(comment.get("human_edited")),
            "replies": replies,
        }
    return snapshot


def _comment_delta_item(comment_id: str, current: dict | None) -> dict:
    current = current or {}
    return {
        "comment_id": comment_id,
        "comment_version": int(current.get("comment_version") or 0),
        "human_edited": bool(current.get("human_edited")),
    }


def compare_comment_snapshots(baseline: dict, current: dict) -> dict[str, list[dict]]:
    delta = {key: [] for key in ("added", "edited", "withdrawn", "restored", "replied")}
    for comment_id in sorted(set(baseline) | set(current)):
        before = baseline.get(comment_id)
        after = current.get(comment_id)
        item = _comment_delta_item(comment_id, after)
        if before is None:
            delta["added"].append(item)
            continue
        if after is None:
            delta["withdrawn"].append(item)
            continue
        before_withdrawn = (before.get("lifecycle_state") == "withdrawn"
                            or before.get("finding_state") == "withdrawn")
        after_withdrawn = (after.get("lifecycle_state") == "withdrawn"
                           or after.get("finding_state") == "withdrawn")
        if not before_withdrawn and after_withdrawn:
            delta["withdrawn"].append(item)
        elif before_withdrawn and not after_withdrawn:
            delta["restored"].append(item)
        content_changed = (before.get("content_hash") != after.get("content_hash")
                           or before.get("human_edited") != after.get("human_edited"))
        state_changed = (before.get("lifecycle_state") != after.get("lifecycle_state")
                         or before.get("finding_state") != after.get("finding_state"))
        if content_changed or (state_changed and not (before_withdrawn != after_withdrawn)):
            delta["edited"].append(item)
        if before.get("replies") != after.get("replies"):
            delta["replied"].append(item)
    return delta


def resolve_anchor(comment: dict, body: str) -> str:
    if str(comment.get("kind") or "") != "anchored":
        return "ready"
    quote = str(comment.get("quote_text") or "")
    if not quote:
        return "missing"
    starts = [match.start() for match in re.finditer(re.escape(quote), body)]
    if len(starts) == 1:
        return "ready"
    if not starts:
        return "missing"
    locator = comment.get("source_locator") or {}
    exact_index = locator.get("text_index", locator.get("textIndex"))
    if isinstance(exact_index, int) and exact_index in starts:
        return "ready"
    prefix = str(locator.get("prefix") or "")
    suffix = str(locator.get("suffix") or "")
    scored = []
    for start in starts:
        score = 0
        if prefix and body[max(0, start - len(prefix)):start] == prefix:
            score += 1
        end = start + len(quote)
        if suffix and body[end:end + len(suffix)] == suffix:
            score += 1
        scored.append(score)
    best = max(scored, default=0)
    return "ready" if best and scored.count(best) == 1 else "ambiguous"


def anchor_health(comments: list[dict], body: str) -> dict:
    health = {"ready": 0, "missing": [], "ambiguous": []}
    for comment in comments:
        if (comment.get("lifecycle_state") == "withdrawn"
                or comment.get("finding_state") == "withdrawn"):
            continue
        state = resolve_anchor(comment, body)
        if state == "ready":
            health["ready"] += 1
            continue
        health[state].append({
            "comment_id": str(comment.get("id") or ""),
            "source_locator": dict(comment.get("source_locator") or {}),
        })
    return health

"""topic2feishu_xhs workflow helpers.

This module implements the deterministic parts of the Coze workflow:
search XHS notes, fetch note details, normalize fields, merge agent-produced
copywriting analysis, and optionally batch-write rows to Feishu Base.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .feed_detail import get_feed_detail
from .search import search_feeds
from .types import CommentLoadConfig, FilterOption
from .urls import make_feed_detail_url

FIELD_ORDER = [
    "笔记链接",
    "创建时间",
    "博主",
    "收藏数",
    "标题",
    "点赞数",
    "评论数",
    "转发数",
    "博主主页链接",
    "笔记标签",
    "内容",
    "深度分析",
    "标题重写",
    "内容重写",
]

FIELD_ALIASES = {
    "创建时间": ["发布时间"],
    "博主": ["账号名称"],
    "标题": ["笔记标题"],
    "转发数": ["分享数"],
    "博主主页链接": ["主页链接"],
    "内容": ["笔记内容"],
}

ANALYSIS_KEYS = ("deep_analysis", "title_re", "rewrite")
READONLY_FIELD_TYPES = {
    "auto_number",
    "lookup",
    "formula",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


@dataclass
class WorkflowResult:
    keyword: str
    notes: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    feishu: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "notes": self.notes,
            "records": self.records,
            "failures": self.failures,
            "summary": {
                "notes": len(self.notes),
                "records": len(self.records),
                "failures": len(self.failures),
                "feishu_written": self.feishu.get("written", 0) if self.feishu else 0,
            },
            "feishu": self.feishu,
        }


def collect_notes(
    page,
    *,
    keyword: str,
    number: int = 10,
    sort_by: str = "综合",
    note_type: str = "图文",
    publish_time: str = "",
    search_scope: str = "",
    location: str = "",
    load_all_comments: bool = False,
    detail_wait_min: float = 10.0,
    detail_wait_max: float = 20.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Search and fetch detail pages, returning normalized notes and failures."""
    filter_opt = FilterOption(
        sort_by=sort_by or "",
        note_type=note_type or "",
        publish_time=publish_time or "",
        search_scope=search_scope or "",
        location=location or "",
    )
    feeds = search_feeds(page, keyword, filter_opt)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feed in feeds:
        feed_dict = feed.to_dict()
        if feed_dict.get("modelType") != "note":
            continue
        feed_id = feed_dict.get("id") or ""
        xsec_token = feed_dict.get("xsecToken") or ""
        if not feed_id or not xsec_token or feed_id in seen:
            continue
        seen.add(feed_id)
        selected.append(feed_dict)
        if len(selected) >= max(0, number):
            break

    notes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    config = CommentLoadConfig(max_comment_items=0)

    for idx, feed in enumerate(selected):
        feed_id = feed["id"]
        try:
            detail = get_feed_detail(
                page,
                feed_id,
                feed["xsecToken"],
                load_all_comments=load_all_comments,
                config=config,
                keyword=keyword,
            )
            notes.append(normalize_note(detail.to_dict(), feed, keyword))
        except Exception as exc:
            failures.append({
                "feed_id": feed_id,
                "title": feed.get("displayTitle", ""),
                "reason": str(exc),
            })

        if idx + 1 < len(selected) and (idx + 1) % 3 == 0:
            time.sleep(random.uniform(detail_wait_min, detail_wait_max))

    return notes, failures


def normalize_note(detail: dict[str, Any], feed: dict[str, Any], keyword: str) -> dict[str, Any]:
    """Convert XHS detail/feed JSON into the canonical note object."""
    note = detail.get("note") or {}
    interact = note.get("interactInfo") or {}
    feed_interact = feed.get("interactInfo") or {}
    user = note.get("user") or feed.get("user") or {}

    note_id = str(note.get("noteId") or feed.get("id") or "")
    xsec_token = str(feed.get("xsecToken") or note.get("xsecToken") or "")
    user_id = str(user.get("userId") or "")
    tags = note.get("tags") if isinstance(note.get("tags"), list) else []

    content = str(note.get("body") or note.get("desc") or "")
    title = str(note.get("title") or feed.get("displayTitle") or "")

    return {
        "note_id": note_id,
        "note_url": make_feed_detail_url(note_id, xsec_token) if note_id else "",
        "create_time": _format_timestamp(note.get("time")),
        "author_nickname": str(user.get("nickname") or ""),
        "author_homepage_url": (
            f"https://www.xiaohongshu.com/user/profile/{user_id}" if user_id else ""
        ),
        "title": title,
        "content": content,
        "tags": [str(tag) for tag in tags],
        "collect_count": _parse_count(
            interact.get("collectedCount") or feed_interact.get("collectedCount")
        ),
        "like_count": _parse_count(interact.get("likedCount") or feed_interact.get("likedCount")),
        "comment_count": _parse_count(
            interact.get("commentCount") or feed_interact.get("commentCount")
        ),
        "share_count": _parse_count(
            interact.get("sharedCount") or feed_interact.get("sharedCount")
        ),
        "source_keyword": keyword,
    }


def build_records(
    notes: list[dict[str, Any]],
    analysis_items: Any | None = None,
    *,
    require_analysis: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge notes with LLM analysis and map them to Feishu record fields."""
    analysis_map = _index_analysis(analysis_items)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for idx, note in enumerate(notes):
        analysis = _match_analysis(note, analysis_map, idx)
        missing = [key for key in ANALYSIS_KEYS if not _stringify(analysis.get(key))]
        if require_analysis and missing:
            failures.append({
                "note_id": note.get("note_id", ""),
                "title": note.get("title", ""),
                "reason": f"missing analysis fields: {', '.join(missing)}",
            })
            continue

        records.append({
            "笔记链接": note.get("note_url", ""),
            "创建时间": note.get("create_time", ""),
            "博主": note.get("author_nickname", ""),
            "收藏数": _parse_count(note.get("collect_count")),
            "标题": note.get("title", ""),
            "点赞数": _parse_count(note.get("like_count")),
            "评论数": _parse_count(note.get("comment_count")),
            "转发数": _parse_count(note.get("share_count")),
            "博主主页链接": note.get("author_homepage_url", ""),
            "笔记标签": ",".join(note.get("tags") or []),
            "内容": note.get("content", ""),
            "深度分析": _stringify(analysis.get("deep_analysis")),
            "标题重写": _stringify(analysis.get("title_re")),
            "内容重写": _stringify(analysis.get("rewrite")),
        })

    return records, failures


def build_lark_batch_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build lark-cli base +record-batch-create payload."""
    return {
        "fields": FIELD_ORDER,
        "rows": [[record.get(field) for field in FIELD_ORDER] for record in records],
    }


def write_feishu_records(
    *,
    records: list[dict[str, Any]],
    base_token: str,
    table_id: str,
    lark_as: str = "user",
    lark_profile: str = "",
    skip_field_schema_check: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Batch-write records to Feishu Base via lark-cli."""
    payload = build_lark_batch_payload(records)
    ignored_fields: list[str] = []

    if not skip_field_schema_check:
        field_schema = _get_feishu_field_schema(base_token, table_id, lark_as, lark_profile)
        payload, ignored_fields = _filter_payload_by_schema(payload, field_schema)

    if not payload["fields"]:
        raise RuntimeError("no writable Feishu fields matched the configured mapping")

    payload_dir = Path.cwd() / ".topic2feishu-runtime"
    payload_dir.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".json",
        prefix="payload-",
        dir=payload_dir,
        delete=False,
    ) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        payload_path = Path(f.name)
    payload_arg = Path(".topic2feishu-runtime") / payload_path.name

    cmd = [
        *_lark_cli_cmd(lark_profile),
        "base",
        "+record-batch-create",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--json",
        f"@{payload_arg}",
        "--as",
        lark_as,
    ]
    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "lark-cli failed").strip())

    response = _loads_json_maybe(proc.stdout)
    return {
        "written": len(records) if not dry_run else 0,
        "dry_run": dry_run,
        "payload_path": str(payload_path),
        "ignored_fields": ignored_fields,
        "response": response if response is not None else proc.stdout.strip(),
    }


def load_workflow_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_analysis_json(value: str | None) -> Any | None:
    if not value:
        return None
    if value.startswith("@"):
        return load_workflow_json(value[1:])
    candidate = Path(value)
    if candidate.exists():
        return load_workflow_json(candidate)
    return json.loads(value)


def save_workflow_json(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip().replace(",", "")
    if not text:
        return 0

    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("千") or text.lower().endswith("k"):
        multiplier = 1000.0
        text = text[:-1]
    elif text.lower().endswith("w"):
        multiplier = 10000.0
        text = text[:-1]

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return int(float(match.group(0)) * multiplier) if match else 0


def _format_timestamp(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    if ts > 10_000_000_000:
        ts /= 1000.0
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return "\n".join(value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _index_analysis(items: Any | None) -> dict[str, dict[str, Any]]:
    if not items:
        return {}
    if isinstance(items, dict) and "items" in items:
        items = items["items"]
    if isinstance(items, dict) and any(key in items for key in ANALYSIS_KEYS):
        items = [items]

    indexed: dict[str, dict[str, Any]] = {}
    if isinstance(items, list):
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for key in _analysis_keys_for_item(item, idx):
                indexed[key] = item
    elif isinstance(items, dict):
        for key, item in items.items():
            if isinstance(item, dict):
                indexed[str(key)] = item
    return indexed


def _analysis_keys_for_item(item: dict[str, Any], idx: int) -> list[str]:
    keys = [str(idx)]
    for key in ("note_id", "note_url", "id", "index"):
        value = item.get(key)
        if value is not None and value != "":
            keys.append(str(value))
    return keys


def _match_analysis(
    note: dict[str, Any],
    analysis_map: dict[str, dict[str, Any]],
    idx: int,
) -> dict[str, Any]:
    for key in (note.get("note_id"), note.get("note_url"), str(idx)):
        if key is not None and str(key) in analysis_map:
            return analysis_map[str(key)]
    return {}


def _lark_cli_cmd(lark_profile: str = "") -> list[str]:
    cmd = ["lark-cli"]
    if lark_profile:
        cmd.extend(["--profile", lark_profile])
    return cmd


def _get_feishu_field_schema(
    base_token: str,
    table_id: str,
    lark_as: str,
    lark_profile: str = "",
) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            *_lark_cli_cmd(lark_profile),
            "base",
            "+field-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--as",
            lark_as,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "lark-cli +field-list failed").strip())
    data = _loads_json_maybe(proc.stdout)
    if data is None:
        raise RuntimeError("lark-cli +field-list returned non-JSON output")
    return _extract_field_items(data)


def _extract_field_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("items", "fields"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = data.get("data")
    if nested is not None:
        return _extract_field_items(nested)
    return []


def _filter_payload_by_schema(
    payload: dict[str, Any],
    field_schema: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    writable: dict[str, str] = {}
    field_types: dict[str, str] = {}
    for item in field_schema:
        name = item.get("field_name") or item.get("name")
        field_id = item.get("field_id") or item.get("id")
        field_type = str(item.get("type") or item.get("field_type") or "").lower()
        if field_type in READONLY_FIELD_TYPES:
            continue
        if name:
            writable[str(name)] = str(name)
            field_types[str(name)] = field_type
        if field_id:
            writable[str(field_id)] = str(field_id)
            field_types[str(field_id)] = field_type

    keep_indices: list[int] = []
    output_fields: list[str] = []
    ignored: list[str] = []
    for idx, field_name in enumerate(payload["fields"]):
        output_name = _resolve_field_name(field_name, writable)
        if output_name:
            keep_indices.append(idx)
            output_fields.append(output_name)
        else:
            ignored.append(field_name)

    filtered = {
        "fields": output_fields,
        "rows": [
            [
                _coerce_cell_value(row[idx], field_types.get(output_fields[pos], ""))
                for pos, idx in enumerate(keep_indices)
            ]
            for row in payload["rows"]
        ],
    }
    return filtered, ignored


def _resolve_field_name(field_name: str, writable: dict[str, str]) -> str:
    if field_name in writable:
        return writable[field_name]
    for alias in FIELD_ALIASES.get(field_name, []):
        if alias in writable:
            return writable[alias]
    return ""


def _coerce_cell_value(value: Any, field_type: str) -> Any:
    if value is None:
        return None
    if field_type == "text":
        return str(value)
    return value


def _loads_json_maybe(text: str) -> Any | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None

#!/usr/bin/env python3
"""Detect proposal-only Event boundaries from a Mario source inventory.

This is the missing Discovery layer between source inventory and Event
reconstruction.  It is deliberately conservative:

* files are evidence, not Events;
* transcripts, minutes, recordings, chat exports, photos, and attachments may
  be grouped into one evidence bundle;
* weak similarity never merges two bundles;
* participant names remain unresolved hints;
* no transcript body is copied into generated artifacts; and
* no Event ledger or downstream world-state file is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import plan_batch


SCHEMA_VERSION = "mario.event-discovery/v0"
MAX_TEXT_BYTES = 2 * 1024 * 1024
TEXT_FORMATS = {"md", "txt", "json", "jsonl", "csv", "yaml", "yml", "html"}
AUDIO_FORMATS = {"m4a", "mp3", "wav", "ogg", "aac", "flac"}
VIDEO_RECORDING_FORMATS = {"m4v", "mp4", "mov", "webm"}
RECORDING_FORMATS = AUDIO_FORMATS | VIDEO_RECORDING_FORMATS
IMAGE_FORMATS = {"image", "png", "jpg", "jpeg", "gif", "webp"}

DERIVED_PATH_TOKENS = (
    "event-candidates",
    "event-reconstruction",
    "mario-unit",
    "game-projection",
    "analysis_request",
    "会议分析底稿",
    "meeting_analysis",
    "作战单",
    "课程设计与报价",
    "_需求卡",
    "/crm/",
)
TRANSCRIPT_TOKENS = (
    "逐字",
    "转写",
    "transcript",
    "文字记录",
    "文字转录",
    "正式会谈",
    "录音稿",
)
MINUTES_TOKENS = (
    "智能纪要",
    "会议纪要",
    "飞书纪要",
    "ai notes",
    "ainotes",
)
CHAT_TOKENS = ("微信", "群聊", "chat")
PRIMARY_ROLES = {"transcript", "recording", "chat_export"}
ACTIVITY_ROLES = PRIMARY_ROLES | {"minutes"}
GENERIC_FILE_STEMS = {
    "meeting_transcript",
    "transcript",
    "转写",
    "逐字稿",
    "纪要",
    "智能纪要",
    "飞书纪要",
}
SEGMENT_TOKENS = ("前场", "晚场", "上半场", "下半场", "回程", "正式会谈", "转写1", "转写2", "转写3")
COMBINED_ACTIVITY_TOKENS = (
    "会谈与回程",
    "会谈和回程",
    "后面培训",
    "后面和",
    "前半部分和",
)
DERIVED_COPY_TOKENS = ("_Claude整理版", "Claude整理版")
COURSE_CONTAINER_RE = re.compile(
    r"^W(?P<week>\d+)-(?P<courses>C\d+(?:C\d+)*)$",
    re.I,
)
COURSE_TOKEN_RE = re.compile(r"C(?P<number>\d+)", re.I)
DATED_ACTIVITY_COMPONENT_RE = re.compile(
    r"(?<!\d)(?P<month>\d{2})(?P<day>\d{2})(?!\d).*"
    r"(?P<activity>录音|调研|访谈|会议)",
    re.I,
)
FULL_DATED_ACTIVITY_COMPONENT_RE = re.compile(
    r"(?P<date>20\d{2}-\d{2}-\d{2}).*"
    r"(?P<activity>录音|调研|访谈|会议)",
    re.I,
)

ISO_DATETIME_RE = re.compile(
    r"(?P<date>20\d{2}-\d{2}-\d{2})[ T](?P<time>\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)"
)
ZH_DATE_RE = re.compile(
    r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?:[^\n|]{0,24}?(?P<period>上午|下午|晚上|中午)?\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?))?"
)
EN_DATE_RE = re.compile(
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?P<year>20\d{2})",
    re.I,
)
EN_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*(?:\\?-|–|—|至)\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?)"
)
SPEAKER_RE = re.compile(
    r"(?im)^(?:speaker|说话人|讲话人)\s*(?P<number>\d+)\b"
)
SHORT_DATE_RE = re.compile(
    r"(?<!\d)(?P<month>0?[1-9]|1[0-2])(?:月|[/.-])"
    r"(?P<day>0?[1-9]|[12]\d|3[01])(?:日)?(?!\d)"
)
COURSE_SCHEDULE_LINE_RE = re.compile(
    r"(?im)^(?P<line>[^\n]{0,16}\bC(?P<number>\d+)\b[^\n]{0,120})$"
)


def _stable_id(prefix, value):
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _source_path(row):
    locator = row.get("content_locator") or row.get("source_locator") or {}
    return str(
        row.get("path")
        or row.get("source_path")
        or locator.get("path")
        or row.get("source_id")
        or ""
    )


def _source_ref(row):
    return (
        row.get("source_id")
        or _stable_id("source", _source_path(row))
    )


def _read_source_bytes(row):
    locator = row.get("content_locator") or {}
    locator_type = locator.get("type")
    size = int(row.get("size_bytes") or 0)
    if size > MAX_TEXT_BYTES:
        return None, "too_large_for_header_scan"
    if locator_type == "local_file":
        path = Path(locator.get("path") or "")
        if not path.is_file():
            return None, "local_source_missing"
        return path.read_bytes(), "read"
    if locator_type == "git_blob":
        repo = Path(locator.get("repo") or "").expanduser().resolve()
        blob_oid = str(locator.get("blob_oid") or "")
        if not repo.is_dir() or not re.fullmatch(r"[0-9a-fA-F]{40,64}", blob_oid):
            return None, "invalid_git_blob_locator"
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", blob_oid],
            check=False,
            capture_output=True,
        )
        if result.returncode:
            return None, "git_blob_unreadable"
        if len(result.stdout) > MAX_TEXT_BYTES:
            return None, "too_large_for_header_scan"
        return result.stdout, "read"
    return None, "metadata_only"


def _decode_text(payload):
    if payload is None:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _path_date(path, default_year=None):
    normalised = str(path).replace("\\-", "-")
    name = Path(normalised).name
    match = plan_batch.DATE_RE.search(name)
    if match:
        return match.group(0)
    english_match = EN_DATE_RE.search(name)
    if english_match:
        month = EN_MONTHS[english_match.group("month")[:3].casefold()]
        return (
            f"{int(english_match.group('year')):04d}-{month:02d}-"
            f"{int(english_match.group('day')):02d}"
        )
    year_match = re.search(r"(?P<year>20\d{2})", normalised)
    year = int(default_year or (year_match.group("year") if year_match else 0) or 0)
    short_match = SHORT_DATE_RE.search(name)
    if short_match and year:
        return (
            f"{year:04d}-{int(short_match.group('month')):02d}-"
            f"{int(short_match.group('day')):02d}"
        )
    compact_match = re.search(
        r"(?<!\d)(?P<month>0[1-9]|1[0-2])(?P<day>[0-3]\d)(?!\d)",
        name,
    )
    compact_date_context = any(
        token in name
        for token in ("录音", "调研", "访谈", "会议", "课程", "授课", "反馈", "复盘")
    )
    if compact_match and year and compact_date_context:
        return (
            f"{year:04d}-{int(compact_match.group('month')):02d}-"
            f"{int(compact_match.group('day')):02d}"
        )
    match = plan_batch.DATE_RE.search(normalised)
    if match:
        return match.group(0)
    month = re.search(r"(?P<year>20\d{2})-(?P<month>\d{2})", normalised)
    day = re.search(
        r"(?:^|[/_-])(?P<month>\d{2})(?P<day>\d{2})(?:[-_/]|$)",
        normalised,
    )
    if month and day and month.group("month") == day.group("month"):
        return f"{month.group('year')}-{day.group('month')}-{day.group('day')}"
    return None


def _label_date(value, default_year=None):
    normalised = str(value).replace("\\-", "-")
    match = plan_batch.DATE_RE.search(normalised)
    if match:
        return match.group(0)
    english_match = EN_DATE_RE.search(normalised)
    if english_match:
        month = EN_MONTHS[english_match.group("month")[:3].casefold()]
        return (
            f"{int(english_match.group('year')):04d}-{month:02d}-"
            f"{int(english_match.group('day')):02d}"
        )
    if not default_year:
        return None
    short_match = SHORT_DATE_RE.search(normalised)
    if short_match:
        return (
            f"{int(default_year):04d}-{int(short_match.group('month')):02d}-"
            f"{int(short_match.group('day')):02d}"
        )
    compact_match = re.search(
        r"(?<!\d)(?P<month>0[1-9]|1[0-2])(?P<day>[0-3]\d)(?!\d)",
        normalised,
    )
    if compact_match and any(
        token in normalised
        for token in ("录音", "调研", "访谈", "会议", "课程", "授课", "反馈", "复盘")
    ):
        return (
            f"{int(default_year):04d}-{int(compact_match.group('month')):02d}-"
            f"{int(compact_match.group('day')):02d}"
        )
    return None


def _normalise_clock(value, period=None):
    parts = value.split(":")
    hour = int(parts[0])
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    parts[0] = f"{hour:02d}"
    return ":".join(parts)


def _timeline_signals(text, row, default_year=None):
    header = text[:12000].replace("\\-", "-")
    candidates = []
    for match in ISO_DATETIME_RE.finditer(header):
        candidates.append({
            "date": match.group("date"),
            "start_time": _normalise_clock(match.group("time")),
            "basis": "source_header",
        })
    for match in ZH_DATE_RE.finditer(header):
        date = (
            f"{match.group('year')}-{int(match.group('month')):02d}-"
            f"{int(match.group('day')):02d}"
        )
        candidates.append({
            "date": date,
            "start_time": (
                _normalise_clock(match.group("time"), match.group("period"))
                if match.group("time")
                else None
            ),
            "basis": "source_header",
        })
    path = _source_path(row)
    path_date = _path_date(path, default_year=default_year)
    hint = row.get("timeline_hint") or {}
    hint_date = row.get("event_date_hint")
    if not hint_date and hint.get("source") == "path":
        hint_date = hint.get("value")
    fallback_date = hint_date or path_date
    if fallback_date:
        candidates.append({
            "date": str(fallback_date),
            "start_time": None,
            "basis": "inventory_or_path",
        })

    dates = sorted({row["date"] for row in candidates if row.get("date")})
    header_candidates = [row for row in candidates if row["basis"] == "source_header"]
    selected = header_candidates[0] if header_candidates else (candidates[0] if candidates else {})
    range_match = TIME_RANGE_RE.search(header)
    end_time = _normalise_clock(range_match.group("end")) if range_match else None
    if range_match and not selected.get("start_time"):
        selected = dict(selected)
        selected["start_time"] = _normalise_clock(range_match.group("start"))
    return {
        "date": selected.get("date"),
        "start_time": selected.get("start_time"),
        "end_time": end_time,
        "precision": (
            "datetime"
            if selected.get("start_time")
            else "date"
            if selected.get("date")
            else "unknown"
        ),
        "basis": selected.get("basis") or "unknown",
        "date_conflict": len(dates) > 1,
        "observed_dates": dates,
    }


def _duration_seconds(text):
    header = text[:2000]
    match = re.search(r"(?P<minutes>\d+)\s*min(?:ute)?s?\s*(?P<seconds>\d+)\s*s", header, re.I)
    if not match:
        match = re.search(r"(?P<minutes>\d+)\s*分钟\s*(?P<seconds>\d+)\s*秒", header)
    if not match:
        return None
    return int(match.group("minutes")) * 60 + int(match.group("seconds"))


def _course_schedule_hints(text, default_year=None):
    hints = []
    for match in COURSE_SCHEDULE_LINE_RE.finditer(text[:200000]):
        line = match.group("line")
        date = _label_date(line, default_year=default_year)
        if not date:
            continue
        hints.append({
            "course_number": int(match.group("number")),
            "date": date,
            "basis": "explicit_course_schedule_line",
        })
    return sorted(
        {
            (row["course_number"], row["date"]): row
            for row in hints
        }.values(),
        key=lambda row: (row["course_number"], row["date"]),
    )


def _role_for_source(row, text):
    path = _source_path(row)
    lowered = path.casefold()
    filename_lowered = Path(path).name.casefold()
    filename_stem = Path(path).stem.casefold()
    immediate_parent = Path(path).parent.name.casefold()
    fmt = str(row.get("format") or row.get("extension") or "").lower().lstrip(".")
    source_kind = str(row.get("source_kind") or "").casefold()
    if any(token.casefold() in lowered for token in DERIVED_PATH_TOKENS):
        return "derived_artifact"
    if fmt in RECORDING_FORMATS:
        return "recording"
    if fmt in IMAGE_FORMATS:
        return "attachment"
    if (
        "transcript" in source_kind
        or any(token.casefold() in filename_lowered for token in TRANSCRIPT_TOKENS)
        or immediate_parent in {"转写", "逐字稿", "transcript", "transcripts"}
    ):
        return "transcript"
    if (
        "meeting_notes" in source_kind
        or any(token.casefold() in filename_lowered for token in MINUTES_TOKENS)
        or filename_stem in {"纪要", "智能纪要", "会议纪要", "飞书纪要"}
        or immediate_parent in {"纪要", "智能纪要", "会议纪要"}
    ):
        return "minutes"
    if (
        any(token.casefold() in filename_lowered for token in CHAT_TOKENS)
        or immediate_parent in {"微信", "群聊", "聊天记录", "chat"}
    ):
        return "chat_export"
    if SPEAKER_RE.search(text) or "文字记录:" in text[:5000]:
        return "transcript"
    if fmt in TEXT_FORMATS:
        return "document"
    return "attachment"


def _clean_title(value):
    value = re.sub(r"\s+20\d{2}年\d{1,2}月\d{1,2}日.*$", "", value).strip()
    value = EN_DATE_RE.sub("", value).strip()
    value = re.sub(r"\bon\s*$", "", value, flags=re.I).strip()
    value = re.sub(r"^20\d{2}-\d{2}-\d{2}[-_ ]*", "", value)
    value = re.sub(r"^\d{4}[-_ ]*", "", value)
    value = re.sub(r"^(文字记录|录音主题)\s*[：:]\s*", "", value)
    return value.strip(" _-：:") or "未命名互动"


def _title_hint(text, row):
    header = text[:8000]
    for pattern in (
        r"(?im)^#\s*(?:文字记录[：:]\s*)?(.+)$",
        r"(?im)^[>\s]*录音主题[：:]\s*(.+)$",
        r"(?im)^title[：:]\s*(.+)$",
    ):
        match = re.search(pattern, header)
        if match:
            return _clean_title(match.group(1))
    path = Path(_source_path(row))
    stem = path.stem
    if stem.casefold() in {item.casefold() for item in GENERIC_FILE_STEMS}:
        parent = path.parent.name
        if parent in {"source", "原始"}:
            parent = path.parent.parent.name
        stem = parent
    return _clean_title(stem)


def _canonical_recording_stem(path):
    name = Path(path).name
    lowered = name.casefold()
    for suffix in (
        ".m4a.transcript.json",
        ".m4a.transcript.md",
        ".mp3.transcript.json",
        ".mp3.transcript.md",
        ".wav.transcript.json",
        ".wav.transcript.md",
        ".transcript.json",
        ".transcript.md",
    ):
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    stem = Path(name).stem
    stem = EN_DATE_RE.sub("", stem)
    stem = re.sub(r"20\d{2}年\d{1,2}月\d{1,2}日", "", stem)
    stem = re.sub(r"20\d{2}-\d{2}-\d{2}", "", stem)
    stem = re.sub(
        r"(?i)(?:AI[\s_-]*notes?|文字转录|文字记录|逐字稿?|转写|智能纪要|会议纪要|"
        r"record[\s_-]*audio)",
        "",
        stem,
    )
    stem = re.sub(r"(?<!\d)\d{12,}(?!\d)", "", stem)
    compact = re.sub(r"[\s_-]+", "", stem).casefold()
    if "面访" in compact and "录音" in compact:
        segment = re.search(r"录音[_\s-]*([1-9])(?:[_\s-]|$)", stem)
        return f"面访录音-{segment.group(1)}" if segment else "面访录音"
    return compact or Path(name).stem.casefold()


def _bundle_key(row):
    path = _source_path(row).replace("\\", "/")
    marker = "/原始资料/录音/"
    if marker in path:
        prefix, remainder = path.split(marker, 1)
        parts = remainder.split("/")
        if len(parts) >= 2 and re.fullmatch(r"20\d{2}-\d{2}", parts[0]):
            return f"{prefix}{marker}{parts[0]}/{parts[1]}"
    source_marker = "/source/"
    if source_marker in path:
        return path.split(source_marker, 1)[0]
    target = Path(path)
    if target.stem.casefold() in {item.casefold() for item in GENERIC_FILE_STEMS}:
        return str(target.parent)
    fmt = str(row.get("format") or row.get("extension") or "").casefold().lstrip(".")
    if fmt in (RECORDING_FORMATS | TEXT_FORMATS):
        return str(target.parent / _canonical_recording_stem(path))
    return str(target.with_suffix(""))


def _path_name_hints(path):
    stem = Path(path).stem
    pieces = [piece.strip() for piece in re.split(r"[-_]", stem) if piece.strip()]
    if not pieces:
        return []
    tail = pieces[-1]
    if (
        len(tail) <= 16
        and not re.fullmatch(r"\d+", tail)
        and tail.casefold() not in {item.casefold() for item in GENERIC_FILE_STEMS}
        and not any(token.casefold() in tail.casefold() for token in TRANSCRIPT_TOKENS)
    ):
        return [tail]
    return []


def _speaker_labels(text):
    numbers = sorted({int(match.group("number")) for match in SPEAKER_RE.finditer(text)})
    return [f"speaker-{number}" for number in numbers]


def _observation_identity(row):
    content_identity = row.get("content_identity") or {}
    return (
        content_identity.get("sha256")
        or content_identity.get("git_blob_oid")
        or row.get("source_ref")
    )


def _observation(row, default_year=None):
    fmt = str(row.get("format") or row.get("extension") or "").lower().lstrip(".")
    should_read = fmt in TEXT_FORMATS
    payload, access_status = _read_source_bytes(row) if should_read else (None, "metadata_only")
    text = _decode_text(payload)
    role = _role_for_source(row, text)
    title = _title_hint(text, row)
    timeline = _timeline_signals(text, row, default_year=default_year)
    title_date = _label_date(title, default_year=default_year)
    if title_date:
        observed_dates = sorted(
            set((timeline.get("observed_dates") or []) + [title_date])
        )
        timeline.update({
            "date": title_date,
            "basis": "source_title_or_filename",
            "date_conflict": len(observed_dates) > 1,
            "observed_dates": observed_dates,
            "precision": (
                "datetime" if timeline.get("start_time") else "date"
            ),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "source_ref": _source_ref(row),
        "source_path": _source_path(row),
        "format": fmt,
        "source_role": role,
        "content_identity": {
            "sha256": row.get("sha256"),
            "git_blob_oid": row.get("git_blob_oid"),
            "duplicate_of": row.get("duplicate_of"),
        },
        "content_access_status": access_status,
        "timeline": timeline,
        "title_hint": title,
        "duration_seconds": _duration_seconds(text),
        "speaker_labels": _speaker_labels(text),
        "participant_name_hints": _path_name_hints(_source_path(row)),
        "participant_identity_status": "unresolved_hints_only",
        "activity_anchor_hints": _course_schedule_hints(
            text,
            default_year=default_year,
        ),
        "bundle_key": _bundle_key(row),
        "sensitivity": row.get("sensitivity") or "inherit_from_source",
        "raw_body_exported": False,
    }


def _ledger_source_index(ledger_dir):
    ledger_dir = Path(ledger_dir)
    pointers = plan_batch.read_jsonl(ledger_dir / "source-pointers.jsonl")
    relations = plan_batch.read_jsonl(ledger_dir / "source-relations.jsonl")
    event_by_source = defaultdict(set)
    for row in relations:
        if row.get("source_id") and row.get("event_id"):
            event_by_source[row["source_id"]].add(row["event_id"])
    ids = {}
    hashes = defaultdict(set)
    paths = defaultdict(set)
    for row in pointers:
        source_id = row.get("source_id")
        if not source_id:
            continue
        ids[source_id] = set(event_by_source.get(source_id) or [])
        if row.get("sha256"):
            hashes[row["sha256"]].update(ids[source_id])
        if row.get("source_path"):
            paths[str(Path(row["source_path"]).expanduser())].update(ids[source_id])
    return {"ids": ids, "hashes": hashes, "paths": paths}


def _existing_event_matches(observation, source_index):
    matches = set(source_index["ids"].get(observation["source_ref"]) or [])
    identity = observation.get("content_identity") or {}
    digest = identity.get("sha256")
    if digest:
        matches.update(source_index["hashes"].get(digest) or [])
    path = observation.get("source_path")
    if path:
        matches.update(source_index["paths"].get(str(Path(path).expanduser())) or [])
    return sorted(matches)


def _event_type_hint(title, roles):
    lowered = title.casefold()
    if any(token in lowered for token in ("课程", "培训", "工作坊", "授课")):
        return "course_or_training_candidate"
    if "调研" in lowered:
        return "research_or_discovery_candidate"
    if "复盘" in lowered:
        return "review_candidate"
    if "chat_export" in roles or any(token in lowered for token in ("微信", "群聊")):
        return "chat_exchange_candidate"
    return "meeting_or_conversation_candidate"


def _primary_episode_key(observation):
    path = Path(observation["source_path"])
    return str(path.parent / _canonical_recording_stem(path.name))


def _clock_semantic_conflict(title, times):
    hours = [
        int(start.split(":", 1)[0])
        for start, _ in times
        if start
    ]
    if not hours:
        return False, []
    if "夜" in title and all(hour < 12 for hour in hours):
        return True, ["title_indicates_night_but_source_clock_indicates_morning"]
    if "上午" in title and all(hour >= 12 for hour in hours):
        return True, [
            "container_indicates_morning_but_source_clock_indicates_afternoon_or_evening"
        ]
    if "中午" in title and all(hour < 11 or hour >= 15 for hour in hours):
        return True, [
            "container_indicates_lunch_but_source_clock_is_outside_lunch_period"
        ]
    return False, []


def _build_candidate(bundle_key, observations, source_index):
    observations = sorted(observations, key=lambda row: row["source_path"])
    bundle_counts = Counter(row["bundle_key"] for row in observations)
    by_identity = defaultdict(list)
    for row in observations:
        by_identity[_observation_identity(row)].append(row)
    representatives = []
    representative_refs = set()
    for rows in by_identity.values():
        representative = sorted(
            rows,
            key=lambda row: (
                -bundle_counts[row["bundle_key"]],
                row["source_path"],
            ),
        )[0]
        representatives.append(representative)
        representative_refs.add(representative["source_ref"])
    representatives = sorted(representatives, key=lambda row: row["source_path"])
    activity = [
        row for row in representatives if row["source_role"] in ACTIVITY_ROLES
    ]
    primary = [
        row for row in representatives if row["source_role"] in PRIMARY_ROLES
    ]
    title_rows = primary + [row for row in activity if row not in primary]
    titles = [
        row["title_hint"]
        for row in title_rows
        if row.get("title_hint") and row["title_hint"] != "未命名互动"
    ]
    title = titles[0] if titles else Path(bundle_key).name
    timeline_rows = [row["timeline"] for row in activity if row["timeline"].get("date")]
    dates = sorted({row["date"] for row in timeline_rows})
    times = sorted(
        {
            (row.get("start_time") or "", row.get("end_time") or "")
            for row in timeline_rows
            if row.get("start_time")
        }
    )
    semantic_clock_conflict, clock_conflict_reasons = _clock_semantic_conflict(
        title,
        times,
    )
    existing = sorted(
        {
            event_id
            for row in observations
            for event_id in _existing_event_matches(row, source_index)
        }
    )
    primary_names = "\n".join(Path(row["source_path"]).name for row in primary)
    split_signals = sorted(
        {
            token
            for token in SEGMENT_TOKENS + COMBINED_ACTIVITY_TOKENS
            if token.casefold() in primary_names.casefold()
        }
    )
    primary_episode_count = len({_primary_episode_key(row) for row in primary})
    multi_primary = primary_episode_count > 1
    text_primary = [
        row
        for row in primary
        if row["source_role"] in {"transcript", "chat_export"}
    ]
    readable_text_primary = [
        row
        for row in text_primary
        if row.get("content_access_status") == "read"
    ]
    combined_activity_signal = any(
        token.casefold() in primary_names.casefold()
        for token in COMBINED_ACTIVITY_TOKENS
    )
    pre_event_evidence_context = any(
        token in row["source_path"].replace("\\", "/")
        for row in observations
        for token in ("/课前资料/", "/课前/")
    )
    if len(existing) > 1:
        boundary_status = "existing_ledger_boundary_conflict"
    elif len(existing) == 1:
        boundary_status = "already_represented_in_event_ledger"
    elif not dates:
        boundary_status = "needs_date_review"
    elif pre_event_evidence_context:
        boundary_status = "needs_parent_event_attachment_review"
    elif multi_primary or combined_activity_signal:
        boundary_status = "needs_split_review"
    elif not primary:
        boundary_status = "needs_event_confirmation_from_minutes_only"
    elif text_primary and not readable_text_primary:
        boundary_status = "needs_source_access_review"
    else:
        boundary_status = "candidate_ready_for_event_review"
    source_refs = []
    for row in observations:
        relation = (
            "duplicate_version"
            if row["source_ref"] not in representative_refs
            else "primary_candidate"
            if row["source_role"] in PRIMARY_ROLES
            else "supporting_candidate"
        )
        source_refs.append({
            "source_ref": row["source_ref"],
            "source_path": row["source_path"],
            "source_role": row["source_role"],
            "relation_proposal": relation,
            "sha256": (row.get("content_identity") or {}).get("sha256"),
            "raw_body_exported": False,
        })
    name_hints = sorted(
        {
            hint
            for row in observations
            for hint in row.get("participant_name_hints") or []
        }
    )
    speaker_labels = sorted(
        {
            label
            for row in observations
            for label in row.get("speaker_labels") or []
        }
    )
    roles = sorted({row["source_role"] for row in observations})
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": _stable_id("event-detection", bundle_key),
        "candidate_status": "proposal_only_no_write",
        "proposed_title": title,
        "event_type_hint": _event_type_hint(title, roles),
        "time_hint": {
            "date": dates[0] if len(dates) == 1 else None,
            "start_time": (
                times[0][0]
                if len(times) == 1 and not semantic_clock_conflict
                else None
            ),
            "end_time": (
                times[0][1]
                if len(times) == 1 and times[0][1] and not semantic_clock_conflict
                else None
            ),
            "date_candidates": dates,
            "time_candidates": [
                {"start_time": start, "end_time": end or None}
                for start, end in times
            ],
            "status": (
                "conflict"
                if len(dates) > 1 or len(times) > 1
                else "source_clock_semantic_conflict"
                if semantic_clock_conflict
                else "source_or_path_supported"
                if dates
                else "unknown"
            ),
            "conflict_reasons": (
                clock_conflict_reasons
                if semantic_clock_conflict
                else []
            ),
        },
        "participant_hints": {
            "speaker_labels": speaker_labels,
            "path_name_hints": name_hints,
            "identity_status": "unresolved_hints_only",
        },
        "boundary": {
            "bundle_key": bundle_key,
            "bundle_keys": sorted({row["bundle_key"] for row in observations}),
            "status": boundary_status,
            "source_roles": roles,
            "primary_source_count": len(primary),
            "primary_episode_count": primary_episode_count,
            "readable_text_primary_count": len(readable_text_primary),
            "split_signals": split_signals,
            "single_source_multi_event_signal": combined_activity_signal,
            "evidence_stage_hint": (
                "before" if pre_event_evidence_context else "unclassified"
            ),
            "rule": (
                "One real interaction is the candidate unit. Multiple evidence files "
                "remain one bundle only by strong same-origin structure; multiple "
                "primary segments require review."
            ),
        },
        "source_refs": source_refs,
        "existing_event_matches": existing,
        "semantic_analysis_status": "not_run",
        "next_allowed_step": "human_or_model_event_boundary_review",
        "promotion_allowed": False,
        "fact_boundary": (
            "Candidate proves source-backed interaction signals only; it does not "
            "confirm participant identity, Event facts, project state, opportunity "
            "state, or world-state change."
        ),
    }


def _is_derived_copy_path(path):
    return any(token.casefold() in str(path).casefold() for token in DERIVED_COPY_TOKENS)


def _path_is_within(path, root):
    path = Path(path)
    root = Path(root)
    return path == root or root in path.parents


def _dated_activity_anchor(path, default_year):
    path = Path(path)
    parts = path.parts
    for index, component in enumerate(parts[:-1]):
        full_match = FULL_DATED_ACTIVITY_COMPONENT_RE.search(component)
        compact_match = DATED_ACTIVITY_COMPONENT_RE.search(component)
        if full_match:
            return {
                "anchor": Path(*parts[: index + 1]),
                "date": full_match.group("date"),
                "activity": full_match.group("activity"),
            }
        if compact_match and default_year:
            return {
                "anchor": Path(*parts[: index + 1]),
                "date": (
                    f"{int(default_year):04d}-"
                    f"{int(compact_match.group('month')):02d}-"
                    f"{int(compact_match.group('day')):02d}"
                ),
                "activity": compact_match.group("activity"),
            }
    return None


def _course_container_occurrences(path):
    path = Path(path)
    parts = path.parts
    occurrences = []
    for index, component in enumerate(parts[:-1]):
        match = COURSE_CONTAINER_RE.fullmatch(component)
        if not match:
            continue
        numbers = tuple(
            int(item.group("number"))
            for item in COURSE_TOKEN_RE.finditer(match.group("courses"))
        )
        occurrences.append({
            "anchor": Path(*parts[: index + 1]),
            "parent": Path(*parts[:index]),
            "component": component,
            "course_numbers": numbers,
        })
    return occurrences


def _merge_activity_groups(groups):
    keys = sorted(groups)
    parent = {key: key for key in keys}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        canonical = min(left_root, right_root)
        parent[right_root if canonical == left_root else left_root] = canonical

    by_identity = defaultdict(set)
    for key, descriptor in groups.items():
        for row in descriptor["rows"]:
            by_identity[_observation_identity(row)].add(key)
    for identity_keys in by_identity.values():
        identity_keys = sorted(identity_keys)
        for key in identity_keys[1:]:
            union(identity_keys[0], key)
    by_course_date_activity = defaultdict(list)
    for key, descriptor in groups.items():
        anchor = Path(descriptor["anchor"])
        course_parent = next(
            (
                str(Path(*anchor.parts[: index + 1]))
                for index, component in enumerate(anchor.parts)
                if COURSE_CONTAINER_RE.fullmatch(component)
            ),
            None,
        )
        if course_parent:
            by_course_date_activity[
                (
                    course_parent,
                    descriptor["date"],
                    descriptor["activity"],
                )
            ].append(key)
    for related_keys in by_course_date_activity.values():
        related_keys = sorted(related_keys)
        for key in related_keys[1:]:
            union(related_keys[0], key)

    merged = {}
    for key in keys:
        canonical = find(key)
        target = merged.setdefault(canonical, {
            "rows": [],
            "anchors": [],
            "dates": set(),
            "activities": set(),
        })
        source = groups[key]
        target["rows"].extend(source["rows"])
        target["anchors"].append(source["anchor"])
        target["dates"].add(source["date"])
        target["activities"].add(source["activity"])
    return merged


def _stage_coverage(rows, anchor):
    stages = set()
    for row in rows:
        text = row["source_path"].replace("\\", "/")
        if "课前" in text:
            stages.add("before")
        if "课件" in text or "现场" in text:
            stages.add("during_support")
        if "课后" in text:
            stages.add("after")
    return sorted(stages)


def _container_date(rows, *, start=None, end=None, course_number=None):
    counts = Counter()
    for row in rows:
        if course_number is not None:
            marker = f"C{course_number}".casefold()
            evidence_text = (
                Path(row["source_path"]).name
                + "\n"
                + str(row.get("title_hint") or "")
            ).casefold()
            if marker not in evidence_text:
                continue
        date = (row.get("timeline") or {}).get("date")
        if not date:
            continue
        if start and date < start:
            continue
        if end and date > end:
            continue
        counts[date] += 1
    if not counts:
        return None, []
    ranked = counts.most_common()
    selected = ranked[0][0] if len(ranked) == 1 or ranked[0][1] > ranked[1][1] else None
    return selected, sorted(counts)


def _container_candidate(
    *,
    bundle_key,
    rows,
    source_index,
    title,
    event_type,
    boundary_basis,
    date=None,
    date_candidates=None,
    stage_coverage=None,
    confirmation_required=False,
    organizer_defined_container=True,
):
    candidate = _build_candidate(bundle_key, rows, source_index)
    candidate["proposed_title"] = title
    candidate["event_type_hint"] = event_type
    dates = sorted(set(date_candidates or ([date] if date else [])))
    candidate["time_hint"].update({
        "date": date,
        "date_candidates": dates,
        "start_time": None,
        "end_time": None,
        "time_candidates": [],
        "status": (
            "organizer_container_supported"
            if date
            else "container_date_conflict"
            if dates
            else "unknown"
        ),
        "conflict_reasons": (
            ["multiple_dates_inside_activity_container"]
            if dates and not date
            else []
        ),
    })
    candidate["boundary"].update({
        "status": (
            "needs_event_confirmation_from_delivery_container"
            if confirmation_required
            else "candidate_ready_for_event_review"
            if date
            else "needs_date_review"
        ),
        "basis": boundary_basis,
        "organizer_defined_container": organizer_defined_container,
        "source_defined_container": not organizer_defined_container,
        "stage_coverage": list(stage_coverage or []),
        "segment_review_recommended": (
            candidate["boundary"].get("primary_episode_count", 0) > 1
        ),
        "rule": (
            (
                "An organizer-defined activity container outranks individual evidence "
                "files. Multiple recordings inside it are segment candidates, not "
                "automatic Event splits."
            )
            if organizer_defined_container
            else (
                "A single dated exported-meeting folder groups recordings, transcripts, "
                "minutes, and direct supporting files as evidence for one Event. Distinct "
                "dates or explicit split signals prevent this automatic grouping."
            )
        ),
    })
    return candidate


def _exported_meeting_folder_groups(observations, consumed_refs, *, start=None, end=None):
    """Find flat folders that represent one exported meeting evidence bundle.

    This covers source drops where a recorder exports media plus PDF transcript
    and AI Notes into one customer folder.  It intentionally does not apply to
    ordinary Markdown/text folders, and it refuses folders with multiple dates
    or explicit front/back-session split labels.
    """

    by_parent = defaultdict(list)
    for row in observations:
        if row["source_ref"] in consumed_refs or row["source_role"] == "derived_artifact":
            continue
        by_parent[str(Path(row["source_path"]).parent)].append(row)

    groups = []
    interaction_tokens = ("面访", "会谈", "访谈", "会议", "调研", "沟通", "交流", "讨论")
    supporting_formats = {
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "image",
        "png",
        "jpg",
        "jpeg",
    }
    for parent_value, rows in sorted(by_parent.items()):
        activity = [row for row in rows if row["source_role"] in ACTIVITY_ROLES]
        if len(activity) < 2:
            continue
        if not any(
            row.get("format") == "pdf"
            or row.get("format") in VIDEO_RECORDING_FORMATS
            for row in activity
        ):
            continue
        activity_names = "\n".join(Path(row["source_path"]).name for row in activity)
        if any(token.casefold() in activity_names.casefold() for token in SEGMENT_TOKENS):
            continue
        dates = sorted({
            row["timeline"]["date"]
            for row in activity
            if row.get("timeline", {}).get("date")
            and (not start or row["timeline"]["date"] >= start)
            and (not end or row["timeline"]["date"] <= end)
        })
        if len(dates) != 1:
            continue
        primary_episodes = {
            _primary_episode_key(row)
            for row in activity
            if row["source_role"] in PRIMARY_ROLES
        }
        parent = Path(parent_value)
        explicit_event_container = any(
            token.casefold() in parent.name.casefold()
            for token in interaction_tokens
        )
        if len(primary_episodes) > 1 and not explicit_event_container:
            continue
        included = [
            row
            for row in rows
            if row["source_role"] in ACTIVITY_ROLES
            or (
                row.get("format") in supporting_formats
                and not Path(row["source_path"]).name.startswith(".")
            )
        ]
        title = parent.name
        if explicit_event_container and re.search(
            r"(?<!\d)\d{1,2}[-/.]\d{1,2}(?!\d)",
            parent.name,
        ):
            title = f"{parent.parent.name} {parent.name}"
        groups.append({
            "anchor": parent,
            "date": dates[0],
            "rows": included,
            "title": title,
        })
    return groups


def _container_candidates(observations, source_index, scope):
    start = (scope.get("time_window") or {}).get("start")
    end = (scope.get("time_window") or {}).get("end")
    default_year = int(start[:4]) if start and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", start) else None
    eligible = [
        row for row in observations
        if row["source_role"] != "derived_artifact"
        and not _is_derived_copy_path(row["source_path"])
    ]
    schedule_dates = defaultdict(Counter)
    for row in eligible:
        for hint in row.get("activity_anchor_hints") or []:
            date = hint.get("date")
            if date and (not start or date >= start) and (not end or date <= end):
                schedule_dates[int(hint["course_number"])][date] += 1

    activity_groups = {}
    for row in eligible:
        descriptor = _dated_activity_anchor(row["source_path"], default_year)
        if not descriptor:
            continue
        key = str(descriptor["anchor"])
        group = activity_groups.setdefault(key, {
            **descriptor,
            "rows": [],
        })
        group["rows"].append(row)
    activity_groups = {
        key: value
        for key, value in activity_groups.items()
        if any(row["source_role"] in ACTIVITY_ROLES for row in value["rows"])
    }

    candidates = []
    consumed_refs = set()
    for key, descriptor in _merge_activity_groups(activity_groups).items():
        rows = descriptor["rows"]
        consumed_refs.update(row["source_ref"] for row in rows)
        dates = sorted(descriptor["dates"])
        date = dates[0] if len(dates) == 1 else None
        activities = sorted(descriptor["activities"])
        title = f"{date or '日期待定'} {'/'.join(activities)}活动"
        candidates.append(_container_candidate(
            bundle_key=f"activity-container:{key}",
            rows=rows,
            source_index=source_index,
            title=title,
            event_type="research_or_discovery_candidate",
            boundary_basis="dated_activity_directory",
            date=date,
            date_candidates=dates,
        ))

    course_occurrences = {}
    for row in eligible:
        if row["source_ref"] in consumed_refs:
            continue
        for occurrence in _course_container_occurrences(row["source_path"]):
            key = str(occurrence["anchor"])
            course_occurrences.setdefault(key, {**occurrence, "rows": []})[
                "rows"
            ].append(row)

    by_parent_course = defaultdict(list)
    for occurrence in course_occurrences.values():
        for course_number in occurrence["course_numbers"]:
            by_parent_course[(str(occurrence["parent"]), course_number)].append(
                occurrence
            )

    selected_course_anchors = {}
    for parent_course, occurrences in by_parent_course.items():
        exact = [
            row for row in occurrences
            if len(row["course_numbers"]) == 1
        ]
        preferred = sorted(
            exact or occurrences,
            key=lambda row: str(row["anchor"]),
        )[0]
        course_number = parent_course[1]
        combined_rows = []
        for occurrence in occurrences:
            occurrence_rows = list(occurrence["rows"])
            if len(occurrence["course_numbers"]) > 1:
                marker = f"C{course_number}".casefold()
                occurrence_rows = [
                    row for row in occurrence_rows
                    if marker in (
                        str(
                            Path(row["source_path"]).relative_to(
                                occurrence["anchor"]
                            )
                        )
                        + "\n"
                        + str(row.get("title_hint") or "")
                    ).casefold()
                ]
            combined_rows.extend(occurrence_rows)
        selected_course_anchors[parent_course] = {
            **preferred,
            "rows": sorted(
                {row["source_ref"]: row for row in combined_rows}.values(),
                key=lambda row: row["source_path"],
            ),
        }

    for (parent, course_number), occurrence in sorted(selected_course_anchors.items()):
        rows = [
            row for row in occurrence["rows"]
            if row["source_ref"] not in consumed_refs
        ]
        stages = _stage_coverage(rows, occurrence["anchor"])
        if len(stages) < 2 and not any(
            row["source_role"] in ACTIVITY_ROLES for row in rows
        ):
            continue
        date, dates = _container_date(
            rows,
            start=start,
            end=end,
            course_number=course_number,
        )
        schedule_candidates = sorted(schedule_dates.get(course_number) or {})
        if not date and dates and schedule_candidates:
            overlap = sorted(set(dates) & set(schedule_candidates))
            if len(overlap) == 1:
                date = overlap[0]
        if not date and schedule_candidates:
            ranked_schedule = schedule_dates[course_number].most_common()
            top_is_clear = (
                len(ranked_schedule) == 1
                or ranked_schedule[0][1] > ranked_schedule[1][1]
            )
            top_is_compatible = (
                not dates or ranked_schedule[0][0] in dates
            )
            if top_is_clear and top_is_compatible:
                date = ranked_schedule[0][0]
                dates = sorted(set(dates) | {date})
        consumed_refs.update(row["source_ref"] for row in rows)
        candidates.append(_container_candidate(
            bundle_key=(
                f"course-container:{occurrence['anchor']}:C{course_number}"
            ),
            rows=rows,
            source_index=source_index,
            title=f"C{course_number} 课程交付",
            event_type="course_or_training_candidate",
            boundary_basis="course_delivery_directory",
            date=date,
            date_candidates=dates,
            stage_coverage=stages,
            confirmation_required="after" not in stages,
        ))

    for group in _exported_meeting_folder_groups(
        eligible,
        consumed_refs,
        start=start,
        end=end,
    ):
        rows = group["rows"]
        consumed_refs.update(row["source_ref"] for row in rows)
        candidates.append(_container_candidate(
            bundle_key=f"exported-meeting-folder:{group['anchor']}",
            rows=rows,
            source_index=source_index,
            title=group["title"],
            event_type="meeting_or_conversation_candidate",
            boundary_basis="same_directory_single_dated_interaction",
            date=group["date"],
            date_candidates=[group["date"]],
            organizer_defined_container=False,
        ))
    consumed_identities = {
        _observation_identity(row)
        for row in observations
        if row["source_ref"] in consumed_refs
    }
    consumed_refs.update(
        row["source_ref"]
        for row in observations
        if _observation_identity(row) in consumed_identities
    )
    return candidates, consumed_refs


def _review_question(candidate):
    status = candidate["boundary"]["status"]
    if status == "candidate_ready_for_event_review" or status == "already_represented_in_event_ledger":
        return None
    evidence = [row["source_ref"] for row in candidate["source_refs"]]
    title = candidate["proposed_title"]
    date = candidate["time_hint"].get("date") or "日期待定"
    if status == "needs_split_review":
        question = f"{date}「{title}」中的多个主证据片段是一场连续 Event，还是应拆成多场 Event？"
        options = ["一场连续 Event", "拆成多场 Event", "暂不裁决"]
    elif status == "needs_event_confirmation_from_minutes_only":
        question = f"{date}「{title}」的纪要是否对应一场真实发生的 Event？"
        options = ["是，建立 Event 候选", "否，只是派生材料", "暂不裁决"]
    elif status == "needs_event_confirmation_from_delivery_container":
        question = f"{date}「{title}」的交付资料束是否对应一场真实发生的课程 Event？"
        options = ["是，课程已发生", "否，只是计划或备课资料", "暂不裁决"]
    elif status == "needs_parent_event_attachment_review":
        question = f"{date}「{title}」是独立 Event，还是相邻正式活动的课前证据？"
        options = ["独立 Event", "挂到相邻正式 Event", "暂不裁决"]
    elif status == "existing_ledger_boundary_conflict":
        question = f"{date}「{title}」的证据为何同时命中多个正式 Event？"
        options = ["保持多个 Event", "应合并为一场 Event", "来源绑定有误"]
    elif status == "needs_source_access_review":
        question = f"{date}「{title}」是否有可读取的原始转写或聊天证据可供 Event 审核？"
        options = ["有，补充可读来源", "没有，只保留元数据候选", "暂不处理"]
    else:
        question = f"「{title}」对应 Event 的发生日期是什么？"
        options = ["补充发生日期", "不是 Event", "暂不裁决"]
    return {
        "schema_version": SCHEMA_VERSION,
        "review_id": _stable_id("event-boundary-review", candidate["candidate_id"]),
        "impact": "high",
        "question_type": "event_boundary",
        "candidate_id": candidate["candidate_id"],
        "evidence_refs": evidence,
        "question": question,
        "answer_options": options,
        "changes_if_answered": "Event boundary or existence",
    }


def discover(batch_root, ledger_dir=None):
    batch_root = Path(batch_root).expanduser().resolve()
    inventory = plan_batch.read_jsonl(batch_root / "source-inventory.jsonl")
    scope = json.loads((batch_root / "batch-scope.json").read_text(encoding="utf-8"))
    ledger_dir = Path(ledger_dir or scope["event_ledger_dir"]).expanduser().resolve()
    source_index = _ledger_source_index(ledger_dir)
    start = (scope.get("time_window") or {}).get("start")
    default_year = (
        int(start[:4])
        if start and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", start)
        else None
    )
    observations = [
        _observation(row, default_year=default_year)
        for row in inventory
    ]
    container_candidates, consumed_refs = _container_candidates(
        observations,
        source_index,
        scope,
    )

    observations_by_bundle = defaultdict(list)
    non_event = []
    for row in observations:
        if row["source_ref"] in consumed_refs:
            continue
        if row["source_role"] != "derived_artifact":
            observations_by_bundle[row["bundle_key"]].append(row)
        else:
            non_event.append({
                "schema_version": SCHEMA_VERSION,
                "source_ref": row["source_ref"],
                "source_path": row["source_path"],
                "source_role": row["source_role"],
                "classification": "does_not_create_event_candidate",
                "reason": (
                    "derived_or_context_material_is_evidence_only"
                    if row["source_role"] == "derived_artifact"
                    else "no_activity_signal_detected"
                ),
            })

    parent = {key: key for key in observations_by_bundle}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        canonical = min(left_root, right_root)
        other = right_root if canonical == left_root else left_root
        parent[other] = canonical

    bundles_by_identity = defaultdict(set)
    for bundle_key, rows in observations_by_bundle.items():
        for row in rows:
            bundles_by_identity[_observation_identity(row)].add(bundle_key)
    for bundle_keys in bundles_by_identity.values():
        bundle_keys = sorted(bundle_keys)
        for bundle_key in bundle_keys[1:]:
            union(bundle_keys[0], bundle_key)

    merged_bundles = defaultdict(list)
    for bundle_key, rows in observations_by_bundle.items():
        merged_bundles[find(bundle_key)].extend(rows)

    candidates = list(container_candidates)
    for bundle_key, rows in sorted(merged_bundles.items()):
        if not any(row["source_role"] in ACTIVITY_ROLES for row in rows):
            for row in rows:
                non_event.append({
                    "schema_version": SCHEMA_VERSION,
                    "source_ref": row["source_ref"],
                    "source_path": row["source_path"],
                    "source_role": row["source_role"],
                    "classification": "does_not_create_event_candidate",
                    "reason": "attachment_without_activity_evidence",
                })
            continue
        candidates.append(_build_candidate(bundle_key, rows, source_index))

    reviews = [row for row in (_review_question(candidate) for candidate in candidates) if row]
    candidates = sorted(
        candidates,
        key=lambda row: (
            row["time_hint"].get("date") or "",
            row["proposed_title"],
            row["candidate_id"],
        ),
    )
    non_event = sorted(non_event, key=lambda row: (row["source_path"], row["source_ref"]))
    reviews = sorted(reviews, key=lambda row: row["review_id"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "batch_scope_hash": scope.get("scope_hash"),
        "source_observation_count": len(observations),
        "event_detection_candidate_count": len(candidates),
        "ready_candidate_count": sum(
            row["boundary"]["status"] == "candidate_ready_for_event_review"
            for row in candidates
        ),
        "already_ledgered_count": sum(
            row["boundary"]["status"] == "already_represented_in_event_ledger"
            for row in candidates
        ),
        "boundary_review_count": len(reviews),
        "non_event_source_count": len(non_event),
        "raw_body_exported": False,
        "canonical_writes": [],
        "outputs": {
            "source_observations": str(batch_root / "source-observations.jsonl"),
            "event_detection_candidates": str(batch_root / "event-detection-candidates.jsonl"),
            "event_detection_review_queue": str(batch_root / "event-detection-review-queue.jsonl"),
            "non_event_sources": str(batch_root / "non-event-sources.jsonl"),
        },
    }
    report["report_hash"] = plan_batch.batch_hash(report)
    plan_batch.write_jsonl(batch_root / "source-observations.jsonl", observations)
    plan_batch.write_jsonl(batch_root / "event-detection-candidates.jsonl", candidates)
    plan_batch.write_jsonl(batch_root / "event-detection-review-queue.jsonl", reviews)
    plan_batch.write_jsonl(batch_root / "non-event-sources.jsonl", non_event)
    plan_batch.write_json(batch_root / "event-discovery-report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=plan_batch.DEFAULT_BATCH_ROOT)
    parser.add_argument("--event-ledger-dir", type=Path)
    args = parser.parse_args(argv)
    report = discover(args.batch_root, args.event_ledger_dir)
    print(json.dumps({
        "ok": True,
        "batch_root": str(Path(args.batch_root).expanduser().resolve()),
        "candidate_count": report["event_detection_candidate_count"],
        "boundary_review_count": report["boundary_review_count"],
        "report_hash": report["report_hash"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

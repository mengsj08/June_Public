"""Read-only evidence adapter for Claude Fleet, Agent-Mail, and map archives.

Claude Fleet contributes structured physical-line context for active Claude and
Codex sessions. Agent-Mail contributes wider archive coverage and fork/shard
deduplication. Conversation Map manifests add archive state. None of these
observations becomes a task or graph fact until another subsystem records a
relation with an explicit assertion type.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


SCHEMA = "session-evidence-search/v1"
AGENT_MAIL_ROW = re.compile(r"^\s*\[(?P<kind>cl|cx)]\s+(?P<day>\d{2}-\d{2})\s+(?P<sid>\S+)\s*(?P<title>.*)$")


def _fleet_search(query, limit, url="http://127.0.0.1:7878/api/search"):
    # 返回 None = 服务不可达(与「可达但零命中」的 [] 区分,供 sources 诚实标注)
    endpoint = url + "?" + urllib.parse.urlencode({"q": query, "limit": limit})
    try:
        with urllib.request.urlopen(endpoint, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
        return None
    return data.get("hits") if isinstance(data, dict) and isinstance(data.get("hits"), list) else []


def _agent_mail_search(query, days, limit, cli_path):
    # 返回 None = 调用失败(与「成功但无输出」的 "" 区分)
    try:
        result = subprocess.run(
            ["python3", str(cli_path), "find", query, "--days", str(days), "--max", str(limit)],
            capture_output=True,
            text=True,
            timeout=65,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout or ""


def _parse_agent_mail(text):
    rows = []
    current = None
    for line in str(text or "").splitlines():
        match = AGENT_MAIL_ROW.match(line)
        if match:
            current = {
                "source": "agent_mail",
                "platform": "claude" if match.group("kind") == "cl" else "codex",
                "session_id_prefix": match.group("sid"),
                "observed_day": match.group("day"),
                "title": match.group("title").strip(),
                "excerpt": "",
            }
            rows.append(current)
            continue
        if current and line.strip().startswith("…"):
            current["excerpt"] = line.strip().strip("…")
    return rows


def _manifest_index(deps):
    result, status = deps["list_conversation_maps"]()
    if status != 200 or not isinstance(result, dict):
        return []
    return [row for row in result.get("maps") or [] if isinstance(row, dict)]


def _archive_match(session_id, prefix, maps):
    session_id = str(session_id or "")
    prefix = str(prefix or "")
    for row in maps:
        thread_id = str(row.get("thread_id") or "")
        if session_id and thread_id == session_id:
            return row
        if prefix and thread_id.startswith(prefix):
            return row
    return None


def search(deps, query, *, days=90, limit=20):
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "缺少搜索词"}, 400
    if len(query) > 200:
        return {"ok": False, "error": "搜索词过长"}, 400
    try:
        days = max(1, min(3650, int(days)))
        limit = max(1, min(60, int(limit)))
    except (TypeError, ValueError):
        return {"ok": False, "error": "days / limit 无效"}, 400

    fleet_search = deps.get("fleet_search") or (lambda _query, _limit: None)
    agent_mail_search = deps.get("agent_mail_search") or (lambda _query, _days, _limit, _cli: None)
    fleet_hits = fleet_search(query, limit)
    fleet_available = fleet_hits is not None
    agent_mail_text = agent_mail_search(query, days, limit, deps.get("agent_mail_cli"))
    agent_mail_available = agent_mail_text is not None
    maps = _manifest_index(deps)
    rows = []
    seen = set()
    seen_sessions = set()
    for hit in fleet_hits or []:
        if not isinstance(hit, dict):
            continue
        session_id = str(hit.get("session_id") or "")
        key = (str(hit.get("platform") or ""), session_id, int(hit.get("line") or 0))
        if key in seen:
            continue
        seen.add(key)
        if session_id:
            seen_sessions.add((str(hit.get("platform") or ""), session_id))
        archived = _archive_match(session_id, "", maps)
        rows.append({
            "source": "claude_fleet",
            "platform": hit.get("platform") or "unknown",
            "session_id": session_id,
            "path": hit.get("path") or "",
            "physical_line": hit.get("line"),
            "project_slug": hit.get("project_slug") or "",
            "timestamp": hit.get("ts") or "",
            "excerpt": hit.get("excerpt") or "",
            "context": hit.get("context") or [],
            "archive": archived,
            "evidence_kind": "transcript_physical_line",
        })
    for hit in _parse_agent_mail(agent_mail_text):
        archived = _archive_match("", hit.get("session_id_prefix"), maps)
        full_id = str((archived or {}).get("thread_id") or "")
        if full_id and (hit["platform"], full_id) in seen_sessions:
            continue
        key = (hit["platform"], full_id or hit["session_id_prefix"], 0)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            **hit,
            "session_id": full_id or None,
            "archive": archived,
            "evidence_kind": "archive_coverage_deduped",
        })
    rows.sort(key=lambda row: (bool(row.get("archive")), row.get("timestamp") or row.get("observed_day") or ""), reverse=True)
    return {
        "ok": True,
        "schema": SCHEMA,
        "query": query,
        "results": rows[:limit],
        "sources": {
            "claude_fleet": (
                "structured line/context; active Claude plus active Codex sessions"
                if fleet_available
                else "unavailable: fleet service unreachable; no structured line evidence in this response"
            ),
            "agent_mail": (
                "Claude plus Codex active/archive coverage with fork/shard deduplication"
                if agent_mail_available
                else "unavailable: am.py invocation failed"
            ),
            "conversation_map": "archive state only",
        },
        "fact_policy": "read_only_observation_not_task_truth",
    }, 200

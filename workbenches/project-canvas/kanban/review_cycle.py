"""Evidence-bound, context-isolated review cycles for Kanban task artifacts.

The module owns review state and prompts.  ``scan-docs.py`` remains a thin
adapter that validates the configured CLI profile and submits returned queue
specifications to the existing AI queue.

Durable state is an append-only, structured review ledger beside the task card:
``<configured-scan-dir>/.reviews/<task-id>/ledger.jsonl``.  Raw model output
and prompts stay in the existing gitignored AI queue.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEDGER_SCHEMA = "kanban.review-cycle/v1"
FINDINGS_SCHEMA = "kanban.review-findings/v1"
ACTIVE_STATES = {"reviewing", "repairing", "rechecking"}
REPAIRABLE_STATE = "revision_required"
_LEDGER_LOCK = threading.Lock()
_TERMINAL_RUN_STATUSES = {"completed", "error", "timeout", "killed"}
_AI_RESULT_MARKER = re.compile(r"\n*<!--\s*ai-result:[\s\S]*$", re.IGNORECASE)
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


class ReviewCycleError(ValueError):
    """A user-correctable review-cycle request error."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _short(value: Any, limit: int = 2000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _task_path(
    repo_root: str | Path,
    task_path: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> Path:
    path = Path(str(task_path or "").strip())
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.suffix.lower() != ".md":
        raise ReviewCycleError("Review Cycle 只支持 scan_dirs 内的 Markdown 任务卡")
    root = Path(repo_root).resolve()
    candidate = (root / path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ReviewCycleError("Review Cycle 只支持 scan_dirs 内的 Markdown 任务卡") from exc
    if scan_dirs is not None:
        allowed = False
        for raw_scan_dir in scan_dirs:
            scan_root = (root / str(raw_scan_dir or "")).resolve()
            try:
                candidate.relative_to(scan_root)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            raise ReviewCycleError("Review Cycle 只支持 scan_dirs 内的 Markdown 任务卡")
    return relative


def ledger_path(
    repo_root: str | Path,
    task_path: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> Path:
    task = _task_path(repo_root, task_path, scan_dirs)
    task_id = re.match(r"^([A-Za-z]+-\d+)", task.stem)
    key = task_id.group(1) if task_id else task.stem
    key = _SAFE_ID.sub("-", key).strip("-._") or "task"
    return Path(repo_root) / task.parent / ".reviews" / key / "ledger.jsonl"


def isolated_contract(card_text: str, limit: int = 100_000) -> str:
    """Return the canonical card artifact without appended AI conversation.

    The task contract and execution evidence remain visible.  Queue messages,
    session history, reviewer opinions, and appended ``ai-result`` transcripts
    are deliberately excluded.
    """

    text = _AI_RESULT_MARKER.sub("", str(card_text or "")).strip()
    if len(text) > limit:
        text = text[:limit] + "\n\n[card contract truncated]"
    return text


def _git_value(workdir: Path, args: list[str], timeout: int = 8) -> bytes:
    try:
        run = subprocess.run(
            ["git", *args], cwd=str(workdir), capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return b""
    return run.stdout if run.returncode == 0 else b""


def _worktree_content_digest(workdir: Path) -> tuple[str, int]:
    """Hash the visible Git worktree without depending on commit boundaries.

    The queue can run while an autosync process commits the exact files being
    reviewed.  A HEAD/status/diff fingerprint would then become stale even
    though no artifact bytes changed.  Hashing the current tracked and
    non-ignored file contents keeps that commit-only transition stable while
    still failing closed when any material byte in the selected workdir moves.
    """

    exclusions = [
        ":(exclude)project/**/.reviews/**",
        ":(exclude)project/**/.comments/**",
        ":(exclude)project/**/.lineage/**",
        ":(glob,exclude)**/.env",
        ":(glob,exclude)**/.env.*",
        ":(glob,exclude)**/*credentials*.json",
        ":(glob,exclude)**/*secrets*.json",
        ":(glob,exclude)**/*cookies*.sqlite",
    ]
    raw_paths = _git_value(workdir, [
        "ls-files", "-co", "--exclude-standard", "-z", "--", ".", *exclusions,
    ])
    if not raw_paths:
        return "", 0

    digest = hashlib.sha256()
    count = 0
    for raw_path in sorted(set(raw_paths.split(b"\0"))):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", "surrogateescape")
        path = workdir / relative
        try:
            stat = path.lstat()
        except OSError:
            marker = b"missing"
            content_hash = hashlib.sha256(marker).digest()
            mode = 0
        else:
            mode = stat.st_mode & 0o7777
            if path.is_symlink():
                content_hash = hashlib.sha256(os.readlink(path).encode("utf-8", "surrogateescape")).digest()
            elif path.is_file():
                file_digest = hashlib.sha256()
                try:
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            file_digest.update(chunk)
                    content_hash = file_digest.digest()
                except OSError:
                    content_hash = hashlib.sha256(b"unreadable").digest()
            else:
                content_hash = hashlib.sha256(b"non-file").digest()
        digest.update(raw_path)
        digest.update(b"\0")
        digest.update(str(mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(content_hash)
        count += 1
    return digest.hexdigest(), count


def artifact_snapshot(card_path: str | Path, workdir: str | Path) -> dict[str, Any]:
    """Freeze a content-addressed fingerprint of the review input."""

    card = Path(card_path)
    cwd = Path(workdir)
    card_bytes = card.read_bytes()
    worktree_digest, worktree_file_count = _worktree_content_digest(cwd)
    payload = {
        "card_sha256": hashlib.sha256(card_bytes).hexdigest(),
        "worktree_content_sha256": worktree_digest,
        "worktree_file_count": worktree_file_count,
    }
    fingerprint_source = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["fingerprint"] = hashlib.sha256(fingerprint_source).hexdigest()
    return payload


def _read_events(
    repo_root: str | Path,
    task_path: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    path = ledger_path(repo_root, task_path, scan_dirs)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("schema") == LEDGER_SCHEMA:
                events.append(value)
    except OSError:
        return []
    return events


def _append_event(
    repo_root: str | Path,
    task_path: str,
    event: dict[str, Any],
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> bool:
    path = ledger_path(repo_root, task_path, scan_dirs)
    clean = {key: value for key, value in event.items() if value is not None}
    clean.setdefault("schema", LEDGER_SCHEMA)
    clean.setdefault("ts", _now())
    event_key = "|".join(str(clean.get(key) or "") for key in ("cycle_id", "event", "run_id"))
    clean.setdefault("event_id", hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:18])
    with _LEDGER_LOCK:
        existing = _read_events(repo_root, task_path, scan_dirs)
        if any(row.get("event_id") == clean["event_id"] for row in existing):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def _latest_cycle_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cycle_id = next((row.get("cycle_id") for row in reversed(events) if row.get("event") == "cycle_started"), "")
    return [row for row in events if row.get("cycle_id") == cycle_id] if cycle_id else []


def project_state(
    repo_root: str | Path,
    task_path: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    rows = _latest_cycle_events(_read_events(repo_root, task_path, scan_dirs))
    if not rows:
        return {"exists": False, "state": "idle", "findings": [], "repair_count": 0}
    started = next(row for row in rows if row.get("event") == "cycle_started")
    state = "reviewing"
    findings: list[dict[str, Any]] = []
    summary_text = ""
    verdict = ""
    repair_count = 0
    last_run_id = ""
    for row in rows:
        event = row.get("event")
        if event in {"review_queued", "repair_queued", "recheck_queued"}:
            state = {"review_queued": "reviewing", "repair_queued": "repairing", "recheck_queued": "rechecking"}[event]
            last_run_id = str(row.get("run_id") or last_run_id)
        elif event == "review_completed":
            verdict = str(row.get("verdict") or "")
            findings = list(row.get("findings") or [])
            summary_text = str(row.get("summary") or "")
            state = {"pass": "resolved", "changes_required": "revision_required", "needs_owner": "needs_owner"}.get(verdict, "system_blocked")
        elif event == "repair_completed":
            repair_count += 1
            state = "rechecking"
        elif event == "recheck_completed":
            verdict = str(row.get("verdict") or "")
            findings = list(row.get("findings") or [])
            summary_text = str(row.get("summary") or "")
            state = "resolved" if verdict == "pass" else "needs_owner"
        elif event == "artifact_stale":
            state = "stale"
            summary_text = str(row.get("reason") or "评审期间产物发生变化")
        elif event in {"run_failed", "enqueue_failed", "parse_failed"}:
            state = "system_blocked"
            summary_text = str(row.get("reason") or "Review Cycle 运行失败")
    return {
        "exists": True,
        "cycle_id": started.get("cycle_id"),
        "state": state,
        "reviewer_tool": started.get("reviewer_tool"),
        "reviewer_profile": started.get("reviewer_profile"),
        "producer_tool": started.get("producer_tool"),
        "producer_profile": started.get("producer_profile"),
        "artifact": started.get("artifact"),
        "findings": findings,
        "summary": summary_text,
        "verdict": verdict,
        "repair_count": repair_count,
        "last_run_id": last_run_id,
        "updated_at": rows[-1].get("ts"),
    }


def _review_output_contract(recheck: bool = False) -> str:
    status_values = "resolved|open|needs_owner|invalid" if recheck else "open|needs_owner"
    return (
        '{"schema_version":"kanban.review-findings/v1",'
        '"verdict":"pass|changes_required|needs_owner",'
        '"summary":"one falsifiable summary",'
        '"findings":[{"finding_id":"F-001","severity":"blocker|major|minor|note",'
        '"claim":"specific defect","evidence_refs":["path:line"],'
        f'"verification":"deterministic check","status":"{status_values}"}}]}}'
    )


def _review_prompt(contract: str, snapshot: dict[str, Any], *, recheck_findings: list[dict[str, Any]] | None = None) -> str:
    recheck = recheck_findings is not None
    purpose = (
        "Recheck only the original findings against the revised artifact. Do not invent a new product goal."
        if recheck else
        "Perform an independent red-team review of the artifact against its stated contract."
    )
    findings_packet = ""
    if recheck:
        findings_packet = "\n\n<original_findings>\n" + json.dumps(recheck_findings, ensure_ascii=False, indent=2) + "\n</original_findings>"
    return f"""You are an independent reviewer in a bounded Agent Team.

{purpose}

CONTEXT ISOLATION RULES:
- This is a fresh session. Do not ask for or infer the producer's hidden reasoning or prior chat.
- Treat only the canonical artifact, its frozen fingerprint, and directly inspectable files as evidence.
- Agreement with another model is not evidence. Cite file:line or a deterministic verification action.
- You are read-only. Do not edit files, change task status, or authorize implementation.
- Never read, quote, or inspect secrets, .env files, tokens, cookies, browser profiles, or raw private logs.
- If a material issue is a value choice rather than an evidence defect, mark it needs_owner.

<artifact_snapshot>
{json.dumps(snapshot, ensure_ascii=False, indent=2)}
</artifact_snapshot>

<canonical_task_contract>
{contract}
</canonical_task_contract>{findings_packet}

Return JSON only, with no Markdown fence and no commentary outside this schema:
{_review_output_contract(recheck)}
"""


def _repair_prompt(contract: str, findings: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
    return f"""You are the original producer/repairer in a bounded Agent Team.

Implement only the open findings below. The task goal and acceptance contract are immutable.
Do not broaden scope, change task status, or treat reviewer agreement as evidence.
Read the real files, make the smallest safe changes, and run proportionate deterministic checks.
Never read, quote, or inspect secrets, .env files, tokens, cookies, browser profiles, or raw private logs.
Do not write a long debate response; leave verifiable file changes and concise execution evidence.

<artifact_snapshot_before_repair>
{json.dumps(snapshot, ensure_ascii=False, indent=2)}
</artifact_snapshot_before_repair>

<canonical_task_contract>
{contract}
</canonical_task_contract>

<findings_to_repair>
{json.dumps(findings, ensure_ascii=False, indent=2)}
</findings_to_repair>
"""


def start_cycle(
    repo_root: str | Path,
    task_path: str,
    card_text: str,
    workdir: str | Path,
    *,
    reviewer_tool: str,
    reviewer_profile: str,
    producer_tool: str,
    producer_profile: str,
    actor: str = "user",
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    current = project_state(repo_root, task_path, scan_dirs)
    if current.get("state") in ACTIVE_STATES | {REPAIRABLE_STATE}:
        raise ReviewCycleError("当前 Review Cycle 尚未结束")
    task_abs = Path(repo_root) / _task_path(repo_root, task_path, scan_dirs)
    snapshot = artifact_snapshot(task_abs, workdir)
    cycle_id = "RC-" + datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + snapshot["fingerprint"][:8].upper()
    _append_event(repo_root, task_path, {
        "event": "cycle_started", "cycle_id": cycle_id, "actor": _short(actor, 80),
        "reviewer_tool": reviewer_tool, "reviewer_profile": reviewer_profile,
        "producer_tool": producer_tool, "producer_profile": producer_profile,
        "artifact": snapshot, "context_mode": "isolated_artifact_only",
    }, scan_dirs)
    return {
        "cycle_id": cycle_id,
        "queue": {
            "tool": reviewer_tool,
            "profile": reviewer_profile,
            "prompt": _review_prompt(isolated_contract(card_text), snapshot),
            "dedupe_key": f"review-cycle:{cycle_id}:review",
            "metadata": {
                "kind": "review_cycle", "cycle_id": cycle_id, "stage": "review",
                "context_mode": "isolated_artifact_only", "artifact_fingerprint": snapshot["fingerprint"],
                "reviewer_tool": reviewer_tool, "reviewer_profile": reviewer_profile,
                "producer_tool": producer_tool, "producer_profile": producer_profile,
                "workdir": str(workdir),
            },
        },
    }


def record_queued(
    repo_root: str | Path,
    task_path: str,
    cycle_id: str,
    stage: str,
    run_id: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> None:
    event_name = {"review": "review_queued", "repair": "repair_queued", "recheck": "recheck_queued"}.get(stage)
    if not event_name:
        raise ReviewCycleError("未知 Review Cycle 阶段")
    _append_event(repo_root, task_path, {
        "event": event_name, "cycle_id": cycle_id, "run_id": run_id,
    }, scan_dirs)


def record_enqueue_failure(
    repo_root: str | Path,
    task_path: str,
    cycle_id: str,
    reason: str,
    scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> None:
    _append_event(repo_root, task_path, {
        "event": "enqueue_failed", "cycle_id": cycle_id, "reason": _short(reason),
    }, scan_dirs)


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    candidates = [raw]
    candidates.extend(re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        candidate = candidate.strip()
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            brace = candidate.find("{")
            if brace < 0:
                continue
            try:
                value, _ = decoder.raw_decode(candidate[brace:])
            except json.JSONDecodeError:
                continue
        if isinstance(value, dict):
            return value
    raise ReviewCycleError("reviewer 未返回可解析 JSON")


def parse_findings(text: str, *, recheck: bool = False) -> dict[str, Any]:
    value = _extract_json(text)
    if value.get("schema_version") != FINDINGS_SCHEMA:
        raise ReviewCycleError("reviewer schema_version 不匹配")
    verdict = str(value.get("verdict") or "").strip().lower()
    if verdict not in {"pass", "changes_required", "needs_owner"}:
        raise ReviewCycleError("reviewer verdict 无效")
    raw_findings = value.get("findings")
    if not isinstance(raw_findings, list):
        raise ReviewCycleError("reviewer findings 必须是数组")
    findings = []
    allowed_statuses = {"resolved", "open", "needs_owner", "invalid"} if recheck else {"open", "needs_owner"}
    for index, raw in enumerate(raw_findings[:50], 1):
        if not isinstance(raw, dict):
            continue
        claim = _short(raw.get("claim"), 1200)
        if not claim:
            continue
        finding_id = str(raw.get("finding_id") or f"F-{index:03d}").strip().upper()
        if not re.fullmatch(r"F-[A-Z0-9_-]{1,24}", finding_id):
            finding_id = f"F-{index:03d}"
        severity = str(raw.get("severity") or "major").lower()
        if severity not in {"blocker", "major", "minor", "note"}:
            severity = "major"
        status = str(raw.get("status") or "open").lower()
        if status not in allowed_statuses:
            status = "open"
        refs = raw.get("evidence_refs") if isinstance(raw.get("evidence_refs"), list) else []
        findings.append({
            "finding_id": finding_id,
            "severity": severity,
            "claim": claim,
            "evidence_refs": [_short(ref, 500) for ref in refs[:12] if str(ref or "").strip()],
            "verification": _short(raw.get("verification"), 1000),
            "status": status,
        })
    if verdict == "pass" and any(row["status"] in {"open", "needs_owner"} for row in findings):
        raise ReviewCycleError("pass 不能包含未关闭 finding")
    if verdict == "changes_required" and not any(row["status"] == "open" for row in findings):
        raise ReviewCycleError("changes_required 必须至少包含一个 open finding")
    return {"verdict": verdict, "summary": _short(value.get("summary"), 2000), "findings": findings}


def prepare_repair(
    repo_root: str | Path, task_path: str, card_text: str, workdir: str | Path,
    *, scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    state = project_state(repo_root, task_path, scan_dirs)
    if state.get("state") != REPAIRABLE_STATE:
        raise ReviewCycleError("当前没有可修订的独立评审 finding")
    if int(state.get("repair_count") or 0) >= 1:
        raise ReviewCycleError("首版 Review Cycle 最多自动修订一轮")
    snapshot = artifact_snapshot(Path(repo_root) / _task_path(repo_root, task_path, scan_dirs), workdir)
    cycle_id = str(state["cycle_id"])
    return {
        "cycle_id": cycle_id,
        "queue": {
            "tool": state["producer_tool"],
            "profile": state["producer_profile"],
            "prompt": _repair_prompt(isolated_contract(card_text), state.get("findings") or [], snapshot),
            "dedupe_key": f"review-cycle:{cycle_id}:repair:1",
            "metadata": {
                "kind": "review_cycle", "cycle_id": cycle_id, "stage": "repair",
                "context_mode": "findings_only", "artifact_fingerprint": snapshot["fingerprint"],
                "reviewer_tool": state["reviewer_tool"], "reviewer_profile": state["reviewer_profile"],
                "producer_tool": state["producer_tool"], "producer_profile": state["producer_profile"],
                "workdir": str(workdir),
            },
        },
    }


def process_terminal(
    repo_root: str | Path, task_path: str, entry: dict[str, Any], card_text: str,
    *, scan_dirs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Record a terminal queue entry and optionally request an automatic recheck."""

    metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    if metadata.get("kind") != "review_cycle":
        return {}
    stage = str(metadata.get("stage") or "")
    cycle_id = str(metadata.get("cycle_id") or "")
    run_id = str(entry.get("id") or "")
    if not cycle_id or not run_id or entry.get("status") not in _TERMINAL_RUN_STATUSES:
        return {}
    rows = _latest_cycle_events(_read_events(repo_root, task_path, scan_dirs))
    if any(row.get("run_id") == run_id and row.get("event") in {
        "review_completed", "repair_completed", "recheck_completed", "run_failed", "artifact_stale", "parse_failed",
    } for row in rows):
        return {}
    if entry.get("status") != "completed":
        _append_event(repo_root, task_path, {
            "event": "run_failed", "cycle_id": cycle_id, "run_id": run_id,
            "stage": stage, "reason": _short(entry.get("error") or entry.get("status")),
        }, scan_dirs)
        return {}

    workdir = Path(str(metadata.get("workdir") or ""))
    current_snapshot = artifact_snapshot(
        Path(repo_root) / _task_path(repo_root, task_path, scan_dirs), workdir,
    )
    if stage in {"review", "recheck"} and current_snapshot["fingerprint"] != metadata.get("artifact_fingerprint"):
        _append_event(repo_root, task_path, {
            "event": "artifact_stale", "cycle_id": cycle_id, "run_id": run_id,
            "stage": stage, "reason": "评审运行期间 canonical artifact 已变化，结果未采纳",
            "artifact": current_snapshot,
        }, scan_dirs)
        return {}

    if stage in {"review", "recheck"}:
        try:
            parsed = parse_findings(str(entry.get("output") or ""), recheck=stage == "recheck")
        except ReviewCycleError as exc:
            _append_event(repo_root, task_path, {
                "event": "parse_failed", "cycle_id": cycle_id, "run_id": run_id,
                "stage": stage, "reason": str(exc),
            }, scan_dirs)
            return {}
        event_name = "review_completed" if stage == "review" else "recheck_completed"
        _append_event(repo_root, task_path, {
            "event": event_name, "cycle_id": cycle_id, "run_id": run_id,
            "verdict": parsed["verdict"], "summary": parsed["summary"],
            "findings": parsed["findings"], "artifact": current_snapshot,
        }, scan_dirs)
        return {}

    if stage != "repair":
        return {}
    state = project_state(repo_root, task_path, scan_dirs)
    _append_event(repo_root, task_path, {
        "event": "repair_completed", "cycle_id": cycle_id, "run_id": run_id,
        "artifact": current_snapshot,
    }, scan_dirs)
    return {
        "enqueue": {
            "tool": metadata.get("reviewer_tool"),
            "profile": metadata.get("reviewer_profile"),
            "prompt": _review_prompt(
                isolated_contract(card_text), current_snapshot,
                recheck_findings=state.get("findings") or [],
            ),
            "dedupe_key": f"review-cycle:{cycle_id}:recheck:1",
            "metadata": {
                "kind": "review_cycle", "cycle_id": cycle_id, "stage": "recheck",
                "context_mode": "original_findings_only", "artifact_fingerprint": current_snapshot["fingerprint"],
                "reviewer_tool": metadata.get("reviewer_tool"),
                "reviewer_profile": metadata.get("reviewer_profile"),
                "producer_tool": metadata.get("producer_tool"),
                "producer_profile": metadata.get("producer_profile"),
                "workdir": str(workdir),
            },
        }
    }

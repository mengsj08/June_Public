"""First-class real-project projection for Owner's personal kanban.

The registry is the confirmed project identity/intent source. Task cards only join a
project through an explicit ``project_ref``. Runtime directory snapshots live in an
ignored state directory; no-change refreshes never create project events or logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "kanban-real-projects/v1"
POSTURE_SCHEMA = "kanban-project-posture/v1"
EVENT_SCHEMA = "kanban-real-project-event/v1"
REGISTRY_REL = Path("project/个人调度/.real-projects/projects.json")
EVENTS_REL = Path("project/个人调度/.real-projects/events.jsonl")
PROJECT_STATE_REL = Path("project/个人调度/.real-projects/project-state.generated.json")
PROJECT_STATE_SCHEMA = "kanban-real-project-state/v1"
PROJECT_ACTIONS_REL = Path("project/个人调度/.real-projects/project-actions.generated.json")
PROJECT_ACTIONS_SCHEMA = "kanban-project-actions/v1"
ACTION_TYPES = {"needs_reply", "needs_progress", "needs_decision", "no_action"}
DEFAULT_ROLE_ACTORS = {"owner": "owner", "operator": "operator", "reviewer": "reviewer"}
ORIGIN_TYPES = {"conversation", "manual"}
LIFECYCLES = {"active", "paused", "completed", "archived"}
HEALTH_STATES = {"normal", "blocked", "stale"}
FEEDBACK_OUTCOMES = {"progress", "no_progress", "handled"}
TERMINAL_TASK_STATUSES = {"done", "completed", "archived", "cancelled", "canceled"}
PROJECT_ROLES = {"execution", "milestone", "evidence", "governance", "delivery"}
DEFAULT_PROJECT_ROLE = "execution"
CANVAS_PROJECT_ROLES = {"execution", "delivery"}
DURABLE_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".csv", ".tsv", ".ppt", ".pptx", ".key",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".rst", ".csv", ".tsv", ".svg"}
EXCLUDED_PARTS = {
    ".git", ".claude", ".agents", ".workbuddy", ".bigapple", ".beacon",
    "node_modules", "__pycache__", ".venv", ".deps", "dist", "build",
    "cache", "caches", "logs", "log", "tmp", "temp",
}


def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_project_role(value, default=DEFAULT_PROJECT_ROLE):
    """Return a stable project-local role without inferring from titles or paths."""
    role = str(value or "").strip().lower()
    if role in PROJECT_ROLES:
        return role
    return default


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _read_json(path, default):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default
    return payload


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _registry_path(deps):
    return Path(deps["repo_root"]) / deps.get("registry_rel", REGISTRY_REL)


def _events_path(deps):
    return Path(deps["repo_root"]) / deps.get("events_rel", EVENTS_REL)


def _project_state_path(deps):
    return Path(deps["repo_root"]) / deps.get("project_state_rel", PROJECT_STATE_REL)


def _project_actions_path(deps):
    return Path(deps["repo_root"]) / deps.get("project_actions_rel", PROJECT_ACTIONS_REL)


def _runtime_root(deps):
    return Path(deps["runtime_root"])


def _role_actors(deps):
    source = deps.get("roles") if isinstance(deps, dict) else {}
    actors = dict(DEFAULT_ROLE_ACTORS)
    if isinstance(source, dict):
        for role in actors:
            item = source.get(role)
            value = item.get("actor") if isinstance(item, dict) else ""
            value = str(value or "").strip().lower()
            if value:
                actors[role] = value
    return actors


def _load_registry(deps):
    payload = _read_json(_registry_path(deps), {})
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return {"ok": False, "error": f"项目注册表必须使用 {SCHEMA}"}, 500
    projects = payload.get("projects")
    if not isinstance(projects, list):
        return {"ok": False, "error": "项目注册表 projects 必须是数组"}, 500
    seen = set()
    normalized = []
    for row in projects:
        if not isinstance(row, dict):
            return {"ok": False, "error": "项目注册表包含非对象条目"}, 500
        project_ref = str(row.get("project_ref") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", project_ref):
            return {"ok": False, "error": f"非法 project_ref: {project_ref or '<empty>'}"}, 500
        if project_ref in seen:
            return {"ok": False, "error": f"重复 project_ref: {project_ref}"}, 500
        seen.add(project_ref)
        if str(row.get("confirmed_by") or "").strip().lower() != _role_actors(deps)["owner"]:
            return {"ok": False, "error": f"项目 {project_ref} 尚未由 Owner 确认"}, 500
        lifecycle = str(row.get("lifecycle") or "active")
        health = str(row.get("health") or "normal")
        action_type = str((row.get("primary_action") or {}).get("type") or "no_action")
        if lifecycle not in LIFECYCLES or health not in HEALTH_STATES or action_type not in ACTION_TYPES:
            return {"ok": False, "error": f"项目 {project_ref} 状态字段非法"}, 500
        normalized.append(dict(row))
    return {"ok": True, "projects": normalized, "registry": payload}, 200


def _single_line(value, *, limit=1024):
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:limit]


def _require_owner(deps, actor):
    return _single_line(actor, limit=40).lower() == _role_actors(deps)["owner"]


def _validate_register_authority(deps, payload, actor):
    actor = _single_line(actor, limit=40).lower()
    role_actors = _role_actors(deps)
    owner_actor = role_actors["owner"]
    if actor not in set(role_actors.values()):
        return None, None, {"ok": False, "error": "项目登记 actor 必须匹配配置的 owner/operator/reviewer"}, 403
    confirmed_by = _single_line(payload.get("confirmed_by"), limit=40).lower()
    origin = payload.get("origin")
    origin = dict(origin) if isinstance(origin, dict) else {}
    origin_type = _single_line(origin.get("type"), limit=40).lower()
    if origin_type and origin_type not in ORIGIN_TYPES:
        return None, None, {"ok": False, "error": "origin.type 仅支持 conversation 或 manual"}, 400
    if actor == owner_actor:
        return actor, confirmed_by or owner_actor, None, 200
    if confirmed_by != owner_actor:
        return None, None, {"ok": False, "error": "非 owner actor 登记项目必须带配置的 owner actor 授权"}, 403
    quote = _single_line(origin.get("confirmation_quote"), limit=1000)
    if not quote:
        return None, None, {"ok": False, "error": "非 Owner actor 登记项目必须带 origin.confirmation_quote 授权原话"}, 400
    normalized_origin = {
        "type": origin_type or "conversation",
        "provider": _single_line(origin.get("provider"), limit=80),
        "thread_id": _single_line(origin.get("thread_id"), limit=200),
        "actor": actor,
        "confirmed_by": owner_actor,
        "confirmation_quote": quote,
    }
    return actor, owner_actor, normalized_origin, 200


def get_registered_project(deps, project_ref):
    """Resolve one confirmed project without guessing from a path or title."""
    project_ref = _single_line(project_ref, limit=64)
    loaded, status = _load_registry(deps)
    if status != 200:
        return loaded, status
    project = next((row for row in loaded["projects"] if row["project_ref"] == project_ref), None)
    if not project:
        return {"ok": False, "error": "未知 project_ref"}, 404
    return {"ok": True, "project": project}, 200


def register_project(deps, payload, *, actor="unspecified"):
    """Register a Owner-confirmed real project; never create or copy its fact root."""
    payload = payload if isinstance(payload, dict) else {}
    actor, confirmed_by, origin, authority_status = _validate_register_authority(deps, payload, actor)
    if authority_status != 200:
        return origin, authority_status
    project_ref = _single_line(payload.get("project_ref"), limit=64).lower()
    title = _single_line(payload.get("title"), limit=120)
    current_intent = _single_line(payload.get("current_intent"), limit=600)
    workdir = _single_line(payload.get("workdir"), limit=1024)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", project_ref):
        return {"ok": False, "error": "项目 ID 仅支持英文小写、数字和连字符，长度 2–63"}, 400
    if len(title) < 2:
        return {"ok": False, "error": "项目名称至少 2 个字符"}, 400
    if len(current_intent) < 4:
        return {"ok": False, "error": "请写明项目要实现的结果"}, 400
    resolved_workdir = ""
    if workdir:
        candidate = Path(workdir).expanduser()
        if not candidate.is_absolute():
            return {"ok": False, "error": "项目目录必须是绝对路径"}, 400
        if not candidate.is_dir():
            return {"ok": False, "error": "项目目录不存在或不是文件夹"}, 400
        resolved_workdir = str(candidate.resolve())

    lock = deps.get("write_lock") or nullcontext()
    with lock:
        loaded, status = _load_registry(deps)
        if status != 200:
            return loaded, status
        origin_thread_id = _single_line((origin or {}).get("thread_id"), limit=200)
        if origin_thread_id:
            existing = next((
                row for row in loaded["projects"]
                if _single_line((row.get("origin") or {}).get("thread_id"), limit=200) == origin_thread_id
            ), None)
            if existing:
                return {"ok": True, "outcome": "existing", "existing": True, "project": dict(existing)}, 200
        if any(row["project_ref"] == project_ref for row in loaded["projects"]):
            return {"ok": False, "error": "这个项目 ID 已存在"}, 409
        if any(_single_line(row.get("title")).casefold() == title.casefold() for row in loaded["projects"]):
            return {"ok": False, "error": "同名真实项目已经存在"}, 409
        confirmed_at = _now()[:10]
        project = {
            "project_ref": project_ref,
            "title": title,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at,
            "lifecycle": "active",
            "health": "normal",
            "current_intent": current_intent,
            "latest_update": "项目身份已建立，尚无已确认进展。",
            "impact": "任务只有显式写入 project_ref 才归入本项目。",
            "recommendation": "建立首张可验收任务卡。",
            "primary_action": {
                "type": "needs_progress",
                "summary": "建立首张可验收任务卡",
                "reason": "项目已登记，尚无内部执行任务",
            },
            "checkpoint": {
                "expected_change": "至少一张任务卡明确归入项目",
                "reason": "先把项目目标转成可验收行动",
            },
            "facts": [{
                "canonical_key": f"{project_ref}-identity-{confirmed_at}",
                "summary": f"Owner 建立并确认真实项目“{title}”",
                "impact": "项目获得稳定身份；目录、标题和语义相似不再被用来猜归属。",
                "observed_at": confirmed_at,
                "certainty": "human_confirmed",
                "sources": [{
                    "kind": "project_registry",
                    "ref": project_ref,
                    "label": "Owner 项目登记",
                }],
            }],
            "milestones": [],
            "unknowns": [],
            "fact_roots": [resolved_workdir] if resolved_workdir else [],
        }
        if origin:
            project["origin"] = origin
        if resolved_workdir:
            project["workdir"] = resolved_workdir
        registry = dict(loaded["registry"])
        registry["projects"] = [*loaded["projects"], project]
        registry["updated_at"] = _now()
        _atomic_write(_registry_path(deps), json.dumps(registry, ensure_ascii=False, indent=2) + "\n")

    projection, status = build_projection(deps)
    if status != 200:
        return projection, status
    created = next(row for row in projection["projects"] if row["project_ref"] == project_ref)
    return {"ok": True, "outcome": "created", "project": created}, 201


def update_project(deps, payload, *, actor="unspecified"):
    """Edit or soft-archive one registered project without touching linked task facts."""
    if not _require_owner(deps, actor):
        return {"ok": False, "error": "只有 Owner 可以修改项目"}, 403
    payload = payload if isinstance(payload, dict) else {}
    project_ref = _single_line(payload.get("project_ref"), limit=64)
    if not project_ref:
        return {"ok": False, "error": "缺少 project_ref"}, 400

    allowed = {"title", "current_intent", "workdir", "lifecycle"}
    requested = {key: payload.get(key) for key in allowed if key in payload}
    if not requested:
        return {"ok": False, "error": "没有可更新的项目字段"}, 400
    if "title" in requested:
        requested["title"] = _single_line(requested["title"], limit=120)
        if len(requested["title"]) < 2:
            return {"ok": False, "error": "项目名称至少 2 个字符"}, 400
    if "current_intent" in requested:
        requested["current_intent"] = _single_line(requested["current_intent"], limit=600)
        if len(requested["current_intent"]) < 4:
            return {"ok": False, "error": "请写明项目要实现的结果"}, 400
    if "lifecycle" in requested:
        requested["lifecycle"] = _single_line(requested["lifecycle"], limit=40).lower()
        if requested["lifecycle"] not in LIFECYCLES:
            return {"ok": False, "error": "lifecycle 仅支持 active、paused、completed、archived"}, 400
    if "workdir" in requested:
        workdir = _single_line(requested["workdir"], limit=1024)
        if workdir:
            candidate = Path(workdir).expanduser()
            if not candidate.is_absolute():
                return {"ok": False, "error": "项目目录必须是绝对路径"}, 400
            if not candidate.is_dir():
                return {"ok": False, "error": "项目目录不存在或不是文件夹"}, 400
            requested["workdir"] = str(candidate.resolve())
        else:
            requested["workdir"] = ""

    changed = {}
    event = None
    lock = deps.get("write_lock") or nullcontext()
    with lock:
        loaded, status = _load_registry(deps)
        if status != 200:
            return loaded, status
        project = next((row for row in loaded["projects"] if row["project_ref"] == project_ref), None)
        if not project:
            return {"ok": False, "error": "未知 project_ref"}, 404
        if "title" in requested and any(
            row["project_ref"] != project_ref
            and _single_line(row.get("title")).casefold() == requested["title"].casefold()
            for row in loaded["projects"]
        ):
            return {"ok": False, "error": "同名真实项目已经存在"}, 409

        updated = dict(project)
        for key, value in requested.items():
            if key == "workdir":
                previous = _single_line(updated.get("workdir"), limit=1024)
                if previous != value:
                    changed[key] = {"from": previous, "to": value}
                    roots = [
                        _single_line(root, limit=1024)
                        for root in updated.get("fact_roots") or []
                        if _single_line(root, limit=1024) and _single_line(root, limit=1024) != previous
                    ]
                    if value:
                        updated["workdir"] = value
                        updated["fact_roots"] = [value, *roots]
                    else:
                        updated.pop("workdir", None)
                        updated["fact_roots"] = roots
                continue
            previous = updated.get(key)
            if previous != value:
                changed[key] = {"from": previous, "to": value}
                updated[key] = value
        if not changed:
            return {"ok": True, "outcome": "no_change", "project": dict(project)}, 200

        now = _now()
        updated["last_edited_at"] = now
        owner_actor = _role_actors(deps)["owner"]
        updated["last_edited_by"] = owner_actor
        registry = dict(loaded["registry"])
        registry["projects"] = [
            updated if row["project_ref"] == project_ref else row
            for row in loaded["projects"]
        ]
        registry["updated_at"] = now
        _atomic_write(_registry_path(deps), json.dumps(registry, ensure_ascii=False, indent=2) + "\n")

        event = {
            "schema": EVENT_SCHEMA,
            "event_id": "rpe_" + hashlib.sha256(
                _stable_json([project_ref, "project_updated", changed, now]).encode("utf-8")
            ).hexdigest()[:20],
            "event": "project_updated",
            "project_ref": project_ref,
            "changed_fields": sorted(changed),
            "changes": changed,
            "actor": owner_actor,
            "at": now,
        }
        encoded = (_stable_json(event) + "\n").encode("utf-8")
        path = _events_path(deps)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)

    projection, status = build_projection(deps)
    if status != 200:
        return projection, status
    project = next(row for row in projection["projects"] if row["project_ref"] == project_ref)
    return {"ok": True, "outcome": "updated", "project": project, "event": event}, 200


def assign_task(deps, payload, *, actor="unspecified"):
    """Attach one scanned task to one confirmed project through explicit project_ref."""
    if not _require_owner(deps, actor):
        return {"ok": False, "error": "只有 Owner 可以确认任务归属"}, 403
    payload = payload if isinstance(payload, dict) else {}
    project_ref = _single_line(payload.get("project_ref"), limit=64)
    raw_project_role = _single_line(payload.get("project_role"), limit=32).lower()
    if raw_project_role and raw_project_role not in PROJECT_ROLES:
        return {"ok": False, "error": f"非法 project_role: {raw_project_role}"}, 400
    path = _single_line(payload.get("path"), limit=2048)
    project_result, status = get_registered_project(deps, project_ref)
    if status != 200:
        return project_result, status
    if not path:
        return {"ok": False, "error": "缺少任务路径"}, 400
    tasks = [row for row in (deps.get("scan_tasks") or (lambda: []))() if isinstance(row, dict)]
    task = next((row for row in tasks if _single_line(row.get("path"), limit=2048) == path), None)
    if not task:
        return {"ok": False, "error": "任务不在当前看板扫描范围内"}, 404
    existing = _single_line(task.get("project_ref"), limit=64)
    if existing == project_ref:
        current_role = _single_line(task.get("project_role"), limit=32).lower()
        project_role = raw_project_role or normalize_project_role(current_role)
        if current_role != project_role:
            role_updater = deps.get("update_task_project_role")
            if callable(role_updater):
                result = role_updater(path, project_role)
                ok = bool(result[0]) if isinstance(result, tuple) and result else bool(result)
                message = str(result[1]) if isinstance(result, tuple) and len(result) > 1 else ""
                if not ok:
                    return {"ok": False, "error": message or "写入 project_role 失败"}, 500
                return {
                    "ok": True,
                    "outcome": "role_updated",
                    "project_ref": project_ref,
                    "project_role": project_role,
                    "task_id": task.get("task_id"),
                    "path": path,
                }, 200
        return {
            "ok": True,
            "outcome": "already_linked",
            "project_ref": project_ref,
            "project_role": normalize_project_role(current_role),
            "task_id": task.get("task_id"),
            "path": path,
        }, 200
    if existing:
        return {"ok": False, "error": f"任务已归入项目 {existing}，不能静默改绑"}, 409
    project_role = raw_project_role or DEFAULT_PROJECT_ROLE
    updater = deps.get("update_task_project_ref")
    if not callable(updater):
        return {"ok": False, "error": "任务归属写入器不可用"}, 500
    result = updater(path, project_ref)
    ok = bool(result[0]) if isinstance(result, tuple) and result else bool(result)
    message = str(result[1]) if isinstance(result, tuple) and len(result) > 1 else ""
    if not ok:
        return {"ok": False, "error": message or "写入 project_ref 失败"}, 500
    role_updater = deps.get("update_task_project_role")
    if callable(role_updater):
        role_result = role_updater(path, project_role)
        role_ok = bool(role_result[0]) if isinstance(role_result, tuple) and role_result else bool(role_result)
        role_message = str(role_result[1]) if isinstance(role_result, tuple) and len(role_result) > 1 else ""
        if not role_ok:
            return {"ok": False, "error": role_message or "project_ref 已写入，但 project_role 写入失败"}, 500
    return {
        "ok": True,
        "outcome": "linked",
        "project_ref": project_ref,
        "project_role": project_role,
        "task_id": task.get("task_id"),
        "path": path,
    }, 200


def _load_events(deps):
    events = []
    malformed = 0
    path = _events_path(deps)
    if not path.exists():
        return events, malformed
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return events, malformed
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(item, dict) and item.get("schema") == EVENT_SCHEMA:
            events.append(item)
    return events, malformed


def _sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _load_project_state(deps):
    path = _project_state_path(deps)
    if not path.is_file():
        return {}, {"status": "missing", "path": str(path)}
    payload = _read_json(path, {})
    if payload.get("schema") != PROJECT_STATE_SCHEMA or not isinstance(payload.get("projects"), list):
        return {}, {"status": "invalid", "path": str(path), "reason": "schema"}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    registry_path = _registry_path(deps)
    if source.get("registry_sha256") != _sha256_file(registry_path):
        return {}, {"status": "stale", "path": str(path), "reason": "registry_changed"}
    manifest_path = Path(str(source.get("event_ledger_manifest_path") or ""))
    manifest = _read_json(manifest_path, {}) if manifest_path.is_file() else {}
    if (
        not manifest
        or source.get("event_ledger_transaction_id") != manifest.get("transaction_id")
        or source.get("event_ledger_manifest_sha256") != _sha256_file(manifest_path)
    ):
        return {}, {"status": "stale", "path": str(path), "reason": "event_ledger_changed"}
    rows = {}
    for row in payload["projects"]:
        if not isinstance(row, dict):
            return {}, {"status": "invalid", "path": str(path), "reason": "project_row"}
        project_ref = str(row.get("project_ref") or "")
        if not project_ref or project_ref in rows:
            return {}, {"status": "invalid", "path": str(path), "reason": "project_ref"}
        rows[project_ref] = row
    return rows, {
        "status": "current",
        "path": str(path),
        "transaction_id": source.get("event_ledger_transaction_id"),
        "generated_at": payload.get("generated_at"),
        "project_count": len(rows),
    }


def _load_project_actions(deps):
    path = _project_actions_path(deps)
    if not path.is_file():
        return {}, {"status": "missing", "path": str(path)}
    payload = _read_json(path, {})
    if payload.get("schema") != PROJECT_ACTIONS_SCHEMA or not isinstance(payload.get("actions"), list):
        return {}, {"status": "invalid", "path": str(path), "reason": "schema"}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    state_path = _project_state_path(deps)
    if source.get("project_state_sha256") != _sha256_file(state_path):
        return {}, {"status": "stale", "path": str(path), "reason": "project_state_changed"}
    repo_root = Path(deps["repo_root"]).resolve()
    grouped = {}
    for action in payload["actions"]:
        if not isinstance(action, dict):
            return {}, {"status": "invalid", "path": str(path), "reason": "action_row"}
        project_ref = str(action.get("project_ref") or "").strip()
        if not project_ref:
            return {}, {"status": "invalid", "path": str(path), "reason": "project_ref"}
        bound_task = action.get("bound_task")
        if bound_task is not None:
            if not isinstance(bound_task, dict):
                return {}, {"status": "invalid", "path": str(path), "reason": "bound_task"}
            task_path = (repo_root / str(bound_task.get("path") or "")).resolve()
            try:
                task_path.relative_to(repo_root)
            except ValueError:
                return {}, {"status": "invalid", "path": str(path), "reason": "task_path"}
            if bound_task.get("sha256") != _sha256_file(task_path):
                return {}, {"status": "stale", "path": str(path), "reason": "bound_task_changed"}
        grouped.setdefault(project_ref, []).append(dict(action))
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    return grouped, {
        "status": "current",
        "path": str(path),
        "generated_at": payload.get("generated_at"),
        "action_count": len(payload["actions"]),
        "counts": counts,
    }


def _apply_project_state(project, state):
    if not isinstance(state, dict):
        return project
    derived = state.get("derived_fields") if isinstance(state.get("derived_fields"), dict) else {}
    allowed = {"latest_update", "impact", "recommendation", "primary_action", "checkpoint"}
    for key in allowed:
        if key in derived:
            project[key] = derived[key]
    project["facts"] = list(project.get("facts") or []) + list(state.get("facts") or [])
    milestones = [dict(row) for row in project.get("milestones") or [] if isinstance(row, dict)]
    updates = {
        str(row.get("label") or ""): row
        for row in state.get("milestone_updates") or []
        if isinstance(row, dict) and row.get("label")
    }
    seen = set()
    for milestone in milestones:
        label = str(milestone.get("label") or "")
        if label in updates:
            milestone.update(updates[label])
            seen.add(label)
    milestones.extend(dict(row) for label, row in updates.items() if label not in seen)
    project["milestones"] = milestones
    if isinstance(state.get("unknowns"), list):
        project["unknowns"] = list(state["unknowns"])
    project["event_summary"] = dict(state.get("event_summary") or {})
    project["generated_project_state"] = {
        "action_hint": state.get("action_hint"),
        "superseded_registry_unknowns": list(state.get("superseded_registry_unknowns") or []),
    }
    return project


def _source_key(source):
    return (
        str(source.get("kind") or ""),
        str(source.get("ref") or source.get("path") or ""),
        str(source.get("anchor") or ""),
    )


def merge_project_facts(facts):
    """Merge repeated descriptions of one fact while preserving every source."""
    merged = {}
    order = []
    for index, row in enumerate(facts if isinstance(facts, list) else []):
        if not isinstance(row, dict):
            continue
        canonical_key = str(row.get("canonical_key") or row.get("fact_id") or f"fact-{index}").strip()
        if canonical_key not in merged:
            merged[canonical_key] = {
                "canonical_key": canonical_key,
                "summary": str(row.get("summary") or "").strip(),
                "impact": str(row.get("impact") or "").strip(),
                "observed_at": str(row.get("observed_at") or "").strip(),
                "certainty": str(row.get("certainty") or "confirmed").strip(),
                "sources": [],
            }
            order.append(canonical_key)
        target = merged[canonical_key]
        if row.get("conflict") is True:
            target["conflict"] = True
        known = {_source_key(source) for source in target["sources"] if isinstance(source, dict)}
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                continue
            key = _source_key(source)
            if key not in known:
                target["sources"].append(dict(source))
                known.add(key)
    return [merged[key] for key in order]


def _task_summary(project_ref, tasks):
    linked = []
    for task in tasks or []:
        if str(task.get("project_ref") or "").strip() != project_ref:
            continue
        normalized = dict(task)
        normalized["project_role"] = normalize_project_role(task.get("project_role"))
        linked.append(normalized)
    active = [
        task for task in linked
        if str(task.get("status") or "todo").strip().lower() not in TERMINAL_TASK_STATUSES
    ]
    active.sort(key=lambda task: (
        {"high": 0, "medium": 1, "low": 2}.get(str(task.get("priority") or "medium"), 1),
        str(task.get("created") or ""),
    ))
    canvas = [task for task in active if task["project_role"] in CANVAS_PROJECT_ROLES]
    milestones = [
        task for task in linked
        if task["project_role"] == "milestone"
        or task.get("project_milestone") is True
        or str(task.get("project_milestone") or "").lower() == "true"
    ]
    by_role = {
        role: [task for task in linked if task["project_role"] == role]
        for role in sorted(PROJECT_ROLES)
    }
    return {
        "linked": linked,
        "active": active,
        "canvas": canvas,
        "milestones": milestones,
        "by_role": by_role,
        "role_counts": {role: len(rows) for role, rows in by_role.items()},
        "active_count": len(active),
        "canvas_count": len(canvas),
        "done_count": len(linked) - len(active),
    }


def _pending_candidates(deps, project_ref):
    path = _runtime_root(deps) / f"{project_ref}.pending.json"
    payload = _read_json(path, {})
    rows = payload.get("changes") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _feedback_facts(events, project_ref):
    facts = []
    for event in events:
        if event.get("project_ref") != project_ref or event.get("event") != "checkpoint_feedback":
            continue
        note = str(event.get("note") or "").strip()
        label = {
            "progress": "Owner 补充了新进展",
            "no_progress": "Owner 确认暂无进展",
            "handled": "Owner 已直接处理",
        }.get(event.get("outcome"), "Owner 检查点反馈")
        summary = f"{label}：{note}" if note else label
        facts.append({
            "canonical_key": f"checkpoint:{event.get('event_id')}",
            "summary": summary,
            "impact": "等待基于新事实刷新项目判断" if event.get("outcome") == "progress" else "",
            "observed_at": event.get("at", ""),
            "certainty": "human_confirmed",
            "sources": [{"kind": "owner_feedback", "ref": event.get("event_id", ""), "label": label}],
        })
    return facts


def _apply_latest_feedback(project, events):
    relevant = [event for event in events if event.get("project_ref") == project["project_ref"] and event.get("event") == "checkpoint_feedback"]
    if not relevant:
        return project
    latest = relevant[-1]
    project["latest_feedback"] = latest
    if latest.get("outcome") == "no_progress" and latest.get("next_check"):
        checkpoint = dict(project.get("checkpoint") or {})
        checkpoint["due_at"] = latest["next_check"]
        project["checkpoint"] = checkpoint
    elif latest.get("outcome") == "handled":
        project["primary_action"] = {
            "type": "no_action",
            "summary": "本次主动作已由 Owner 直接处理",
            "reason": str(latest.get("note") or "").strip(),
        }
    return project


def _action_rank(project):
    lifecycle = project.get("lifecycle")
    if lifecycle != "active":
        return (9, "")
    action = project.get("primary_action") or {}
    kind = action.get("type")
    due = str(action.get("due_at") or (project.get("checkpoint") or {}).get("due_at") or "")
    if kind == "needs_reply" and due:
        return (0, due)
    if kind == "needs_decision" and project.get("health") == "blocked":
        return (1, due)
    if kind == "needs_progress":
        return (2, due)
    if kind == "needs_reply":
        return (3, due)
    if kind == "needs_decision":
        return (4, due)
    return (8, due)


def _gated_active_cards(project, owner_action_needed):
    """Open project cards that the shared contract says need Owner now."""
    summary = project.get("tasks") or {}
    gated = []
    for task in summary.get("active") or []:
        status = str(task.get("status") or "todo").strip().lower()
        if status in TERMINAL_TASK_STATUSES:
            continue
        if owner_action_needed(task):
            gated.append(task)
    return gated


def _attention_assessment(project, owner_action_needed):
    """Whether a project needs Owner today, and why.

    Two independent signals, either sufficient, evaluated regardless of
    lifecycle so a 'completed' project that still has live productization
    work surfaces (fixes the completed-with-open-work blind spot, and stays
    correct even if a re-run flips primary_action back to no_action):
      - primary_action asks for a non-trivial action; or
      - a human-gated card currently needs Owner under the shared attention
        contract (``todo``/``review``; an ``in-progress`` gate stays in flight).
    """
    action_type = str((project.get("primary_action") or {}).get("type") or "").strip().lower()
    needs_action = action_type not in {"", "no_action"}
    gated = _gated_active_cards(project, owner_action_needed)
    if not needs_action and not gated:
        return None
    lifecycle = str(project.get("lifecycle") or "active").strip().lower()
    if lifecycle == "completed":
        reason = "completed_with_open_work"
    elif needs_action:
        reason = "active_needs_action"
    else:
        reason = "gated_card_waiting"
    return {
        "reason": reason,
        "needs_action": needs_action,
        "gated_card_ids": [str(task.get("task_id") or "") for task in gated if task.get("task_id")],
    }


def build_projection(deps):
    loaded, status = _load_registry(deps)
    if status != 200:
        return loaded, status
    tasks = deps["scan_tasks"]()
    owner_action_needed = deps.get("owner_action_needed")
    if not callable(owner_action_needed):
        if tasks:
            return {"ok": False, "error": "有项目卡时必须提供共享 Owner 注意力判据"}, 500
        owner_action_needed = lambda _task: False
    events, malformed = _load_events(deps)
    generated_states, project_state_status = _load_project_state(deps)
    generated_actions, project_actions_status = _load_project_actions(deps)
    projects = []
    for registered in loaded["projects"]:
        project = dict(registered)
        project = _apply_project_state(project, generated_states.get(project["project_ref"]))
        task_summary = _task_summary(project["project_ref"], tasks)
        project["tasks"] = task_summary
        project["facts"] = merge_project_facts(
            list(project.get("facts") or []) + _feedback_facts(events, project["project_ref"])
        )
        project["pending_changes"] = _pending_candidates(deps, project["project_ref"])
        project["backstage_actions"] = generated_actions.get(project["project_ref"], [])
        project = _apply_latest_feedback(project, events)
        projects.append(project)
    projects.sort(key=_action_rank)
    attention = []
    for project in projects:
        assessment = _attention_assessment(project, owner_action_needed)
        if assessment is None:
            continue
        project["attention_reason"] = assessment["reason"]
        project["attention_signals"] = assessment
        attention.append(project)
    return {
        "ok": True,
        "schema": SCHEMA,
        "projects": projects,
        "attention": attention,
        "counts": {
            "projects": len(projects),
            "attention": len(attention),
            "pending_changes": sum(len(project.get("pending_changes") or []) for project in projects),
        },
        "event_ledger": str(deps.get("events_rel", EVENTS_REL)),
        "project_state": project_state_status,
        "project_actions": project_actions_status,
        "malformed_events": malformed,
    }, 200


def filter_archived_projects(projection, *, include_archived=False):
    """Hide registry-level archives from Owner-facing lists without losing facts."""
    if include_archived or not isinstance(projection, dict) or projection.get("ok") is not True:
        return projection
    visible = [
        project for project in projection.get("projects") or []
        if str(project.get("lifecycle") or "active").strip().lower() != "archived"
    ]
    visible_refs = {str(project.get("project_ref") or "") for project in visible}
    filtered = dict(projection)
    filtered["projects"] = visible
    filtered["attention"] = [
        project for project in projection.get("attention") or []
        if str(project.get("project_ref") or "") in visible_refs
    ]
    counts = dict(projection.get("counts") or {})
    counts["projects"] = len(visible)
    counts["attention"] = len(filtered["attention"])
    counts["pending_changes"] = sum(len(project.get("pending_changes") or []) for project in visible)
    filtered["counts"] = counts
    return filtered


def build_project_posture(projection):
    """Compile the compact project posture consumed by the dispatch console.

    The full real-project projection remains the evidence/detail contract.  This
    surface deliberately carries only portfolio counts and enough identity/action
    context to decide whether to drill down; facts, milestones and reply packs do
    not leak into the console bootstrap.
    """
    if not isinstance(projection, dict) or projection.get("ok") is not True:
        return {
            "ok": False,
            "schema": POSTURE_SCHEMA,
            "error": str((projection or {}).get("error") or "真实项目投影不可用"),
        }

    projects = [row for row in projection.get("projects") or [] if isinstance(row, dict)]
    attention_rows = [row for row in projection.get("attention") or [] if isinstance(row, dict)]
    attention_refs = {
        str(row.get("project_ref") or "").strip()
        for row in attention_rows
        if row.get("project_ref")
    }

    def compact(project):
        action = project.get("primary_action") if isinstance(project.get("primary_action"), dict) else {}
        checkpoint = project.get("checkpoint") if isinstance(project.get("checkpoint"), dict) else {}
        task_summary = project.get("tasks") if isinstance(project.get("tasks"), dict) else {}
        attention_signals = project.get("attention_signals") if isinstance(project.get("attention_signals"), dict) else {}
        project_ref = str(project.get("project_ref") or "").strip()
        return {
            "project_ref": project_ref,
            "title": str(project.get("title") or project_ref),
            "lifecycle": str(project.get("lifecycle") or "active"),
            "health": str(project.get("health") or "normal"),
            "needs_owner": project_ref in attention_refs,
            "attention_reason": str(project.get("attention_reason") or ""),
            "attention_signals": {
                "needs_action": bool(attention_signals.get("needs_action")),
                "gated_card_ids": list(attention_signals.get("gated_card_ids") or []),
            },
            "primary_action": {
                "type": str(action.get("type") or "no_action"),
                "summary": str(action.get("summary") or ""),
                "due_at": str(action.get("due_at") or ""),
            },
            "checkpoint_due_at": str(checkpoint.get("due_at") or ""),
            "active_task_count": int(task_summary.get("active_count") or 0),
            "pending_change_count": len(project.get("pending_changes") or []),
        }

    compact_projects = [compact(project) for project in projects]
    compact_by_ref = {row["project_ref"]: row for row in compact_projects}
    compact_attention = [
        compact_by_ref[project_ref]
        for project_ref in (
            str(row.get("project_ref") or "").strip() for row in attention_rows
        )
        if project_ref in compact_by_ref
    ]
    quiet_active = [
        row for row in compact_projects
        if row["lifecycle"] == "active" and not row["needs_owner"]
    ]
    paused = [
        row for row in compact_projects
        if row["lifecycle"] == "paused" and not row["needs_owner"]
    ]
    completed = [
        row for row in compact_projects
        if row["lifecycle"] == "completed" and not row["needs_owner"]
    ]
    return {
        "ok": True,
        "schema": POSTURE_SCHEMA,
        "source_schema": str(projection.get("schema") or SCHEMA),
        "counts": {
            "total": len(compact_projects),
            "needs_owner": len(compact_attention),
            "quiet_active": len(quiet_active),
            "paused": len(paused),
            "completed": len(completed),
            "pending_changes": sum(row["pending_change_count"] for row in compact_projects),
        },
        "attention": compact_attention,
        "projects": compact_projects,
    }


def append_checkpoint_feedback(deps, payload, *, actor="unspecified"):
    project_ref = str(payload.get("project_ref") or "").strip()
    outcome = str(payload.get("outcome") or "").strip()
    note = str(payload.get("note") or "").strip()
    next_check = str(payload.get("next_check") or "").strip()
    loaded, status = _load_registry(deps)
    if status != 200:
        return loaded, status
    if project_ref not in {row["project_ref"] for row in loaded["projects"]}:
        return {"ok": False, "error": "未知 project_ref"}, 404
    if outcome not in FEEDBACK_OUTCOMES:
        return {"ok": False, "error": "outcome 必须是 progress/no_progress/handled"}, 400
    if outcome == "no_progress" and not next_check:
        return {"ok": False, "error": "暂无进展时必须给出下一次检查时间"}, 400
    if outcome in {"progress", "handled"} and not note:
        return {"ok": False, "error": "有新进展或已处理时必须补充事实"}, 400
    event = {
        "schema": EVENT_SCHEMA,
        "event_id": "rpe_" + hashlib.sha256(
            _stable_json([project_ref, outcome, note, next_check, _now()]).encode("utf-8")
        ).hexdigest()[:20],
        "event": "checkpoint_feedback",
        "project_ref": project_ref,
        "outcome": outcome,
        "note": note,
        "next_check": next_check,
        "actor": str(actor or "unspecified")[:40],
        "at": _now(),
    }
    encoded = (_stable_json(event) + "\n").encode("utf-8")
    path = _events_path(deps)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = deps.get("write_lock")
    if lock:
        lock.acquire()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if lock:
            lock.release()
    projection, projection_status = build_projection(deps)
    if projection_status != 200:
        return projection, projection_status
    project = next(row for row in projection["projects"] if row["project_ref"] == project_ref)
    return {"ok": True, "event": event, "project": project}, 200


def _is_durable(path):
    lowered = {part.lower() for part in path.parts}
    if lowered & EXCLUDED_PARTS:
        return False
    if any(part.startswith(".") for part in path.parts):
        return False
    return path.suffix.lower() in DURABLE_EXTENSIONS


def _semantic_bytes(path, raw):
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized.encode("utf-8")


def _scan_fact_roots(project, repo_root):
    snapshot = {}
    for root_text in project.get("fact_roots") or []:
        root = Path(str(root_text)).expanduser()
        if not root.is_absolute():
            root = Path(repo_root) / root
        root = root.resolve(strict=False)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if not _is_durable(rel):
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            key = f"{root}:{rel.as_posix()}"
            snapshot[key] = {
                "root": str(root),
                "path": str(path),
                "relative_path": rel.as_posix(),
                "size": len(raw),
                "sha256": _sha256_bytes(raw),
                "semantic_sha256": _sha256_bytes(_semantic_bytes(path, raw)),
            }
    return snapshot


def _snapshot_changes(previous, current):
    changes = []
    ignored = []
    for key in sorted(set(previous) | set(current)):
        before = previous.get(key)
        after = current.get(key)
        if before is None:
            changes.append({"kind": "added", **after})
        elif after is None:
            changes.append({"kind": "deleted", **before})
        elif before.get("sha256") != after.get("sha256"):
            if before.get("semantic_sha256") == after.get("semantic_sha256"):
                ignored.append({"kind": "format_only", **after})
            else:
                changes.append({"kind": "changed", **after})
    return changes, ignored


def refresh_project(deps, project_ref):
    loaded, status = _load_registry(deps)
    if status != 200:
        return loaded, status
    project = next((row for row in loaded["projects"] if row["project_ref"] == project_ref), None)
    if not project:
        return {"ok": False, "error": "未知 project_ref"}, 404
    current = _scan_fact_roots(project, deps["repo_root"])
    snapshot_path = _runtime_root(deps) / f"{project_ref}.snapshot.json"
    previous_payload = _read_json(snapshot_path, {})
    previous = previous_payload.get("files") if isinstance(previous_payload, dict) else None
    if not isinstance(previous, dict):
        payload = {"schema": "kanban-real-project-snapshot/v1", "project_ref": project_ref, "files": current}
        _atomic_write(snapshot_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "outcome": "baseline_created", "project_ref": project_ref, "changes": [], "ignored": [], "business_event_written": False}, 200
    changes, ignored = _snapshot_changes(previous, current)
    if not changes and not ignored:
        return {"ok": True, "outcome": "no_change", "project_ref": project_ref, "changes": [], "ignored": [], "business_event_written": False, "state_written": False}, 200
    payload = {"schema": "kanban-real-project-snapshot/v1", "project_ref": project_ref, "files": current}
    _atomic_write(snapshot_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if changes:
        pending = {
            "schema": "kanban-real-project-pending/v1",
            "project_ref": project_ref,
            "detected_at": _now(),
            "changes": changes,
        }
        _atomic_write(
            _runtime_root(deps) / f"{project_ref}.pending.json",
            json.dumps(pending, ensure_ascii=False, indent=2) + "\n",
        )
        return {"ok": True, "outcome": "candidates", "project_ref": project_ref, "changes": changes, "ignored": ignored, "business_event_written": False}, 200
    return {"ok": True, "outcome": "no_material_change", "project_ref": project_ref, "changes": [], "ignored": ignored, "business_event_written": False}, 200

"""Project-to-conversation sidecar registry and material projection.

The real-project registry owns project identity.  This sidecar owns explicit
conversation attribution and never edits projects.json.
"""

import json
import os
import tempfile
from pathlib import Path


SCHEMA = "kanban-project-conversations/v1"
REGISTRY_REL = Path("project/个人调度/.real-projects/project-conversations.json")
PROJECTS_REL = Path("project/个人调度/.real-projects/projects.json")
ALLOWED_KINDS = {"codex", "claude-science"}


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取登记文件 {path}: {exc}") from exc


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def _project(repo_root, project_ref):
    payload = _read_json(Path(repo_root) / PROJECTS_REL)
    for row in payload.get("projects", []):
        if row.get("project_ref") == project_ref:
            return row
    return None


def _registry(repo_root):
    path = Path(repo_root) / REGISTRY_REL
    if not path.exists():
        return {"schema": SCHEMA, "projects": []}
    payload = _read_json(path)
    if payload.get("schema") != SCHEMA or not isinstance(payload.get("projects"), list):
        raise ValueError("project conversation registry schema 无效")
    return payload


def _clean_asset(asset):
    if not isinstance(asset, dict):
        raise ValueError("asset 必须是对象")
    path = str(asset.get("path") or "").strip()
    role = str(asset.get("role") or "").strip()
    opaque_science_pointer = role == "pointer" and path.startswith("claude-science:proj_")
    if not path or (not Path(path).is_absolute() and not opaque_science_pointer) or role not in {"manifest", "unexpanded", "rollout", "pointer"}:
        raise ValueError("asset 需要绝对 path 与合法 role")
    return {"role": role, "path": path, "draggable": bool(asset.get("draggable", role != "pointer"))}


def _clean_conversation(row):
    if not isinstance(row, dict):
        raise ValueError("conversation 必须是对象")
    kind = str(row.get("kind") or "").strip()
    conversation_id = str(row.get("conversation_id") or "").strip()
    title = str(row.get("title") or conversation_id).strip()
    if kind not in ALLOWED_KINDS or not conversation_id or not title:
        raise ValueError("conversation 缺少合法 kind/conversation_id/title")
    assets = [_clean_asset(asset) for asset in row.get("assets", [])]
    if not assets:
        raise ValueError("conversation 至少需要一个 asset")
    if kind == "claude-science":
        for asset in assets:
            if asset["path"].startswith("claude-science:") and asset["path"] != f"claude-science:{conversation_id}":
                raise ValueError("Claude Science 标识指针必须与 conversation_id 一致")
        assets = [{**asset, "draggable": False} for asset in assets]
    elif any(asset["path"].startswith("claude-science:") for asset in assets):
        raise ValueError("Claude Science 标识指针只允许 claude-science kind")
    return {"kind": kind, "conversation_id": conversation_id, "title": title, "assets": assets}


def list_materials(deps, project_ref):
    project_ref = str(project_ref or "").strip()
    if not project_ref:
        return {"ok": False, "error": "缺少 project_ref"}, 400
    try:
        project = _project(deps["repo_root"], project_ref)
        if not project:
            return {"ok": False, "error": "项目不存在"}, 404
        registry = _registry(deps["repo_root"])
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 500
    linked = next((row for row in registry["projects"] if row.get("project_ref") == project_ref), None)
    conversations = linked.get("conversations", []) if linked else []
    fact_roots = []
    for value in project.get("fact_roots", []):
        clean = str(value or "").strip()
        if clean and clean not in fact_roots:
            fact_roots.append(clean)
    return {
        "ok": True,
        "project_ref": project_ref,
        "workdir": project.get("workdir") or "",
        "fact_roots": fact_roots,
        "conversations": conversations,
    }, 200


def link_conversation(deps, payload):
    project_ref = str(payload.get("project_ref") or "").strip()
    try:
        conversation = _clean_conversation(payload.get("conversation"))
        if not _project(deps["repo_root"], project_ref):
            return {"ok": False, "error": "项目不存在"}, 404
        registry = _registry(deps["repo_root"])
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400
    projects = registry["projects"]
    linked = next((row for row in projects if row.get("project_ref") == project_ref), None)
    if linked is None:
        linked = {"project_ref": project_ref, "conversations": []}
        projects.append(linked)
    rows = linked.setdefault("conversations", [])
    existing = next((idx for idx, row in enumerate(rows) if row.get("conversation_id") == conversation["conversation_id"]), None)
    if existing is None:
        rows.append(conversation)
        status = 201
    else:
        rows[existing] = conversation
        status = 200
    with deps["write_lock"]:
        _atomic_write_json(Path(deps["repo_root"]) / REGISTRY_REL, registry)
    return {"ok": True, "project_ref": project_ref, "conversation": conversation}, status


def unlink_conversation(deps, payload):
    project_ref = str(payload.get("project_ref") or "").strip()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not project_ref or not conversation_id:
        return {"ok": False, "error": "缺少 project_ref 或 conversation_id"}, 400
    try:
        if not _project(deps["repo_root"], project_ref):
            return {"ok": False, "error": "项目不存在"}, 404
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400

    with deps["write_lock"]:
        try:
            registry = _registry(deps["repo_root"])
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        linked = next((row for row in registry["projects"] if row.get("project_ref") == project_ref), None)
        rows = linked.get("conversations", []) if linked else []
        removed = next((row for row in rows if row.get("conversation_id") == conversation_id), None)
        if removed is None:
            return {"ok": False, "error": "归属对话不存在"}, 404
        linked["conversations"] = [
            row for row in rows if row.get("conversation_id") != conversation_id
        ]
        if not linked["conversations"]:
            registry["projects"] = [
                row for row in registry["projects"] if row.get("project_ref") != project_ref
            ]
        _atomic_write_json(Path(deps["repo_root"]) / REGISTRY_REL, registry)
    return {
        "ok": True,
        "project_ref": project_ref,
        "conversation_id": conversation_id,
        "conversation": removed,
    }, 200


def resolve_registered_material(deps, project_ref, path_value):
    requested = str(path_value or "").strip()
    result, status = list_materials(deps, project_ref)
    if status != 200:
        return None, result.get("error", "无法读取项目材料"), status
    registered = {
        asset.get("path")
        for row in result["conversations"]
        for asset in row.get("assets", [])
    }
    if requested not in registered:
        return None, "路径未登记为该项目材料", 403
    if requested.startswith("claude-science:"):
        return None, "Claude Science 会话标识仅作归属指针，不能作为本地路径打开", 400
    target = Path(os.path.realpath(os.path.expanduser(requested)))
    if not target.exists():
        return None, "已登记材料不存在", 404
    if target.suffix.lower() in {".app", ".command", ".terminal", ".workflow", ".scpt", ".applescript", ".webloc"}:
        return None, "拒绝打开可执行类型", 400
    return target, None, 200

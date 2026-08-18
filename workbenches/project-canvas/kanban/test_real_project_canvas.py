import importlib.util
import hashlib
import json
import threading
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("project_map_for_real_project_test", HERE / "project_map.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _deps(tmp_path):
    tasks = [
        {"task_id": "RSH-1", "project_ref": "research-alpha", "status": "todo", "path": "project/p/RSH-1.md"},
        {"task_id": "RSH-2", "project_ref": "research-alpha", "status": "done", "path": "project/p/RSH-2.md"},
        {"task_id": "RSH-2B", "project_ref": "research-alpha", "status": "completed", "path": "project/p/RSH-2B.md"},
        {"task_id": "RSH-3", "project_ref": "research-alpha", "project_role": "evidence", "status": "todo", "path": "project/p/RSH-3.md"},
        {"task_id": "RSH-4", "project_ref": "research-alpha", "project_role": "delivery", "status": "todo", "path": "project/p/RSH-4.md"},
        {"task_id": "KAN-1", "project_ref": "another-project", "status": "todo", "path": "project/p/KAN-1.md"},
    ]
    return {
        "repo_root": tmp_path,
        "scan_all": lambda: tasks,
        "list_real_projects": lambda: ({
            "ok": True,
            "projects": [{"project_ref": "research-alpha"}, {"project_ref": "another-project"}],
        }, 200),
    }


def test_real_project_scope_filters_explicit_project_ref_and_has_stable_path(tmp_path):
    deps = _deps(tmp_path)
    scope, error, status = MODULE._normalize_scope("project:research-alpha", deps)
    assert status == 200
    assert error == ""
    assert scope["type"] == "project"

    docs = MODULE._active_docs_for_scope(scope, deps)
    assert [row["task_id"] for row in docs] == ["RSH-1", "RSH-4"]
    canvas_path, canvas_ref, host_project, error, status = MODULE._resolve_map_path(scope, docs, deps)
    assert status == 200
    assert error == ""
    assert host_project == "个人调度"
    assert canvas_ref == "project/个人调度/.canvas/_project_maps/project/research-alpha/main.canvas.json"
    assert canvas_path == tmp_path / canvas_ref


def test_real_project_scope_rejects_unknown_project_ref(tmp_path):
    scope, error, status = MODULE._normalize_scope("project:not-registered", _deps(tmp_path))
    assert scope is None
    assert status == 404
    assert "unknown project_ref" in error


def test_project_card_metadata_carries_scannable_task_fields():
    metadata = MODULE._project_map_metadata(
        {"type": "project", "value": "research-alpha"},
        "个人调度",
        {
            "task_id": "RSH-1",
            "title": "Verify the evidence chain",
            "status": "in-progress",
            "stage": "证据核验",
            "assignee": "Claude",
            "next_action": "Read the three primary sources and write the claim table",
            "priority": "high",
            "due_date": "2026-08-12",
            "project_role": "delivery",
        },
    )
    card = metadata["project_map"]
    assert card["task_id"] == "RSH-1"
    assert card["task_title"] == "Verify the evidence chain"
    assert card["assignee"] == "Claude"
    assert card["next_action"].startswith("Read the three")
    assert card["priority"] == "high"
    assert card["due_date"] == "2026-08-12"
    assert card["project_role"] == "delivery"


def test_project_map_snapshot_and_restore_round_trip(tmp_path):
    deps = _deps(tmp_path)

    def read_canvas(path):
        target = Path(path)
        if not target.exists():
            return None, ""
        return json.loads(target.read_text(encoding="utf-8")), ""

    def canvas_rev(canvas):
        if not canvas:
            return ""
        encoded = json.dumps(canvas, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def atomic_write(path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    deps.update({
        "canvas_schema": "kanban.canvas/v1",
        "canvas_max_bytes": 1024 * 1024,
        "canvas_write_lock": threading.Lock(),
        "read_existing_canvas": read_canvas,
        "canvas_rev": canvas_rev,
        "atomic_write_text": atomic_write,
        "resolve_canvas_source_ref": lambda *_args, **_kwargs: {"status": "resolved", "resolved_path": ""},
        "canvas_status_counts": lambda _canvas: {},
        "canvas_audit_event": lambda actor, event, **fields: {"actor": actor, "event": event, **fields},
        "canvas_events_append": lambda _path, _events: True,
        "canvas_event_append_failure": lambda *_args: {"ok": False, "error": "event append failed"},
    })
    scope, _error, _status = MODULE._normalize_scope("project:research-alpha", deps)
    docs = MODULE._active_docs_for_scope(scope, deps)
    canvas_path, _canvas_ref, _project, _error, _status = MODULE._resolve_map_path(scope, docs, deps)
    original = {
        "schema": "kanban.canvas/v1",
        "nodes": [{"id": "note-1", "type": "note", "position": {"x": 10, "y": 20}, "data": {"text": "before"}}],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    atomic_write(canvas_path, json.dumps(original))
    version_id, snapshot_error = MODULE._snapshot_canvas(canvas_path, original, deps)
    assert snapshot_error == ""

    changed = {**original, "nodes": [{**original["nodes"][0], "data": {"text": "after"}}]}
    atomic_write(canvas_path, json.dumps(changed))
    conflict, conflict_status = MODULE.restore_project_map_version(
        "project:research-alpha",
        version_id,
        deps,
        actor="owner",
        base_rev="stale-revision",
    )
    assert conflict_status == 409
    assert conflict["conflict"] is True
    assert read_canvas(canvas_path)[0] == changed

    payload, status = MODULE.restore_project_map_version(
        "project:research-alpha",
        version_id,
        deps,
        actor="owner",
        base_rev=canvas_rev(changed),
    )

    assert status == 200
    assert payload["canvas"] == original
    assert read_canvas(canvas_path)[0] == original
    versions, versions_status = MODULE.list_project_map_versions("project:research-alpha", deps)
    assert versions_status == 200
    assert len(versions["versions"]) == 2
    assert versions["versions"][0]["node_count"] == 1


def test_project_map_save_records_file_library_add_remove_with_actor(tmp_path):
    deps = _deps(tmp_path)
    appended_events = []

    def read_canvas(path):
        target = Path(path)
        if not target.exists():
            return None, ""
        return json.loads(target.read_text(encoding="utf-8")), ""

    def canvas_rev(canvas):
        if not canvas:
            return ""
        encoded = json.dumps(canvas, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def atomic_write(path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def append_events(_path, events):
        appended_events.extend(events)
        return True

    deps.update({
        "canvas_schema": "kanban.canvas/v1",
        "canvas_max_bytes": 1024 * 1024,
        "canvas_write_lock": threading.Lock(),
        "read_existing_canvas": read_canvas,
        "canvas_rev": canvas_rev,
        "atomic_write_text": atomic_write,
        "resolve_canvas_source_ref": lambda *_args, **_kwargs: {"status": "resolved", "resolved_path": ""},
        "canvas_status_counts": lambda _canvas: {},
        "canvas_audit_event": lambda actor, event, **fields: {"actor": actor, "event": event, **fields},
        "canvas_diff_events": lambda _old, _new, _actor: [],
        "canvas_events_append": append_events,
        "canvas_event_append_failure": lambda *_args: {"ok": False, "error": "event append failed"},
    })
    scope, _error, _status = MODULE._normalize_scope("project:research-alpha", deps)
    docs = MODULE._active_docs_for_scope(scope, deps)
    canvas_path, _canvas_ref, _project, _error, _status = MODULE._resolve_map_path(scope, docs, deps)
    original = {
        "schema": "kanban.canvas/v1",
        "nodes": [],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "metadata": {
            "file_library": [
                {"id": "file:/materials/old.mov", "kind": "file", "path": "/materials/old.mov", "title": "old.mov", "source": "rail"},
                {"id": "dir:/materials", "kind": "dir", "path": "/materials", "title": "materials", "source": "rail"},
            ],
        },
    }
    atomic_write(canvas_path, json.dumps(original))
    updated = {
        **original,
        "metadata": {
            "file_library": [
                original["metadata"]["file_library"][1],
                {"id": "file:/materials/new.mov", "kind": "file", "path": "/materials/new.mov", "title": "new.mov", "source": "rail"},
            ],
        },
    }

    payload, status = MODULE.put_project_map(
        "project:research-alpha",
        updated,
        deps,
        actor="codex",
        base_rev=canvas_rev(original),
    )

    assert status == 200
    assert payload["ok"] is True
    file_events = [event for event in appended_events if event["event"].startswith("file_")]
    assert [(event["event"], event["path"]) for event in file_events] == [
        ("file_added", "/materials/new.mov"),
        ("file_removed", "/materials/old.mov"),
    ]
    assert {event["actor"] for event in file_events} == {"codex"}

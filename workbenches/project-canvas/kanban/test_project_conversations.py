import importlib.util
import json
import threading
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("project_conversations_test", HERE / "project_conversations.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SCAN_DOCS = (HERE / "scan-docs.py").read_text(encoding="utf-8")


def _deps(tmp_path):
    repo = tmp_path / "repo"
    projects = repo / MODULE.PROJECTS_REL
    projects.parent.mkdir(parents=True)
    projects.write_text(json.dumps({"projects": [{
        "project_ref": "alpha",
        "workdir": "/tmp/alpha",
        "fact_roots": ["/tmp/facts-a", "/tmp/facts-a", "/tmp/facts-b"],
    }]}))
    return {"repo_root": repo, "write_lock": threading.Lock()}


def test_empty_project_materials_preserve_workdir_and_empty_conversations(tmp_path):
    payload, status = MODULE.list_materials(_deps(tmp_path), "alpha")
    assert status == 200
    assert payload["workdir"] == "/tmp/alpha"
    assert payload["fact_roots"] == ["/tmp/facts-a", "/tmp/facts-b"]
    assert payload["conversations"] == []


def test_link_conversation_writes_sidecar_not_projects_registry(tmp_path):
    deps = _deps(tmp_path)
    projects_path = Path(deps["repo_root"]) / MODULE.PROJECTS_REL
    before = projects_path.read_bytes()
    target = tmp_path / "rollout.jsonl"
    target.write_text("{}\n")
    payload = {
        "project_ref": "alpha",
        "conversation": {
            "kind": "codex", "conversation_id": "session-1", "title": "Session one",
            "assets": [{"role": "rollout", "path": str(target), "draggable": True}],
        },
    }
    result, status = MODULE.link_conversation(deps, payload)
    assert status == 201 and result["ok"] is True
    assert projects_path.read_bytes() == before
    registry = json.loads((Path(deps["repo_root"]) / MODULE.REGISTRY_REL).read_text())
    assert registry["projects"][0]["conversations"][0]["conversation_id"] == "session-1"


def test_claude_science_assets_are_forced_non_draggable_and_open_is_exact(tmp_path):
    deps = _deps(tmp_path)
    target = tmp_path / "science-project"
    target.mkdir()
    payload = {
        "project_ref": "alpha",
        "conversation": {
            "kind": "claude-science", "conversation_id": "proj_1", "title": "Science",
            "assets": [{"role": "pointer", "path": str(target), "draggable": True}],
        },
    }
    result, status = MODULE.link_conversation(deps, payload)
    assert status == 201
    assert result["conversation"]["assets"][0]["draggable"] is False
    resolved, error, status = MODULE.resolve_registered_material(deps, "alpha", str(target))
    assert status == 200 and error is None and resolved == target.resolve()
    _, error, status = MODULE.resolve_registered_material(deps, "alpha", str(tmp_path))
    assert status == 403 and "未登记" in error


def test_claude_science_identifier_can_be_linked_as_readonly_opaque_pointer(tmp_path):
    deps = _deps(tmp_path)
    result, status = MODULE.link_conversation(deps, {
        "project_ref": "alpha",
        "conversation": {
            "kind": "claude-science", "conversation_id": "proj_opaque", "title": "Science pointer",
            "assets": [{"role": "pointer", "path": "claude-science:proj_opaque", "draggable": True}],
        },
    })
    assert status == 201
    assert result["conversation"]["assets"] == [{
        "role": "pointer", "path": "claude-science:proj_opaque", "draggable": False,
    }]
    _, error, status = MODULE.resolve_registered_material(deps, "alpha", "claude-science:proj_opaque")
    assert status == 400 and "仅作归属指针" in error


def test_unlink_conversation_atomically_removes_only_requested_attribution(tmp_path):
    deps = _deps(tmp_path)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text("{}\n")
    second.write_text("{}\n")
    for conversation_id, target in (("session-1", first), ("session-2", second)):
        result, status = MODULE.link_conversation(deps, {
            "project_ref": "alpha",
            "conversation": {
                "kind": "codex", "conversation_id": conversation_id, "title": conversation_id,
                "assets": [{"role": "rollout", "path": str(target), "draggable": True}],
            },
        })
        assert result["ok"] is True and status == 201

    result, status = MODULE.unlink_conversation(deps, {
        "project_ref": "alpha", "conversation_id": "session-1",
    })
    assert status == 200 and result["conversation"]["conversation_id"] == "session-1"
    registry = json.loads((Path(deps["repo_root"]) / MODULE.REGISTRY_REL).read_text())
    assert [row["conversation_id"] for row in registry["projects"][0]["conversations"]] == ["session-2"]
    assert first.exists() and second.exists()

    result, status = MODULE.unlink_conversation(deps, {
        "project_ref": "alpha", "conversation_id": "session-2",
    })
    assert status == 200 and result["ok"] is True
    registry = json.loads((Path(deps["repo_root"]) / MODULE.REGISTRY_REL).read_text())
    assert registry["projects"] == []


def test_unlink_missing_conversation_is_non_destructive(tmp_path):
    deps = _deps(tmp_path)
    result, status = MODULE.unlink_conversation(deps, {
        "project_ref": "alpha", "conversation_id": "missing",
    })
    assert status == 404 and result["ok"] is False
    assert not (Path(deps["repo_root"]) / MODULE.REGISTRY_REL).exists()


def test_scan_docs_exposes_thin_guarded_routes():
    assert "project_conversations.list_materials(_project_conversation_deps(), project_ref)" in SCAN_DOCS
    assert "project_conversations.link_conversation(_project_conversation_deps(), payload or {})" in SCAN_DOCS
    assert "project_conversations.unlink_conversation(_project_conversation_deps(), payload or {})" in SCAN_DOCS
    assert "'/api/real-projects/link-conversation'" in SCAN_DOCS
    assert "'/api/real-projects/unlink-conversation'" in SCAN_DOCS
    assert "'/api/project-materials/open'" in SCAN_DOCS
    assert "if not self._state_change_guard(parsed.path):" in SCAN_DOCS

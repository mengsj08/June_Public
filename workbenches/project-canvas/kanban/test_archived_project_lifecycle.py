import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("real_projects_archived_contract", HERE / "real_projects.py")
real_projects = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(real_projects)


def _deps(tmp_path):
    registry = tmp_path / "project/个人调度/.real-projects/projects.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "schema": real_projects.SCHEMA,
        "projects": [{
            "project_ref": "kept-project",
            "title": "Kept project",
            "confirmed_by": "owner",
            "lifecycle": "active",
            "health": "normal",
            "primary_action": {"type": "no_action"},
        }],
    }), encoding="utf-8")
    tasks = [{
        "task_id": "KMO-142",
        "title": "售后活动",
        "path": "project/个人调度/KMO-142.md",
        "project_ref": "kept-project",
        "status": "todo",
    }]
    return {
        "repo_root": tmp_path,
        "runtime_root": tmp_path / ".runtime",
        "scan_tasks": lambda: tasks,
        "owner_action_needed": lambda _task: False,
    }


def test_archived_update_keeps_registry_event_and_linked_cards(tmp_path):
    deps = _deps(tmp_path)

    result, status = real_projects.update_project(
        deps, {"project_ref": "kept-project", "lifecycle": "archived"}, actor="owner"
    )

    assert status == 200
    assert result["project"]["lifecycle"] == "archived"
    registry = json.loads((tmp_path / real_projects.REGISTRY_REL).read_text(encoding="utf-8"))
    assert registry["projects"][0]["project_ref"] == "kept-project"
    event = json.loads((tmp_path / real_projects.EVENTS_REL).read_text(encoding="utf-8").strip())
    assert event["changes"]["lifecycle"] == {"from": "active", "to": "archived"}

    projection, status = real_projects.build_projection(deps)
    assert status == 200
    assert projection["projects"][0]["tasks"]["active"][0]["task_id"] == "KMO-142"


def test_archived_projection_is_hidden_by_default_and_recallable(tmp_path):
    deps = _deps(tmp_path)
    result, status = real_projects.update_project(
        deps, {"project_ref": "kept-project", "lifecycle": "archived"}, actor="owner"
    )
    assert status == 200, result
    projection, status = real_projects.build_projection(deps)
    assert status == 200

    visible = real_projects.filter_archived_projects(projection)
    recalled = real_projects.filter_archived_projects(projection, include_archived=True)

    assert visible["projects"] == []
    assert visible["counts"]["projects"] == 0
    assert recalled["projects"][0]["project_ref"] == "kept-project"
    assert recalled["projects"][0]["tasks"]["active"][0]["task_id"] == "KMO-142"


def test_existing_lifecycles_remain_valid(tmp_path):
    for lifecycle in ("active", "paused", "completed", "archived"):
        deps = _deps(tmp_path / lifecycle)
        result, status = real_projects.update_project(
            deps, {"project_ref": "kept-project", "lifecycle": lifecycle}, actor="owner"
        )
        assert status == 200, result

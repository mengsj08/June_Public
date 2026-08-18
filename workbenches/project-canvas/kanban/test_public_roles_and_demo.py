import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


role_policy = _load("public_role_policy_test", HERE / "role_policy.py")
scan_docs = _load("public_scan_docs_role_test", HERE / "scan-docs.py")


def test_example_members_and_actors_are_role_configured():
    config = json.loads((HERE / ".kanban.config.example.json").read_text(encoding="utf-8"))
    roles = role_policy.normalize_roles(config["roles"])
    assert config["members"] == [roles["owner"]["member"]]
    assert config["ai_members"] == [roles["operator"]["member"], roles["reviewer"]["member"]]
    assert {item["actor"] for item in roles.values()} == {
        "project_owner", "automation_operator", "quality_reviewer",
    }


def test_acceptance_audit_uses_configured_role_actor():
    config = {
        "roles": {
            "owner": {"actor": "principal", "member": "Project Owner"},
            "operator": {"actor": "automation", "member": "Automation Operator"},
            "reviewer": {"actor": "quality", "member": "Quality Reviewer"},
        }
    }
    writes = []
    with patch.object(scan_docs, "update_frontmatter_field", side_effect=lambda path, field, value, **kwargs: writes.append((field, value))):
        scan_docs._stamp_acceptance("demo.md", "reviewer", config)
    assert ("accepted_role", "reviewer") in writes
    assert ("accepted_by", "quality") in writes


def test_demo_fixture_shape_and_config_paths():
    config = json.loads((ROOT / "demo" / "kanban.demo.config.json").read_text(encoding="utf-8"))
    project_files = sorted((ROOT / "demo" / "projects").glob("*/project.json"))
    cards = sorted((ROOT / "demo" / "projects").glob("*/*.md"))
    canvases = sorted((ROOT / "demo" / "projects").glob("*/.canvas/*/main.canvas.json"))
    assert len(project_files) == 2
    assert len(cards) == 8
    assert len(canvases) == 1
    assert str(canvases[0].relative_to(ROOT)) == (
        "demo/projects/literature-review/.canvas/DEMO-001/main.canvas.json"
    )
    assert {str(path.relative_to(ROOT)) for path in (ROOT / item for item in config["scan_dirs"])} == {
        "demo/projects/literature-review", "demo/projects/data-analysis",
    }
    assert all((ROOT / item).is_dir() for item in config["scan_dirs"])


def test_demo_real_project_registry_drives_two_project_canvas_entries(tmp_path):
    config = json.loads((ROOT / "demo" / "kanban.demo.config.json").read_text(encoding="utf-8"))
    registry_path = ROOT / config["real_projects_dir"] / "projects.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert registry["schema"] == "kanban-real-projects/v1"
    assert {row["project_ref"] for row in registry["projects"]} == {
        "literature-review", "data-analysis",
    }
    assert all(not Path(row["workdir"]).is_absolute() for row in registry["projects"])
    assert all((ROOT / row["workdir"]).is_dir() for row in registry["projects"])

    tasks = [
        scan_docs._parse_task_document(path, path.parent.name)
        for path in sorted((ROOT / "demo" / "projects").glob("*/*.md"))
    ]
    assert all(tasks)

    with patch.object(scan_docs, "REPO_ROOT", ROOT), \
         patch.object(scan_docs, "load_config", return_value=config):
        deps = scan_docs._real_projects_deps(tasks)
    assert Path(deps["registry_rel"]) == Path("demo/.real-projects/projects.json")
    deps["runtime_root"] = tmp_path / "runtime"
    projection, status = scan_docs.real_projects.build_projection(deps)

    assert status == 200
    assert projection["ok"] is True
    assert {row["project_ref"] for row in projection["projects"]} == {
        "literature-review", "data-analysis",
    }
    assert projection["event_ledger"] == "demo/.real-projects/events.jsonl"
    by_ref = {row["project_ref"]: row for row in projection["projects"]}
    assert len(by_ref["literature-review"]["tasks"]["linked"]) == 4
    assert len(by_ref["data-analysis"]["tasks"]["linked"]) == 4

    refreshed, refresh_status = scan_docs.real_projects.refresh_project(
        deps, "literature-review"
    )
    assert refresh_status == 200
    assert refreshed["outcome"] == "baseline_created"
    snapshot = json.loads(
        (deps["runtime_root"] / "literature-review.snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["files"], "repo-relative demo fact_roots must resolve and scan"


def test_interactive_canvas_actor_comes_from_server_session():
    client = (ROOT / "canvas-studio" / "src" / "services" / "canvasApi.ts").read_text(encoding="utf-8")
    assert "actor: 'owner'" not in client
    assert "_session_actor(session)" in (HERE / "scan-docs.py").read_text(encoding="utf-8")


def test_demo_task_detail_uses_scan_dir_leaf_as_project_name():
    config = json.loads((ROOT / "demo" / "kanban.demo.config.json").read_text(encoding="utf-8"))
    with patch.object(scan_docs, "REPO_ROOT", ROOT), \
         patch.object(scan_docs, "SCAN_DIRS", config["scan_dirs"]):
        result, status = scan_docs.get_task_detail(
            path="demo/projects/literature-review/DEMO-001.md",
        )

    assert status == 200
    assert result["task"]["project"] == "literature-review"

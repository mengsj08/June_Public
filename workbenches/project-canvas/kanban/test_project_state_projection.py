import importlib.util
import json
import threading
from hashlib import sha256
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPILER = _load("project_state_projection_test", "project_state_projection.py")
REAL_PROJECTS = _load("real_projects_projection_test", "real_projects.py")


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    repo = tmp_path / "repo"
    registry_path = repo / COMPILER.REGISTRY_REL
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema": COMPILER.REGISTRY_SCHEMA,
                "projects": [
                    {
                        "project_ref": "project-alpha",
                        "title": "Project Alpha",
                        "confirmed_by": "owner",
                        "lifecycle": "completed",
                        "health": "normal",
                        "latest_update": "旧的 1 个待校对子事件",
                        "primary_action": {"type": "needs_progress", "summary": "继续校对子事件"},
                        "unknowns": ["2 个子事件尚未全部晋升为 Event 正本并建立正式项目关联"],
                        "facts": [],
                        "milestones": [
                            {"label": "Event 正式项目关联", "state": "in_progress", "receipt": "old"}
                        ],
                        "fact_roots": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    closure = tmp_path / "closure.json"
    closure.write_text(
        json.dumps(
            {
                "project": {"project_id": "prj-project-alpha", "registration_status": "registered"},
                "coverage": {
                    "event_count": 2,
                    "events_with_high_confidence_source": 2,
                    "missing_stage_counts": {"before": 0, "during": 1, "after": 0},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events = [
        {
            "event_id": "evt-alpha-c1",
            "event_type": "course",
            "title": "C1",
            "canonical_time": "2026-05-01",
            "status": "confirmed",
            "project_ref": "project-alpha",
        },
        {
            "event_id": "evt-alpha-field-research-1",
            "event_type": "business_conversation",
            "title": "第一次驻场调研",
            "canonical_time": "2026-05-02",
            "status": "confirmed",
            "project_ref": "project-alpha",
        },
    ]
    pointers = [
        {
            "source_id": "closure-source",
            "source_kind": "project_fact_closure",
            "source_path": str(closure),
            "sha256": _sha(closure),
        }
    ]
    relations = [
        {"source_relation_id": f"rel-{row['event_id']}", "source_id": "closure-source", "event_id": row["event_id"]}
        for row in events
    ]
    files = {
        "events.jsonl": events,
        "source-pointers.jsonl": pointers,
        "source-relations.jsonl": relations,
    }
    manifest_files = {}
    for filename, rows in files.items():
        path = ledger / filename
        _write_jsonl(path, rows)
        manifest_files[filename] = {"sha256": _sha(path), "row_count": len(rows)}
    manifest = {
        "manifest_version": "event-ledger-manifest/v1",
        "transaction_id": "library-write-test",
        "written_at": "2026-07-18T12:00:00+08:00",
        "files": manifest_files,
        "write_receipt": {"canonical_path": str(ledger)},
    }
    (ledger / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return repo, ledger


def test_compile_and_merge_replaces_stale_event_summary_without_changing_identity(tmp_path):
    repo, ledger = _fixture(tmp_path)
    output = repo / COMPILER.STATE_REL
    compiled = COMPILER.compile_state(repo, ledger, output)
    assert compiled["changed"] is True
    assert compiled["event_count"] == 2
    first_mtime = output.stat().st_mtime_ns
    unchanged = COMPILER.compile_state(repo, ledger, output)
    assert unchanged["changed"] is False
    assert output.stat().st_mtime_ns == first_mtime

    deps = {
        "repo_root": repo,
        "runtime_root": tmp_path / "runtime",
        "scan_tasks": lambda: [],
        "write_lock": threading.Lock(),
    }
    projection, status = REAL_PROJECTS.build_projection(deps)
    assert status == 200
    project = projection["projects"][0]
    assert project["project_ref"] == "project-alpha"
    assert project["lifecycle"] == "completed"
    assert project["event_summary"]["count"] == 2
    assert "2 个 Event" in project["latest_update"]
    assert project["primary_action"]["type"] == "no_action"
    assert project["milestones"][0]["state"] == "verified"
    assert all("尚未全部晋升" not in item for item in project["unknowns"])
    assert any("现场 1 项" in item for item in project["unknowns"])
    assert projection["project_state"]["status"] == "current"


def test_api_ignores_sidecar_after_event_manifest_changes(tmp_path):
    repo, ledger = _fixture(tmp_path)
    COMPILER.compile_state(repo, ledger, repo / COMPILER.STATE_REL)
    manifest_path = ledger / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["transaction_id"] = "library-write-new"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    projection, status = REAL_PROJECTS.build_projection(
        {
            "repo_root": repo,
            "runtime_root": tmp_path / "runtime",
            "scan_tasks": lambda: [],
            "write_lock": threading.Lock(),
        }
    )
    assert status == 200
    assert projection["project_state"]["status"] == "stale"
    assert projection["project_state"]["reason"] == "event_ledger_changed"
    assert "event_summary" not in projection["projects"][0]
    assert projection["projects"][0]["primary_action"]["type"] == "needs_progress"

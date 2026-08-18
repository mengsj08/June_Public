from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("attention_queue_tested", HERE / "attention_queue.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_queue_reuses_classifier_and_is_global():
    tasks = [
        {"task_id": "KAN-1", "project_ref": "alpha", "status": "review", "path": "a", "updated": "2026-08-11"},
        {"task_id": "KAN-2", "project_ref": "beta", "status": "todo", "path": "b", "updated": "2026-08-10"},
        {"task_id": "KAN-3", "project_ref": "alpha", "status": "in-progress", "path": "c", "updated": "2026-08-09"},
    ]
    seen = []

    def classifier(task):
        seen.append(task["task_id"])
        return task["task_id"] in {"KAN-1", "KAN-2"}

    payload = MODULE.build_attention_queue(tasks, classifier)
    assert payload["scope"] == "global"
    assert [row["task_id"] for row in payload["needs_you"]] == ["KAN-1", "KAN-2"]
    assert payload["counts"]["needs_you"] == 2
    assert set(seen) == {"KAN-1", "KAN-2", "KAN-3"}


def test_recent_handled_has_bounded_window():
    payload = MODULE.build_attention_queue(
        [
            {"task_id": "NEW", "status": "done", "updated": "2026-08-10T00:00:00+00:00"},
            {"task_id": "OLD", "status": "done", "updated": "2026-07-01T00:00:00+00:00"},
        ],
        lambda _task: False,
        now=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    assert [row["task_id"] for row in payload["handled"]] == ["NEW"]


def test_project_queue_matches_canvas_contract_and_excludes_done():
    tasks = [
        {"task_id": "A-REVIEW", "project_ref": "alpha", "status": "review", "path": "a", "updated": "2026-08-11"},
        {"task_id": "A-RUN", "project_ref": "alpha", "status": "in-progress", "path": "b"},
        {"task_id": "A-TODO", "project_ref": "alpha", "status": "todo", "path": "c"},
        {"task_id": "A-DONE", "project_ref": "alpha", "status": "done", "path": "d"},
        {"task_id": "B-REVIEW", "project_ref": "beta", "status": "review", "path": "e"},
        {"task_id": "UNSCOPED", "status": "review", "path": "f"},
    ]
    gated = {"A-REVIEW", "B-REVIEW", "UNSCOPED"}

    payload = MODULE.build_attention_queue(
        tasks, lambda task: task["task_id"] in gated, project="alpha"
    )

    assert payload["scope"] == "project"
    assert payload["project"] == "alpha"
    assert payload["counts"] == {
        "needs_you": 1,
        "processing": 1,
        "planned": 1,
        "other_projects_needs_you": 1,
    }
    assert [row["task_id"] for row in payload["needs_you"]] == ["A-REVIEW"]
    assert [row["task_id"] for row in payload["processing"]] == ["A-RUN"]
    assert [row["task_id"] for row in payload["planned"]] == ["A-TODO"]
    assert all(row["project_ref"] == "alpha" for key in ("needs_you", "processing", "planned") for row in payload[key])
    assert "handled" not in payload


def test_project_queue_uses_shared_classifier_for_record_and_done_routing():
    attention_spec = importlib.util.spec_from_file_location(
        "attention_gate_for_queue_test", HERE / "attention_gate.py"
    )
    attention = importlib.util.module_from_spec(attention_spec)
    sys.modules[attention_spec.name] = attention
    attention_spec.loader.exec_module(attention)
    tasks = [
        {"task_id": "RECORD", "project_ref": "alpha", "status": "review", "doc_type": "record", "path": "a"},
        {"task_id": "DONE", "project_ref": "alpha", "status": "done", "human_gate": True, "attention_scope": "owner", "path": "b"},
        {"task_id": "GATE", "project_ref": "alpha", "status": "review", "human_gate": True, "attention_scope": "owner", "path": "c"},
    ]

    payload = MODULE.build_attention_queue(
        tasks,
        attention.requires_role_action,
        project="alpha",
        record_classifier=attention.is_backstage_record,
    )

    assert [row["task_id"] for row in payload["needs_you"]] == ["GATE"]
    assert payload["planned"] == []
    assert all(row["task_id"] not in {"RECORD", "DONE"} for key in ("needs_you", "processing", "planned") for row in payload[key])

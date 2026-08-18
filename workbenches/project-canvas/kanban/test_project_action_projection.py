import importlib.util
import json
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("project_action_projection_test", HERE / "project_action_projection.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _state(repo: Path, unknown: str = "Material coverage gap") -> Path:
    path = repo / MODULE.STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": MODULE.STATE_SCHEMA,
        "generated_at": "2026-07-18T00:00:00+08:00",
        "source": {"event_ledger_transaction_id": "tx-1"},
        "projects": [{"project_ref": "project-alpha", "unknowns": [unknown]}],
    }), encoding="utf-8")
    return path


def _task(repo: Path, **overrides) -> Path:
    values = {
        "title": "Alpha task",
        "task_id": "KAN-1",
        "project_ref": "project-alpha",
        "status": "review",
        "priority": "high",
        "responsibility": "pi-gated",
        "human_gate": "true",
        "attention_scope": "owner",
        "safety": "reversible",
        "next_action": "Owner chooses the boundary",
    }
    values.update(overrides)
    path = repo / "project" / "dispatch" / "KAN-1.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "---\n" + "\n".join(f"{key}: {value}" for key, value in values.items()) + "\n---\n\n# Task\n"
    path.write_text(body, encoding="utf-8")
    return path


def test_existing_human_gate_is_reused_without_execution_or_duplicate_card(tmp_path):
    repo = tmp_path / "repo"
    _state(repo)
    _task(repo)
    result = MODULE.compile_actions(repo)
    assert result["counts"] == {
        "ready_backstage": 0,
        "requires_owner": 1,
        "unbound": 0,
        "executed": 0,
        "duplicate_cards_created": 0,
    }
    payload = json.loads((repo / MODULE.ACTION_REL).read_text(encoding="utf-8"))
    action = payload["actions"][0]
    assert action["bound_task"]["task_id"] == "KAN-1"
    assert action["routing_status"] == "requires_owner"
    assert action["reason_code"] == "existing_task_human_gate"
    assert action["attention_reused"] is True
    assert action["automatic_execution_allowed"] is False
    assert action["execution_performed"] is False
    assert action["duplicate_card_created"] is False


def test_safe_backstage_task_is_ready_but_compiler_still_does_not_execute(tmp_path):
    repo = tmp_path / "repo"
    _state(repo)
    _task(
        repo,
        status="in_progress",
        responsibility="agent-executable",
        human_gate="false",
        attention_scope="backstage",
        safety="read-only",
        next_action="Inspect local evidence",
    )
    MODULE.compile_actions(repo)
    action = json.loads((repo / MODULE.ACTION_REL).read_text(encoding="utf-8"))["actions"][0]
    assert action["routing_status"] == "ready_backstage"
    assert action["automatic_execution_allowed"] is True
    assert action["execution_performed"] is False


def test_unbound_gap_stays_unbound_and_does_not_create_a_card(tmp_path):
    repo = tmp_path / "repo"
    _state(repo)
    MODULE.compile_actions(repo)
    action = json.loads((repo / MODULE.ACTION_REL).read_text(encoding="utf-8"))["actions"][0]
    assert action["routing_status"] == "unbound"
    assert action["bound_task"] is None
    assert action["duplicate_card_created"] is False
    assert list((repo / "project").rglob("*.md")) == []


def test_no_change_compile_preserves_generated_sidecar_mtime(tmp_path):
    repo = tmp_path / "repo"
    _state(repo)
    _task(repo)
    first = MODULE.compile_actions(repo)
    output = repo / MODULE.ACTION_REL
    first_mtime = output.stat().st_mtime_ns
    time.sleep(0.01)
    second = MODULE.compile_actions(repo)
    assert first["changed"] is True
    assert second["changed"] is False
    assert output.stat().st_mtime_ns == first_mtime

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("review_cycle_tested", HERE / "review_cycle.py")
review_cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_cycle)


def _fixture(tmp_path):
    repo = tmp_path / "repo"
    task = repo / "project" / "个人调度" / "KAN-1_demo.md"
    workdir = tmp_path / "work"
    task.parent.mkdir(parents=True)
    workdir.mkdir()
    task.write_text(
        """---
title: Demo
task_id: KAN-1
status: review
workdir: WORKDIR
---

## 要做什么
实现一个有证据的功能。

## 完成标准
- [x] 有测试

## 执行结果
- `demo.py:1`
""".replace("WORKDIR", str(workdir)),
        encoding="utf-8",
    )
    (workdir / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo, task.relative_to(repo).as_posix(), task, workdir


def _output(verdict="changes_required", status="open"):
    findings = [] if verdict == "pass" else [{
        "finding_id": "F-001",
        "severity": "major",
        "claim": "demo.py lacks a deterministic assertion",
        "evidence_refs": ["demo.py:1"],
        "verification": "python -m pytest",
        "status": status,
    }]
    return json.dumps({
        "schema_version": review_cycle.FINDINGS_SCHEMA,
        "verdict": verdict,
        "summary": "review summary",
        "findings": findings,
    })


def test_review_ledger_accepts_configured_demo_scan_dir(tmp_path):
    repo = tmp_path / "repo"
    task_path = "demo/projects/literature-review/DEMO-001.md"
    task = repo / task_path
    task.parent.mkdir(parents=True)
    task.write_text("---\ntask_id: DEMO-001\n---\n", encoding="utf-8")

    ledger = review_cycle.ledger_path(
        repo, task_path, ["demo/projects/literature-review"],
    )

    assert ledger == task.parent / ".reviews" / "DEMO-001" / "ledger.jsonl"
    with pytest.raises(review_cycle.ReviewCycleError, match="scan_dirs"):
        review_cycle.ledger_path(repo, task_path, ["demo/projects/data-analysis"])


def _start(repo, task_path, task, workdir):
    prepared = review_cycle.start_cycle(
        repo, task_path, task.read_text(encoding="utf-8"), workdir,
        reviewer_tool="claude", reviewer_profile="review_claude",
        producer_tool="codex", producer_profile="execute_codex",
        actor="Owner",
    )
    review_cycle.record_queued(repo, task_path, prepared["cycle_id"], "review", "run-review")
    return prepared


def test_isolated_contract_drops_appended_ai_transcript():
    raw = "## 目标\n事实契约\n\n<!-- ai-result: codex 2026-07-19 -->\nproducer private discussion"
    isolated = review_cycle.isolated_contract(raw)
    assert "事实契约" in isolated
    assert "producer private discussion" not in isolated
    assert "ai-result" not in isolated


def test_full_review_repair_recheck_cycle_is_bounded(tmp_path):
    repo, task_path, task, workdir = _fixture(tmp_path)
    prepared = _start(repo, task_path, task, workdir)
    review_entry = {
        "id": "run-review", "status": "completed", "output": _output(),
        "metadata": prepared["queue"]["metadata"],
    }
    assert review_cycle.process_terminal(repo, task_path, review_entry, task.read_text(encoding="utf-8")) == {}
    reviewed = review_cycle.project_state(repo, task_path)
    assert reviewed["state"] == "revision_required"
    assert reviewed["findings"][0]["finding_id"] == "F-001"

    repair = review_cycle.prepare_repair(repo, task_path, task.read_text(encoding="utf-8"), workdir)
    assert repair["queue"]["tool"] == "codex"
    assert "producer private" not in repair["queue"]["prompt"]
    review_cycle.record_queued(repo, task_path, prepared["cycle_id"], "repair", "run-repair")

    repair_entry = {
        "id": "run-repair", "status": "completed", "output": "repair done",
        "metadata": repair["queue"]["metadata"],
    }
    action = review_cycle.process_terminal(repo, task_path, repair_entry, task.read_text(encoding="utf-8"))
    recheck = action["enqueue"]
    assert recheck["tool"] == "claude"
    assert recheck["profile"] == "review_claude"
    assert recheck["metadata"]["context_mode"] == "original_findings_only"
    assert "F-001" in recheck["prompt"]
    review_cycle.record_queued(repo, task_path, prepared["cycle_id"], "recheck", "run-recheck")

    recheck_entry = {
        "id": "run-recheck", "status": "completed", "output": _output("pass"),
        "metadata": recheck["metadata"],
    }
    review_cycle.process_terminal(repo, task_path, recheck_entry, task.read_text(encoding="utf-8"))
    final = review_cycle.project_state(repo, task_path)
    assert final["state"] == "resolved"
    assert final["repair_count"] == 1
    with pytest.raises(review_cycle.ReviewCycleError, match="没有可修订"):
        review_cycle.prepare_repair(repo, task_path, task.read_text(encoding="utf-8"), workdir)


def test_recheck_open_finding_escalates_to_owner(tmp_path):
    repo, task_path, task, workdir = _fixture(tmp_path)
    prepared = _start(repo, task_path, task, workdir)
    review_cycle.process_terminal(repo, task_path, {
        "id": "run-review", "status": "completed", "output": _output(),
        "metadata": prepared["queue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    repair = review_cycle.prepare_repair(repo, task_path, task.read_text(encoding="utf-8"), workdir)
    review_cycle.record_queued(repo, task_path, prepared["cycle_id"], "repair", "run-repair")
    action = review_cycle.process_terminal(repo, task_path, {
        "id": "run-repair", "status": "completed", "output": "done",
        "metadata": repair["queue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    review_cycle.record_queued(repo, task_path, prepared["cycle_id"], "recheck", "run-recheck")
    review_cycle.process_terminal(repo, task_path, {
        "id": "run-recheck", "status": "completed", "output": _output(),
        "metadata": action["enqueue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    assert review_cycle.project_state(repo, task_path)["state"] == "needs_owner"


def test_artifact_change_makes_review_stale(tmp_path):
    repo, task_path, task, workdir = _fixture(tmp_path)
    prepared = _start(repo, task_path, task, workdir)
    task.write_text(task.read_text(encoding="utf-8") + "\nexternal change\n", encoding="utf-8")
    review_cycle.process_terminal(repo, task_path, {
        "id": "run-review", "status": "completed", "output": _output("pass"),
        "metadata": prepared["queue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    state = review_cycle.project_state(repo, task_path)
    assert state["state"] == "stale"
    assert not state["findings"]


def test_commit_boundary_alone_does_not_make_review_stale(tmp_path):
    repo, task_path, task, workdir = _fixture(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    prepared = _start(repo, task_path, task, workdir)
    subprocess.run(["git", "add", "demo.py"], cwd=workdir, check=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "autosync",
    ], cwd=workdir, check=True)
    review_cycle.process_terminal(repo, task_path, {
        "id": "run-review", "status": "completed", "output": _output("pass"),
        "metadata": prepared["queue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    assert review_cycle.project_state(repo, task_path)["state"] == "resolved"


def test_invalid_reviewer_json_fails_closed(tmp_path):
    repo, task_path, task, workdir = _fixture(tmp_path)
    prepared = _start(repo, task_path, task, workdir)
    review_cycle.process_terminal(repo, task_path, {
        "id": "run-review", "status": "completed", "output": "looks good to me",
        "metadata": prepared["queue"]["metadata"],
    }, task.read_text(encoding="utf-8"))
    state = review_cycle.project_state(repo, task_path)
    assert state["state"] == "system_blocked"
    assert "JSON" in state["summary"]


def test_frontend_wires_model_choice_and_explicit_repair():
    frontend = (HERE / "static" / "kanban" / "modules" / "review-cycle.js").read_text(encoding="utf-8")
    main = (HERE / "static" / "kanban" / "main.js").read_text(encoding="utf-8")
    assert "review_claude" in frontend and "review_codex" in frontend
    assert "/api/review-cycle/start" in frontend
    assert "/api/review-cycle/repair" in frontend
    assert "全新只读 session" in frontend
    assert "setupReviewCycle(ctx)" in main

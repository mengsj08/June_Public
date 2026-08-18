import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scan_docs_review_cycle", HERE / "scan-docs.py")
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


def _task(tmp_path, status="review"):
    workdir = tmp_path / "work"
    workdir.mkdir()
    task = tmp_path / "project" / "P" / "KAN-1_demo.md"
    task.parent.mkdir(parents=True)
    task.write_text(f"""---
title: Demo
task_id: KAN-1
status: {status}
workdir: {workdir}
---

## 要做什么
实现功能。

## 完成标准
- [x] 验证

## 执行结果
- `demo.py:1`
""", encoding="utf-8")
    (workdir / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    return "project/P/KAN-1_demo.md", task, workdir


def _patch_context(tmp_path, workdir):
    return (
        patch.object(scan, "REPO_ROOT", tmp_path),
        patch.object(scan, "resolve_workdir", return_value=(workdir, None)),
        patch.object(scan, "_coerce_workdir_to_cwd", return_value=(workdir, None)),
        patch.object(scan, "resolve_ai_profile", side_effect=lambda tool, requested, *a, **k: (requested, "")),
    )


def test_start_review_cycle_uses_separate_reviewer_and_existing_queue(tmp_path):
    task_path, _task_file, workdir = _task(tmp_path)
    queued = []
    patches = _patch_context(tmp_path, workdir)
    with patches[0], patches[1], patches[2], patches[3], \
            patch.object(scan, "_queue_get_by_path", return_value=[{
                "status": "completed", "tool": "codex", "ai_profile": "execute_codex",
                "timestamp": "2026-07-19T10:00:00", "metadata": {},
            }]), \
            patch.object(scan, "_queue_add_entry", side_effect=lambda *a, **k: queued.append((a, k)) or "run-review"), \
            patch.object(scan, "_queue_consume_next"):
        result, status = scan.start_review_cycle(task_path, reviewer_tool="claude", actor="Owner")
    assert status == 200 and result["ok"]
    args, kwargs = queued[0]
    assert args[0] == "claude"
    assert kwargs["ai_profile"] == "review_claude"
    assert kwargs["metadata"]["context_mode"] == "isolated_artifact_only"
    assert kwargs["metadata"]["producer_tool"] == "codex"
    assert "hidden reasoning" in kwargs["prompt_override"]


def test_done_card_can_be_reviewed_but_cannot_be_repaired(tmp_path):
    task_path, _task_file, workdir = _task(tmp_path, status="done")
    patches = _patch_context(tmp_path, workdir)
    with patches[0], patches[1], patches[2], patches[3], \
            patch.object(scan, "_queue_get_by_path", return_value=[]), \
            patch.object(scan, "_queue_add_entry", return_value="run-review"), \
            patch.object(scan, "_queue_consume_next"):
        started, start_status = scan.start_review_cycle(task_path, reviewer_tool="claude")
        repair, repair_status = scan.repair_review_cycle(task_path)
    assert start_status == 200 and started["ok"]
    assert repair_status == 409
    assert "重新打开" in repair["error"]


def test_terminal_repair_enqueues_same_reviewer_recheck(tmp_path):
    task_path, task_file, workdir = _task(tmp_path)
    prepared = scan.review_cycle.start_cycle(
        tmp_path, task_path, task_file.read_text(encoding="utf-8"), workdir,
        reviewer_tool="claude", reviewer_profile="review_claude",
        producer_tool="codex", producer_profile="execute_codex",
    )
    cycle_id = prepared["cycle_id"]
    scan.review_cycle.record_queued(tmp_path, task_path, cycle_id, "review", "run-review")
    output = json.dumps({
        "schema_version": scan.review_cycle.FINDINGS_SCHEMA,
        "verdict": "changes_required", "summary": "fix it",
        "findings": [{
            "finding_id": "F-001", "severity": "major", "claim": "missing assertion",
            "evidence_refs": ["demo.py:1"], "verification": "pytest", "status": "open",
        }],
    })
    scan.review_cycle.process_terminal(tmp_path, task_path, {
        "id": "run-review", "status": "completed", "output": output,
        "metadata": prepared["queue"]["metadata"],
    }, task_file.read_text(encoding="utf-8"))
    repair = scan.review_cycle.prepare_repair(
        tmp_path, task_path, task_file.read_text(encoding="utf-8"), workdir,
    )
    scan.review_cycle.record_queued(tmp_path, task_path, cycle_id, "repair", "run-repair")
    repair_entry = {
        "id": "run-repair", "path": task_path, "status": "completed", "output": "done",
        "metadata": repair["queue"]["metadata"],
    }
    queued = []
    patches = _patch_context(tmp_path, workdir)
    with patches[0], patches[1], patches[2], patches[3], \
            patch.object(scan, "_queue_get_entry", return_value=repair_entry), \
            patch.object(scan, "_queue_add_entry", side_effect=lambda *a, **k: queued.append((a, k)) or "run-recheck"):
        scan._handle_review_cycle_terminal("run-repair")
    assert len(queued) == 1
    args, kwargs = queued[0]
    assert args[0] == "claude"
    assert kwargs["ai_profile"] == "review_claude"
    assert kwargs["metadata"]["stage"] == "recheck"
    assert scan.review_cycle.project_state(tmp_path, task_path)["state"] == "rechecking"

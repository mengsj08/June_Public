import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "backfill_watcher_record_doc_type_tested",
    HERE / "backfill_watcher_record_doc_type.py",
)
assert SPEC and SPEC.loader
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


def _write_card(
    path: Path,
    *,
    task_id="KAN-1",
    status="done",
    source="archive-map-watcher/run-1",
    title="Conversation Map 自动生成记录 — sample",
    extra="",
    body="## 执行结果\n\n完成。\n",
):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"title: {title}\n"
        f"task_id: {task_id}\n"
        f"status: {status}\n"
        "updated: 2026-07-01T01:02:03+08:00\n"
        "status_changed_at: 2026-07-02T03:04:05+08:00\n"
        "attention_scope: backstage\n"
        "human_gate: false\n"
        f"source: {source}\n"
        f"{extra}"
        "---\n\n" + body,
        encoding="utf-8",
    )


def _config():
    return {"scan_dirs": ["project/个人调度"]}


def test_dry_run_apply_preserves_timestamps_and_second_run_is_idempotent(tmp_path):
    card_path = tmp_path / "project" / "个人调度" / "KAN-1.md"
    _write_card(card_path)
    before = card_path.read_bytes()

    dry = backfill.build_backfill_report(tmp_path, apply=False, config=_config())
    assert dry["matched_count"] == 1
    assert card_path.read_bytes() == before
    assert dry["changes"][0]["old_value"] is None
    assert dry["changes"][0]["new_value"] == "record"

    applied = backfill.build_backfill_report(tmp_path, apply=True, config=_config())
    assert applied["matched_count"] == 1
    proof = applied["write_proofs"][0]
    assert proof["only_expected_line_added"] is True
    assert proof["updated"]["byte_equal"] is True
    assert proof["status_changed_at"]["byte_equal"] is True
    assert card_path.read_bytes() == before.replace(b"---\n\n##", b"doc_type: record\n---\n\n##", 1)

    second = backfill.build_backfill_report(tmp_path, apply=True, config=_config())
    assert second["matched_count"] == 0
    assert any("doc_type_already_present:record" in row["reasons"] for row in second["exclusions"])


def test_selector_rejects_human_gate_active_nonstandard_and_excluded_sources(tmp_path):
    directory = tmp_path / "project" / "个人调度"
    _write_card(directory / "human.md", task_id="KAN-2", extra="responsibility: pi-gated\n")
    _write_card(directory / "active.md", task_id="KAN-3", status="review")
    _write_card(directory / "prefix.md", task_id="KAN-4", source="skill-board/asset-1")
    _write_card(directory / "title.md", task_id="KAN-5", title="普通执行记录")
    _write_card(directory / "existing.md", task_id="KAN-6", extra="doc_type: task\n")

    report = backfill.build_backfill_report(tmp_path, apply=False, config=_config())
    assert report["matched_count"] == 0
    reasons = {row["task_id"]: row["reasons"] for row in report["exclusions"]}
    assert "pi_gate:responsibility" in reasons["KAN-2"]
    assert "non_terminal_status:review" in reasons["KAN-3"]
    assert "excluded_source_prefix:skill-board/" in reasons["KAN-4"]
    assert "title_not_watcher_standard_template" in reasons["KAN-5"]
    assert "doc_type_already_present:task" in reasons["KAN-6"]


def test_phase_a_is_allowlisted_and_fail_closed(monkeypatch, tmp_path):
    directory = tmp_path / "project" / "个人调度"
    retrospective = "## 背景 / 来源\n\n本卡只补记已发生执行。\n\n## 执行结果\n\n已完成。\n"
    _write_card(directory / "allowed.md", task_id="KAN-200", title="样例账外执行记录", body=retrospective)
    _write_card(directory / "unknown.md", task_id="KAN-201", title="另一样例执行记录", body=retrospective)
    _write_card(directory / "weak.md", task_id="KAN-202", title="修复记录卡路由问题", body=retrospective)
    _write_card(directory / "human.md", task_id="KAN-203", title="人闸执行记录", extra="human_gate: true\n", body=retrospective)
    monkeypatch.setattr(backfill, "PHASE_A_ALLOWLIST", frozenset({"KAN-200"}))

    dry = backfill.build_phase_a_report(tmp_path, apply=False, config=_config())
    assert dry["candidate_count"] == 4
    assert dry["decision_counts"] == {"backfill": 1, "excluded": 2, "uncertain": 1}
    assert dry["changes"][0]["task_id"] == "KAN-200"
    assert dry["decisions"]["uncertain"][0]["reasons"] == ["not_in_reviewed_allowlist"]

    applied = backfill.build_phase_a_report(tmp_path, apply=True, config=_config())
    assert applied["matched_count"] == 1
    assert applied["write_proofs"][0]["updated"]["byte_equal"] is True
    second = backfill.build_phase_a_report(tmp_path, apply=True, config=_config())
    assert second["matched_count"] == 0


def test_phase_b_removes_only_doc_type_task_and_preserves_timestamps(tmp_path):
    directory = tmp_path / "project" / "个人调度"
    task_path = directory / "task.md"
    record_path = directory / "record.md"
    _write_card(task_path, extra="doc_type: task\n")
    _write_card(record_path, task_id="KAN-2", extra="doc_type: record\n")
    before = task_path.read_bytes()

    dry = backfill.build_phase_b_report(tmp_path, apply=False, config=_config())
    assert dry["matched_count"] == 1
    assert task_path.read_bytes() == before

    applied = backfill.build_phase_b_report(tmp_path, apply=True, config=_config())
    assert applied["matched_count"] == 1
    proof = applied["write_proofs"][0]
    assert proof["only_expected_line_removed"] is True
    assert proof["updated"]["byte_equal"] is True
    assert proof["status_changed_at"]["byte_equal"] is True
    assert task_path.read_bytes() == before.replace(b"doc_type: task\n", b"", 1)
    assert b"doc_type: record\n" in record_path.read_bytes()

    second = backfill.build_phase_b_report(tmp_path, apply=True, config=_config())
    assert second["matched_count"] == 0

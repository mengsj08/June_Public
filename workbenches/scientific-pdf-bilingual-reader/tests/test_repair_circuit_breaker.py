import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_workflow  # noqa: E402
from qa_contract import build_contract  # noqa: E402
from review_workflow import (  # noqa: E402
    build_review,
    create_diagnosis,
    decide_escalation,
    diagnose,
    run_repair,
    start_repair,
    write_json,
)


def advice(alternatives=None):
    return {
        "schema": "claude-repair-strategy-advice/v1",
        "is_repairable": True,
        "problem_family": "layout",
        "strategy_summary": "restore layout on this page only",
        "execution_family": "layout",
        "bounded_steps": ["repair selected page"],
        "validation_expectations": ["target red disappears"],
        "risks": ["layout may still need June visual check"],
        "alternatives": alternatives or [
            {
                "strategy_id": "manual_overlay",
                "label": "手工局部覆盖",
                "boundary": "仅当前页",
                "risk": "坐标偏移",
                "cost": "中",
            }
        ],
    }


class RepairCircuitBreakerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.task = {
            "id": "sample",
            "name": "sample.pdf",
            "original_file": "original.pdf",
            "translated_file": "translated-zh.pdf",
            "page_plan_file": "page-plan.json",
            "qa_alpha_file": "qa-alpha.json",
        }
        (self.folder / "original.pdf").write_text("original")
        (self.folder / "translated-zh.pdf").write_text("current")
        write_json(self.folder / "page-plan.json", {"pages": [{"pdf_page": 1, "type": "body"}]})
        self.write_qa("qa-alpha.json", red_pages=[1], output=self.folder / "translated-zh.pdf")

    def tearDown(self):
        self.temp.cleanup()

    def write_qa(self, name, red_pages, output):
        pages = []
        for page in [1, 2]:
            issues = []
            status = "pass"
            if page in red_pages:
                status = "red"
                issues = [{"issue_type": "rendered_structure_drift", "severity": "red", "evidence": "grid drift"}]
            pages.append({"pdf_page": page, "status": status, "metrics": {}, "issues": issues})
        report = {
            "status": "needs_review" if red_pages else "passed",
            "page_count": 2,
            "summary": {"red": len(red_pages), "orange": 0, "warning": 0, "pass": 2 - len(red_pages)},
            "flagged_pages": red_pages,
            "pages": pages,
        }
        report["contract"] = build_contract(
            original_path=self.folder / "original.pdf",
            output_path=output,
            plan_path=self.folder / "page-plan.json",
            task=self.task,
        )
        write_json(self.folder / name, report)
        return report

    def make_attempt(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")
        diagnose(self.folder, self.task, record["repair_id"], 1, [issue_id], "claude", "", advice_provider=advice)
        return record["repair_id"]

    def executor(self, red_pages):
        def run(folder, task, record, staging):
            staging.mkdir(parents=True, exist_ok=True)
            (staging / "translated.pdf").write_text("candidate")
            (staging / "dual.pdf").write_text("dual")
            write_json(staging / "plan.json", {"pages": [{"pdf_page": 1, "type": "body"}]})
            result = {"repaired_file": "translated.pdf", "qa_file": "qa.json", "repaired_plan": "plan.json"}
            self.write_qa(staging / "qa.json", red_pages=red_pages, output=staging / "translated.pdf")
            return result, {
                "translated": staging / "translated.pdf",
                "dual": staging / "dual.pdf",
                "qa": staging / "qa.json",
                "plan": staging / "plan.json",
            }
        return run

    def test_advice_success_then_candidate_awaits_june_acceptance(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([]))
        record = (self.folder / "repairs" / repair_id / "repair.json").read_text()
        self.assertIn('"status": "awaiting_acceptance"', record)
        self.assertIn('"machine_gate": "pass"', record)

    def test_generation_failure_escalates_with_report(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)

        def failing(*_args):
            raise RuntimeError("render failed")

        run_repair(self.folder, self.task, repair_id, repair_executor=failing)
        repair_dir = self.folder / "repairs" / repair_id
        record = repair_dir / "repair.json"
        self.assertIn('"status": "repair_escalated"', record.read_text())
        self.assertTrue((repair_dir / "failure-report.json").is_file())
        self.assertTrue((repair_dir / "failure-report.md").is_file())

    def test_target_red_remaining_escalates(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([1]))
        record = (self.folder / "repairs" / repair_id / "repair.json").read_text()
        self.assertIn('"repair_escalated"', record)
        self.assertIn("目标 red hard blocker 未消除", record)

    def test_new_red_escalates(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([2]))
        record = (self.folder / "repairs" / repair_id / "repair.json").read_text()
        self.assertIn('"repair_escalated"', record)
        self.assertIn("候选版本新增 red 页面", record)

    def test_duplicate_attempt_and_parallel_attempt_are_rejected(self):
        repair_id = self.make_attempt()
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        with self.assertRaisesRegex(RuntimeError, "未关闭 repair attempt"):
            create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([1]))
        with self.assertRaisesRegex(RuntimeError, "未关闭 repair attempt"):
            create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")

    def test_june_decision_can_stop_or_create_referenced_next_attempt(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([1]))
        result = decide_escalation(self.folder, self.task, repair_id, {"choice": "manual_overlay", "note": "use tighter bounds"})
        next_record = result["created_attempt"]
        self.assertIsNotNone(next_record)
        self.assertEqual(next_record["previous_failure_report_id"], repair_id)

    def test_claude_missing_fail_closed_without_fake_provider(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        with mock.patch.object(review_workflow, "model_cli_available", return_value=False):
            run_repair(self.folder, self.task, repair_id)
        record = (self.folder / "repairs" / repair_id / "repair.json").read_text()
        self.assertIn('"status": "repair_escalated"', record)
        self.assertIn("CLI 可用", record)


if __name__ == "__main__":
    unittest.main()

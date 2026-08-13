import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_workflow  # noqa: E402
from qa_contract import build_contract  # noqa: E402
from review_workflow import (  # noqa: E402
    ADVISOR_RECOVERY_STRATEGY_ID,
    ProviderInvocationError,
    build_review,
    create_diagnosis,
    decide_escalation,
    diagnose,
    enforce_execution_readiness,
    inspect_execution_readiness,
    normalize_advice,
    revise_advisor_failure_report,
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

    def test_visual_feedback_can_refine_generic_untranslated_family_to_table(self):
        refined = advice()
        refined.update(problem_family="table_untranslated", execution_family="table_untranslated")
        normalized = normalize_advice(refined, "untranslated_region")
        self.assertEqual(normalized["execution_family"], "table_untranslated")

    def test_visual_feedback_cannot_jump_to_incompatible_family(self):
        incompatible = advice()
        incompatible.update(problem_family="toc_layout", execution_family="toc_layout")
        with self.assertRaisesRegex(RuntimeError, "untranslated_region -> toc_layout"):
            normalize_advice(incompatible, "untranslated_region")

    def test_diagnosis_updates_executor_to_advisor_refined_family(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "table visual feedback")

        def refined_advice():
            payload = advice()
            payload.update(problem_family="table_untranslated", execution_family="table_untranslated")
            return payload

        diagnose(
            self.folder, self.task, record["repair_id"], 1, [issue_id], "claude",
            "table visual feedback", advice_provider=refined_advice,
        )
        saved = review_workflow.read_json(
            self.folder / "repairs" / record["repair_id"] / "repair.json", {}
        )
        self.assertEqual(saved["status"], "diagnosed")
        self.assertEqual(saved["execution_strategy"]["family"], "table_untranslated")
        self.assertEqual(saved["execution_strategy"]["advisor_refinement"], {
            "from_family": "layout",
            "to_family": "table_untranslated",
            "changed": True,
        })

    def test_table_strategy_preflight_blocks_page_without_detected_grid(self):
        import fitz

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Quantity Growth Initial Conditions")
        document.save(self.folder / "original.pdf")
        document.close()
        readiness = inspect_execution_readiness(self.folder, self.task, {
            "pdf_page": 1,
            "execution_strategy": {"family": "table_untranslated"},
        })
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["reason_code"], "strict_table_detection_missing")

    def test_failed_executor_preflight_escalates_without_candidate(self):
        repair_id = self.make_attempt()
        record_path = self.folder / "repairs" / repair_id / "repair.json"
        record = review_workflow.read_json(record_path, {})
        blocked = {
            "schema": "repair-execution-readiness/v1",
            "checked": True,
            "ready": False,
            "reason_code": "strict_table_detection_missing",
            "reason": "no deterministic table cells",
        }
        with mock.patch.object(review_workflow, "inspect_execution_readiness", return_value=blocked):
            result = enforce_execution_readiness(self.folder, self.task, record)
        self.assertEqual(result["status"], "repair_escalated")
        self.assertEqual(result["failure_stage"], "executor_capability")
        self.assertFalse((self.folder / "repairs" / repair_id / "candidate").exists())
        report = review_workflow.read_json(
            self.folder / "repairs" / repair_id / "failure-report.json", {}
        )
        self.assertEqual(report["execution_readiness"], blocked)

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
        self.assertEqual(next_record["feedback"], "use tighter bounds")

    def test_successor_attempt_preserves_prior_visual_feedback(self):
        repair_id = self.make_attempt()
        repair_path = self.folder / "repairs" / repair_id / "repair.json"
        record = review_workflow.read_json(repair_path, {})
        record["feedback"] = "表头中文悬浮，必须原位替换"
        write_json(repair_path, record)
        start_repair(self.folder, repair_id)
        run_repair(self.folder, self.task, repair_id, repair_executor=self.executor([1]))
        result = decide_escalation(
            self.folder, self.task, repair_id,
            {"choice": "manual_overlay", "note": "已修复兼容族迁移"},
        )
        self.assertEqual(
            result["created_attempt"]["feedback"],
            "表头中文悬浮，必须原位替换\n\n本次补充：已修复兼容族迁移",
        )

    def test_claude_missing_fail_closed_without_fake_provider(self):
        repair_id = self.make_attempt()
        start_repair(self.folder, repair_id)
        with mock.patch.object(review_workflow, "model_cli_available", return_value=False):
            run_repair(self.folder, self.task, repair_id)
        record = (self.folder / "repairs" / repair_id / "repair.json").read_text()
        self.assertIn('"status": "repair_escalated"', record)
        self.assertIn("CLI 可用", record)

    def test_advisor_failure_persists_bounded_retry_events_and_recovery_option(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")

        def failing_advisor():
            raise ProviderInvocationError("schema rejected")

        diagnose(
            self.folder, self.task, record["repair_id"], 1, [issue_id], "claude", "",
            advice_provider=failing_advisor,
        )
        repair_dir = self.folder / "repairs" / record["repair_id"]
        failed = review_workflow.read_json(repair_dir / "repair.json", {})
        report = review_workflow.read_json(repair_dir / "failure-report.json", {})
        self.assertEqual(failed["status"], "repair_escalated")
        self.assertEqual([event["attempt"] for event in failed["provider_retry_events"]], [1, 2])
        self.assertTrue(all(event["kind"] == "provider_or_network_error" for event in failed["provider_retry_events"]))
        self.assertEqual(report["provider_retry_events"], failed["provider_retry_events"])
        self.assertEqual(report["feedback"], "")
        self.assertIsNone(report["previous_failure_report_id"])
        self.assertIn(
            ADVISOR_RECOVERY_STRATEGY_ID,
            [item["strategy_id"] for item in report["options"]["alternatives"]],
        )

    def test_revised_legacy_advisor_report_can_create_referenced_attempt(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")
        record.update(status="repair_escalated", failure_stage="claude_advice", error="legacy failure")
        write_json(self.folder / "repairs" / record["repair_id"] / "repair.json", record)
        legacy_report = review_workflow.make_failure_report(
            record, failure_stage="candidate_generation", error="legacy failure"
        )
        legacy_report["failure_stage"] = "claude_advice"
        legacy_report["options"]["alternatives"] = []
        write_json(self.folder / "repairs" / record["repair_id"] / "failure-report.json", legacy_report)

        revised = revise_advisor_failure_report(self.folder, record["repair_id"], "compatibility fix")
        self.assertEqual(revised["revision_history"][0]["kind"], "advisor_recovery_option_added")
        result = decide_escalation(
            self.folder,
            self.task,
            record["repair_id"],
            {"choice": ADVISOR_RECOVERY_STRATEGY_ID, "note": "retry read-only advice"},
        )
        self.assertEqual(result["created_attempt"]["previous_failure_report_id"], record["repair_id"])


if __name__ == "__main__":
    unittest.main()

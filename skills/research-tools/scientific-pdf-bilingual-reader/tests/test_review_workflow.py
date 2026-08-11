import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qa_contract import build_contract  # noqa: E402
from review_workflow import (  # noqa: E402
    accept_repair, build_review, create_diagnosis, update_decision, write_json,
)


class ReviewWorkflowTest(unittest.TestCase):
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
        for name in ("original.pdf", "translated-zh.pdf"):
            (self.folder / name).write_text(name)
        write_json(self.folder / "page-plan.json", {"pages": [{"pdf_page": 1, "type": "body"}]})
        report = {
            "status": "needs_review", "page_count": 1, "summary": {"red": 1, "orange": 0, "warning": 0, "pass": 0},
            "pages": [{"pdf_page": 1, "status": "critical", "metrics": {}, "issues": [
                {"issue_type": "rendered_structure_drift", "severity": "red", "evidence": "grid drift"},
                {"issue_type": "rendered_structure_drift", "severity": "red", "evidence": "grid drift"},
            ]}],
        }
        report["pages"][0]["status"] = "red"
        report["contract"] = build_contract(
            original_path=self.folder / "original.pdf",
            output_path=self.folder / "translated-zh.pdf",
            plan_path=self.folder / "page-plan.json",
            task=self.task,
        )
        write_json(self.folder / "qa-alpha.json", report)

    def tearDown(self):
        self.temp.cleanup()

    def test_review_deduplicates_and_persists_decision(self):
        review = build_review(self.folder, self.task)
        self.assertEqual(len(review["pages"][0]["issues"]), 1)
        issue_id = review["pages"][0]["issues"][0]["issue_id"]
        update_decision(self.folder, issue_id, "ignored")
        refreshed = build_review(self.folder, self.task)
        self.assertEqual(refreshed["pages"][0]["issues"][0]["review"]["decision"], "ignored")

    def test_diagnosis_record_is_isolated(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "错位")
        self.assertEqual(record["status"], "advising")
        self.assertTrue(record["repair_id"].startswith("attempt-"))
        self.assertTrue((self.folder / "repairs" / record["repair_id"] / "repair.json").is_file())

    def test_accept_backs_up_and_promotes_candidate(self):
        for name in ("translated-zh.pdf", "bilingual-side-by-side.pdf", "qa-alpha.json", "page-plan.json"):
            (self.folder / name).write_text("old")
        repair_id = "repair123"
        candidate = self.folder / "repairs" / repair_id / "candidate"
        candidate.mkdir(parents=True)
        for name in ("translated.pdf", "dual.pdf", "plan.json"):
            (candidate / name).write_text("new")
        write_json(candidate / "qa.json", {"status": "passed_with_warnings", "summary": {"warning": 1}, "flagged_pages": [1]})
        write_json(self.folder / "repairs" / repair_id / "repair.json", {
            "repair_id": repair_id, "pdf_page": 1, "status": "awaiting_acceptance",
            "qa_comparison": {"machine_gate": "pass"},
            "candidate": {
                "translated": f"repairs/{repair_id}/candidate/translated.pdf",
                "dual": f"repairs/{repair_id}/candidate/dual.pdf",
                "qa": f"repairs/{repair_id}/candidate/qa.json",
                "plan": f"repairs/{repair_id}/candidate/plan.json",
            },
        })
        result = accept_repair(self.folder, self.task, repair_id)
        self.assertEqual((self.folder / "translated-zh.pdf").read_text(), "new")
        self.assertEqual(result["status"], "completed_with_warnings")
        self.assertTrue((self.folder / "versions" / f"before-{repair_id}" / "translated-zh.pdf").is_file())


if __name__ == "__main__":
    unittest.main()

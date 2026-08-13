import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import fitz


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qa_contract import attention_summary, build_contract  # noqa: E402
from review_workflow import (  # noqa: E402
    accept_repair, build_review, create_diagnosis, create_human_review,
    diagnose_human_review, human_review_record_path, run_model, update_decision,
    write_json,
)


def write_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


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
            write_pdf(self.folder / name, name)
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

    def test_attention_summary_separates_actions_from_technical_tips(self):
        pages = [
            {"pdf_page": 4, "issues": [
                {"issue_type": "rendered_page_too_sparse", "severity": "red", "user_impact": "hard_blocker", "evidence": "sparse"},
                {"issue_type": "english_region_untranslated", "severity": "warning", "user_impact": "tip", "evidence": "SSP"},
                {"issue_type": "english_region_untranslated", "severity": "warning", "user_impact": "tip", "evidence": "SSP"},
            ]},
            {"pdf_page": 5, "issues": [
                {"issue_type": "english_region_untranslated", "severity": "warning", "user_impact": "tip", "evidence": "DRCS"},
            ]},
        ]
        attention = attention_summary(pages)
        self.assertEqual(attention["actionable_pages"], [4])
        self.assertEqual(attention["actionable_issue_count"], 1)
        self.assertEqual(attention["technical_tip_pages"], [4, 5])
        self.assertEqual(attention["technical_tip_issue_count"], 2)

    def test_review_attention_excludes_ignored_actionable_issue(self):
        review = build_review(self.folder, self.task)
        issue_id = review["pages"][0]["issues"][0]["issue_id"]
        update_decision(self.folder, issue_id, "ignored")
        refreshed = build_review(self.folder, self.task)
        self.assertEqual(refreshed["attention"]["actionable_page_count"], 0)
        self.assertEqual(refreshed["attention"]["ignored_actionable_issue_count"], 1)

    def test_review_projection_adds_page_route_without_mutating_qa_issues(self):
        write_json(self.folder / "document-plan.json", {"pages": [{"page": 1, "route": "ocr"}]})
        original_report = json.loads((self.folder / "qa-alpha.json").read_text())
        review = build_review(self.folder, self.task)
        self.assertEqual(review["pages"][0]["route"], "ocr")
        self.assertEqual(json.loads((self.folder / "qa-alpha.json").read_text())["pages"], original_report["pages"])

    def test_review_keeps_pages_without_machine_issues_for_human_navigation(self):
        report = json.loads((self.folder / "qa-alpha.json").read_text())
        report["page_count"] = 2
        report["pages"].append({"pdf_page": 2, "status": "pass", "metrics": {}, "issues": []})
        write_json(self.folder / "qa-alpha.json", report)
        review = build_review(self.folder, self.task)
        self.assertEqual([page["pdf_page"] for page in review["pages"]], [1, 2])
        self.assertEqual(review["pages"][1]["issues"], [])

    def test_human_review_is_separate_from_repair_attempts_and_persists_analysis(self):
        record = create_human_review(self.folder, self.task, 1, "表头层级不清，但不要改数字")
        self.assertEqual(record["status"], "advising")
        self.assertTrue(human_review_record_path(self.folder, record["review_id"]).is_file())
        self.assertFalse((self.folder / "repairs" / record["review_id"]).exists())
        source = self.folder / "source.png"
        translated = self.folder / "translated.png"
        source.write_bytes(b"png")
        translated.write_bytes(b"png")
        diagnosis = {
            "is_real_problem": True, "explanation": "层级需要优化",
            "recommended_action": "仅调整表头", "repair_family": "table_layout",
            "risk": "low", "cost_level": "low",
        }
        with (
            mock.patch("review_workflow.ensure_repair_model_health"),
            mock.patch("review_workflow.render_page_images", return_value=(source, translated)),
            mock.patch("review_workflow.run_model", return_value=diagnosis),
        ):
            diagnose_human_review(self.folder, self.task, record["review_id"])
        saved = json.loads(human_review_record_path(self.folder, record["review_id"]).read_text())
        self.assertEqual(saved["status"], "diagnosed")
        self.assertEqual(saved["diagnosis"]["recommended_action"], "仅调整表头")
        review = build_review(self.folder, self.task)
        self.assertEqual(review["human_reviews"][0]["feedback"], "表头层级不清，但不要改数字")
        self.assertEqual(review["pages"][0]["human_review_count"], 1)

    def test_repair_diagnosis_inherits_matching_human_review_context(self):
        human = create_human_review(self.folder, self.task, 1, "下一轮只优化表头，不改数字")
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "")
        self.assertEqual(record["human_review_refs"], [human["review_id"]])
        self.assertEqual(record["human_review_context"][0]["feedback"], "下一轮只优化表头，不改数字")

    def test_diagnosis_record_is_isolated(self):
        issue_id = build_review(self.folder, self.task)["pages"][0]["issues"][0]["issue_id"]
        record = create_diagnosis(self.folder, self.task, 1, [issue_id], "claude", "错位")
        self.assertEqual(record["status"], "advising")
        self.assertTrue(record["repair_id"].startswith("attempt-"))
        self.assertTrue((self.folder / "repairs" / record["repair_id"] / "repair.json").is_file())

    def test_accept_backs_up_and_promotes_candidate(self):
        for name in ("translated-zh.pdf", "bilingual-side-by-side.pdf", "qa-alpha.json", "page-plan.json"):
            if name.endswith(".pdf"):
                write_pdf(self.folder / name, f"old:{name}")
            else:
                (self.folder / name).write_text("old")
        repair_id = "repair123"
        candidate = self.folder / "repairs" / repair_id / "candidate"
        candidate.mkdir(parents=True)
        for name in ("translated.pdf", "dual.pdf", "plan.json"):
            if name.endswith(".pdf"):
                write_pdf(candidate / name, f"new:{name}")
            else:
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
        self.assertTrue((self.folder / "page-manifest.json").is_file())
        self.assertEqual(result["status"], "completed_with_warnings")
        self.assertTrue((self.folder / "versions" / f"before-{repair_id}" / "translated-zh.pdf").is_file())

    def test_accept_backs_up_versioned_current_task_references(self):
        self.task.update(
            translated_file="translated-zh-v8.pdf",
            dual_file="bilingual-v8.pdf",
            qa_alpha_file="qa-v8.json",
            page_plan_file="page-plan-v8.json",
        )
        for name in ("translated-zh-v8.pdf", "bilingual-v8.pdf", "qa-v8.json", "page-plan-v8.json"):
            if name.endswith(".pdf"):
                write_pdf(self.folder / name, f"old:{name}")
            else:
                (self.folder / name).write_text(f"old:{name}")
        repair_id = "repair-versioned"
        candidate = self.folder / "repairs" / repair_id / "candidate"
        candidate.mkdir(parents=True)
        for name in ("translated.pdf", "dual.pdf", "plan.json"):
            if name.endswith(".pdf"):
                write_pdf(candidate / name, f"new:{name}")
            else:
                (candidate / name).write_text(f"new:{name}")
        write_json(candidate / "qa.json", {"status": "passed", "summary": {}, "flagged_pages": []})
        write_json(self.folder / "repairs" / repair_id / "repair.json", {
            "repair_id": repair_id,
            "pdf_page": 1,
            "status": "awaiting_acceptance",
            "qa_comparison": {"machine_gate": "pass"},
            "candidate": {
                "translated": f"repairs/{repair_id}/candidate/translated.pdf",
                "dual": f"repairs/{repair_id}/candidate/dual.pdf",
                "qa": f"repairs/{repair_id}/candidate/qa.json",
                "plan": f"repairs/{repair_id}/candidate/plan.json",
            },
        })
        accept_repair(self.folder, self.task, repair_id)
        backup = self.folder / "versions" / f"before-{repair_id}"
        for name in ("translated-zh-v8.pdf", "bilingual-v8.pdf", "qa-v8.json", "page-plan-v8.json"):
            self.assertTrue((backup / name).is_file())
        receipt = json.loads((backup / "acceptance-receipt.json").read_text())
        self.assertEqual(receipt["pre_accept_files"]["translated-zh.pdf"], "translated-zh-v8.pdf")

    def test_claude_cli_schema_copy_omits_unsupported_meta_schema(self):
        schema = self.folder / "schema.json"
        write_json(schema, {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"execution_family": {"const": "layout"}},
        })
        completed = mock.Mock(returncode=0, stdout=json.dumps({
            "structured_output": {"execution_family": "layout"}
        }), stderr="")
        (self.folder / "source.png").write_bytes(b"source-image")
        (self.folder / "translated.png").write_bytes(b"translated-image")
        with mock.patch("review_workflow.subprocess.run", return_value=completed) as run:
            result = run_model(
                "claude", "prompt", self.folder / "source.png", self.folder / "translated.png",
                self.folder / "output.json", schema,
            )
        command = run.call_args.args[0]
        cli_schema = json.loads(command[command.index("--json-schema") + 1])
        self.assertNotIn("$schema", cli_schema)
        self.assertEqual(cli_schema["type"], "object")
        self.assertEqual(command[command.index("--tools") + 1], "Read")
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("source-page.png", command[-1])
        self.assertNotIn(str(self.folder), command[-1])
        self.assertTrue(Path(run.call_args.kwargs["cwd"]).name.startswith("pdf-reader-claude-review-"))
        self.assertEqual(result["execution_family"], "layout")


if __name__ == "__main__":
    unittest.main()

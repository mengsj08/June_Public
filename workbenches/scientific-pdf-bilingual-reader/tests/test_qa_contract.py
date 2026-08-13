import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_REGRESSION = Path(os.environ.get(
    "PDF_READER_PRIVATE_REGRESSION_DIR", ROOT / "references" / "regression",
)).expanduser()
sys.path.insert(0, str(ROOT / "scripts"))

from qa_contract import (  # noqa: E402
    build_contract, classify_issue, new_deterministic_visual_violations,
    score_precision_recall, verify_contract,
)
from qa_alpha import audit  # noqa: E402


class QaContractTest(unittest.TestCase):
    def test_severity_mapping_splits_red_orange_and_warning(self):
        red = classify_issue({"issue_type": "rotation_metadata_mismatch", "severity": "critical"})
        self.assertEqual(red["severity"], "red")
        self.assertEqual(red["issue_category"], "translation_failed")

        orange = classify_issue(
            {"issue_type": "page_translation_coverage_low", "severity": "critical"},
            {"policy": "protect_table_translate_caption"},
        )
        self.assertEqual(orange["severity"], "orange")
        self.assertEqual(orange["issue_category"], "protected_by_policy")

        warning = classify_issue({"issue_type": "prominent_english_untranslated", "severity": "critical"})
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["issue_category"], "qa_suspect")

    def test_hash_contract_detects_fresh_and_stale_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.pdf"
            output = root / "translated.pdf"
            plan = root / "page-plan.json"
            original.write_bytes(b"%PDF- original")
            output.write_bytes(b"%PDF- translated")
            plan.write_text('{"pages":[]}')
            task = {"id": "sample", "original_file": "original.pdf", "translated_file": "translated.pdf", "page_plan_file": "page-plan.json"}
            report = {"contract": build_contract(original_path=original, output_path=output, plan_path=plan, task=task)}
            self.assertEqual(
                verify_contract(report, original_path=original, output_path=output, plan_path=plan, task=task)["status"],
                "fresh",
            )
            output.write_bytes(b"%PDF- changed")
            stale = verify_contract(report, original_path=original, output_path=output, plan_path=plan, task=task)
            self.assertEqual(stale["status"], "stale")
            self.assertIn("translated_pdf:sha256_mismatch", stale["mismatches"])

    def test_draft_labels_cannot_issue_quality_gate_pass(self):
        report = {"pages": [{"pdf_page": 1, "status": "red"}]}
        fixture = [{
            "pdf_page": 1,
            "labels": {"status": "codex-draft"},
            "expected_result": {"expected_severity": "red"},
        }]
        score = score_precision_recall(report, fixture)
        self.assertEqual(score["status"], "blocked")
        self.assertIn("不可签发 PASS", score["message"])

    def test_confirmed_labels_compute_precision_and_recall(self):
        report = {"pages": [{"pdf_page": 1, "status": "red"}, {"pdf_page": 2, "status": "warning"}]}
        fixture = [
            {"pdf_page": 1, "labels": {"status": "june-confirmed"}, "expected_result": {"expected_severity": "red"}},
            {"pdf_page": 2, "labels": {"status": "june-confirmed"}, "expected_result": {"expected_severity": "warning"}},
        ]
        score = score_precision_recall(report, fixture)
        self.assertEqual(score["status"], "pass")
        self.assertEqual(score["hard_blocker_recall"], 1.0)
        self.assertEqual(score["red_precision"], 1.0)

    def test_precision_recall_uses_document_identity_not_bare_page_number(self):
        report = {"pages": [
            {"task_id": "doc-red", "fixture_page_id": "doc-red-p6", "pdf_page": 6, "status": "red"},
            {"task_id": "doc-pass", "fixture_page_id": "doc-pass-p6", "pdf_page": 6, "status": "pass"},
        ]}
        fixture = [
            {
                "fixture_page_id": "doc-red-p6",
                "task_pointer": {"task_id": "doc-red"},
                "pdf_page": 6,
                "labels": {"status": "june-confirmed"},
                "expected_result": {"expected_severity": "red"},
            },
            {
                "fixture_page_id": "doc-pass-p6",
                "task_pointer": {"task_id": "doc-pass"},
                "pdf_page": 6,
                "labels": {"status": "june-confirmed"},
                "expected_result": {"expected_severity": "pass"},
            },
        ]
        score = score_precision_recall(report, fixture)
        self.assertEqual(score["status"], "pass")
        self.assertEqual(score["known_hard_blocker_pages"], ["doc-red-p6"])
        self.assertEqual(score["actual_red_pages"], ["doc-red-p6"])
        self.assertEqual(score["missed_red_pages"], [])

    def test_skl_209_real_regression_detects_visual_damage_without_incremental_false_positive(self):
        root = PRIVATE_REGRESSION / "skl-209-516bd41c7ce9"
        if not root.is_dir():
            self.skipTest("SKL-209 private regression samples not present")
        before = audit(root / "page-001-original.pdf", root / "page-001-before-repair-translated.pdf")
        current = audit(root / "page-001-original.pdf", root / "page-001-current-translated.pdf")
        current_types = {issue["issue_type"] for page in current["pages"] for issue in page["issues"]}
        self.assertIn("rendered_text_overlap", current_types)
        self.assertIn("rendered_text_clipped", current_types)
        self.assertEqual(new_deterministic_visual_violations(before, current, 1), [])

        before_page8 = audit(root / "page-008-original.pdf", root / "page-008-before-repair-translated.pdf")
        current_page8 = audit(root / "page-008-original.pdf", root / "page-008-current-translated.pdf")
        self.assertEqual(new_deterministic_visual_violations(before_page8, current_page8, 1), [])

    def test_new_deterministic_visual_issue_type_is_incremental(self):
        before = {"pages": [{"pdf_page": 1, "issues": []}]}
        after = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "red", "evidence": "overlap", "region": [10, 10, 30, 30]},
        ]}]}
        self.assertEqual(
            new_deterministic_visual_violations(before, after, 1)[0]["issue_type"],
            "rendered_text_overlap",
        )
        existing = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "red", "evidence": "old overlap", "region": [10, 10, 30, 30]},
        ]}]}
        same_region = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "red", "evidence": "same overlap", "region": [11, 9, 30, 31]},
        ]}]}
        self.assertEqual(new_deterministic_visual_violations(existing, same_region, 1), [])

    def test_existing_same_type_plus_new_region_is_incremental(self):
        before = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "old", "region": [10, 10, 30, 30]},
        ]}]}
        after = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "old", "region": [10, 10, 30, 30]},
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "new", "region": [80, 80, 120, 120]},
        ]}]}
        violations = new_deterministic_visual_violations(before, after, 1)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["region"], [80, 80, 120, 120])

    def test_same_signature_count_increase_is_incremental(self):
        before = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "old", "region": [10, 10, 30, 30]},
        ]}]}
        after = {"pages": [{"pdf_page": 1, "issues": [
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "old", "region": [10, 10, 30, 30]},
            {"issue_type": "rendered_text_overlap", "severity": "orange", "evidence": "duplicate new", "region": [11, 10, 31, 29]},
        ]}]}
        self.assertEqual(len(new_deterministic_visual_violations(before, after, 1)), 1)


class RegressionManifestTest(unittest.TestCase):
    def test_short_sprint_manifest_is_desensitized_and_draft_only(self):
        manifest_path = PRIVATE_REGRESSION / "fixture-manifest.json"
        if not manifest_path.is_file():
            # 私有回归 fixture 清单不随公开分发包发布；缺失时跳过而非失败。
            self.skipTest("private regression fixture manifest not present in this distribution")
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["schema_version"], "pdf-reader-private-fixture-manifest/v1")
        self.assertEqual(len(manifest["pages"]), 60)
        self.assertTrue({page["labels"]["status"] for page in manifest["pages"]} <= {"codex-draft", "june-confirmed"})
        forbidden = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("ocr-results.json", forbidden)
        self.assertNotIn("source.png", forbidden)
        self.assertNotIn("translated.png", forbidden)


if __name__ == "__main__":
    unittest.main()

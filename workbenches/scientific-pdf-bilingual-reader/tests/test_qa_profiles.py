import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from qa_alpha import model_meta_response_leak, page_issues
from qa_contract import classify_issue


def page_with_text(text: str) -> tuple[fitz.Document, fitz.Page]:
    document = fitz.open()
    page = document.new_page(width=420, height=595)
    page.insert_textbox(fitz.Rect(40, 40, 380, 550), text, fontsize=11)
    return document, page


class QaProfileTest(unittest.TestCase):
    def test_ocr_route_skips_render_comparisons(self):
        source_doc, source = page_with_text("English source paragraph. " * 20)
        output_doc, output = page_with_text("中文译文。" * 20)
        with patch("qa_alpha.render_gray", side_effect=AssertionError("render should be skipped")):
            issues, metrics = page_issues(source, output, None, route="ocr")
        self.assertIsNone(metrics["source_ink_ratio"])
        self.assertFalse(any(item["issue_type"].startswith("rendered_") for item in issues))
        source_doc.close(); output_doc.close()

    def test_clean_ocr_route_uses_text_geometry_metrics_without_render_similarity(self):
        source_doc, source = page_with_text("English source paragraph. " * 20)
        output_doc, output = page_with_text("中文译文。" * 20)
        with patch("qa_alpha.render_gray", side_effect=AssertionError("render should be skipped")):
            issues, metrics = page_issues(source, output, {"render_mode": "clean"}, route="ocr")
        self.assertIn("clean_text_coverage_ratio", metrics)
        self.assertTrue(metrics["clean_text_bbox_valid"])
        self.assertIsNone(metrics["structure_iou"])
        self.assertFalse(any(item["issue_type"] == "clean_text_geometry_invalid" for item in issues))
        source_doc.close(); output_doc.close()

    def test_ocr_route_without_render_mode_fails_closed(self):
        source_doc, source = page_with_text("English source paragraph. " * 20)
        output_doc, output = page_with_text("中文译文。" * 20)
        issues, _ = page_issues(source, output, None, route="ocr")
        missing = next(item for item in issues if item["issue_type"] == "scan_render_mode_missing")
        self.assertEqual(missing["severity"], "critical")
        source_doc.close(); output_doc.close()

    def test_refusal_fallback_coverage_is_warning_with_reason(self):
        source_doc, source = page_with_text("English source paragraph that remains untranslated. " * 8)
        output_doc, output = page_with_text("English source paragraph that remains untranslated. " * 8)
        issues, _ = page_issues(source, output, None, route="ocr", refusal_fallback=True)
        coverage = next(item for item in issues if item["issue_type"] == "page_translation_coverage_low")
        classified = classify_issue(coverage)
        self.assertEqual(classified["severity"], "warning")
        self.assertIn("按设计保留原文", coverage["evidence"])
        source_doc.close(); output_doc.close()

    def test_meta_response_in_chinese_output_is_red(self):
        match = model_meta_response_leak("I translate the source text as requested. 这是中文译文内容。" * 4)
        self.assertIsNotNone(match)
        leaked = {"issue_type": "model_meta_response_leak", "severity": "critical", "evidence": match.group(0)}
        self.assertEqual(classify_issue(leaked)["severity"], "red")

    def test_pure_english_fallback_does_not_trigger_meta_leak(self):
        self.assertIsNone(model_meta_response_leak("I can't translate this source text."))
        source_doc, source = page_with_text("English source paragraph. " * 12)
        output_doc, output = page_with_text("I can't translate this source text.")
        issues, _ = page_issues(source, output, None, route="ocr", refusal_fallback=True)
        self.assertNotIn("model_meta_response_leak", {item["issue_type"] for item in issues})
        source_doc.close(); output_doc.close()


if __name__ == "__main__":
    unittest.main()

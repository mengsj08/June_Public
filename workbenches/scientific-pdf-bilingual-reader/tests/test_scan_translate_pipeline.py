import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fitz
except ImportError:
    fitz = None

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PRIVATE_REGRESSION = Path(os.environ.get(
    "PDF_READER_PRIVATE_REGRESSION_DIR",
    Path(__file__).resolve().parents[1] / "references" / "regression",
)).expanduser()
HOWTOREAD = PRIVATE_REGRESSION / "skl-212-howtoread"
FIXTURE = HOWTOREAD / "ocr-results.json"
DESKEW_IMAGES = HOWTOREAD / "deskew-images"
sys.path.insert(0, str(SCRIPTS))

from scan_translate_pipeline import (  # noqa: E402
    ScanTranslationError, aggregate_paragraphs, build_scan_translation_pdf,
    classify_scan_page_render_mode,
    deskew_record_image, detect_layout_blocks, deterministic_layout_blocks,
    estimate_page_angle, geometry_audit, line_pdf_rect, scan_page_plan,
    render_scan_page, validate_blocks,
)


class FakeBroker:
    def __init__(self):
        self.metrics = {"requests": 0, "ai_seconds": 0.0, "cache_hits": 0, "glossary_hits": 0, "unique_ai_items": 0, "unresolved": [], "errors": []}

    def translate(self, texts, instruction):
        self.metrics["requests"] += 1
        self.metrics["unique_ai_items"] += len(texts)
        return [f"译文：{text[:28]}" for text in texts]


class ScanTranslatePipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIXTURE.is_file():
            raise unittest.SkipTest("private scan regression fixtures not configured")
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def page_record(self, page: int = 1) -> dict:
        record = dict(next(item for item in self.fixture["pages"] if int(item["page"]) == page))
        image = DESKEW_IMAGES / f"page-{page:04d}-deskew.png"
        self.assertTrue(image.is_file(), f"missing required fixture image: {image}")
        record["image_file"] = str(image)
        return record

    def test_polygon_geometry_removes_bbox_height_inflation_and_left_edge_collapse(self):
        page1 = self.page_record(1)
        report = geometry_audit(page1)
        self.assertGreater(report["median_height_before_px"], report["median_height_after_px"] * 1.35)
        self.assertEqual(report["x0_collapse_after"], 0)

    def test_deskew_rotates_image_and_polygon_coordinates_together(self):
        page1 = self.page_record(1)
        with tempfile.TemporaryDirectory() as temp:
            adjusted = deskew_record_image(page1, Path(temp))
            self.assertTrue(Path(adjusted["image_file"]).is_file())
            self.assertLess(abs(estimate_page_angle(adjusted)), abs(estimate_page_angle(page1)))
            self.assertTrue(adjusted["deskew"]["applied"])

    @unittest.skipIf(fitz is None, "PyMuPDF required")
    def test_searchable_text_rect_uses_polygon_height_not_axis_aligned_box(self):
        page1 = self.page_record(1)
        line = page1["lines"][0]
        rect = line_pdf_rect(page1, line)
        raw_height_pdf = (line["box_px"][3] - line["box_px"][1]) * page1["pdf_height"] / page1["image_height"]
        self.assertLess(rect.height, raw_height_pdf * 0.75)

    def test_deterministic_layout_separates_howtoread_double_columns(self):
        page1 = self.page_record(1)
        layout = detect_layout_blocks(page1, prefer_model=False)
        self.assertTrue(layout["validation"]["ok"], layout["validation"])
        paragraphs = [block for block in layout["blocks"] if block["kind"] == "paragraph"]
        self.assertGreaterEqual(len(paragraphs), 2)
        left = [block for block in paragraphs if block["bbox_px"][2] < page1["image_width"] * 0.50]
        right = [block for block in paragraphs if block["bbox_px"][0] > page1["image_width"] * 0.50]
        self.assertTrue(left)
        self.assertTrue(right)

    def test_howtoread_page2_fallback_splits_columns_and_rejects_giant_title_blocks(self):
        page2 = self.page_record(2)
        layout = detect_layout_blocks(page2, prefer_model=False)
        self.assertTrue(layout["validation"]["ok"], layout["validation"])
        self.assertEqual(layout["source"], "deterministic_columns")
        paragraph_blocks = [block for block in layout["blocks"] if block["kind"] == "paragraph"]
        title_blocks = [block for block in layout["blocks"] if block["kind"] == "title"]
        self.assertGreaterEqual(len(paragraph_blocks), 8)
        self.assertLessEqual(max(block["line_count"] for block in paragraph_blocks), 18)
        for block in title_blocks:
            width_ratio = (block["bbox_px"][2] - block["bbox_px"][0]) / page2["image_width"]
            self.assertLess(block["line_count"], 8)
            self.assertLess(width_ratio, 0.82)

    def test_model_attempt_metadata_survives_deterministic_fallback(self):
        page2 = self.page_record(2)
        meta = {
            "model_attempted": True,
            "model_backend": "cpu",
            "model_provider": "pdf2zh.doclayout",
            "model_elapsed_seconds": 0.123,
            "model_block_count": 0,
            "model_error": "RuntimeError: unavailable",
        }
        with mock.patch("scan_translate_pipeline.doclayout_blocks", return_value=([], meta)):
            layout = detect_layout_blocks(page2, prefer_model=True)
        self.assertEqual(layout["source"], "deterministic_columns")
        self.assertTrue(layout["fallback_used"])
        self.assertEqual(layout["fallback_reason"], "model_unavailable_or_empty")
        self.assertTrue(layout["model_attempted"])
        self.assertIn("unavailable", layout["model_error"])
        self.assertTrue(layout["validation"]["ok"])

    def test_valid_doclayout_path_carries_model_status_and_passes_page2_geometry(self):
        page2 = self.page_record(2)
        blocks = deterministic_layout_blocks(page2)
        meta = {
            "model_attempted": True,
            "model_backend": "cpu",
            "model_provider": "pdf2zh.doclayout",
            "model_elapsed_seconds": 0.456,
            "model_block_count": len(blocks),
            "model_error": None,
        }
        with mock.patch("scan_translate_pipeline.doclayout_blocks", return_value=(blocks, meta)):
            layout = detect_layout_blocks(page2, prefer_model=True)
        self.assertEqual(layout["source"], "doclayout_onnx_cpu")
        self.assertFalse(layout["fallback_used"])
        self.assertTrue(layout["validation"]["ok"])
        self.assertEqual(layout["model_block_count"], len(blocks))

    def test_paragraph_aggregation_dehyphenates_and_preserves_block_order(self):
        page2 = self.page_record(2)
        layout = detect_layout_blocks(page2, prefer_model=False)
        paragraphs = aggregate_paragraphs(page2, layout["blocks"])
        text = "\n".join(item["text"] for item in paragraphs)
        self.assertIn("top conferences", text)
        self.assertIn("conferences", text)
        self.assertNotIn("con- ferences", text)
        self.assertGreater(len(paragraphs), 4)

    def test_block_validation_fails_closed_on_overlap(self):
        record = self.page_record(1)
        bad = [
            {"block_id": "a", "kind": "paragraph", "bbox_px": [100, 100, 900, 900]},
            {"block_id": "b", "kind": "paragraph", "bbox_px": [120, 120, 920, 920]},
        ]
        validation = validate_blocks(record, bad)
        self.assertFalse(validation["ok"])
        self.assertIn("block_overlap", {item["code"] for item in validation["errors"]})

    @unittest.skipIf(fitz is None, "PyMuPDF required")
    def test_scan_failure_report_lists_prior_pages_and_validation_numbers(self):
        page1 = self.page_record(1)
        page2 = self.page_record(2)
        if not Path(page1["image_file"]).is_file():
            self.skipTest("fixture image is outside this checkout")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            doc = fitz.open()
            for record in (page1, page2):
                doc.new_page(width=record["pdf_width"], height=record["pdf_height"])
            doc.save(source)
            doc.close()
            ok_layout = detect_layout_blocks(page1, prefer_model=False)
            bad_blocks = [{
                "block_id": "title-bad",
                "kind": "title",
                "order": 0,
                "bbox_px": [5.5, 63.0, 3083.7, 702.0],
                "line_count": 20,
                "line_indices": list(range(20)),
            }]
            bad_layout = {
                "page": 2,
                "source": "deterministic_columns",
                "blocks": bad_blocks,
                "validation": validate_blocks(page2, bad_blocks),
                "fallback_used": True,
                "fallback_reason": "model_validation_failed",
                "model_attempted": True,
                "model_error": None,
                "model_elapsed_seconds": 0.2,
                "model_block_count": 1,
            }
            output = root / "translated.pdf"
            with mock.patch("scan_translate_pipeline.detect_layout_blocks", side_effect=[ok_layout, bad_layout]):
                with self.assertRaises(ScanTranslationError) as raised:
                    build_scan_translation_pdf(
                        source,
                        {"pages": [{"page": 1, "route": "ocr"}, {"page": 2, "route": "ocr"}]},
                        {"pages": [page1, page2]},
                        output,
                        FakeBroker(),
                        prefer_model=False,
                    )
            self.assertIn("报告：", str(raised.exception))
            report_path = root / "scan-translation-failure.json"
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["reason"], "layout_validation_failed")
            self.assertEqual([page["status"] for page in report["pages"]], ["translated", "layout_failed"])
            errors = report["pages"][1]["layout"]["validation"]["errors"]
            self.assertIn("title_block_too_large", {item["code"] for item in errors})
            self.assertIn("width_ratio", errors[0] if errors[0]["code"] == "title_block_too_large" else errors[-1])

    def test_scan_page_plan_marks_ocr_pages_without_touching_text_route(self):
        plan = {"pages": [{"page": 1, "route": "ocr"}, {"page": 2, "route": "text"}]}
        report = {"pages": [{
            "page": 1,
            "render_mode": "clean",
            "render_reason": "text_only",
            "paragraph_count": 3,
            "render": {"mode": "clean", "placed": 2, "fallbacks": ["p1"]},
        }]}
        routed = scan_page_plan(plan, report)
        self.assertEqual([item["type"] for item in routed["pages"]], ["scan_ocr", "narrative"])
        self.assertEqual(routed["pages"][0]["policy"], "scan_page_dual_mode")
        self.assertEqual(routed["pages"][0]["render_mode"], "clean")
        self.assertEqual(routed["pages"][0]["fallbacks"], ["p1"])

    @unittest.skipIf(fitz is None, "PyMuPDF required")
    def test_overlay_fit_failure_keeps_source_image_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "source.png"
            self.write_synthetic_image(image, figure=True)
            paragraphs = [{
                "paragraph_id": "too-small",
                "kind": "paragraph",
                "bbox_px": [40, 55, 45, 60],
                "text": "source remains",
            }]
            document = fitz.open()
            page = document.new_page(width=200, height=260)
            result = render_scan_page(
                page, self.synthetic_record(image), paragraphs,
                {"too-small": "非常长的译文" * 30},
                {"blocks": [{"kind": "figure"}]},
            )
            self.assertEqual(result["mode"], "overlay")
            self.assertEqual(result["fallbacks"], ["too-small"])
            self.assertTrue(page.get_images(full=True))
            document.close()

    def synthetic_record(self, image: Path, *, lines: list[dict] | None = None) -> dict:
        return {
            "page": 1,
            "image_file": str(image),
            "image_width": 400,
            "image_height": 520,
            "pdf_width": 200,
            "pdf_height": 260,
            "lines": lines or [
                {"text": "A text line", "score": 0.99, "box_px": [40, 60, 310, 86]},
                {"text": "Another text line", "score": 0.99, "box_px": [40, 100, 330, 126]},
            ],
        }

    def write_synthetic_image(self, path: Path, *, figure: bool = False, highlight: bool = False) -> None:
        import cv2
        import numpy as np
        image = np.full((520, 400, 3), 255, dtype=np.uint8)
        for y in (70, 110):
            if highlight:
                cv2.rectangle(image, (35, y - 16), (340, y + 16), (0, 255, 255), -1)
            cv2.line(image, (42, y), (320, y), (0, 0, 0), 3)
        if figure:
            cv2.rectangle(image, (70, 210), (330, 390), (0, 0, 0), 4)
            cv2.line(image, (85, 350), (315, 240), (0, 0, 0), 5)
            cv2.line(image, (85, 350), (315, 350), (0, 0, 0), 3)
        cv2.imwrite(str(path), image)

    def test_classifier_ink_floor_recovers_when_layout_model_misses_figure(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "figure.png"
            self.write_synthetic_image(image, figure=True)
            record = self.synthetic_record(image)
            layout = {"blocks": [{"block_id": "p0", "kind": "paragraph", "bbox_px": [40, 55, 340, 130]}]}
            decision = classify_scan_page_render_mode(record, layout)
            self.assertEqual(decision["mode"], "overlay")
            self.assertEqual(decision["reason"], "non_text_ink_floor")

    def test_classifier_keeps_text_highlight_page_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "highlight.png"
            self.write_synthetic_image(image, highlight=True)
            record = self.synthetic_record(image)
            layout = {"blocks": [{"block_id": "p0", "kind": "paragraph", "bbox_px": [40, 55, 340, 130]}]}
            decision = classify_scan_page_render_mode(record, layout)
            self.assertEqual(decision["mode"], "clean")
            self.assertEqual(decision["reason"], "text_blocks_only_and_no_non_text_ink")

    def test_howtoread_real_deskew_pages_are_clean_with_diagnostic_floor(self):
        for page_number in (1, 2):
            record = self.page_record(page_number)
            layout = detect_layout_blocks(record, prefer_model=False)
            decision = classify_scan_page_render_mode(record, layout)
            self.assertEqual(decision["mode"], "clean", f"page {page_number}: {decision}")
            self.assertEqual(decision["reason"], "text_blocks_only_and_no_non_text_ink")
            self.assertIn("ignored_line_like_component_count", decision)

    @unittest.skipIf(fitz is None, "PyMuPDF required")
    def test_render_dual_mode_clean_has_white_page_without_base_image_and_overlay_preserves_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clean_image = root / "highlight.png"
            figure_image = root / "figure.png"
            self.write_synthetic_image(clean_image, highlight=True)
            self.write_synthetic_image(figure_image, figure=True)
            paragraphs = [{"paragraph_id": "p1", "kind": "paragraph", "bbox_px": [40, 55, 340, 130], "text": "source"}]
            translations = {"p1": "译文测试"}

            doc = fitz.open()
            clean_page = doc.new_page(width=200, height=260)
            clean = render_scan_page(clean_page, self.synthetic_record(clean_image), paragraphs, translations, {"blocks": []})
            self.assertEqual(clean["mode"], "clean")
            self.assertFalse(clean_page.get_images(full=True))
            overlay_page = doc.new_page(width=200, height=260)
            overlay = render_scan_page(overlay_page, self.synthetic_record(figure_image), paragraphs, translations, {"blocks": []})
            self.assertEqual(overlay["mode"], "overlay")
            self.assertTrue(overlay_page.get_images(full=True))
            doc.close()

    @unittest.skipIf(fitz is None, "PyMuPDF required")
    def test_block_level_render_uses_clean_mode_for_howtoread_text_page(self):
        page1 = self.page_record(1)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pdf"
            doc = fitz.open()
            doc.new_page(width=page1["pdf_width"], height=page1["pdf_height"])
            doc.save(source)
            doc.close()
            output = root / "translated.pdf"
            report = build_scan_translation_pdf(
                source,
                {"pages": [{"page": 1, "route": "ocr"}]},
                {"pages": [page1]},
                output,
                FakeBroker(),
                prefer_model=False,
            )
            translated = fitz.open(output)
            self.assertFalse(translated[0].get_images(full=True))
            self.assertEqual(report["pages"][0]["render"]["mode"], "clean")
            self.assertGreater(report["paragraph_count"], 0)
            translated.close()


if __name__ == "__main__":
    unittest.main()

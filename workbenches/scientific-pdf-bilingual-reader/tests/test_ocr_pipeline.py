import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import fitz
except ImportError:  # The canonical test command also runs under the managed 3.12 runtime.
    fitz = None

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

if fitz is not None:
    from ocr_pipeline import analyze_document, build_searchable_pdf, build_translation_source, parse_page_selection, run_worker


@unittest.skipIf(fitz is None, "PyMuPDF lives in the managed workbench runtime")
class OcrPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "mixed.pdf"

        raster_source = fitz.open()
        raster_page = raster_source.new_page(width=420, height=595)
        raster_page.insert_text((42, 80), "SCAN ONLY PAGE SAMPLE", fontsize=24)
        pixmap = raster_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        self.scan_image = self.root / "scan.png"
        pixmap.save(self.scan_image)
        raster_source.close()

        document = fitz.open()
        text_page = document.new_page(width=420, height=595)
        text_page.insert_textbox(
            fitz.Rect(40, 50, 380, 300),
            "This is a reliable native text layer. " * 12,
            fontsize=11,
        )
        text_page.insert_image(fitz.Rect(280, 430, 400, 550), filename=str(self.scan_image))
        image_page = document.new_page(width=420, height=595)
        image_page.insert_image(image_page.rect, filename=str(self.scan_image))
        document.new_page(width=420, height=595)
        document.save(self.source)
        document.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_page_level_route_is_deterministic(self):
        plan = analyze_document(self.source)
        self.assertEqual([page["route"] for page in plan["pages"]], ["text", "ocr", "blank"])
        self.assertEqual(plan["routes"], {"text": 1, "ocr": 1, "blank": 1})
        self.assertEqual(plan["ocr_pages"], [2])

    def test_manual_page_override(self):
        plan = analyze_document(self.source, [1])
        self.assertEqual(plan["ocr_pages"], [1, 2])
        self.assertTrue(plan["pages"][0]["manual"])
        with self.assertRaises(ValueError):
            analyze_document(self.source, [4])

    def test_manual_embedded_image_keeps_text_page_route(self):
        plan = analyze_document(self.source, forced_images=[{"page": 1, "image": 1}])
        self.assertEqual(plan["pages"][0]["route"], "text")
        self.assertTrue(plan["ocr_required"])
        self.assertEqual([(item["page"], item["image"]) for item in plan["ocr_images"]], [(1, 1)])
        with self.assertRaises(ValueError):
            analyze_document(self.source, forced_images=[{"page": 1, "image": 99}])

    def test_searchable_pdf_preserves_order_and_adds_ocr_text(self):
        plan = analyze_document(self.source)
        record = {
            "page": 2,
            "image_file": str(self.scan_image),
            "image_width": 840,
            "image_height": 1190,
            "lines": [{"text": "SCAN ONLY PAGE SAMPLE", "score": 0.99, "box_px": [84, 80, 720, 160]}],
        }
        destination = self.root / "searchable.pdf"
        warnings = build_searchable_pdf(self.source, plan, {"pages": [record]}, destination)
        self.assertTrue(destination.is_file())
        result = fitz.open(destination)
        self.assertEqual(result.page_count, 3)
        self.assertIn("reliable native text layer", result[0].get_text("text"))
        self.assertIn("SCAN ONLY PAGE SAMPLE", result[1].get_text("text"))
        self.assertEqual(result[2].get_text("text").strip(), "")
        result.close()
        self.assertIsInstance(warnings, list)

    def test_embedded_image_text_is_overlaid_only_in_image_rect(self):
        plan = analyze_document(self.source, forced_images=[{"page": 1, "image": 1}])
        page_record = {
            "kind": "page", "page": 2, "image_file": str(self.scan_image),
            "image_width": 840, "image_height": 1190,
            "lines": [{"text": "SCAN ONLY PAGE SAMPLE", "score": 0.99, "box_px": [84, 80, 720, 160]}],
        }
        image_plan = plan["ocr_images"][0]
        image_record = {
            "kind": "image", "page": 1, "image": 1,
            "target_rect_pdf": image_plan["rect_pdf"],
            "image_width": 400, "image_height": 400,
            "lines": [{"text": "EMBEDDED FIGURE LABEL", "score": 0.98, "box_px": [20, 20, 360, 80]}],
        }
        destination = self.root / "searchable-image.pdf"
        build_searchable_pdf(self.source, plan, {"pages": [page_record], "images": [image_record]}, destination)
        result = fitz.open(destination)
        self.assertIn("EMBEDDED FIGURE LABEL", result[0].get_text("text"))
        self.assertIn("SCAN ONLY PAGE SAMPLE", result[1].get_text("text"))
        result.close()

    def test_translation_source_removes_scan_pixels_but_preserves_page_contract(self):
        plan = analyze_document(self.source)
        record = {
            "page": 2, "image_file": str(self.scan_image),
            "image_width": 840, "image_height": 1190, "line_count": 1,
            "lines": [{"text": "SCAN ONLY PAGE SAMPLE", "score": 0.99, "box_px": [84, 80, 720, 160]}],
        }
        # Force the synthetic page through the text-dominant branch.
        plan["pages"][1]["image_coverage"] = 1.0
        record["lines"] = record["lines"] * 60
        record["line_count"] = 60
        destination = self.root / "translation-source.pdf"
        build_translation_source(self.source, plan, {"pages": [record]}, destination)
        result = fitz.open(destination)
        original = fitz.open(self.source)
        self.assertEqual(result.page_count, original.page_count)
        self.assertEqual([page.rect for page in result], [page.rect for page in original])
        self.assertIn("reliable native text layer", result[0].get_text("text"))
        self.assertIn("SCAN ONLY PAGE SAMPLE", result[1].get_text("text"))
        self.assertEqual(len(result[1].get_images(full=True)), 0)
        result.close()
        original.close()

    def test_translation_source_figure_page_keeps_image_and_whites_text_boxes(self):
        plan = analyze_document(self.source)
        record = {
            "page": 2, "image_file": str(self.scan_image),
            "image_width": 840, "image_height": 1190, "line_count": 1,
            "lines": [{"text": "SCAN ONLY PAGE SAMPLE", "score": 0.99, "box_px": [84, 80, 720, 160]}],
        }
        destination = self.root / "translation-figure.pdf"
        build_translation_source(self.source, plan, {"pages": [record]}, destination)
        result = fitz.open(destination)
        self.assertTrue(result[1].get_images(full=True))
        self.assertIn("SCAN ONLY PAGE SAMPLE", result[1].get_text("text"))
        result.close()

    def test_page_selection_parser(self):
        self.assertEqual(parse_page_selection("1, 3-5，8"), [1, 3, 4, 5, 8])
        with self.assertRaises(ValueError):
            parse_page_selection("3-2")

    def test_worker_uses_canonical_ocr_model_directory(self):
        runtime = self.root / "ocr-runtime-v1"
        results = self.root / "ocr-results.json"
        results.write_text('{"summary":{"warnings":[]}}')
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch.dict("os.environ", {"PDF_READER_OCR_RUNTIME_DIR": str(runtime)}), patch(
            "ocr_pipeline.subprocess.run", return_value=completed,
        ) as invoked:
            run_worker(
                self.source, {"ocr_pages": [2], "ocr_images": []},
                runtime / "venv/bin/python", results, self.root / "ocr-pages",
            )
        worker_env = invoked.call_args.kwargs["env"]
        self.assertEqual(worker_env["PADDLE_PDX_CACHE_HOME"], str(runtime.resolve() / "models"))
        self.assertEqual(worker_env["PADDLEX_HOME"], str(runtime.resolve() / "models"))


if __name__ == "__main__":
    unittest.main()

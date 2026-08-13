import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from qa_repair_harness import font_path, line_records, page_contract, resolve_task_files, run_full  # noqa: E402


def make_pdf(path: Path, labels: list[str], colors: list[tuple[float, float, float]]) -> None:
    document = fitz.open()
    for label, color in zip(labels, colors):
        page = document.new_page(width=240, height=180)
        page.draw_rect(page.rect, color=None, fill=color)
        page.insert_text((24, 80), label, fontsize=16, color=(0, 0, 0))
    document.save(path)


def make_single_page_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page(width=360, height=220)
    page.insert_text((50, 60), text, fontsize=14, color=(0, 0, 0))
    document.save(path)
    document.close()


class RepairHarnessTaskReferencesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_pdf(self.root / "original.pdf", ["source target", "source page two"], [(1, 1, 1), (1, 1, 1)])
        make_pdf(self.root / "translated-zh.pdf", ["legacy target", "legacy page two"], [(1, .8, .8), (1, .8, .8)])
        make_pdf(self.root / "translated-zh-v8.pdf", ["current target", "current page two"], [(.8, 1, .8), (.8, 1, .8)])
        (self.root / "page-plan.json").write_text(json.dumps({"marker": "legacy", "pages": []}))
        (self.root / "page-plan-v8.json").write_text(json.dumps({
            "marker": "v8",
            "pages": [
                {"pdf_page": 1, "type": "body", "policy": "standard_translation"},
                {"pdf_page": 2, "type": "body", "policy": "standard_translation"},
            ],
        }))
        (self.root / "task.json").write_text(json.dumps({
            "id": "sample",
            "original_file": "original.pdf",
            "translated_file": "translated-zh-v8.pdf",
            "page_plan_file": "page-plan-v8.json",
            "qa_alpha_file": "qa-alpha.json",
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_full_repair_uses_versioned_current_and_preserves_non_target_page(self):
        output = self.root / "candidate"
        result = run_full(
            self.root,
            [{"pdf_page": 1, "family": "unexpected_text"}],
            output,
            task_id="sample",
        )
        candidate = fitz.open(output / "translated-zh.repaired.pdf")
        current = fitz.open(self.root / "translated-zh-v8.pdf")
        legacy = fitz.open(self.root / "translated-zh.pdf")
        self.assertEqual(page_contract(candidate[1]), page_contract(current[1]))
        self.assertNotEqual(page_contract(candidate[1]), page_contract(legacy[1]))
        self.assertEqual(result["input_files"]["current"]["path"], "translated-zh-v8.pdf")
        self.assertEqual(result["non_target_integrity"], {"checked_pages": 1, "mismatched_pages": []})
        repaired_plan = json.loads((output / "page-plan.repaired.json").read_text())
        self.assertEqual(repaired_plan["marker"], "v8")
        repaired_qa = json.loads((output / "qa-repaired.json").read_text())
        self.assertEqual(
            repaired_qa["contract"]["task_projection"]["payload"]["translated_file"],
            "translated-zh-v8.pdf",
        )

    def test_task_reference_cannot_escape_task_root(self):
        task = json.loads((self.root / "task.json").read_text())
        task["translated_file"] = "../outside.pdf"
        (self.root / "task.json").write_text(json.dumps(task))
        with self.assertRaisesRegex(RuntimeError, "越出任务目录"):
            resolve_task_files(self.root)


class FakeTranslationBroker:
    def __init__(self, *args, **kwargs):
        self.metrics = {
            "requests": 0,
            "ai_seconds": 0.0,
            "cache_hits": 0,
            "glossary_hits": 0,
            "unique_ai_items": 0,
            "unresolved": [],
            "errors": [],
        }

    def translate(self, texts, instruction):
        translations = []
        for text in texts:
            if "First English" in text:
                translations.append("时间扭曲距离下的流监测")
            elif "Second English" in text:
                translations.append("第二次修复标记")
            else:
                translations.append("已修复")
        return translations


def make_expected_repair_crop(path: Path, rect: fitz.Rect, text: str) -> None:
    document = fitz.open()
    page = document.new_page(width=360, height=220)
    page.draw_rect(
        fitz.Rect(rect.x0 - 1.2, rect.y0 - 0.6, rect.x1 + 1.2, rect.y1 + 0.8),
        color=None,
        fill=(1, 1, 1),
    )
    page.insert_font(fontname="expected-cjk", fontfile=str(font_path()))
    for size in (12, 10, 9, 8, 7, 6, 5, 4):
        if page.insert_textbox(rect, text, fontname="expected-cjk", fontsize=size, color=(0, 0, 0)) >= 0:
            break
    document.save(path)
    document.close()


def rendered_mean_abs_diff(left: Path, right: Path, clip: fitz.Rect) -> float:
    left_doc = fitz.open(left)
    right_doc = fitz.open(right)
    left_pix = left_doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
    right_pix = right_doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
    left_doc.close()
    right_doc.close()
    return sum(abs(a - b) for a, b in zip(left_pix.samples, right_pix.samples)) / len(left_pix.samples)


class RepairHarnessRepeatedRepairRenderingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_single_page_pdf(self.root / "original.pdf", "source page")
        make_single_page_pdf(self.root / "translated-zh.pdf", "First English marker Problem")
        (self.root / "page-plan.json").write_text(json.dumps({
            "version": 2,
            "pages": [{"pdf_page": 1, "type": "body", "policy": "standard_translation"}],
        }))
        (self.root / "task.json").write_text(json.dumps({
            "id": "sample",
            "original_file": "original.pdf",
            "translated_file": "translated-zh.pdf",
            "page_plan_file": "page-plan.json",
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_repairing_already_repaired_page_keeps_new_cjk_glyphs_renderable(self):
        with patch("qa_repair_harness.TranslationBroker", FakeTranslationBroker):
            run_full(
                self.root,
                [{"pdf_page": 1, "family": "untranslated_region"}],
                self.root / "round1",
                task_id="sample",
            )
        shutil.copyfile(self.root / "round1" / "translated-zh.repaired.pdf", self.root / "translated-zh.pdf")

        current = fitz.open(self.root / "translated-zh.pdf")
        current[0].insert_text((50, 150), "Second English marker Problem", fontsize=14)
        current.save(self.root / "translated-zh-next.pdf")
        current.close()
        (self.root / "translated-zh-next.pdf").replace(self.root / "translated-zh.pdf")

        current = fitz.open(self.root / "translated-zh.pdf")
        second_line = next(
            item for item in line_records(current[0])
            if "Second English marker Problem" in item["text"]
        )
        text_rect = fitz.Rect(second_line["bbox"])
        current.close()

        with patch("qa_repair_harness.TranslationBroker", FakeTranslationBroker):
            run_full(
                self.root,
                [{"pdf_page": 1, "family": "untranslated_region"}],
                self.root / "round2",
                task_id="sample",
            )

        expected = self.root / "expected-second-repair.pdf"
        make_expected_repair_crop(expected, text_rect, "第二次修复标记")
        clip = fitz.Rect(text_rect.x0 - 3, text_rect.y0 - 3, text_rect.x1 + 3, text_rect.y1 + 3)
        repaired = self.root / "round2" / "translated-zh.repaired.pdf"
        repaired_doc = fitz.open(repaired)
        repair_font_names = {
            str(font[4]) for font in repaired_doc[0].get_fonts(full=True)
            if len(font) > 4 and str(font[4]).startswith("repair-cjk")
        }
        repaired_doc.close()
        self.assertGreaterEqual(len(repair_font_names), 2)

        diff = rendered_mean_abs_diff(repaired, expected, clip)
        self.assertLess(diff, 1.0)


if __name__ == "__main__":
    unittest.main()

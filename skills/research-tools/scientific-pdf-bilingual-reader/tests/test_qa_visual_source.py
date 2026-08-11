import sys
import tempfile
import unittest
from pathlib import Path

import fitz

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from qa_alpha import audit


class QaVisualSourceTest(unittest.TestCase):
    def test_white_translation_source_does_not_make_normal_page_crowded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            translation_source = root / "translation-source.pdf"
            visible_source = root / "searchable-original.pdf"
            output = root / "translated.pdf"

            visible = fitz.open()
            page = visible.new_page(width=420, height=595)
            page.insert_textbox(
                fitz.Rect(45, 50, 375, 540),
                "Reader-visible source paragraph. " * 45,
                fontsize=11,
            )
            visible.save(visible_source)
            visible.save(output)
            visible.close()

            blank = fitz.open()
            page = blank.new_page(width=420, height=595)
            page.insert_textbox(
                fitz.Rect(45, 50, 375, 540),
                "Reader-visible source paragraph. " * 45,
                fontsize=11, render_mode=3,
            )
            blank.save(translation_source)
            blank.close()

            report = audit(
                translation_source, output, visual_source_path=visible_source,
            )
            issue_types = {
                issue["issue_type"]
                for issue in report["pages"][0]["issues"]
            }
            self.assertNotIn("rendered_regions_crowded", issue_types)
            self.assertGreater(report["pages"][0]["metrics"]["source_ink_ratio"], 0.01)


if __name__ == "__main__":
    unittest.main()

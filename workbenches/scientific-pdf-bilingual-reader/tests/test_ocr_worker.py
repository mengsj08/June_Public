import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ocr_worker import check_assets, extract_lines, model_assets_manifest_sha256, model_cache_root, parse_pages, result_payload


class FakeResult:
    @property
    def json(self):
        return {"res": {"rec_texts": ["Alpha", "Beta"], "rec_scores": [0.99, 0.82], "rec_boxes": [[1, 2, 30, 12], [4, 20, 40, 33]], "rec_polys": [[[1, 2], [30, 2], [30, 12], [1, 12]], [[4, 20], [40, 20], [40, 33], [4, 33]]]}}


class OcrWorkerContractTest(unittest.TestCase):
    def test_result_contract_normalises_paddle_payload(self):
        payload = result_payload(FakeResult())
        lines = extract_lines(payload)
        self.assertEqual([line["text"] for line in lines], ["Alpha", "Beta"])
        self.assertEqual(lines[0]["box_px"], [1.0, 2.0, 30.0, 12.0])
        self.assertEqual(lines[0]["polygon_px"][2], [30.0, 12.0])
        self.assertAlmostEqual(lines[1]["score"], 0.82)

    def test_page_parser_is_sorted_and_unique(self):
        self.assertEqual(parse_pages("4,2-3,3"), [2, 3, 4])
        with self.assertRaises(ValueError):
            parse_pages("0")

    def test_model_cache_prefers_current_paddlex_variable(self):
        with patch.dict(os.environ, {
            "PADDLE_PDX_CACHE_HOME": "/tmp/current-paddlex-cache",
            "PADDLEX_HOME": "/tmp/legacy-paddlex-cache",
        }, clear=False):
            self.assertEqual(model_cache_root(), Path("/tmp/current-paddlex-cache"))

    def test_asset_check_uses_recorded_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "models"
            model.mkdir()
            asset = model / "weights.bin"
            asset.write_bytes(b"model")
            manifest = root / "assets.json"
            manifest.write_text(json.dumps({
                "model_root": str(model), "asset_count": 1,
                "assets": [{"path": "weights.bin", "bytes": 5, "sha256": hashlib.sha256(b"model").hexdigest()}],
            }))
            check_assets(manifest)
            asset.write_bytes(b"changed")
            with self.assertRaises(SystemExit):
                check_assets(manifest)

    def test_model_manifest_hash_uses_parent_of_canonical_model_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "models").mkdir()
            manifest = root / "model-assets.json"
            manifest.write_bytes(b'{"asset_count":1}')
            with patch.dict(os.environ, {
                "PADDLE_PDX_CACHE_HOME": str(root / "models"),
                "PADDLEX_HOME": str(root / "shadow-models"),
            }, clear=False):
                self.assertEqual(
                    model_assets_manifest_sha256(),
                    hashlib.sha256(manifest.read_bytes()).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()

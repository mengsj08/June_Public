from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import build_pdf_html
import fetch_drug_label
import label_common


class SafetyTests(unittest.TestCase):
    def test_url_allowlist_and_private_network(self):
        self.assertEqual(
            label_common.validate_https_url(
                "https://www.cde.org.cn/path", label_common.DEFAULT_OFFICIAL_HOSTS
            ),
            "https://www.cde.org.cn/path",
        )
        with self.assertRaises(label_common.LabelError):
            label_common.validate_https_url(
                "http://www.cde.org.cn/path", label_common.DEFAULT_OFFICIAL_HOSTS
            )
        with self.assertRaises(label_common.LabelError):
            label_common.validate_https_url(
                "https://127.0.0.1/file.pdf", label_common.DEFAULT_OFFICIAL_HOSTS
            )
        with self.assertRaises(label_common.LabelError):
            label_common.validate_https_url(
                "https://nmpa.gov.cn.evil.example/file.pdf", label_common.DEFAULT_OFFICIAL_HOSTS
            )

    def test_external_html_removes_active_content(self):
        raw = b"""<!doctype html><html><head><title>Official Label</title>
        <script>steal()</script></head><body><main><h1>Medicine</h1>
        <p>This is a sufficiently long official label paragraph with warnings, dosage,
        contraindications, adverse reactions, storage details, and manufacturer information.</p>
        <form><input value='secret'></form><iframe src='https://evil.example'></iframe>
        </main></body></html>"""
        rendered, title, text_chars = label_common.sanitize_external_html(
            raw, title=None, source_url="https://www.cde.org.cn/example"
        )
        self.assertEqual(title, "Official Label")
        self.assertGreater(text_chars, 80)
        self.assertNotIn("steal()", rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<iframe", rendered)
        self.assertNotIn("<form", rendered)

    def test_zip_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.jpg", b"fake")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(label_common.LabelError):
                fetch_drug_label.extract_zip_assets(buffer.getvalue(), Path(temp))


class ParsingTests(unittest.TestCase):
    def test_legacy_html_accepts_attribute_order_and_nested_divs(self):
        raw = """<html><head><title>说明书</title></head><body>
        <ul class="items" id='instruction'>
          <li class="entry"><div class="dict-name"><span>药品名称</span></div>
            <div class="dict-value"><div>通用名称：测试药</div><p>后文<script>alert(1)</script></p></div></li>
          <li><div class="dict-name"><span>成份</span></div><div class="dict-value"><p>成份甲</p></div></li>
          <li><div class="dict-name"><span>适应症</span></div><div class="dict-value"><p>适应症正文</p></div></li>
          <li><div class="dict-name"><span>禁忌</span></div><div class="dict-value"><p>禁忌正文</p></div></li>
        </ul></body></html>""".encode()
        sections, _ = build_pdf_html.parse_sections(raw)
        self.assertEqual(len(sections), 4)
        self.assertIn("后文", sections[0][1])
        self.assertNotIn("alert(1)", sections[0][1])
        self.assertEqual(build_pdf_html.infer_title(sections, None), "测试药说明书")

    def test_spl_xml_renders_sections_without_executable_markup(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <document xmlns='urn:hl7-org:v3'>
          <id root='doc-id'/><setId root='00000000-0000-0000-0000-000000000001'/>
          <versionNumber value='1'/><effectiveTime value='20260901'/>
          <component><structuredBody>
            <component><section><title>INDICATIONS</title><text><paragraph>Use text.</paragraph></text></section></component>
            <component><section><title>WARNINGS</title><text><paragraph><content styleCode='Bold'>Warning text.</content></paragraph></text></section></component>
            <component><section><title>STORAGE</title><text><paragraph>Store safely.</paragraph></text></section></component>
          </structuredBody></component>
        </document>"""
        rendered, count, metadata = fetch_drug_label.render_spl_html(
            xml,
            title="TEST DRUG",
            source_url="https://dailymed.nlm.nih.gov/example.xml",
            asset_mapping={},
        )
        self.assertEqual(count, 3)
        self.assertEqual(metadata["version_number"], "1")
        self.assertIn("<strong>Warning text.</strong>", rendered)
        self.assertNotIn("<script", rendered)


class WorkflowTests(unittest.TestCase):
    def test_fetch_commands_require_explicit_output_format(self):
        parser = fetch_drug_label.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["fetch-dailymed", "--setid", "00000000-0000-0000-0000-000000000001", "--out-dir", "/tmp/out"])
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "fetch-url",
                "--url",
                "https://www.cde.org.cn/label.pdf",
                "--jurisdiction",
                "cn",
                "--out-dir",
                "/tmp/out",
            ])

    def test_ambiguous_query_requires_selection(self):
        candidates = [
            {"setid": "a", "title": "A", "published_date": "x", "spl_version": "1"},
            {"setid": "b", "title": "B", "published_date": "x", "spl_version": "1"},
        ]
        args = Namespace(
            setid=None,
            query="test",
            name_type="both",
            limit=10,
            timeout=1,
            select=None,
        )
        with patch.object(fetch_drug_label, "dailymed_search", return_value=(candidates, {})):
            with self.assertRaises(fetch_drug_label.AmbiguousCandidates):
                fetch_drug_label.select_candidate(args)

    def test_explicit_sample_selection_is_deterministic(self):
        candidates = [
            {"setid": "a", "title": "A", "published_date": "x", "spl_version": "1"},
            {"setid": "b", "title": "B", "published_date": "x", "spl_version": "1"},
        ]
        args = Namespace(
            setid=None,
            query="test",
            name_type="both",
            limit=10,
            timeout=1,
            select=1,
        )
        with patch.object(fetch_drug_label, "dailymed_search", return_value=(candidates, {"db": "test"})):
            selected, metadata = fetch_drug_label.select_candidate(args)
        self.assertEqual(selected["setid"], "a")
        self.assertEqual(metadata, {"db": "test"})

    def test_manifest_hash_verification_detects_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "label.html"
            label_common.write_text(
                path,
                "<!doctype html><html><body><p>" + ("verified content " * 20) + "</p></body></html>",
            )
            artifact = label_common.artifact_entry(
                root,
                path,
                role="derived_html",
                media_type="text/html",
                derived=True,
            )
            manifest = {"artifacts": [artifact]}
            self.assertEqual(label_common.verify_manifest(root, manifest)["status"], "pass")
            path.write_text("tampered", encoding="utf-8")
            report = label_common.verify_manifest(root, manifest)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("SHA-256" in item for item in report["errors"]))

    def test_raw_html_may_preserve_scripts_but_derived_html_may_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "source.html"
            raw.write_text(
                "<!doctype html><html><body><script>site()</script><p>" + ("official source " * 20) + "</p></body></html>",
                encoding="utf-8",
            )
            raw_artifact = label_common.artifact_entry(
                root,
                raw,
                role="official_source_html",
                media_type="text/html",
                derived=False,
            )
            raw_report = label_common.verify_manifest(root, {"artifacts": [raw_artifact]})
            self.assertEqual(raw_report["status"], "pass")
            self.assertEqual(raw_report["checks"][0]["untrusted_active_tags_preserved"], ["script"])

            derived_artifact = dict(raw_artifact)
            derived_artifact["role"] = "derived_sanitized_html"
            derived_artifact["derived"] = True
            derived_report = label_common.verify_manifest(root, {"artifacts": [derived_artifact]})
            self.assertEqual(derived_report["status"], "fail")
            self.assertTrue(any("派生 HTML" in item for item in derived_report["errors"]))


if __name__ == "__main__":
    unittest.main()

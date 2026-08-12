import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
import install_skill  # noqa: E402
import launch  # noqa: E402
import ocr_runtime  # noqa: E402


class DistributionTest(unittest.TestCase):
    def test_dual_ecosystem_install_is_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            env = {
                "CODEX_SKILLS_DIR": str(base / ".agents" / "skills"),
                "CLAUDE_SKILLS_DIR": str(base / ".claude" / "skills"),
            }
            with patch.dict(os.environ, env, clear=False):
                results = install_skill.install(SOURCE, "both", force=False, dry_run=False)
            self.assertEqual({row["ecosystem"] for row in results}, {"codex", "claude"})
            for root in (base / ".agents" / "skills", base / ".claude" / "skills"):
                target = root / install_skill.SKILL_NAME
                self.assertTrue((target / "SKILL.md").is_file())
                self.assertTrue((target / "scripts" / "bootstrap.py").is_file())
                self.assertFalse(any(path.name == "__pycache__" for path in target.rglob("*")))
                self.assertFalse(any(path.suffix == ".pyc" for path in target.rglob("*")))

    def test_existing_install_requires_force_and_is_backed_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skills"
            target = root / install_skill.SKILL_NAME
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old", encoding="utf-8")
            env = {
                "CODEX_SKILLS_DIR": str(root),
                "PDF_READER_SKILL_BACKUP_DIR": str(Path(temp) / "backups"),
            }
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(FileExistsError):
                    install_skill.install(SOURCE, "codex", force=False, dry_run=False)
                result = install_skill.install(SOURCE, "codex", force=True, dry_run=False)[0]
            self.assertTrue(Path(result["backup"]).is_dir())
            self.assertEqual((Path(result["backup"]) / "SKILL.md").read_text(), "old")
            self.assertFalse(Path(result["backup"]).is_relative_to(root))

    def test_dual_install_preflight_prevents_partial_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            codex_root = base / ".agents" / "skills"
            claude_root = base / ".claude" / "skills"
            existing = claude_root / install_skill.SKILL_NAME
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text("existing", encoding="utf-8")
            env = {"CODEX_SKILLS_DIR": str(codex_root), "CLAUDE_SKILLS_DIR": str(claude_root)}
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(FileExistsError):
                    install_skill.install(SOURCE, "both", force=False, dry_run=False)
            self.assertFalse((codex_root / install_skill.SKILL_NAME).exists())
            self.assertEqual((existing / "SKILL.md").read_text(), "existing")

    def test_bootstrap_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime"
            with patch.dict(os.environ, {"PDF_READER_RUNTIME_DIR": str(runtime)}, clear=False):
                bootstrap.install(yes=True, dry_run=True, skip_assets=False)
            self.assertFalse(runtime.exists())

    def test_ocr_bootstrap_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "ocr-runtime"
            with patch.dict(os.environ, {"PDF_READER_OCR_RUNTIME_DIR": str(runtime)}, clear=False):
                ocr_runtime.install(yes=True, dry_run=True)
            self.assertFalse(runtime.exists())

    def test_ocr_runtime_uses_paddlex_cache_home(self):
        paths = ocr_runtime.runtime_paths()
        env = ocr_runtime.runtime_environment(paths)
        self.assertEqual(env["PADDLE_PDX_CACHE_HOME"], str(paths["models"]))
        self.assertEqual(env["PADDLEX_HOME"], str(paths["models"]))

    def test_ocr_manifest_script_is_valid_python(self):
        paths = ocr_runtime.runtime_paths()
        completed = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"python": "3.12.13", "packages": {}}),
            "stderr": "",
        })()
        with patch.object(ocr_runtime.subprocess, "run", return_value=completed) as run:
            manifest = ocr_runtime._build_manifest(paths, ocr_runtime.load_lock())
        code = run.call_args.args[0][2]
        compile(code, "<ocr-manifest>", "exec")
        self.assertEqual(manifest["python"], "3.12.13")

    def test_launch_dry_run_uses_managed_python_and_engine(self):
        fake = {
            "root": Path("/tmp/reader runtime"),
            "venv_python": Path("/tmp/reader runtime/venv/bin/python"),
            "pdf2zh": Path("/tmp/reader runtime/venv/bin/pdf2zh"),
        }
        output = io.StringIO()
        with (
            patch.object(launch, "runtime_paths", return_value=fake),
            patch.object(launch, "probe_runtime", return_value={"ready": True}),
            patch.object(launch, "port_available", side_effect=lambda _host, port: port == 8876),
            patch.object(sys, "argv", ["launch.py", "start", "--dry-run", "--open"]),
            contextlib.redirect_stdout(output),
        ):
            launch.main()
        self.assertIn(str(fake["venv_python"]), output.getvalue())
        self.assertIn("workbench.py", output.getvalue())
        self.assertIn("--port 8876", output.getvalue())
        self.assertIn("自动使用 8876", output.getvalue())

    def test_explicit_launch_port_is_preserved(self):
        with patch.object(launch, "port_available") as available:
            self.assertEqual(launch.resolve_port("127.0.0.1", 9001), 9001)
        available.assert_not_called()

    def test_runtime_lock_is_pinned(self):
        lock = json.loads((SOURCE / "references" / "runtime-lock.json").read_text())
        self.assertEqual(lock["python"], "3.12")
        self.assertEqual(len(lock["pdf2zh"]["commit"]), 40)
        self.assertIn("babeldoc==0.2.33", lock["constraints"])
        self.assertIn("tencentcloud-sdk-python-tmt==3.0.1000", lock["constraints"])
        self.assertIn("pdf2zh.translator", lock["required_imports"])
        self.assertIn("pdf2zh.high_level", lock["required_imports"])
        ocr_lock = json.loads((SOURCE / "references" / "ocr-runtime-lock.json").read_text())
        self.assertEqual(ocr_lock["python"], "3.12")
        self.assertIn("paddleocr==3.7.0", ocr_lock["packages"])
        self.assertEqual(ocr_lock["pipeline"]["language"], "en")

    def test_frontend_runtime_lock_matches_vendored_pdfjs(self):
        lock = json.loads((SOURCE / "references" / "frontend-runtime-lock.json").read_text())
        self.assertEqual(lock["package"]["name"], "pdfjs-dist")
        self.assertEqual(lock["package"]["version"], "6.1.200")
        vendor = SOURCE / lock["vendored"]["root"]
        for filename, key in (
            ("pdf.mjs", "pdf_mjs_sha256"),
            ("pdf.worker.mjs", "worker_mjs_sha256"),
            ("LICENSE", "license_sha256"),
        ):
            digest = hashlib.sha256((vendor / filename).read_bytes()).hexdigest()
            self.assertEqual(digest, lock["vendored"][key])
        for folder, expected in lock["vendored"]["support_asset_counts"].items():
            self.assertEqual(sum(path.is_file() for path in (vendor / folder).rglob("*")), expected)


if __name__ == "__main__":
    unittest.main()

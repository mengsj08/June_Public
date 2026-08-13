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

    def test_user_facing_product_name_is_long_pdf_reader(self):
        page = (SOURCE / "assets" / "app" / "index.html").read_text(encoding="utf-8")
        skill = (SOURCE / "SKILL.md").read_text(encoding="utf-8")
        workbench = (SOURCE / "scripts" / "workbench.py").read_text(encoding="utf-8")
        setup = (SOURCE / "scripts" / "setup.py").read_text(encoding="utf-8")
        install = (SOURCE / "scripts" / "install_skill.py").read_text(encoding="utf-8")
        bootstrap = (SOURCE / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
        display_surfaces = "\n".join([page, skill, workbench, setup, install, bootstrap])
        self.assertIn("长 PDF 双语阅读器", display_surfaces)
        self.assertIn("Long PDF Bilingual Reader", page)
        self.assertNotIn("科研长 PDF 双语阅读器", display_surfaces)
        self.assertNotIn("Scientific PDF Bilingual Reader</small>", page)
        self.assertIn("scientific-pdf-bilingual-reader", skill)
        self.assertIn("Scientific PDF Bilingual Reader", workbench)

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

    def test_repair_feedback_uses_in_page_dialog(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        page = (SOURCE / "assets" / "app" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("prompt(", app)
        self.assertIn("repairDecisionDialog", app)
        self.assertIn('id="repairDecisionDialog"', page)
        self.assertIn('id="repairDecisionNote"', page)

    def test_frontend_hides_technical_tips_from_default_action_queue(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        page = (SOURCE / "assets" / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function isActionableIssue", app)
        self.assertIn("reviewShowTips=false", app)
        self.assertIn('class="technical-tips"', app)
        self.assertIn('id="reviewTipsToggle"', page)
        self.assertIn("target.issues.some(needsAction)", app)
        self.assertIn("为什么标记？", app)
        self.assertIn("机器只统计 PDF 的可选择文字层", app)
        self.assertIn("你的补充意见（可选）", app)
        self.assertIn("历史处理记录", app)
        self.assertIn('class="repair-history"', app)
        self.assertIn("旧提示已退出待办", app)
        self.assertIn("旧 QA 参考", app)
        self.assertIn("reviewData?.pages.some", app)
        self.assertIn("当前页 / 待办", app)
        self.assertIn("human-review", app)
        self.assertIn("填写本页的人工发现", app)

    def test_review_polling_preserves_active_feedback_input(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function reviewInteractionActive", app)
        self.assertIn("reviewComposing", app)
        self.assertIn("async function pollReview", app)
        self.assertIn("pollReview().catch", app)
        self.assertNotIn("if(reviewTask)loadReview().catch", app)

    def test_review_polling_uses_block_hashes_for_static_dom(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("reviewBlockHashes", app)
        self.assertIn("function patchReviewBlock", app)
        self.assertIn("data-review-block", app)
        self.assertIn("function ensureReviewDetailSkeleton", app)
        self.assertIn("preserveOpenDetails", app)
        self.assertIn("setHtmlIfChanged", app)
        self.assertNotIn("$('#reviewDetail').innerHTML=`<div class=\"detail-head\"", app)

    def test_frontend_exposes_comment_decision_controls_without_duplicate_hints(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("进修复", app)
        self.assertIn("作废移除", app)
        self.assertIn("撤回批准", app)
        self.assertIn('data-cycle-comment-decision="not_adopted"', app)
        self.assertNotIn("疑似重复", app)

    def test_frontend_groups_same_type_machine_issues_display_only(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function issueGroups", app)
        self.assertIn("data-group-issues", app)
        self.assertIn("for(const issueId of issueIds)", app)
        self.assertIn("structuralOcrBanner", app)
        self.assertIn("target?.route!=='ocr'", app)

    def test_frontend_rerun_uses_start_with_snapshot_flag(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-rerun="${t.id}"', app)
        self.assertIn("body.rerun=true", app)
        self.assertIn("await startTask(b.dataset.rerun,{rerun:true})", app)

    def test_scan_route_uses_dedicated_pipeline_and_shared_translation_broker(self):
        workbench = (SOURCE / "scripts" / "workbench.py").read_text(encoding="utf-8")
        repair = (SOURCE / "scripts" / "qa_repair_harness.py").read_text(encoding="utf-8")
        broker = (SOURCE / "scripts" / "translation_broker.py").read_text(encoding="utf-8")
        self.assertIn("build_scan_translation_pdf", workbench)
        self.assertIn("merge_scan_pages", workbench)
        self.assertIn("scan_pages and int(plan.get(\"routes\", {}).get(\"text\", 0)) == 0", workbench)
        self.assertIn("scan route complete", workbench)
        self.assertIn("from translation_broker import TranslationBroker", repair)
        self.assertIn("class TranslationBroker", broker)
        self.assertNotIn("class TranslationBroker", repair)

    def test_comment_decision_success_is_visible_and_revisable(self):
        app = (SOURCE / "assets" / "app" / "app.js").read_text(encoding="utf-8")
        styles = (SOURCE / "assets" / "app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("已同意修改，已加入修复池", app)
        self.assertIn("当前 PDF 尚未改变", app)
        self.assertIn("更改决定", app)
        self.assertIn("commentDecisionPanel", app)
        self.assertIn(".comment-decision-state.approved", styles)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import hashlib
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from workbench import (
    ACTIVE_TASKS, ACTIVE_TASKS_LOCK, ENGINE_TRANSLATION_THREADS, PROXY_BEHAVIOR_VERSION,
    engine_coreml_ort_failure, engine_fatal_marker, engine_gateway_failure_count, engine_progress,
    ensure_localhost_no_proxy, proxy_provider, running_task_is_stale,
    log_scan_translation_report,
    pdf2zh_cpu_retry_command, pdf2zh_cpu_retry_environment, reset_translation_warnings,
    resume_agent_review_queue_for_projection,
    scan_route_count, schedule_created_diagnosis, snapshot_before_rerun, summarize_qa,
    terminate_recorded_engine,
)
from repair_batch import formal_output_status
from qa_alpha import load_refusal_pages


class WorkbenchResilienceTest(unittest.TestCase):
    def tearDown(self):
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.clear()

    def test_proxy_model_version_and_legacy_format_resolve_provider(self):
        self.assertEqual(proxy_provider(f"claude+{PROXY_BEHAVIOR_VERSION}"), "claude")
        self.assertEqual(proxy_provider("claude"), "claude")

    def test_running_task_is_stale_only_when_not_active_here(self):
        task = {"id": "task1", "status": "running"}
        self.assertTrue(running_task_is_stale(task))
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.add("task1")
        self.assertFalse(running_task_is_stale(task))

    def test_authentication_failures_are_fatal_markers(self):
        self.assertEqual(engine_fatal_marker("API Error: Failed to authenticate"), "Failed to authenticate")
        self.assertEqual(engine_fatal_marker("OAuth session expired; login again"), "OAuth session expired")
        self.assertIsNone(engine_fatal_marker("ordinary retryable output"))

    def test_engine_progress_ignores_log_date_and_reads_tqdm(self):
        self.assertIsNone(engine_progress("[08/12/26 21:09:08] Error code: 502"))
        self.assertEqual(engine_progress(" 30%|###       | 3/10 [00:12<00:30, 4.2s/it]"), (3, 10))

    def test_gateway_failure_count_only_counts_status_lines(self):
        text = "Error code: converter.py:359\n  502\npage text 502 is not a status\n 503\n"
        self.assertEqual(engine_gateway_failure_count(text), 2)

    def test_translation_uses_stable_serial_engine_mode(self):
        self.assertEqual(ENGINE_TRANSLATION_THREADS, "1")

    def test_scan_route_count_is_page_route_scoped(self):
        self.assertEqual(scan_route_count({"pages": [{"route": "ocr"}, {"route": "text"}, {"route": "ocr"}]}), 2)

    def test_scan_failure_report_logs_page_stats_and_report_path(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            report_file = folder / "scan-translation-failure.json"
            report = {
                "reason": "layout_validation_failed",
                "elapsed_seconds": 1.25,
                "pages": [{
                    "page": 2,
                    "route": "ocr",
                    "status": "layout_failed",
                    "layout": {
                        "source": "deterministic_columns",
                        "model_attempted": True,
                        "model_error": "RuntimeError: unavailable",
                        "model_elapsed_seconds": 0.2,
                        "blocks": [{"block_id": "b1"}],
                        "validation": {
                            "ok": False,
                            "errors": [{"code": "title_block_too_large", "line_count": 20}],
                        },
                    },
                    "paragraph_count": 0,
                    "translation_request_count": 0,
                    "elapsed_seconds": 0.4,
                }],
            }
            log_scan_translation_report(folder, report, failed=True, report_file=report_file)
            log = (folder / "engine.log").read_text(encoding="utf-8")
            self.assertIn("scan page stats: page=2", log)
            self.assertIn("model_attempted=True", log)
            self.assertIn("title_block_too_large", log)
            self.assertIn(f"report={report_file}", log)

    def test_coreml_onnxruntime_failure_signature_requires_nonzero_exit(self):
        log = (
            "onnxruntime_pybind11_state.Fail: Error executing model: "
            "Error in building plan for CoreMLExecutionProvider"
        )
        self.assertTrue(engine_coreml_ort_failure(1, log))
        self.assertFalse(engine_coreml_ort_failure(0, log))
        self.assertFalse(engine_coreml_ort_failure(1, "onnxruntime failed on CPUExecutionProvider"))
        self.assertFalse(engine_coreml_ort_failure(1, "CoreMLExecutionProvider loaded successfully"))

    def test_pdf2zh_cpu_retry_command_and_env_are_isolated_to_retry(self):
        original = ["pdf2zh", "input.pdf", "--service", "openailiked", "--backend", "auto"]
        retried = pdf2zh_cpu_retry_command(original)
        self.assertEqual(retried[-2:], ["--backend", "cpu"])
        self.assertEqual(original[-1], "auto")

        added = pdf2zh_cpu_retry_command(["pdf2zh", "input.pdf"])
        self.assertEqual(added[-2:], ["--backend", "cpu"])

        env = pdf2zh_cpu_retry_environment({"PYTHONPATH": "/existing"})
        self.assertEqual(env["PDF_READER_ORT_CPU_ONLY"], "1")
        self.assertTrue(env["PYTHONPATH"].split(os.pathsep)[0].endswith("pdf2zh_ort_cpu_shim"))
        self.assertIn("/existing", env["PYTHONPATH"].split(os.pathsep))

    def test_cpu_only_sitecustomize_removes_coreml_provider(self):
        calls = []
        fake = types.ModuleType("onnxruntime")

        def inference_session(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return {"providers": kwargs.get("providers") if kwargs else args[2]}

        fake.InferenceSession = inference_session
        fake.get_available_providers = lambda: ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        previous = sys.modules.get("onnxruntime")
        try:
            sys.modules["onnxruntime"] = fake
            with patch.dict(os.environ, {"PDF_READER_ORT_CPU_ONLY": "1"}, clear=False):
                shim = SCRIPTS / "pdf2zh_ort_cpu_shim" / "sitecustomize.py"
                spec = importlib.util.spec_from_file_location("pdf_reader_cpu_sitecustomize_test", shim)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            fake.InferenceSession("model.onnx", object(), providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])
            self.assertEqual(calls[-1]["kwargs"]["providers"], ["CPUExecutionProvider"])
            self.assertEqual(fake.get_available_providers(), ["CPUExecutionProvider"])
        finally:
            if previous is None:
                sys.modules.pop("onnxruntime", None)
            else:
                sys.modules["onnxruntime"] = previous

    def test_local_agent_proxy_bypasses_system_http_proxy(self):
        env = ensure_localhost_no_proxy({"NO_PROXY": "example.org"})
        self.assertEqual(env["NO_PROXY"], "example.org,127.0.0.1,localhost,::1")
        self.assertEqual(env["no_proxy"], "127.0.0.1,localhost,::1")

    def test_only_recorded_matching_pdf2zh_process_is_terminated(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "engine.pid").write_text("321")
            checked = subprocess.CompletedProcess([], 0, stdout=f"pdf2zh {folder}/translation-source.pdf", stderr="")
            with patch("workbench.subprocess.run", return_value=checked), patch(
                "workbench.os.kill", side_effect=[None, ProcessLookupError],
            ) as killed:
                self.assertTrue(terminate_recorded_engine(folder))
            killed.assert_any_call(321, 15)
            self.assertFalse((folder / "engine.pid").exists())

    def test_previous_run_refusal_warning_is_absent_from_next_run_qa(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            warning_file = folder / "translation-warnings.jsonl"
            warning_file.write_text(
                '{"code":"translation_refusal_kept_source","pages":[14]}\n',
                encoding="utf-8",
            )
            self.assertEqual(load_refusal_pages(warning_file), {14})
            reset_translation_warnings(folder)
            self.assertEqual(load_refusal_pages(warning_file), set())
            self.assertEqual(warning_file.read_text(encoding="utf-8"), "")

    def test_june_successor_attempt_schedules_read_only_diagnosis(self):
        record = {
            "repair_id": "attempt-next",
            "pdf_page": 54,
            "issue_ids": ["issue-1"],
            "feedback": "retry advice only",
        }
        with patch("workbench.threading.Thread") as thread:
            started = schedule_created_diagnosis(
                {"created_attempt": record}, Path("/tmp/task"), {"id": "task"}
            )
        self.assertTrue(started)
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        self.assertEqual(thread.call_args.kwargs["target"].__name__, "diagnose")
        self.assertEqual(thread.call_args.kwargs["args"][2:6], ("attempt-next", 54, ["issue-1"], "claude"))
        thread.return_value.start.assert_called_once_with()

    def test_review_cycle_projection_resumes_queued_agent_review_jobs(self):
        folder = Path("/tmp/review-cycle-task")
        task = {"id": "task1"}
        with (
            patch("workbench.queued_agent_review_jobs", return_value=[{"job_id": "queued"}]),
            patch("workbench.agent_runner_active", return_value=False),
            patch("workbench.schedule_agent_review_queue", return_value=True) as scheduled,
        ):
            self.assertTrue(resume_agent_review_queue_for_projection(folder, task))
        scheduled.assert_called_once_with(folder, task)

    def test_review_cycle_projection_does_not_resume_when_runner_active(self):
        with (
            patch("workbench.queued_agent_review_jobs", return_value=[{"job_id": "queued"}]),
            patch("workbench.agent_runner_active", return_value=True),
            patch("workbench.schedule_agent_review_queue") as scheduled,
        ):
            self.assertFalse(resume_agent_review_queue_for_projection(Path("/tmp/task"), {"id": "task1"}))
        scheduled.assert_not_called()

    def test_task_qa_summary_reports_attention_not_all_flagged_pages(self):
        report = {
            "status": "needs_review",
            "flagged_pages": [4, 5],
            "pages": [
                {"pdf_page": 4, "issues": [
                    {"issue_type": "rendered_page_too_sparse", "severity": "red", "user_impact": "hard_blocker", "evidence": "sparse"},
                    {"issue_type": "english_region_untranslated", "severity": "warning", "user_impact": "tip", "evidence": "SSP"},
                ]},
                {"pdf_page": 5, "issues": [
                    {"issue_type": "english_region_untranslated", "severity": "warning", "user_impact": "tip", "evidence": "DRCS"},
                ]},
            ],
        }
        summary = summarize_qa(report)
        self.assertEqual(summary["flagged_pages"], [4, 5])
        self.assertEqual(summary["attention"]["actionable_pages"], [4])
        self.assertEqual(summary["attention"]["technical_tip_pages"], [4, 5])

    def test_snapshot_before_rerun_copies_current_outputs_and_receipt_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "task-rerun"
            folder.mkdir()
            for filename, content in {
                "translated-zh.pdf": b"translated",
                "bilingual-side-by-side.pdf": b"dual",
                "qa-alpha.json": b'{"status":"passed"}',
                "page-plan.json": b'{"pages":[]}',
                "document-plan.json": b'{"pages":[]}',
            }.items():
                (folder / filename).write_bytes(content)
            task = {
                "id": "task-rerun",
                "status": "completed",
                "translated_file": "translated-zh.pdf",
                "dual_file": "bilingual-side-by-side.pdf",
                "qa_alpha_file": "qa-alpha.json",
                "page_plan_file": "page-plan.json",
                "document_plan_file": "document-plan.json",
            }

            receipt = snapshot_before_rerun(folder, task)
            backup = Path(receipt["backup_dir"])

            self.assertEqual(receipt["schema"], "rerun-snapshot-receipt/v1")
            self.assertTrue((backup / "translated-zh.pdf").is_file())
            self.assertTrue((backup / "bilingual-side-by-side.pdf").is_file())
            self.assertTrue((backup / "rerun-receipt.json").is_file())
            self.assertEqual((backup / "task.json").read_text(encoding="utf-8").count("task-rerun"), 1)
            self.assertEqual(
                receipt["pre_rerun_hashes"]["translated-zh.pdf"]["sha256"],
                hashlib.sha256(b"translated").hexdigest(),
            )
            self.assertIn("translated-zh.pdf", receipt["pre_rerun_files"])

    def test_formal_output_timestamp_uses_output_mtime_before_task_creation_time(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            translated = folder / "translated-zh.pdf"
            translated.write_bytes(b"pdf")
            (folder / "qa-alpha.json").write_text('{"status":"passed"}', encoding="utf-8")
            os.utime(translated, (1234567890, 1234567890))
            status = formal_output_status(folder, {
                "id": "task-time",
                "created_at": 100,
                "translated_file": "translated-zh.pdf",
            }, [])
            self.assertEqual(status["installed_at"], 1234567890)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""SKL-102 Gate 2 executor, cancellation, recovery, and receipt contracts."""
from contextlib import contextmanager
import json
import os
import signal
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

import review_executor
import server


def _write_executable(path, source):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(source))
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR)
    return path


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class ReviewExecutorTests(unittest.TestCase):
    @contextmanager
    def _store(self, tmp):
        with mock.patch.object(server, "DATA_ROOT", tmp), \
                mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")), \
                mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
            yield

    def test_windows_platform_command_wraps_cmd_and_bat_launchers(self):
        with mock.patch.object(review_executor, "_is_windows", return_value=True), \
                mock.patch.dict(review_executor.os.environ, {"COMSPEC": r"C:\Windows\System32\cmd.exe"}):
            command = review_executor.platform_command(
                [r"C:\Users\june\AppData\Roaming\npm\codex.cmd", "exec", "prompt"])
        self.assertEqual(
            command,
            [
                r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c",
                r"C:\Users\june\AppData\Roaming\npm\codex.cmd", "exec", "prompt",
            ],
        )

    def test_windows_invoke_provider_uses_process_group_and_taskkill(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = {
                "run_id": "run-windows",
                "trace_root": os.path.join(tmp, "trace-windows"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            process = mock.Mock()
            process.pid = 4321
            process.returncode = 0
            process.communicate.return_value = (
                json.dumps({"type": "thread.started", "thread_id": "thread-windows"}) + "\n",
                "",
            )
            process.poll.return_value = None
            process.wait.return_value = None
            version_result = mock.Mock(stdout="fake-codex 1.0\n", stderr="", returncode=0)
            creation_flag = 0x00000200
            with mock.patch.object(review_executor, "_is_windows", return_value=True), \
                    mock.patch.object(review_executor.subprocess, "CREATE_NEW_PROCESS_GROUP", creation_flag, create=True), \
                    mock.patch.object(review_executor.subprocess, "Popen", return_value=process) as popen, \
                    mock.patch.object(review_executor.subprocess, "run", return_value=version_result) as run, \
                    mock.patch.dict(review_executor.os.environ, {"COMSPEC": "cmd.exe"}):
                result = review_executor.invoke_provider(
                    "codex", "prompt", timeout=2, schema=None,
                    executable=r"C:\Tools\codex.cmd", cwd=tmp, metadata=metadata)
                review_executor.terminate_process_tree(process)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(popen.call_args.args[0][:5], ["cmd.exe", "/d", "/s", "/c", r"C:\Tools\codex.cmd"])
            self.assertEqual(popen.call_args.kwargs["creationflags"], creation_flag)
            self.assertNotIn("start_new_session", popen.call_args.kwargs)
            taskkill_args = run.call_args_list[-1].args[0]
            self.assertEqual(taskkill_args, ["taskkill", "/PID", "4321", "/T", "/F"])

    def test_state_machine_reaches_running_and_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = review_executor.ReviewExecutor(os.path.join(tmp, "traces"))
            release = threading.Event()

            def provider():
                release.wait(timeout=2)
                return {"output": "{}", "receipt": {"status": "completed"}}

            first = executor.submit("run-state", provider, {"run_id": "run-state"})
            self.assertIn(first["state"], {"queued", "running"})
            observed = set()
            for _ in range(50):
                state = executor.snapshot("run-state")["state"]
                observed.add(state)
                if state == "running":
                    break
                time.sleep(0.01)
            release.set()
            done = executor.wait("run-state", timeout=2)
            self.assertIn("running", observed)
            self.assertEqual(done["state"], "completed")

    def test_invoke_ai_creates_executor_trace_root_for_clean_data_root(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            fake = _write_executable(os.path.join(tmp, "codex"), f"""#!{sys.executable}
import json
import sys
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
if sys.argv[1:3] == ["login", "status"]:
    print("logged in")
    raise SystemExit(0)
out = sys.argv[sys.argv.index("--output-last-message") + 1]
open(out, "w").write('{{"summary":"","assistant_text":"","findings":[]}}')
print(json.dumps({{"type": "thread.started", "thread_id": "thread-trace-root"}}))
""")
            trace_parent = os.path.join(tmp, ".comma-review", "executor-traces")
            with self._store(tmp), mock.patch.dict(os.environ, {"PATH": tmp}, clear=False):
                self.assertFalse(os.path.exists(trace_parent))
                result = server._invoke_ai("codex", "prompt", timeout=2)
                self.assertEqual(result["returncode"], 0)
                self.assertTrue(os.path.isdir(trace_parent))
                self.assertTrue(result["trace_root"].startswith(trace_parent + os.sep))
                self.assertTrue(os.path.isfile(os.path.join(result["trace_root"], "receipt.json")))

    def test_timeout_marks_failed_with_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _write_executable(os.path.join(tmp, "fake-codex"), """#!/usr/bin/env python3
import sys, time
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
time.sleep(2)
""")
            metadata = {
                "run_id": "run-timeout",
                "trace_root": os.path.join(tmp, "trace-timeout"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            with self.assertRaises(review_executor.ProviderExecutionError) as ctx:
                review_executor.invoke_provider(
                    "codex", "prompt", timeout=0.1, schema=None,
                    executable=fake, cwd=tmp, metadata=metadata)
            receipt = ctx.exception.receipt
            self.assertEqual(receipt["status"], "failed")
            self.assertIn("timed out", receipt["error"])
            self.assertEqual(receipt["web_policy"]["mode"], "disabled")

    def test_cancel_terminates_process_group_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_file = os.path.join(tmp, "child.pid")
            fake = _write_executable(os.path.join(tmp, "fake-codex"), f"""#!/usr/bin/env python3
import subprocess, sys, time
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
open({child_pid_file!r}, "w").write(str(child.pid))
time.sleep(30)
""")
            executor = review_executor.ReviewExecutor(os.path.join(tmp, "traces"))
            metadata = {
                "run_id": "run-cancel",
                "trace_root": os.path.join(tmp, "trace-cancel"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            executor.submit(
                "run-cancel",
                lambda: review_executor.invoke_provider(
                    "codex", "prompt", timeout=30, schema=None,
                    executable=fake, cwd=tmp, metadata=metadata),
                metadata,
            )
            for _ in range(100):
                if os.path.exists(child_pid_file):
                    break
                time.sleep(0.02)
            self.assertTrue(os.path.exists(child_pid_file))
            with open(child_pid_file, encoding="utf-8") as handle:
                child_pid = int(handle.read())
            self.assertTrue(_alive(child_pid))
            executor.cancel("run-cancel")
            done = executor.wait("run-cancel", timeout=2)
            self.assertEqual(done["state"], "cancelled")
            for _ in range(50):
                if not _alive(child_pid):
                    break
                time.sleep(0.02)
            self.assertFalse(_alive(child_pid))

    def test_web_search_trace_is_hard_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _write_executable(os.path.join(tmp, "fake-codex"), """#!/usr/bin/env python3
import json, sys
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
out = sys.argv[sys.argv.index("--output-last-message") + 1]
open(out, "w").write('{"summary":"","assistant_text":"","findings":[]}')
print(json.dumps({"type": "response.web_search_call.completed"}))
""")
            metadata = {
                "run_id": "run-web",
                "trace_root": os.path.join(tmp, "trace-web"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            with self.assertRaises(review_executor.ProviderExecutionError) as ctx:
                review_executor.invoke_provider(
                    "codex", "prompt", timeout=2, schema=None,
                    executable=fake, cwd=tmp, metadata=metadata)
            self.assertEqual(ctx.exception.receipt["status"], "failed")
            self.assertTrue(ctx.exception.receipt["web_policy"]["web_search_used"])

    def test_codex_schema_is_passed_as_trace_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _write_executable(os.path.join(tmp, "fake-codex"), """#!/usr/bin/env python3
import json, os, sys
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
schema = sys.argv[sys.argv.index("--output-schema") + 1]
if schema.lstrip().startswith("{") or not os.path.isfile(schema):
    print(f"schema was not a file path: {schema}", file=sys.stderr)
    raise SystemExit(2)
with open(schema, encoding="utf-8") as handle:
    loaded = json.load(handle)
out = sys.argv[sys.argv.index("--output-last-message") + 1]
open(out, "w", encoding="utf-8").write(json.dumps({"schema_type": loaded["type"]}))
print(json.dumps({"type": "thread.started", "thread_id": "thread-schema-file"}))
""")
            metadata = {
                "run_id": "run-schema",
                "trace_root": os.path.join(tmp, "trace-schema"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            result = review_executor.invoke_provider(
                "codex", "prompt", timeout=2,
                schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                executable=fake, cwd=tmp, metadata=metadata)
            receipt = result["receipt"]
            self.assertEqual(receipt["status"], "completed")
            self.assertTrue(receipt["output_schema"]["path"].endswith("output_schema.json"))
            self.assertTrue(receipt["output_schema"]["sha256"].startswith("sha256:"))
            self.assertEqual(json.loads(result["output"])["schema_type"], "object")

    def test_receipt_contains_workbench_parity_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _write_executable(os.path.join(tmp, "fake-codex"), """#!/usr/bin/env python3
import json, sys
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
out = sys.argv[sys.argv.index("--output-last-message") + 1]
open(out, "w").write('{"summary":"","assistant_text":"","findings":[]}')
print(json.dumps({"type": "thread.started", "thread_id": "thread-test"}))
""")
            metadata = {
                "run_id": "run-receipt",
                "trace_root": os.path.join(tmp, "trace-receipt"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "academic-paper-review", "version": "1"},
                "profile": {"id": "primary", "rubric_version": "r1"},
                "skill": {"id": "test-skill", "path": __file__, "sha256": "sha256:skill"},
                "provider": {"tool": "codex"},
                "input_manifest": {"document": {"path": "paper.md", "revision": "sha256-doc"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            result = review_executor.invoke_provider(
                "codex", "prompt", timeout=2, schema=None,
                executable=fake, cwd=tmp, metadata=metadata)
            receipt = result["receipt"]
            for key in (
                "adapter", "profile", "skill", "provider", "input_manifest",
                "prompt_template_hash", "sandbox", "web_policy", "timing",
                "exit", "result", "trace", "recovery",
            ):
                self.assertIn(key, receipt)
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["sandbox"]["mode"], "read-only")
            self.assertFalse(receipt["web_policy"]["web_search_used"])
            self.assertTrue(receipt["result"]["sha256"].startswith("sha256:"))
            self.assertTrue(receipt["trace"]["events_sha256"].startswith("sha256:"))

    def test_startup_recovery_fails_stale_active_runs(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                for index, state in enumerate(("queued", "running", "cancelling"), 1):
                    run = {
                        "id": f"run-00000000000{index}",
                        "status": state,
                        "mode": "initial",
                        "input": {"document_rev": "sha256-doc", "comments_rev": "sha256-comments"},
                    }
                    session = {
                        "id": f"review-00000000000{index}",
                        "doc_path": "paper.md",
                        "status": state,
                        "run": run,
                        "findings": [],
                        "writeback_receipts": [],
                    }
                    server._save_session(session)
                report = server._fail_stale_running_reviews()
                self.assertEqual(report["runs_failed"], 3)
                for index, state in enumerate(("queued", "running", "cancelling"), 1):
                    session, run = server._load_review_run(f"run-00000000000{index}")
                    self.assertEqual(session["status"], "failed")
                    self.assertEqual(run["status"], "failed")
                    self.assertTrue(run["model_receipt"]["recovery"]["recovered"])
                    self.assertEqual(
                        run["model_receipt"]["recovery"]["reason"],
                        f"host_restart_from_{state}",
                    )


if __name__ == "__main__":
    unittest.main()

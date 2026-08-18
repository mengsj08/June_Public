#!/usr/bin/env python3
"""Single-instance server guard and queue recovery tests."""

import importlib.util
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


_HERE = Path(__file__).resolve().parent


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scan_mod = _load_module("scan_docs_single_instance", _HERE / "scan-docs.py")
server_instance = _load_module("kanban_server_instance_test", _HERE / "server_instance.py")


def _write_queue(root, entry):
    (root / "task.md").write_text("---\ntitle: task\n---\n", encoding="utf-8")
    queue = {"version": 1, "concurrency": 3, "entries": [entry]}
    (root / ".ai-queue.json").write_text(json.dumps(queue), encoding="utf-8")


def _read_queue(root):
    return json.loads((root / ".ai-queue.json").read_text(encoding="utf-8"))


def test_recover_queue_keeps_running_entry_when_pid_is_alive(tmp_path):
    _write_queue(tmp_path, {
        "id": "run-live",
        "path": "task.md",
        "status": "running",
        "pid": 12345,
        "started_at": "2026-07-09T12:00:00",
    })

    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod.server_instance, "process_matches_started_at", return_value=True), \
         patch.object(scan_mod, "_queue_consume_next", lambda: None):
        scan_mod._recover_queue()

    entry = _read_queue(tmp_path)["entries"][0]
    assert entry["status"] == "orphaned-running"
    assert entry["pid"] == 12345
    assert entry["recovery_state"] == "pid-still-running-output-detached"
    assert "输出管道已断" in entry["error"]


def test_recover_queue_marks_running_entry_lost_when_pid_is_dead(tmp_path):
    _write_queue(tmp_path, {
        "id": "run-dead",
        "path": "task.md",
        "status": "running",
        "pid": 54321,
        "started_at": "2026-07-09T12:00:00",
    })

    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod.server_instance, "process_matches_started_at", return_value=False), \
         patch.object(scan_mod, "_queue_consume_next", lambda: None):
        scan_mod._recover_queue()

    entry = _read_queue(tmp_path)["entries"][0]
    assert entry["status"] == "orphaned-unknown"
    assert entry["pid"] == 54321
    assert entry["recovery_state"] == "pid-exited-output-unknown"
    assert "最终结果未知" in entry["error"]


def test_process_started_at_rejects_reused_live_pid():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        started_at = server_instance.process_start_time(proc.pid)
        if not started_at:
            pytest.skip("ps did not expose process start time")
        assert server_instance.process_matches_started_at(proc.pid, started_at)
        assert not server_instance.process_matches_started_at(proc.pid, "2000-01-01T00:00:00")
    finally:
        _stop_proc(proc)


def test_force_restart_process_from_toolkit_cwd_is_reused_without_stale_takeover(
    tmp_path, capsys
):
    repo = tmp_path / "repo"
    toolkit = repo / "shared" / "toolkit" / "kanban"
    toolkit.mkdir(parents=True)
    (toolkit / "scan-docs.py").touch()
    logs = []

    with patch.object(server_instance, "process_exists", return_value=True), \
         patch.object(
             server_instance,
             "process_command",
             return_value="./.venv/bin/python scan-docs.py --serve --force-restart",
         ), \
         patch.object(server_instance, "process_cwd", return_value=toolkit), \
         patch.object(server_instance, "port_owner_pids", return_value=[12571]), \
         patch.object(server_instance, "port_accepts_connection", return_value=True):
        (repo / ".kanban-server.pid").write_text(
            json.dumps({"pid": 12571, "port": 8890}), encoding="utf-8"
        )
        existing = server_instance.detect_existing_instance(repo, 8890, logger=logs.append)

    assert existing == server_instance.ExistingInstance(
        pid=12571, port=8890, source="pidfile", port_owner_pids=[12571]
    )
    assert logs == []
    scan_existing = scan_mod.server_instance.ExistingInstance(
        pid=existing.pid,
        port=existing.port,
        source=existing.source,
        port_owner_pids=existing.port_owner_pids,
    )
    with patch.object(scan_mod, "REPO_ROOT", repo), \
         patch.object(scan_mod, "PORT", 8890), \
         patch.object(
             scan_mod.server_instance,
             "detect_existing_instance",
             return_value=scan_existing,
         ):
        assert scan_mod._prepare_single_instance_or_exit(force_restart=False) is False
    output = capsys.readouterr()
    assert "already running" in output.out
    assert "reusing it" in output.out
    assert "stale" not in output.out + output.err
    assert "taking over" not in output.out + output.err


@pytest.mark.parametrize("launch_cwd", ["repo", "toolkit", "outside"])
@pytest.mark.parametrize("force_restart", [False, True])
def test_pidfile_owner_is_fixed_to_repo_root_for_every_launch_shape(
    tmp_path, monkeypatch, launch_cwd, force_restart
):
    repo = tmp_path / "repo"
    toolkit = repo / "shared" / "toolkit" / "kanban"
    toolkit.mkdir(parents=True)
    cwd = {"repo": repo, "toolkit": toolkit, "outside": tmp_path}[launch_cwd]
    monkeypatch.chdir(cwd)

    # The flag must not influence pidfile placement; it is consumed before the
    # same server ownership lease is established.
    assert force_restart in (False, True)
    assert server_instance.ensure_pidfile_owner(repo, 39001)
    info = json.loads((repo / ".kanban-server.pid").read_text(encoding="utf-8"))
    assert info["pid"] == os.getpid()
    assert info["pgid"] == os.getpgid(os.getpid())
    assert info["port"] == 39001
    assert info["started_at"]
    assert not (cwd / ".kanban-server.pid").exists() or cwd == repo


def test_running_server_service_action_recreates_missing_pidfile(tmp_path):
    fake_server = object.__new__(scan_mod.ThreadedHTTPServer)
    fake_server.kanban_repo_root = tmp_path
    fake_server.kanban_port = 39002

    fake_server.service_actions()
    pidfile = tmp_path / ".kanban-server.pid"
    first = json.loads(pidfile.read_text(encoding="utf-8"))
    pidfile.unlink()

    fake_server.service_actions()
    repaired = json.loads(pidfile.read_text(encoding="utf-8"))
    assert repaired["pid"] == os.getpid() == first["pid"]
    assert repaired["port"] == 39002 == first["port"]


def test_force_restart_refuses_when_live_ai_run_exists(tmp_path):
    existing = scan_mod.server_instance.ExistingInstance(
        pid=111,
        port=39999,
        source="pidfile",
        port_owner_pids=[111],
    )

    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod, "PORT", 39999), \
         patch.object(scan_mod.server_instance, "detect_existing_instance", return_value=existing), \
         patch.object(scan_mod, "_active_live_running_queue_entries", return_value=[{"id": "run-live"}]):
        with pytest.raises(SystemExit) as exc:
            scan_mod._prepare_single_instance_or_exit(force_restart=True)

    assert exc.value.code == 2


def test_default_start_refuses_lost_port_orphan_process(tmp_path):
    existing = scan_mod.server_instance.ExistingInstance(
        pid=222,
        port=39998,
        source="process",
        port_owner_pids=[222],
    )

    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod, "PORT", 39998), \
         patch.object(scan_mod.server_instance, "detect_existing_instance", return_value=existing):
        with pytest.raises(SystemExit) as exc:
            scan_mod._prepare_single_instance_or_exit(force_restart=False)

    assert exc.value.code == 1


def test_default_start_refuses_unfingerprinted_port_listener(tmp_path):
    existing = scan_mod.server_instance.ExistingInstance(
        pid=None,
        port=39997,
        source="socket",
        port_owner_pids=[],
    )
    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod, "PORT", 39997), \
         patch.object(scan_mod.server_instance, "detect_existing_instance", return_value=existing), \
         patch.object(scan_mod.server_instance, "probe_product_instance", return_value=False):
        with pytest.raises(SystemExit) as exc:
            scan_mod._prepare_single_instance_or_exit(force_restart=False)
    assert exc.value.code == 1


def test_product_health_probe_accepts_only_exact_fingerprint():
    port = _free_port()

    class ProbeHandler(http.server.BaseHTTPRequestHandler):
        fingerprint = "project-canvas/health-v1"

        def do_GET(self):
            body = json.dumps({
                "product": "project-canvas",
                "fingerprint": self.fingerprint,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _fmt, *_args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), ProbeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        assert server_instance.probe_product_instance(port)
        ProbeHandler.fingerprint = "another-product/v1"
        assert not server_instance.probe_product_instance(port)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_terminate_process_group_clears_started_process():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        assert server_instance.process_exists(proc.pid)
        ok = server_instance.terminate_process_group(proc.pid, timeout_seconds=1, logger=lambda _msg: None)
        if not ok:
            pytest.skip("sandbox denied process-group signaling")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("sandbox denied localhost bind")
        return sock.getsockname()[1]


def _wait_for_port(port, *, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"port {port} did not become ready")


def _copy_temp_repo(tmp_path, port):
    repo = tmp_path / "repo"
    toolkit_src = _HERE
    toolkit_dst = repo / "kanban"
    shutil.copytree(
        toolkit_src,
        toolkit_dst,
        ignore=shutil.ignore_patterns(".venv", ".deps", "__pycache__", "test_*.py"),
    )
    project = repo / "project" / "个人调度"
    project.mkdir(parents=True)
    (project / "KAN-1_test.md").write_text(
        "---\ntitle: test\nstatus: todo\ntask_id: KAN-1\n---\n\nbody\n",
        encoding="utf-8",
    )
    (repo / ".kanban.scan-allowlist.json").write_text(
        json.dumps({"scan_dirs": ["project"]}),
        encoding="utf-8",
    )
    (repo / ".kanban.config.json").write_text(
        json.dumps({
            "port": port,
            "scan_dirs": ["project"],
            "members": ["Owner"],
            "auth": {"local_bypass": True, "bypass_user": "Owner"},
            "git_sync": {"enabled": False},
            "claude_sync": {"enabled": False},
            "team_sync": {"enabled": False},
        }),
        encoding="utf-8",
    )
    return repo


def _start_temp_server(repo, port, *extra_args):
    env = dict(os.environ)
    env.update({
        "KANBAN_REPO_ROOT": str(repo),
        "KANBAN_CONFIG": str(repo / ".kanban.config.json"),
        "PYTHONUNBUFFERED": "1",
    })
    proc = subprocess.Popen(
        [
            sys.executable,
            str(repo / "kanban" / "scan-docs.py"),
            "--serve",
            "--port",
            str(port),
            *extra_args,
        ],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _wait_for_port(port)
        if "--force-restart" in extra_args:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    info = json.loads((repo / ".kanban-server.pid").read_text(encoding="utf-8"))
                except (FileNotFoundError, json.JSONDecodeError):
                    info = {}
                if info.get("pid") == proc.pid:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
    except AssertionError:
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise AssertionError(
            f"port {port} did not become ready; returncode={proc.poll()}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )
    return proc


def _stop_proc(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_second_start_reuses_existing_server_and_preserves_running_queue(tmp_path):
    port = _free_port()
    repo = _copy_temp_repo(tmp_path, port)
    first = _start_temp_server(repo, port)
    try:
        (repo / ".ai-queue.json").write_text(
            json.dumps({
                "version": 1,
                "concurrency": 3,
                "entries": [{
                    "id": "sim-running",
                    "path": "project/个人调度/KAN-1_test.md",
                    "status": "running",
                    "pid": first.pid,
                    "started_at": "2026-07-09T12:00:00",
                }],
            }),
            encoding="utf-8",
        )
        second = subprocess.run(
            [
                sys.executable,
                str(repo / "kanban" / "scan-docs.py"),
                "--serve",
                "--port",
                str(port),
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        queue = json.loads((repo / ".ai-queue.json").read_text(encoding="utf-8"))
        assert second.returncode == 0
        assert "reusing it" in second.stdout
        assert first.poll() is None
        assert queue["entries"][0]["status"] == "running"
    finally:
        _stop_proc(first)


def test_start_overwrites_stale_pidfile_pointing_to_live_non_server_process(tmp_path):
    port = _free_port()
    repo = _copy_temp_repo(tmp_path, port)
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    server = None
    try:
        (repo / ".kanban-server.pid").write_text(
            json.dumps({
                "pid": sleeper.pid,
                "pgid": sleeper.pid,
                "port": port,
                "started_at": "2026-07-09T18:06:03",
            }),
            encoding="utf-8",
        )
        server = _start_temp_server(repo, port)
        info = json.loads((repo / ".kanban-server.pid").read_text(encoding="utf-8"))
        assert info["pid"] == server.pid
        assert info["port"] == port
        assert sleeper.poll() is None
    finally:
        if server is not None:
            _stop_proc(server)
        _stop_proc(sleeper)


def test_force_restart_replaces_old_temp_server(tmp_path):
    port = _free_port()
    repo = _copy_temp_repo(tmp_path, port)
    first = _start_temp_server(repo, port)
    second = None
    try:
        second = _start_temp_server(repo, port, "--force-restart")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and first.poll() is None:
            time.sleep(0.1)
        assert first.poll() is not None
        assert second.poll() is None
        info = json.loads((repo / ".kanban-server.pid").read_text(encoding="utf-8"))
        assert info["pid"] == second.pid
    finally:
        _stop_proc(first)
        if second is not None:
            _stop_proc(second)

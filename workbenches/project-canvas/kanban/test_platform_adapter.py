#!/usr/bin/env python3
"""Cross-platform contracts for the thin OS adapter."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "platform_adapter_under_test",
    _HERE / "platform_adapter.py",
)
adapter_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter_mod)


def test_linux_open_path_uses_xdg_open():
    adapter = adapter_mod.get_platform_adapter("linux")

    with patch.object(adapter_mod.shutil, "which", return_value="/usr/bin/xdg-open"), \
         patch.object(adapter_mod.subprocess, "Popen") as popen:
        ok, error = adapter.open_path(Path("/tmp/report.md"))

    assert ok is True
    assert error == ""
    popen.assert_called_once_with(["/usr/bin/xdg-open", "/tmp/report.md"])


def test_linux_launches_configured_command_as_detached_child(tmp_path):
    adapter = adapter_mod.get_platform_adapter("linux")

    with patch.object(adapter_mod.subprocess, "Popen") as popen:
        ok, error = adapter.launch_command("npm run dev", tmp_path)

    assert ok is True
    assert error == ""
    popen.assert_called_once_with(
        "npm run dev",
        cwd=str(tmp_path),
        shell=True,
        start_new_session=True,
        stdin=adapter_mod.subprocess.DEVNULL,
        stdout=adapter_mod.subprocess.DEVNULL,
        stderr=adapter_mod.subprocess.DEVNULL,
    )


def test_linux_missing_xdg_open_degrades_and_logs_only_once():
    logs = []
    adapter = adapter_mod.get_platform_adapter("linux", logger=logs.append)

    with patch.object(adapter_mod.shutil, "which", return_value=None):
        first = adapter.open_path("/tmp/a.md")
        second = adapter.open_path("/tmp/b.md")

    assert first == (False, "xdg-open 不存在；桌面打开已禁用")
    assert second == first
    assert logs == ["xdg-open 不存在；桌面打开已禁用"]


def test_linux_marks_app_bundle_and_system_proxy_as_darwin_only():
    adapter = adapter_mod.get_platform_adapter("linux", logger=lambda _message: None)

    assert adapter.capabilities()["app_bundle_control"] is False
    assert adapter.capabilities()["system_proxy"] is False
    assert adapter.open_app_bundle("example.bundle")["ok"] is False
    assert adapter.system_proxy_output()[0] is False


def test_darwin_open_path_preserves_usr_bin_open_behavior():
    adapter = adapter_mod.get_platform_adapter("darwin")

    with patch.object(adapter_mod.Path, "is_file", return_value=True), \
         patch.object(adapter_mod.subprocess, "Popen") as popen:
        ok, error = adapter.open_path("/tmp/report.md")

    assert ok is True
    assert error == ""
    popen.assert_called_once_with(["/usr/bin/open", "/tmp/report.md"])


def test_darwin_terminal_launch_preserves_terminal_bridge(tmp_path):
    adapter = adapter_mod.get_platform_adapter("darwin")
    process = Mock(returncode=0)

    with patch.object(adapter_mod.Path, "is_file", return_value=True), \
         patch.object(adapter_mod.subprocess, "Popen", return_value=process) as popen:
        ok, error = adapter.launch_command("npm run dev", tmp_path)

    assert ok is True
    assert error == ""
    popen.assert_called_once_with(
        ["/usr/bin/osascript"],
        stdin=adapter_mod.subprocess.PIPE,
        text=True,
    )
    script = process.communicate.call_args.args[0]
    assert 'tell application "Terminal"' in script
    assert f"cd {tmp_path}" in script
    assert "npm run dev" in script

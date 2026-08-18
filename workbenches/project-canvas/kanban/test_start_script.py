#!/usr/bin/env python3
"""Static portability contracts for the public one-command launcher."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
START = ROOT / "start.sh"


def test_start_script_is_valid_bash():
    completed = subprocess.run(
        ["bash", "-n", str(START)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr


def test_start_script_has_linux_opener_and_platform_install_hints():
    source = START.read_text(encoding="utf-8")

    assert "xdg-open" in source
    assert "python3-venv" in source
    assert "Native Windows is not supported. Use WSL" in source
    assert "MINGW*|MSYS*|CYGWIN*" in source
    assert "brew" not in source.lower()
    assert "for command_name in python3 node npm" in source


def test_start_script_reuses_only_verified_product_fingerprint():
    source = START.read_text(encoding="utf-8")

    assert '"/api/health"' in source
    assert "project-canvas/health-v1" in source
    assert 'PORT_STATE="$(probe_port_state)"' in source
    assert "Port $PORT is occupied by another service" in source

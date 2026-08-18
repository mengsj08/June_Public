#!/usr/bin/env python3
"""Thin, opt-in adapter from the kanban panel to an external net-doctor.sh.

The shell script remains the diagnostic and repair source of truth.  This module
only selects one of three fixed actions, enforces confirmation for mutations,
and extracts the script's single safe JSON receipt line.  Request data can never
select a script path or append shell arguments.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path


PANEL_MARKER = "@@NET_DOCTOR_JSON@@"
ACTION_ARGS = {
    "diagnose": (),
    "fix": ("--fix",),
    "emergency": ("--emergency",),
}
ACTION_TIMEOUTS = {
    "diagnose": 90,
    "fix": 300,
    "emergency": 300,
}
_RUN_LOCK = threading.Lock()


def _configured_script(config=None):
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return None, "网络医生未启用"
    raw = str(config.get("script") or "").strip()
    if not raw:
        return None, "网络医生脚本未配置"
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve(strict=False)
    if resolved.name != "net-doctor.sh":
        return None, "网络医生只允许使用 net-doctor.sh"
    if not resolved.is_file():
        return None, f"未找到网络医生脚本: {resolved}"
    return resolved, ""


def availability(config=None):
    script, error = _configured_script(config)
    return {
        "available": script is not None,
        "script_name": script.name if script else "net-doctor.sh",
        "error": error,
    }


def parse_panel_receipt(output):
    for line in reversed(str(output or "").splitlines()):
        if not line.startswith(PANEL_MARKER):
            continue
        try:
            payload = json.loads(line[len(PANEL_MARKER):])
        except json.JSONDecodeError:
            return None, "网络医生回执不是有效 JSON"
        if not isinstance(payload, dict) or payload.get("schema") != "net-doctor/panel-v2":
            return None, "网络医生回执 schema 不匹配"
        return payload, ""
    return None, "网络医生没有返回结构化回执"


def run(action, *, confirmed=False, config=None):
    action = str(action or "").strip()
    if action not in ACTION_ARGS:
        return {"ok": False, "error": "invalid network doctor action"}, 400
    if action != "diagnose" and confirmed is not True:
        return {"ok": False, "error": "修复网络前需要在面板确认"}, 409

    script, error = _configured_script(config)
    if not script:
        return {"ok": False, "error": error}, 503
    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "网络医生正在运行"}, 409

    command = ["/bin/bash", str(script), "--panel-json", *ACTION_ARGS[action]]
    try:
        try:
            env = os.environ.copy()
            if action != "diagnose":
                env["NET_DOCTOR_CONFIRMED"] = "1"
            completed = subprocess.run(
                command,
                cwd=str(script.parent),
                capture_output=True,
                text=True,
                timeout=ACTION_TIMEOUTS[action],
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "网络医生运行超时", "action": action}, 504
        except OSError as exc:
            return {
                "ok": False,
                "error": f"网络医生无法启动: {type(exc).__name__}",
                "action": action,
            }, 500

        receipt, parse_error = parse_panel_receipt(completed.stdout)
        if not receipt:
            return {
                "ok": False,
                "error": parse_error,
                "action": action,
                "exit_code": completed.returncode,
            }, 502
        return {
            "ok": True,
            "schema": "kanban.network-doctor-result/v1",
            "action": action,
            "exit_code": completed.returncode,
            "diagnosis": receipt,
        }, 200
    finally:
        _RUN_LOCK.release()

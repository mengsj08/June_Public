#!/usr/bin/env python3
"""Tests for the fixed-action network doctor adapter."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "network_doctor_panel",
    _HERE / "network_doctor_panel.py",
)
network_doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(network_doctor)


def _receipt(**overrides):
    payload = {
        "schema": "net-doctor/panel-v2",
        "version": "3.0",
        "health": "good",
        "conclusion": "网络状态正常",
        "failures": 0,
        "warnings": 0,
        "providers": {"total": 0, "healthy": 0},
    }
    payload.update(overrides)
    return network_doctor.PANEL_MARKER + json.dumps(payload, ensure_ascii=False)


def test_parse_panel_receipt_ignores_human_log_and_reads_last_marker():
    payload, error = network_doctor.parse_panel_receipt(
        "PASS current node\n公网 IPv4: should-not-be-parsed\n" + _receipt()
    )

    assert error == ""
    assert payload["schema"] == "net-doctor/panel-v2"
    assert payload["health"] == "good"
    assert payload["providers"] == {"total": 0, "healthy": 0}


def test_invalid_action_and_unconfirmed_mutation_never_start_subprocess():
    with patch.object(network_doctor.subprocess, "run") as run:
        invalid, invalid_status = network_doctor.run("shell; rm -rf /")
        unconfirmed, unconfirmed_status = network_doctor.run("fix")

    assert invalid_status == 400
    assert invalid["ok"] is False
    assert unconfirmed_status == 409
    assert "确认" in unconfirmed["error"]
    run.assert_not_called()


def test_diagnose_uses_fixed_script_and_fixed_arguments():
    script = Path("/tmp/net-doctor.sh")
    completed = type(
        "Completed",
        (),
        {"stdout": _receipt(), "stderr": "", "returncode": 0},
    )()

    with patch.object(network_doctor, "_configured_script", return_value=(script, "")), \
         patch.object(network_doctor.subprocess, "run", return_value=completed) as run:
        result, status = network_doctor.run("diagnose")

    assert status == 200
    assert result["ok"] is True
    assert result["diagnosis"]["conclusion"] == "网络状态正常"
    assert run.call_args.args[0] == ["/bin/bash", "/tmp/net-doctor.sh", "--panel-json"]
    assert run.call_args.kwargs["cwd"] == "/tmp"
    assert run.call_args.kwargs["timeout"] == 90
    assert "NET_DOCTOR_CONFIRMED" not in run.call_args.kwargs["env"]


def test_confirmed_emergency_maps_to_only_allowlisted_flag():
    script = Path("/tmp/net-doctor.sh")
    completed = type(
        "Completed",
        (),
        {"stdout": _receipt(health="warn", warnings=1), "stderr": "", "returncode": 0},
    )()

    with patch.object(network_doctor, "_configured_script", return_value=(script, "")), \
         patch.object(network_doctor.subprocess, "run", return_value=completed) as run:
        result, status = network_doctor.run("emergency", confirmed=True)

    assert status == 200
    assert result["diagnosis"]["health"] == "warn"
    assert run.call_args.args[0] == [
        "/bin/bash", "/tmp/net-doctor.sh", "--panel-json", "--emergency",
    ]
    assert run.call_args.kwargs["env"]["NET_DOCTOR_CONFIRMED"] == "1"

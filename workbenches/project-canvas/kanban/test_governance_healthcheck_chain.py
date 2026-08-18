#!/usr/bin/env python3
"""Contract tests for the narrow governance healthcheck runner."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest


_MODULE = Path(__file__).resolve().parents[1] / 'governance' / 'run_governance_healthcheck_chain.py'
if not _MODULE.is_file():
    pytest.skip("missing optional source path: governance/run_governance_healthcheck_chain.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location('run_governance_healthcheck_chain', _MODULE)
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)


def test_command_contract_has_one_scan_and_no_hidden_mutation_flags(tmp_path):
    args = SimpleNamespace(
        root=str(tmp_path), status_out=str(tmp_path / 'status.md'),
        probe_json=str(tmp_path / 'probe.json'), json_out=str(tmp_path / 'previous.json'),
        card_result_out=str(tmp_path / 'card.json'),
        card_endpoint='http://127.0.0.1:8890/api/governance/result-card', card_mode='auto',
    )

    specs = runner.command_specs(args)
    flattened = [' '.join(command) for _, command, _ in specs]

    assert sum('scan_governance.py' in command for command in flattened) == 1
    forbidden = ('--backfill', '--infer-responsibility', '--sweep-auto-accept', '--detect-compression')
    assert not any(flag in command for command in flattened for flag in forbidden)
    assert any('--lint-naming --json' in command for command in flattened)
    assert any('--lint-ownership --json' in command for command in flattened)
    assert any('--card-mode auto' in command for command in flattened)

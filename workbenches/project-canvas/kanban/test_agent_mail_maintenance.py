#!/usr/bin/env python3
"""Tests for the agent-mail 基建维护台账 reader (治理页底部维护面板数据源, KAN-998)。"""

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_amm_spec = importlib.util.spec_from_file_location('agent_mail_maintenance', _HERE / 'agent_mail_maintenance.py')
amm = importlib.util.module_from_spec(_amm_spec)
_amm_spec.loader.exec_module(amm)


def _seed_home(tmp_path, *, events, registry, inbox, runs):
    home = tmp_path / '.agent-mail'
    home.mkdir()
    if events is not None:
        (home / 'maintenance.jsonl').write_text(
            '\n'.join(events) + '\n', encoding='utf-8'
        )
    if registry is not None:
        (home / 'registry.json').write_text(json.dumps(registry, ensure_ascii=False), encoding='utf-8')
    inbox_dir = home / 'inbox'
    inbox_dir.mkdir()
    for sid, json_files in inbox.items():
        sid_dir = inbox_dir / sid
        sid_dir.mkdir()
        for i in range(json_files):
            (sid_dir / f'{i}.json').write_text('{}', encoding='utf-8')
    runs_dir = home / 'archive-map-watcher' / 'runs'
    runs_dir.mkdir(parents=True)
    for name in runs:
        (runs_dir / name).write_text('log', encoding='utf-8')
    return home


def test_overview_counts_events_dead_letters_and_runs(tmp_path):
    home = _seed_home(
        tmp_path,
        events=[
            json.dumps({'ts': '2026-07-11T03:31:49+08:00', 'action': 'dead-letter', 'sid': 'orphan-a', 'msgs': 3, 'reason': 'x'}),
            json.dumps({'ts': '2026-07-11T03:32:49+08:00', 'action': 'compact-run-logs', 'reason': 'y'}),
        ],
        registry={'known-sid': {}},
        # orphan-a not in registry with 2 json => dead letters; known-sid in registry ignored.
        inbox={'orphan-a': 2, 'known-sid': 5, 'orphan-empty': 0},
        runs=['a.log', 'b.log.gz', '.hidden'],
    )
    overview = amm.load_maintenance_overview(home=str(home))
    assert overview['ok'] is True
    assert overview['home_exists'] is True
    assert overview['event_total'] == 2
    # Newest first (reversed insertion order).
    assert overview['events'][0]['action'] == 'compact-run-logs'
    assert overview['dead_letters'] == 2  # only orphan-a's 2 json count; known-sid excluded
    assert overview['orphan_dirs'] == 2   # orphan-a + orphan-empty
    assert overview['watcher_runs'] == 2  # .hidden excluded
    assert overview['registry_ok'] is True


def test_missing_home_degrades_gracefully():
    overview = amm.load_maintenance_overview(home='/nonexistent/path/xyz-agent-mail')
    assert overview['ok'] is True
    assert overview['home_exists'] is False
    assert overview['events'] == []
    assert overview['event_total'] == 0
    assert overview['dead_letters'] == 0
    assert overview['watcher_runs'] == 0


def test_unconfigured_home_is_disabled_without_reading_user_home():
    overview = amm.load_maintenance_overview()
    assert overview['ok'] is True
    assert overview['enabled'] is False
    assert overview['home_exists'] is False
    assert overview['events'] == []


def test_empty_and_malformed_maintenance_lines_are_skipped(tmp_path):
    home = _seed_home(
        tmp_path,
        events=['not json at all', '', json.dumps({'ts': '2026-07-11T01:00:00+08:00', 'action': 'ok'}), '   '],
        registry={},
        inbox={},
        runs=[],
    )
    overview = amm.load_maintenance_overview(home=str(home))
    assert overview['ok'] is True
    assert overview['event_total'] == 1
    assert overview['events'][0]['action'] == 'ok'


def test_limit_caps_returned_events_but_not_total(tmp_path):
    events = [json.dumps({'ts': f'2026-07-11T0{i}:00:00+08:00', 'action': f'ev{i}'}) for i in range(1, 6)]
    home = _seed_home(tmp_path, events=events, registry={}, inbox={}, runs=[])
    overview = amm.load_maintenance_overview(home=str(home), limit=2)
    assert overview['event_total'] == 5
    assert len(overview['events']) == 2
    # newest first
    assert overview['events'][0]['action'] == 'ev5'


def test_missing_registry_treats_all_inbox_dirs_as_orphans(tmp_path):
    home = _seed_home(tmp_path, events=[], registry=None, inbox={'a': 1, 'b': 2}, runs=[])
    overview = amm.load_maintenance_overview(home=str(home))
    assert overview['registry_ok'] is False
    assert overview['dead_letters'] == 3
    assert overview['orphan_dirs'] == 2


def test_reason_field_is_truncated(tmp_path):
    long_reason = 'x' * 900
    home = _seed_home(
        tmp_path,
        events=[json.dumps({'ts': '2026-07-11T01:00:00+08:00', 'action': 'ok', 'reason': long_reason})],
        registry={},
        inbox={},
        runs=[],
    )
    overview = amm.load_maintenance_overview(home=str(home))
    assert len(overview['events'][0]['reason']) <= 401


def _load_scan_docs():
    spec = importlib.util.spec_from_file_location('scan_docs_amm_test', _HERE / 'scan-docs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_docs_wrapper_and_endpoint_registered():
    scan = _load_scan_docs()
    # Wrapper exists and delegates to the module (always ok=True on real home).
    result = scan.load_agent_mail_maintenance()
    assert isinstance(result, dict)
    assert 'ok' in result
    # Thin GET forwarder is registered in the central route table.
    source = (_HERE / 'scan-docs.py').read_text(encoding='utf-8')
    assert "('GET', '/api/governance/maintenance'): '_route_get_api_governance_maintenance'" in source
    assert 'self._json(load_agent_mail_maintenance())' in source

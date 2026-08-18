#!/usr/bin/env python3
"""Tests for the KM chain data bridge (链路视图 v2 的 knowledge-layers-state.json 数据源)."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _ResponseCapture:
    def __init__(self):
        self.status_code = None
        self.headers = {}
        self.body = None

    @property
    def json(self):
        return json.loads(self.body.decode('utf-8')) if self.body else None


def _make_handler(path):
    response = _ResponseCapture()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Host': 'localhost', 'Content-Length': '0'}
            self.rfile = io.BytesIO(b'')

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            response.headers[key] = value

        def end_headers(self):
            pass

        def _json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            response.status_code = code
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Length'] = str(len(body))
            response.body = body

        def send_error(self, code, message=None):
            response.status_code = code
            response.body = json.dumps({'ok': False, 'error': message or 'Not Found'}).encode('utf-8')

    return TestHandler(), response


def _valid_payload():
    return {
        'generated_at': '2026-06-10T22:08:16+08:00',
        'ok': True,
        'summary': '2 markdown · 1 paper cards',
        'sources': [{'name': 'knowledge_system', 'as_of': '2026-06-10T22:00:00+08:00'}],
        'dashboard_path': '/tmp/dash.html',
        'kpis': [{'label': 'Zotero 快照', 'value': '21.8 天', 'state': 'warn'}],
        'stages': {
            'km/source_intake': {'summary': '2 files · 0 signals', 'state': 'ok'},
            'km/zotero_master': {'summary': '5679 文献 · 快照 21.8d', 'state': 'warn'},
            'km/triage_queue': {'summary': 'queue 114', 'state': 'ok'},
            'km/card_reading': {'summary': 'paper cards 1', 'state': 'ok'},
            'km/evidence': {'summary': 'evidence rows 1', 'state': 'ok'},
            'km/synthesis': {'summary': 'indexes 1', 'state': 'ok'},
            'km/ops': {'summary': 'scripts 1', 'state': 'ok'},
        },
        'distributions': [
            {'title': 'Paper card tiers', 'rows': [{'label': 'T1', 'value': 11}]},
        ],
    }


def test_loads_valid_chain_data(tmp_path):
    path = tmp_path / 'chain-km.json'
    path.write_text(json.dumps(_valid_payload(), ensure_ascii=False), encoding='utf-8')

    result = scan_mod.load_km_chain_data({'km_chain_data': str(path)})

    assert result['ok'] is True
    assert result['schema_version'] == 'skill-state/v1'
    assert result['health']['summary'] == '2 markdown · 1 paper cards'
    assert result['stage_map']['km/zotero_master']['state'] == 'warn'
    assert result['stages']['km/zotero_master']['state'] == 'warn'
    assert result['kpis'][0]['label'] == 'Zotero 快照'
    assert result['sources'][0]['as_of']


def test_loads_skill_state_stage_array(tmp_path):
    payload = _valid_payload()
    payload['stages'] = [
        {'key': 'km/source_intake', 'summary': '2 files · 0 signals', 'state': 'ok'},
        {'key': 'km/zotero_master', 'summary': '5679 文献 · 快照 21.8d', 'state': 'warn'},
    ]
    payload['schema_version'] = 'skill-state/v1'
    payload['invocations'] = [{'id': 'refresh', 'label': '刷新', 'mechanism': 'cli'}]
    payload['needs_decision'] = [{'id': 'gate', 'question': '是否自动化？'}]
    path = tmp_path / 'chain-km.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    result = scan_mod.load_km_chain_data({'km_chain_data': str(path)})

    assert result['ok'] is True
    assert result['schema_version'] == 'skill-state/v1'
    assert result['stage_map']['km/zotero_master']['state'] == 'warn'
    assert len(result['stage_list']) == 2
    assert result['invocations'][0]['id'] == 'refresh'
    assert result['needs_decision'][0]['id'] == 'gate'


def test_configured_chains_preserve_stage_responsibility(tmp_path):
    state_path = tmp_path / 'custom-state.json'
    state_path.write_text(json.dumps(_valid_payload(), ensure_ascii=False), encoding='utf-8')
    config = {
        'chains': [
            {
                'key': 'custom',
                'title': 'Custom Chain',
                'provider': '',
                'state_path': str(state_path),
                'stages': [
                    {'key': 'custom/ai', 'title': 'AI Work', 'responsibility': 'ai-owned', 'kw': ['ai']},
                    {'key': 'custom/pi', 'title': 'PI Gate', 'responsibility': 'pi-gated', 'kw': ['gate']},
                    {'key': 'custom/shared', 'title': 'Shared', 'responsibility': 'shared'},
                ],
            }
        ],
    }

    chains = scan_mod.configured_chains(config)
    result = scan_mod.load_chain_data('custom', config)

    assert chains[0]['title'] == 'Custom Chain'
    assert [stage['responsibility'] for stage in chains[0]['stages']] == ['ai-owned', 'pi-gated', 'shared']
    assert result['ok'] is True
    assert result['chain']['stages'][1]['responsibility'] == 'pi-gated'


def test_api_chains_id_and_km_compatibility(tmp_path):
    state_path = tmp_path / 'chain-state.json'
    state_path.write_text(json.dumps(_valid_payload(), ensure_ascii=False), encoding='utf-8')
    config = {
        'chains': [
            {
                'key': 'custom',
                'title': 'Custom Chain',
                'provider': '',
                'state_path': str(state_path),
                'stages': [{'key': 'custom/ai', 'title': 'AI Work', 'responsibility': 'ai-owned'}],
            },
            {
                'key': 'km',
                'title': '知识管理链',
                'provider': '',
                'state_path': str(state_path),
                'stages': [{'key': 'km/source_intake', 'title': '0. 外部情报入口', 'responsibility': 'ai-owned'}],
            },
        ],
    }

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
            patch.object(scan_mod, 'load_config', return_value=config):
        custom_handler, custom_resp = _make_handler('/api/chains/custom')
        custom_handler.do_GET()
        km_handler, km_resp = _make_handler('/api/chains/km')
        km_handler.do_GET()

    assert custom_resp.status_code == 200
    assert custom_resp.json['ok'] is True
    assert custom_resp.json['chain']['key'] == 'custom'
    assert custom_resp.json['chain']['stages'][0]['responsibility'] == 'ai-owned'
    assert km_resp.status_code == 200
    assert km_resp.json['ok'] is True
    assert km_resp.json['chain']['key'] == 'km'


def test_missing_chain_state_returns_chain_for_frontend_degrade(tmp_path):
    config = {
        'chains': [
            {
                'key': 'custom',
                'title': 'Custom Chain',
                'provider': '',
                'state_path': str(tmp_path / 'absent.json'),
                'stages': [{'key': 'custom/ai', 'title': 'AI Work', 'responsibility': 'ai-owned'}],
            },
        ],
    }

    result = scan_mod.load_chain_data('custom', config)

    assert result['ok'] is False
    assert result['chain']['key'] == 'custom'
    assert result['chain']['stages'][0]['responsibility'] == 'ai-owned'


def test_missing_file_degrades(tmp_path):
    result = scan_mod.load_km_chain_data({'km_chain_data': str(tmp_path / 'absent.json')})
    assert result['ok'] is False


def test_invalid_json_and_missing_stages_degrade(tmp_path):
    broken = tmp_path / 'broken.json'
    broken.write_text('{oops', encoding='utf-8')
    assert scan_mod.load_km_chain_data({'km_chain_data': str(broken)})['ok'] is False

    no_stages = tmp_path / 'no_stages.json'
    no_stages.write_text(json.dumps({'kpis': []}), encoding='utf-8')
    assert scan_mod.load_km_chain_data({'km_chain_data': str(no_stages)})['ok'] is False


def test_km_chain_data_key_denied_in_user_config():
    assert scan_mod._is_denied_user_config_key('km_chain_data') is True


def test_seed_file_matches_convention_when_present():
    result = scan_mod.load_km_chain_data({})
    if not result['ok']:
        return  # seed 文件不在本机时跳过（约定上由 RKO build 脚本生成）
    assert set(result['stages']) >= {
        'km/source_intake', 'km/zotero_master', 'km/triage_queue',
        'km/card_reading', 'km/evidence', 'km/synthesis', 'km/ops',
    }
    for stage in result['stages'].values():
        assert 'summary' in stage
    for source in result.get('sources', []):
        assert 'as_of' in source
    for kpi in result.get('kpis', []):
        assert kpi.get('state') in ('ok', 'warn')
    for group in result.get('distributions', []):
        assert group.get('title') and isinstance(group.get('rows'), list)

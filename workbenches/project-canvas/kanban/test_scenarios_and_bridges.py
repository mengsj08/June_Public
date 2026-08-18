#!/usr/bin/env python3
"""Tests for local bridge status endpoints."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class ResponseCapture:
    def __init__(self):
        self.status_code = None
        self.headers = {}
        self.body = None

    @property
    def json(self):
        return json.loads(self.body.decode('utf-8')) if self.body else None


def make_handler(path):
    response = ResponseCapture()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {}

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


def test_api_bridges_status_hides_unconfigured_local_integrations():
    handler, resp = make_handler('/api/bridges/status')

    def fake_port_open(port):
        return int(port) == 3000

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
            patch.object(scan_mod, '_is_local_port_open', side_effect=fake_port_open), \
            patch.object(scan_mod, '_read_skill_board_url', return_value='http://127.0.0.1:8766/'):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json == {}
    assert all(isinstance(value, bool) for value in resp.json.values())


def test_api_bridges_status_returns_only_configured_existing_targets(tmp_path):
    local_tool = tmp_path / 'scenario-library'
    local_tool.mkdir()
    config = {
        'paths': {'workspace_root': str(tmp_path), 'data_root': str(tmp_path)},
        'open_allowed_roots': [str(tmp_path)],
        'integrations': {
            'local_tools': {
                'scenario-library': {
                    'enabled': True,
                    'name': 'Scenario Library',
                    'cwd': str(local_tool),
                    'command': 'npm run dev',
                    'url': 'http://localhost:3000/',
                    'port': 3000,
                },
            },
        },
    }
    with patch.object(scan_mod, 'load_config', return_value=config), \
            patch.object(scan_mod, '_is_local_port_open', return_value=True):
        assert scan_mod.get_bridge_status() == {'scenario-library': True}

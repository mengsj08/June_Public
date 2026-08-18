#!/usr/bin/env python3
"""HTTP contract tests for the network doctor panel endpoint."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_network_doctor', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _make_handler(payload):
    response = type('Resp', (), {'status_code': None, 'json': None})()
    raw = json.dumps(payload).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = '/api/network/doctor'
            self.headers = {
                'Host': 'localhost',
                'Content-Length': str(len(raw)),
            }
            self.rfile = io.BytesIO(raw)

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

        def _json(self, data, code=200):
            response.status_code = code
            response.json = data

        def send_error(self, code, message=None):
            response.status_code = code
            response.json = {'ok': False, 'error': message or 'Not Found'}

    return TestHandler(), response


def test_diagnose_endpoint_forwards_only_action_and_false_confirmation():
    handler, resp = _make_handler({'action': 'diagnose', 'script': '/tmp/evil.sh'})
    result = {'ok': True, 'diagnosis': {'health': 'good'}}

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'run_network_doctor_action', return_value=(result, 200)) as run:
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    run.assert_called_once_with('diagnose', confirmed=False)


def test_fix_endpoint_forwards_explicit_boolean_confirmation():
    handler, resp = _make_handler({'action': 'fix', 'confirmed': True})
    result = {'ok': True, 'diagnosis': {'health': 'good', 'fixed': 1}}

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'run_network_doctor_action', return_value=(result, 200)) as run:
        handler.do_POST()

    assert resp.status_code == 200
    run.assert_called_once_with('fix', confirmed=True)

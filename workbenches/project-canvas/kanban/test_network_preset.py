#!/usr/bin/env python3
"""Tests for local network preset actions."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _make_handler(path, payload):
    response = type('Resp', (), {'status_code': None, 'json': None})()
    raw = json.dumps(payload).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Content-Length': str(len(raw))}
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


def test_network_preset_rejects_invalid_name():
    handler, resp = _make_handler('/api/network/preset', {'preset': 'shell'})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}):
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json == {'ok': False, 'error': 'invalid preset'}


def test_network_preset_no_longer_exposes_clash_global():
    handler, resp = _make_handler('/api/network/preset', {'preset': 'clash_global'})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod.subprocess, 'Popen') as popen:
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json == {'ok': False, 'error': 'invalid preset'}
    popen.assert_not_called()


def test_legacy_tag_network_preset_aliases_to_verge_without_request_path():
    handler, resp = _make_handler(
        '/api/network/preset',
        {
            'preset': 'tag_tun_global',
            'confirmed': True,
            'bundle_id': 'bad.bundle',
            'app_path': '/tmp/request-injected.app',
        },
    )
    doctor_result = {
        'ok': True,
        'action': 'fix',
        'diagnosis': {'conclusion': '网络状态正常'},
    }

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(
             scan_mod,
             'run_network_doctor_action',
             return_value=(doctor_result, 200),
         ) as doctor:
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['preset'] == 'verge_tun_global'
    assert resp.json['preset_alias'] == 'tag_tun_global'
    assert resp.json['message'] == '网络状态正常'
    doctor.assert_called_once_with('fix', confirmed=True)


def test_verge_network_preset_requires_confirmation_before_mutation():
    handler, resp = _make_handler('/api/network/preset', {'preset': 'verge_tun_global'})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(
             scan_mod,
             'run_network_doctor_action',
             return_value=({'ok': False, 'error': '修复网络前需要在面板确认'}, 409),
         ) as doctor:
        handler.do_POST()

    assert resp.status_code == 409
    assert resp.json['ok'] is False
    doctor.assert_called_once_with('fix', confirmed=False)

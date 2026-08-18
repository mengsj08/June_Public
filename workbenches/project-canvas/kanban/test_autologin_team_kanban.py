#!/usr/bin/env python3
"""Tests for team board bridge config and opt-in autologin."""

from pathlib import Path
from unittest.mock import patch
import importlib.util
import os

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _make_get_handler(path):
    response = type('Resp', (), {'status_code': None, 'json': None})()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {}

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


def test_get_data_includes_default_team_kanban_url():
    config = dict(scan_mod._DEFAULTS)
    with patch.object(scan_mod, 'scan_all', return_value=[]), \
         patch.object(scan_mod, 'list_projects', return_value=[]), \
         patch.object(scan_mod, 'load_user_config', return_value={}), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod, '_active_sync_manager', return_value=None):
        data = scan_mod.get_data()

    assert data['team_kanban_url'] == 'http://localhost:8899/'


@pytest.mark.parametrize(
    'config',
    [
        {},
        {'auth': {'autologin': False, 'bypass_user': 'Owner'}},
    ],
)
def test_autologin_query_does_not_bypass_when_disabled_or_missing(config):
    handler, resp = _make_get_handler('/api/data?autologin=1')

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.dict(os.environ, {'CI': 'false'}):
        handler.do_GET()

    assert resp.status_code == 401
    assert resp.json == {'ok': False, 'requireLogin': True}


def test_autologin_query_bypasses_when_enabled_and_bypass_user_is_member():
    handler, resp = _make_get_handler('/api/data?autologin=1')
    config = {'auth': {'autologin': True, 'bypass_user': 'Owner'}}
    payload = {'ok': True, 'team_kanban_url': 'http://localhost:8899/'}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod, 'get_data', return_value=payload), \
         patch.dict(os.environ, {'CI': 'false'}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json == payload


def test_autologin_query_does_not_bypass_when_bypass_user_is_not_member():
    handler, resp = _make_get_handler('/api/data?autologin=1')
    config = {'auth': {'autologin': True, 'bypass_user': 'NotAMember'}}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.dict(os.environ, {'CI': 'false'}):
        handler.do_GET()

    assert resp.status_code == 401
    assert resp.json == {'ok': False, 'requireLogin': True}

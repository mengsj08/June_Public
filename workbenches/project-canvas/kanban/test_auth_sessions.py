#!/usr/bin/env python3
"""Tests for in-memory auth session TTL and autologin reuse."""

import importlib.util
import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


@pytest.fixture(autouse=True)
def clean_sessions():
    scan_mod._sessions.clear()
    yield
    scan_mod._sessions.clear()


def _session_handler(headers=None, path='/api/data'):
    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = headers or {}

    return TestHandler()


def test_get_session_expires_old_session_and_keeps_fresh_session():
    now = 1000.0
    scan_mod._sessions['old'] = {'user': 'Owner', 'created_at': now - 11}
    scan_mod._sessions['fresh'] = {'user': 'Owner', 'created_at': now - 9}
    config = {'auth': {'session_ttl_seconds': 10}}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.time, 'time', return_value=now), \
         patch.dict(os.environ, {'CI': 'false'}):
        expired = _session_handler({'Cookie': 'kanban_session=old'})._get_session()
        fresh = _session_handler({'Cookie': 'kanban_session=fresh'})._get_session()

    assert expired is None
    assert 'old' not in scan_mod._sessions
    assert fresh == {'user': 'Owner', 'created_at': now - 9}
    assert 'fresh' in scan_mod._sessions


def test_fallback_session_created_at_zero_is_not_ttl_expired():
    now = 1000.0
    config = {'auth': {'session_ttl_seconds': 10}}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', 'Owner'), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.time, 'time', return_value=now), \
         patch.dict(os.environ, {'CI': 'false'}):
        session = _session_handler({})._get_session()

    assert session == {'user': 'Owner', 'created_at': 0}
    assert scan_mod._session_is_expired(session, now) is False


def test_ci_fallback_session_created_at_zero_is_not_ttl_expired():
    now = 1000.0
    config = {'auth': {'session_ttl_seconds': 10}}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.time, 'time', return_value=now), \
         patch.dict(os.environ, {'CI': 'true'}):
        session = _session_handler({})._get_session()

    assert session == {'user': 'Owner', 'created_at': 0}
    assert scan_mod._session_is_expired(session, now) is False


def test_autologin_html_reuses_existing_valid_cookie():
    response = {'status': None, 'headers': []}

    class TestHandler(scan_mod.Handler):
        def __init__(self, headers):
            self.path = '/?autologin=1'
            self.headers = headers
            self.wfile = io.BytesIO()

        def send_response(self, code, message=None):
            response['status'] = code

        def send_header(self, key, value):
            response['headers'].append((key, value))

        def end_headers(self):
            pass

    config = {'auth': {'autologin': True, 'bypass_user': 'Owner', 'session_ttl_seconds': 604800}}

    with patch.object(scan_mod, 'ALL_MEMBERS', ['Owner']), \
         patch.object(scan_mod, 'CURRENT_MEMBER', ''), \
         patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod, 'get_data', return_value={}), \
         patch.object(scan_mod, 'generate_html', return_value='<html></html>'), \
         patch.dict(os.environ, {'CI': 'false'}):
        first = TestHandler({})
        first._serve_html()
        set_cookie = [value for key, value in response['headers'] if key == 'Set-Cookie']
        assert len(set_cookie) == 1
        assert len(scan_mod._sessions) == 1

        response['headers'] = []
        second = TestHandler({'Cookie': set_cookie[0].split(';', 1)[0]})
        second._serve_html()

    assert response['status'] == 200
    assert [value for key, value in response['headers'] if key == 'Set-Cookie'] == []
    assert len(scan_mod._sessions) == 1

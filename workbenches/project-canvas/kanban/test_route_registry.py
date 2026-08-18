#!/usr/bin/env python3
"""Contract tests for the central HTTP route registry."""

import importlib.util
import io
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest


_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location('scan_docs_route_registry', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scan_mod)


class _Response:
    def __init__(self):
        self.status_code = None
        self.json = None


def _make_handler(path, *, host='localhost', payload=None):
    response = _Response()
    raw = json.dumps(payload if payload is not None else {}).encode('utf-8')

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Host': host, 'Content-Length': str(len(raw))}
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


def test_route_registry_matches_refactor_baseline_and_handlers_exist():
    counts = Counter(method for method, _path in scan_mod._ROUTE_REGISTRY)

    assert len(scan_mod._ROUTE_REGISTRY) == 108
    assert sum(path.startswith('/api/') for _method, path in scan_mod._ROUTE_REGISTRY) == 107
    assert counts == {'GET': 49, 'POST': 50, 'PUT': 7, 'DELETE': 2}
    assert scan_mod._STATE_CHANGE_GUARD_EXEMPT_PATHS == {'/api/sync/webhook'}
    assert scan_mod._PUBLIC_ROUTE_KEYS <= scan_mod._ROUTE_REGISTRY.keys()
    assert scan_mod._EXTRA_GUARDED_ROUTE_KEYS <= scan_mod._ROUTE_REGISTRY.keys()
    for handler_name in scan_mod._ROUTE_REGISTRY.values():
        assert callable(getattr(scan_mod.Handler, handler_name, None)), handler_name


@pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'DELETE'])
def test_unknown_registered_route_falls_through_to_404(method):
    handler, response = _make_handler('/api/definitely-not-registered')
    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        getattr(handler, f'do_{method}')()

    assert response.status_code == 404


@pytest.mark.parametrize('path', [
    '/api/mario-level',
    '/api/mario-levels',
    '/api/mario-game-map',
    '/api/mario-surfaces',
])
def test_retired_mario_runtime_routes_return_404(path):
    handler, response = _make_handler(path)
    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        handler.do_GET()

    assert response.status_code == 404


def test_owner_world_route_remains_registered_after_mario_retirement():
    assert scan_mod._ROUTE_REGISTRY[('GET', '/api/owner-world')] == '_route_get_api_owner_world'


@pytest.mark.parametrize(('method', 'path'), [
    ('GET', '/api/automations/schedule'),
    ('POST', '/api/automations/preflight'),
    ('POST', '/api/automations/run'),
    ('POST', '/api/automations/toggle'),
    ('POST', '/api/morning-batch'),
    ('GET', '/api/team/handoff/options'),
    ('POST', '/api/team/handoff'),
    ('POST', '/api/team/handoff/commit'),
    ('POST', '/api/team/handoff/preview'),
    ('POST', '/api/promote'),
    ('POST', '/api/promote-fill'),
    ('POST', '/api/promote-fill-apply'),
    ('POST', '/api/spawn-prior-art'),
])
def test_retired_runtime_routes_return_json_404(method, path):
    handler, response = _make_handler(path)
    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}):
        getattr(handler, f'do_{method}')()

    assert response.status_code == 404
    assert response.json == {'ok': False, 'error': 'Not Found'}


def test_every_registered_write_route_crosses_shared_guard():
    guarded_routes = [
        (method, path)
        for method, path in scan_mod._ROUTE_REGISTRY
        if method in scan_mod._STATE_CHANGE_METHODS
        and path not in scan_mod._STATE_CHANGE_GUARD_EXEMPT_PATHS
    ]
    assert len(guarded_routes) == 58

    for method, path in guarded_routes:
        handler, response = _make_handler(path, host='evil.example')
        getattr(handler, f'do_{method}')()
        assert response.status_code == 403, (method, path, response.json)
        assert response.json == {'ok': False, 'error': 'cross-origin blocked'}


@pytest.mark.parametrize(('method', 'path', 'expected_handler'), [
    ('POST', '/api/create', '_route_post_api_create'),
    ('PUT', '/api/update', '_route_put_api_update'),
    ('PUT', '/api/canvas', '_route_put_api_canvas'),
    ('GET', '/api/queue', '_route_get_api_queue'),
    ('POST', '/api/ai-run', '_route_post_api_ai_run'),
    ('GET', '/api/real-projects', '_route_get_api_real_projects'),
])
def test_six_high_frequency_endpoints_dispatch_to_registered_handler(
        method, path, expected_handler):
    handler, response = _make_handler(path)

    def route_probe(self, parsed, query, session):
        self._json({'ok': True, 'handler': expected_handler})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'Owner'}), \
         patch.object(scan_mod.Handler, expected_handler, route_probe):
        getattr(handler, f'do_{method}')()

    assert response.status_code == 200
    assert response.json == {'ok': True, 'handler': expected_handler}

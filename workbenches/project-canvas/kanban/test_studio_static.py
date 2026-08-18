#!/usr/bin/env python3
"""Tests for Canvas Studio static hosting under /canvas/."""

import io
import importlib.util
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


def make_handler(path):
    response = ResponseCapture()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {}
            self.wfile = io.BytesIO()

        def send_response(self, code, message=None):
            response.status_code = code

        def send_header(self, key, value):
            response.headers[key] = value

        def end_headers(self):
            pass

        def send_error(self, code, message=None):
            response.status_code = code
            self.wfile.write((message or str(code)).encode('utf-8'))

    return TestHandler(), response


def make_dist(tmp_path):
    dist = tmp_path / 'canvas-studio' / 'dist'
    assets = dist / 'assets'
    assets.mkdir(parents=True)
    (dist / 'index.html').write_text('<!doctype html><div id="root">studio index</div>', encoding='utf-8')
    (assets / 'app.js').write_text('console.log("studio asset");\n', encoding='utf-8')
    return dist


def test_studio_root_serves_index_html(tmp_path):
    dist = make_dist(tmp_path)
    handler, resp = make_handler('/canvas/')

    with patch.object(scan_mod, 'load_config', return_value={'studio_dist_dir': str(dist)}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'text/html; charset=utf-8'
    assert b'studio index' in handler.wfile.getvalue()


def test_studio_asset_serves_file_inside_dist(tmp_path):
    dist = make_dist(tmp_path)
    handler, resp = make_handler('/canvas/assets/app.js')

    with patch.object(scan_mod, 'load_config', return_value={'studio_dist_dir': str(dist)}):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/javascript; charset=utf-8'
    assert handler.wfile.getvalue() == b'console.log("studio asset");\n'


def test_studio_unknown_path_falls_back_to_spa_index(tmp_path):
    dist = make_dist(tmp_path)
    handler, resp = make_handler('/canvas/maps/KAN')

    with patch.object(scan_mod, 'load_config', return_value={'studio_dist_dir': str(dist)}):
        handler.do_GET()

    assert resp.status_code == 200
    assert b'studio index' in handler.wfile.getvalue()


def test_studio_rejects_path_traversal_outside_dist(tmp_path):
    dist = make_dist(tmp_path)
    (dist.parent / 'secret.txt').write_text('secret', encoding='utf-8')
    handler, resp = make_handler('/canvas/%2e%2e/secret.txt')

    with patch.object(scan_mod, 'load_config', return_value={'studio_dist_dir': str(dist)}):
        handler.do_GET()

    assert resp.status_code == 403
    assert b'secret' not in handler.wfile.getvalue()


def test_studio_missing_dist_returns_explainer_page(tmp_path):
    missing = tmp_path / 'canvas-studio' / 'dist'
    handler, resp = make_handler('/canvas/')

    with patch.object(scan_mod, 'load_config', return_value={'studio_dist_dir': str(missing)}):
        handler.do_GET()

    body = handler.wfile.getvalue().decode('utf-8')
    assert resp.status_code == 200
    assert '运行 npm run build' in body
    assert str(missing) in body


def test_canvas_studio_url_defaults_to_same_origin_canvas_path():
    with patch.object(scan_mod, 'load_config', return_value={}):
        assert scan_mod._canvas_studio_url_for_path('project/Demo/card.md') == (
            '/canvas/?path=project%2FDemo%2Fcard.md'
        )


def test_legacy_studio_path_redirects_to_canvas():
    handler, resp = make_handler('/studio/?path=project%2FDemo%2Fcard.md')

    handler.do_GET()

    assert resp.status_code == 308
    assert resp.headers['Location'] == '/canvas/?path=project%2FDemo%2Fcard.md'


def test_canvas_studio_url_allows_dev_server_override():
    with patch.object(scan_mod, 'load_config', return_value={'canvas_studio_url': 'http://localhost:5173/'}):
        assert scan_mod._canvas_studio_url_for_path('project/Demo/card.md') == (
            'http://localhost:5173/?path=project%2FDemo%2Fcard.md'
        )

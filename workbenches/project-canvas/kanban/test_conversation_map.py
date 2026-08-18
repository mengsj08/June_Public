#!/usr/bin/env python3
"""Tests for read-only Conversation Map manifest endpoints."""

import json
import io
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
import importlib.util

_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)
Handler = scan_mod.Handler


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

    class TestHandler(Handler):
        def __init__(self):
            self.path = path
            self._response = response

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


@pytest.fixture
def maps_root(tmp_path):
    root = tmp_path / 'conversation-map'
    root.mkdir()
    manifest = root / 'manifest.yaml'
    manifest.write_text("""schema: conversation-map-v1.2
manifest_version: 2
status: calibration_draft
generated_at: 2026-07-05
updated: 2026-07-05
thread:
  id: "thread-1"
  title: "Conversation Map test"
  raw_rollout: "/tmp/rollout-test.jsonl"
current_cursor:
  node: node-next
  source:
    - "L20"
plan:
  premises:
    - node-decision
  steps:
    - node-next
nodes:
  - id: node-root
    type: mainline
    title: Root
    status: active
    reviewed_on: 2026-07-05
    source:
      - "L1..L3"
    next_nodes:
      - node-next
  - id: node-decision
    type: mystery_type
    title: Unknown type survives
    status: accepted
    source:
      - "L10..L12"
    parent: node-root
  - id: node-next
    type: next
    title: Next work
    status: open
    source:
      - "L20"
    parent: node-root
    branch_from: node-decision
    return_to: node-root
""", encoding='utf-8')
    (root / 'manifest.v1.yaml').write_text('nodes: []\n', encoding='utf-8')
    child = root / 'child'
    child.mkdir()
    (child / 'manifest.yaml').write_text("""thread:
  id: "thread-child"
  title: "Child map"
  raw_rollout: "/tmp/child-rollout.jsonl"
nodes:
  - id: child-node
    type: decision
    title: Child
    source: ["L5"]
""", encoding='utf-8')
    return root


def _cfg(root):
    return {'conversation_maps_dir': str(root)}


def _clone_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _manual_note(node_id='manual-note', text='Owner manual note'):
    return {
        'id': node_id,
        'type': 'note',
        'position': {'x': 720, 'y': 180},
        'data': {
            'label': text,
            'content': text,
            'origin': 'manual',
        },
    }


def _canvas_path(repo_root, canvas_ref):
    return repo_root / canvas_ref


def _canvas_events(repo_root, canvas_ref):
    events_path = repo_root / Path(canvas_ref).parent / 'events.jsonl'
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]


def _put_convmap_api(repo_root, maps_root, payload):
    handler, resp = make_handler('/api/canvas')
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    with patch.object(scan_mod, 'REPO_ROOT', repo_root), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_PUT()
    return resp


def test_conversation_map_list_discovers_manifest_yaml_only(maps_root):
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        result, status = scan_mod.list_conversation_map_manifests()

    assert status == 200
    assert result['ok'] is True
    by_path = {item['path']: item for item in result['maps']}
    assert set(by_path) == {'manifest.yaml', 'child/manifest.yaml'}
    assert by_path['manifest.yaml']['title'] == 'Conversation Map test'
    assert by_path['manifest.yaml']['node_count'] == 3
    assert 'manifest.v1.yaml' not in by_path


def test_conversation_map_parses_unknown_type_edges_and_sed_commands(maps_root):
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        result, status = scan_mod.get_conversation_map_manifest('manifest.yaml')

    assert status == 200
    assert result['node_count'] == 3
    by_id = {node['id']: node for node in result['nodes']}
    assert by_id['node-decision']['type'] == 'mystery_type'
    assert by_id['node-decision']['source_commands'][0]['command'] == "sed -n '10,12p' /tmp/rollout-test.jsonl"
    assert by_id['node-next']['source_commands'][0]['command'] == "sed -n '20p' /tmp/rollout-test.jsonl"
    assert result['current_cursor']['source_commands'][0]['command'] == "sed -n '20p' /tmp/rollout-test.jsonl"
    relations = {(edge['source'], edge['target'], edge['relation']) for edge in result['edges']}
    assert ('node-root', 'node-decision', 'parent') in relations
    assert ('node-root', 'node-next', 'next') in relations
    assert ('node-next', 'node-root', 'return_to') in relations
    assert result['plan']['premise_nodes'][0]['id'] == 'node-decision'
    assert result['plan']['step_nodes'][0]['id'] == 'node-next'


def test_conversation_map_manifest_dates_are_json_serializable(maps_root):
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        result, status = scan_mod.get_conversation_map_manifest('manifest.yaml')

    assert status == 200
    assert result['generated_at'] == '2026-07-05'
    by_id = {node['id']: node for node in result['nodes']}
    assert by_id['node-root']['reviewed_on'] == '2026-07-05'
    json.dumps(result, ensure_ascii=False)

    handler, resp = make_handler('/api/conversation-map?path=manifest.yaml')
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['generated_at'] == '2026-07-05'


def test_conversation_map_rejects_path_escape_and_archived_manifest(maps_root, tmp_path):
    outside = tmp_path / 'manifest.yaml'
    outside.write_text('nodes: []\n', encoding='utf-8')
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        escaped, escaped_status = scan_mod.get_conversation_map_manifest(str(outside))
        archived, archived_status = scan_mod.get_conversation_map_manifest('manifest.v1.yaml')

    assert escaped_status == 403
    assert escaped['ok'] is False
    assert archived_status == 400
    assert archived['error'] == '只允许读取 manifest.yaml'


def test_conversation_map_http_endpoints(maps_root):
    handler, resp = make_handler('/api/conversation-maps')
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['maps'][0]['path'] == 'child/manifest.yaml'
    assert any(item['path'] == 'manifest.yaml' for item in resp.json['maps'])

    handler, resp = make_handler('/api/conversation-map?path=manifest.yaml')
    with patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['thread']['title'] == 'Conversation Map test'


def test_conversation_map_canvas_generate_writes_manifest_projection(maps_root, tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        result, status = scan_mod.generate_conversation_map_canvas('thread-1')

    assert status == 200
    assert result['ok'] is True
    assert result['canvas_ref'] == 'project/个人调度/.canvas/_conversation_maps/thread-1/main.canvas.json'
    canvas = result['canvas']
    assert canvas['metadata']['node_count'] == 3
    assert len(canvas['nodes']) == 3
    by_id = {node['id']: node for node in canvas['nodes']}
    assert set(by_id) == {'conv-node-node-root', 'conv-node-node-decision', 'conv-node-node-next'}
    for node in canvas['nodes']:
        metadata = node['data']['metadata']
        assert metadata['conversation_map_generated'] is True
        assert metadata['conversation_map']['generated'] is True
        assert metadata['conversation_map']['canvas_scope'] == 'thread-1'
    saved = json.loads(_canvas_path(tmp_path, result['canvas_ref']).read_text(encoding='utf-8'))
    assert saved['metadata']['node_count'] == canvas['metadata']['node_count']


def test_conversation_map_canvas_merge_preserves_manual_layer_and_refreshes_generated_nodes(maps_root, tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        first, status = scan_mod.generate_conversation_map_canvas('thread-1')
    assert status == 200

    editable = _clone_json(first['canvas'])
    by_id = {node['id']: node for node in editable['nodes']}
    by_id['conv-node-node-root']['data']['title'] = 'Manual edit should be overwritten'
    by_id['conv-node-node-root']['data']['label'] = 'Manual edit should be overwritten'
    editable['nodes'].append(_manual_note())

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        saved, save_status = scan_mod.put_conversation_map_canvas(
            'thread-1',
            editable,
            actor='owner',
            base_rev=first['canvas_rev'],
        )
        regenerated, regen_status = scan_mod.generate_conversation_map_canvas(
            'thread-1',
            base_rev=saved['canvas_rev'],
        )

    assert save_status == 200
    assert regen_status == 200
    saved_by_id = {node['id']: node for node in saved['canvas']['nodes']}
    regenerated_by_id = {node['id']: node for node in regenerated['canvas']['nodes']}
    assert 'manual-note' in saved_by_id
    assert 'manual-note' in regenerated_by_id
    assert saved_by_id['conv-node-node-root']['data']['title'] == 'Root'
    assert regenerated_by_id['conv-node-node-root']['data']['label'] == 'Root'


def test_conversation_map_canvas_put_rejects_stale_base_rev_without_overwriting_sidecar(maps_root, tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        generated, status = scan_mod.generate_conversation_map_canvas('thread-1')
    assert status == 200

    base_rev = generated['canvas_rev']
    server_canvas = _clone_json(generated['canvas'])
    server_canvas['nodes'].append(_manual_note('server-note', 'server update'))
    server_write = _put_convmap_api(tmp_path, maps_root, {
        'convmap': 'thread-1',
        'canvas': server_canvas,
        'actor': 'codex',
        'base_rev': base_rev,
    })
    assert server_write.status_code == 200

    sidecar = _canvas_path(tmp_path, generated['canvas_ref'])
    before_reject = sidecar.read_text(encoding='utf-8')
    stale_canvas = _clone_json(generated['canvas'])
    stale_canvas['nodes'].append(_manual_note('stale-note', 'stale update'))
    rejected = _put_convmap_api(tmp_path, maps_root, {
        'convmap': 'thread-1',
        'canvas': stale_canvas,
        'actor': 'owner',
        'base_rev': base_rev,
    })

    assert rejected.status_code == 409
    assert rejected.json['conflict'] is True
    assert sidecar.read_text(encoding='utf-8') == before_reject
    saved = json.loads(before_reject)
    saved_ids = {node['id'] for node in saved['nodes']}
    assert 'server-note' in saved_ids
    assert 'stale-note' not in saved_ids
    assert any(
        event.get('event') == 'canvas_save_rejected'
        and event.get('actor') == 'owner'
        and event.get('reason') == 'base_rev_mismatch'
        for event in _canvas_events(tmp_path, generated['canvas_ref'])
    )


def test_conversation_map_canvas_open_twice_without_content_change_does_not_append_events(maps_root, tmp_path):
    handler, resp = make_handler('/api/canvas?convmap=thread-1')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_GET()
    assert resp.status_code == 200
    first = resp.json
    first_events = _canvas_events(tmp_path, first['canvas_ref'])
    assert len(first_events) == 1
    assert first_events[0]['event'] == 'conversation_map_refreshed'

    handler, resp = make_handler('/api/canvas?convmap=thread-1')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'load_config', return_value=_cfg(maps_root)):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['unchanged'] is True
    assert resp.json['canvas_rev'] == first['canvas_rev']
    assert len(_canvas_events(tmp_path, first['canvas_ref'])) == len(first_events)

#!/usr/bin/env python3
"""Tests for document opening, LLM provider routing, and scenario fill preview."""

import io
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _FakeLLMResponse:
    def __init__(self, content='ok'):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({
            'choices': [{'message': {'content': self.content}}],
        }).encode('utf-8')


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


def _make_raw_handler(path, raw):
    response = type('Resp', (), {'status_code': None, 'json': None})()

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


@pytest.fixture
def temp_repo(tmp_path):
    repo = tmp_path / 'repo'
    task_dir = repo / 'project' / 'Hermes'
    task_dir.mkdir(parents=True)
    (task_dir / 'sample-task.md').write_text("""---
title: Sample Task
task_id: HER-1
workdir: project/Hermes/
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: medium
status: review
scenario_slug: sample-scenario
tags: []
---

## 要做什么
把当前交付沉淀成客户可复用场景。

## 完成标准
- [ ] 8 小节齐全
- [ ] 不包含私有路径
""", encoding='utf-8')
    return repo


def test_llm_chat_routes_provider_settings():
    calls = []
    config = {
        'zhipu_api_key': 'zhipu-key',
        'zhipu_api_url': 'https://zhipu.example/chat',
        'zhipu_model': 'glm-test',
        'deepseek_api_key': 'deepseek-key',
        'deepseek_api_url': 'https://deepseek.example/chat',
        'deepseek_model': 'deepseek-test',
    }

    def fake_urlopen(req, timeout=15):
        calls.append({
            'url': req.full_url,
            'payload': json.loads(req.data.decode('utf-8')),
            'auth': req.headers.get('Authorization'),
            'timeout': timeout,
        })
        return _FakeLLMResponse('provider ok')

    with patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.urllib.request, 'urlopen', side_effect=fake_urlopen):
        assert scan_mod._llm_chat('zhipu', [{'role': 'user', 'content': 'a'}]) == (True, 'provider ok')
        assert scan_mod._llm_chat('deepseek', [{'role': 'user', 'content': 'b'}]) == (True, 'provider ok')

    assert calls[0]['url'] == 'https://zhipu.example/chat'
    assert calls[0]['payload']['model'] == 'glm-test'
    assert calls[0]['payload']['thinking'] == {'type': 'disabled'}
    assert calls[0]['auth'] == 'Bearer zhipu-key'
    assert calls[1]['url'] == 'https://deepseek.example/chat'
    assert calls[1]['payload']['model'] == 'deepseek-test'
    assert 'thinking' not in calls[1]['payload']
    assert calls[1]['auth'] == 'Bearer deepseek-key'


def test_llm_chat_empty_content_returns_error_without_throwing():
    config = {
        'deepseek_api_key': 'deepseek-key',
        'deepseek_api_url': 'https://deepseek.example/chat',
        'deepseek_model': 'deepseek-test',
    }

    with patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.urllib.request, 'urlopen', return_value=_FakeLLMResponse(None)):
        ok, message = scan_mod._llm_chat('deepseek', [{'role': 'user', 'content': 'a'}])

    assert ok is False
    assert '空内容' in message


def test_llm_chat_http_4xx_does_not_retry_and_returns_body():
    config = {
        'deepseek_api_key': 'deepseek-key',
        'deepseek_api_url': 'https://deepseek.example/chat',
        'deepseek_model': 'deepseek-test',
    }
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req.full_url)
        raise scan_mod.urllib.error.HTTPError(
            req.full_url,
            429,
            'Too Many Requests',
            hdrs=None,
            fp=io.BytesIO(b'{"error":"rate limited"}'),
        )

    with patch.object(scan_mod, 'load_config', return_value=config), \
         patch.object(scan_mod.urllib.request, 'urlopen', side_effect=fake_urlopen), \
         patch.object(scan_mod.time, 'sleep') as sleep:
        ok, message = scan_mod._llm_chat('deepseek', [{'role': 'user', 'content': 'a'}])

    assert ok is False
    assert len(calls) == 1
    sleep.assert_not_called()
    assert 'HTTP 429' in message
    assert 'rate limited' in message


def test_do_post_bad_json_returns_json_400(temp_repo):
    handler, resp = _make_raw_handler('/api/create', b'{"project":')

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        handler.do_POST()

    assert resp.status_code == 400
    assert resp.json == {'ok': False, 'error': 'invalid JSON body'}


def test_api_open_allows_absolute_path_inside_allowed_root(tmp_path, temp_repo):
    allowed_root = tmp_path / 'Documents'
    allowed_root.mkdir()
    target = allowed_root / 'brief.md'
    target.write_text('hello\n', encoding='utf-8')
    handler, resp = _make_handler('/api/open', {'path': str(target)})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(allowed_root)]}), \
         patch.object(scan_mod.PLATFORM_ADAPTER, 'open_path', return_value=(True, '')) as open_path:
        handler.do_POST()

    assert resp.status_code == 200
    assert resp.json == {'ok': True}
    open_path.assert_called_once_with(target.resolve())


def test_api_open_rejects_absolute_path_outside_allowed_root(tmp_path, temp_repo):
    allowed_root = tmp_path / 'Documents'
    allowed_root.mkdir()
    handler, resp = _make_handler('/api/open', {'path': '/etc/hosts'})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(allowed_root)]}), \
         patch.object(scan_mod.PLATFORM_ADAPTER, 'open_path') as open_path:
        handler.do_POST()

    assert resp.status_code == 403
    assert resp.json['ok'] is False
    assert '可信根' in resp.json['error']
    open_path.assert_not_called()


def test_api_open_rejects_missing_absolute_path_inside_allowed_root(tmp_path, temp_repo):
    allowed_root = tmp_path / 'Documents'
    allowed_root.mkdir()
    missing = allowed_root / 'missing.md'
    handler, resp = _make_handler('/api/open', {'path': str(missing)})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value={'open_allowed_roots': [str(allowed_root)]}), \
         patch.object(scan_mod.PLATFORM_ADAPTER, 'open_path') as open_path:
        handler.do_POST()

    assert resp.status_code == 404
    assert resp.json['ok'] is False
    assert '文件不存在' in resp.json['error']
    open_path.assert_not_called()


def test_api_open_still_allows_repo_relative_path(temp_repo):
    handler, resp = _make_handler('/api/open', {'path': 'project/Hermes/sample-task.md'})

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod.PLATFORM_ADAPTER, 'open_path', return_value=(True, '')) as open_path:
        handler.do_POST()

    assert resp.status_code == 200
    open_path.assert_called_once_with((temp_repo / 'project/Hermes/sample-task.md').resolve())


def test_promote_fill_prompt_redacts_paths_and_excludes_execution_results():
    task_file = {
        'frontmatter': {
            'title': 'Sensitive Task',
            'task_id': 'SEN-1',
            'workdir': '/Users/example/workspace/customer/raw-meeting',
        },
        'body': """## 背景 / 来源
- 来源：/Users/example/workspace/customer/raw-meeting/report.html

## 要做什么
沉淀成场景。

## 完成标准
- [ ] 输出物明确

## 执行结果
这里是执行结果和客户转录原文，不应发送给外部 LLM。
""",
    }

    messages = scan_mod._build_promote_fill_messages('sensitive-scenario', task_file)
    prompt = messages[1]['content']

    assert '/Users/example' not in prompt
    assert 'raw-meeting' not in prompt
    assert '工作目录仅作来源判断' not in prompt
    assert '客户转录原文' not in prompt
    assert '## 执行结果' not in prompt
    assert '[本机路径已省略]' in prompt
    assert '沉淀成场景' in prompt


def test_normalize_scenario_sections_keeps_horizontal_rule_content():
    llm_body = """---
这是普通水平线后的说明，不是 frontmatter。

## 场景解决什么问题

保留的问题描述。
---
补充说明也要保留。

## 适合谁

适合业务负责人。
"""

    preview = scan_mod._normalize_scenario_sections(llm_body)

    assert '保留的问题描述' in preview
    assert '补充说明也要保留' in preview
    assert preview.startswith('## 场景解决什么问题')


def test_normalize_scenario_sections_strips_real_frontmatter():
    llm_body = """---
status: draft
title: 示例
---

## 场景解决什么问题

真实正文。
"""

    preview = scan_mod._normalize_scenario_sections(llm_body)

    assert 'status: draft' not in preview
    assert '真实正文' in preview

#!/usr/bin/env python3
"""AI profile 默认档与来源锁定的回归。

约定:三个选区/卡聊来源锁死只读档;canvas 对话节点默认只读 deep 档
(写入必须显式请求 execute profile);无来源整卡运行默认 execute。

Run: CI=true python3 -m pytest shared/toolkit/kanban/test_ai_profile_defaults.py -v
"""

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_profile_defaults', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_canvas_origin_defaults_to_read_only_deep_profile():
    for tool in ('claude', 'codex'):
        name, error = scan_mod.resolve_ai_profile(tool, '', 'canvas', has_custom_prompt=True)
        assert error == ''
        assert name == f'deep_{tool}'
        assert scan_mod.AI_PROFILES[name]['mode'] == 'read_only'


def test_selection_origins_reject_profile_override():
    name, error = scan_mod.resolve_ai_profile(
        'codex', 'execute_codex', 'selection_side_chat', has_custom_prompt=True,
    )
    assert name == ''
    assert '只允许 profile deep_codex' in error
    name, error = scan_mod.resolve_ai_profile(
        'codex', 'deep_codex', 'selection_quick_explain', has_custom_prompt=True,
    )
    assert name == ''
    assert '只允许 profile quick_explain' in error


def test_card_chat_origin_stays_locked_to_deep_read_only_profile():
    name, error = scan_mod.resolve_ai_profile(
        'codex', 'scoped_write_codex', 'card_chat', has_custom_prompt=True,
    )
    assert name == ''
    assert '只允许 profile deep_codex' in error

    name, error = scan_mod.resolve_ai_profile(
        'codex', '', 'card_chat', has_custom_prompt=True,
    )
    assert error == ''
    assert name == 'deep_codex'
    assert scan_mod.AI_PROFILES[name]['mode'] == 'read_only'


def test_scoped_write_codex_command_does_not_embed_deployment_roots():
    profile = scan_mod.AI_PROFILES['scoped_write_codex']
    command = profile['command']
    assert profile['mode'] == 'write'
    assert 'sandbox_mode=workspace-write' in command
    assert 'approval_policy=never' in command
    assert 'sandbox_workspace_write.network_access=true' in command

    assert not any(
        arg.startswith('sandbox_workspace_write.writable_roots=')
        for arg in command
    )
    assert '/Users/' not in ' '.join(command)


def test_canvas_origin_allows_explicit_execute_request():
    name, error = scan_mod.resolve_ai_profile(
        'codex', 'execute_codex', 'canvas', has_custom_prompt=True,
    )
    assert error == ''
    assert name == 'execute_codex'


def test_plain_card_run_defaults_to_execute():
    name, error = scan_mod.resolve_ai_profile('claude', '', '', has_custom_prompt=False)
    assert error == ''
    assert name == 'execute_claude'

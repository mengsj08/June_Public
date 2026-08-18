#!/usr/bin/env python3
"""Static UI seam checks for the AttentionGate network doctor controls."""

from pathlib import Path


_HERE = Path(__file__).resolve().parent


def test_network_doctor_is_visible_on_live_api_and_uses_fixed_actions():
    source = (_HERE / 'static' / 'kanban' / 'modules' / 'render-board-console-runtime.js').read_text(encoding='utf-8')

    assert "sumTitle.textContent = '网络医生'" in source
    assert "makeAction('检查网络', 'diagnose'" in source
    assert "makeAction('一键修复', 'fix'" in source
    assert "makeAction('断网急救', 'emergency'" in source
    assert "ctx.api.networkDoctor(action, confirmed)" in source
    assert "confirmed = window.confirm(prompt)" in source
    assert "!ctx.hasApi && dataState.clash_configured" in source


def test_network_doctor_api_and_summary_style_are_wired():
    api = (_HERE / 'static' / 'kanban' / 'modules' / 'api.js').read_text(encoding='utf-8')
    css = (_HERE / 'static' / 'kanban' / 'console.css').read_text(encoding='utf-8')

    assert "apiJson('/api/network/doctor'" in api
    assert 'networkDoctor,' in api
    assert '.console-network-doctor-summary' in css

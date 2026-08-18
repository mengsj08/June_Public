#!/usr/bin/env python3
"""Optional external network-doctor contract (never required by public core)."""

import os
from pathlib import Path

import pytest


SCRIPT = Path(os.environ.get("KANBAN_NET_DOCTOR_SCRIPT") or "/nonexistent/net-doctor.sh")
if not SCRIPT.is_file():
    pytest.skip("KANBAN_NET_DOCTOR_SCRIPT is not configured", allow_module_level=True)


def test_zero_http_provider_is_normal_verge_profile_state():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "api_get '/providers/proxies'" in source
    assert "vehicleType" in source
    assert "未发现 HTTP 型 provider；订阅在 Clash Verge profile 层管理，此项为正常态" in source
    assert "节点可用性以真实传输检查为准" in source
    assert "pass 'macOS 系统代理已开启'" in source
    assert "TUN 与 macOS 系统代理均未接管流量" in source
    assert "pass 'Verge 真实传输通过'" in source
    assert 'disable_system_proxy' not in source
    assert '-setwebproxystate' not in source
    assert "warn 'mihomo API 未枚举到可评估的供应商策略组'" not in source
    assert "fail 'mihomo API 未枚举到可评估的供应商策略组'" not in source

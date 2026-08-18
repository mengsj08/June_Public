#!/usr/bin/env python3
"""Tests for the read-only network status panel."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


class _RunResult:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class _SocketStub:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_handler(path):
    response = type('Resp', (), {'status_code': None, 'json': None})()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {'Host': 'localhost', 'Content-Length': '0'}
            self.rfile = io.BytesIO(b'')

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


def test_system_proxy_parser_handles_full_same_port():
    status = scan_mod._system_proxy_from_scutil(
        """
        <dictionary> {
          HTTPEnable : 1
          HTTPProxy : 127.0.0.1
          HTTPPort : 7897
          HTTPSEnable : 1
          HTTPSProxy : 127.0.0.1
          HTTPSPort : 7897
          SOCKSEnable : 1
          SOCKSProxy : 127.0.0.1
          SOCKSPort : 7897
        }
        """
    )

    assert status['enabled'] is True
    assert status['label'] == '已启用'
    assert status['health'] == 'good'
    assert status['consistent'] is True
    assert status['primary_port'] == 7897
    assert status['ports'] == [7897]


def test_system_proxy_parser_handles_disabled_and_mismatched_ports():
    disabled = scan_mod._system_proxy_from_scutil('HTTPEnable : 0\nHTTPSEnable : 0\nSOCKSEnable : 0\n')
    assert disabled['enabled'] is False
    assert disabled['label'] == '未启用'
    assert disabled['health'] == 'inactive'
    assert disabled['primary_port'] is None

    partial = scan_mod._system_proxy_from_scutil(
        """
        HTTPEnable : 1
        HTTPProxy : 127.0.0.1
        HTTPPort : 7890
        HTTPSEnable : 1
        HTTPSProxy : 127.0.0.1
        HTTPSPort : 7897
        SOCKSEnable : 0
        """
    )
    assert partial['enabled'] is True
    assert partial['label'] == '部分启用'
    assert partial['health'] == 'warn'
    assert partial['consistent'] is False
    assert partial['primary_port'] is None
    assert partial['ports'] == [7890, 7897]


def test_verified_verge_profile_accepts_tun_with_real_transport():
    status = {
        'verge_core': {'running': True},
        'verge_service': {'running': True},
        'tun': {'enabled': True},
        'system_proxy': scan_mod._system_proxy_from_scutil(
            'HTTPEnable : 0\nHTTPSEnable : 0\nSOCKSEnable : 0\n'
        ),
        'checks': {'github': {'health': 'good'}},
    }

    profile = scan_mod._network_profile_verge_tun_global(status)

    assert profile['enabled'] is True
    assert profile['label'] == '入口就绪'
    assert profile['health'] == 'good'
    assert '真实传输通过' in profile['summary']
    assert profile['deep_check_required'] is True


def test_verge_profile_accepts_system_proxy_with_real_transport():
    status = {
        'verge_core': {'running': True},
        'verge_service': {'running': True},
        'tun': {'enabled': True},
        'system_proxy': scan_mod._system_proxy_from_scutil(
            'HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7890\n'
            'HTTPSEnable : 1\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 7890\n'
            'SOCKSEnable : 1\nSOCKSProxy : 127.0.0.1\nSOCKSPort : 7890\n'
        ),
        'checks': {'github': {'health': 'good'}},
    }

    profile = scan_mod._network_profile_verge_tun_global(status)

    assert profile['enabled'] is True
    assert profile['label'] == '入口就绪'
    assert profile['health'] == 'good'
    assert 'TUN 或系统代理' in profile['summary']


def test_verge_profile_requires_real_transport_even_with_both_entry_paths():
    status = {
        'verge_core': {'running': True},
        'verge_service': {'running': True},
        'tun': {'enabled': True},
        'system_proxy': {'enabled': True},
        'checks': {'github': {'health': 'bad'}},
    }

    profile = scan_mod._network_profile_verge_tun_global(status)

    assert profile['enabled'] is False
    assert profile['health'] == 'warn'
    assert '真实传输未通过' in profile['summary']


def test_tun_status_parser_detects_198_18_utun():
    status = scan_mod._tun_status_from_ifconfig(
        """
        en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500
            inet 192.168.1.3 netmask 0xffffff00
        utun6: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 9000
            inet 198.18.0.1 --> 198.18.0.1 netmask 0xfffffffc
        """
    )

    assert status['enabled'] is True
    assert status['label'] == '已启用'
    assert status['health'] == 'good'
    assert status['interface'] == 'utun6'
    assert status['address'] == '198.18.0.1'
    assert 'utun6' in status['summary']


def test_tun_status_parser_ignores_non_utun_198_18():
    status = scan_mod._tun_status_from_ifconfig(
        """
        en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500
            inet 198.18.0.2 netmask 0xffffff00
        """
    )

    assert status['enabled'] is False
    assert status['label'] == '未检测'
    assert status['health'] == 'inactive'


def test_network_status_endpoint_returns_structured_failures_without_target_input():
    handler, resp = _make_handler('/api/network/status?target=/bin/sh')

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ['ps', '-axo', 'comm=']:
            return _RunResult('')
        if cmd[0] == 'ifconfig':
            return _RunResult('lo0: flags=8049\n')
        if cmd[0] == '/usr/bin/curl':
            return _RunResult('000', returncode=28)
        raise AssertionError(f'unexpected command: {cmd}')

    with patch.object(scan_mod.Handler, '_get_session', return_value={'user': 'tester'}), \
         patch.object(scan_mod, 'configured_ui_features', return_value={'network_doctor': True}), \
         patch.object(
             scan_mod.PLATFORM_ADAPTER,
             'system_proxy_output',
             return_value=(True, 'HTTPEnable : 0\nHTTPSEnable : 0\nSOCKSEnable : 0\n', ''),
         ), \
         patch.object(scan_mod.subprocess, 'run', side_effect=fake_run), \
         patch.object(scan_mod.socket, 'create_connection', side_effect=OSError):
        handler.do_GET()

    assert resp.status_code == 200
    assert resp.json['ok'] is True
    assert resp.json['verge_core']['label'] == '未运行'
    assert resp.json['verge_service']['label'] == '未运行'
    assert 'clash_verge' not in resp.json
    assert 'clashx_pro' not in resp.json
    assert resp.json['tun']['label'] == '未检测'
    assert resp.json['system_proxy']['label'] == '未启用'
    assert resp.json['checks']['github']['label'] == '不可达'
    assert resp.json['checks']['feishu']['label'] == '不可达'
    assert resp.json['checks']['imap_163']['label'] == '不可达'


def test_network_status_success_shape_uses_reachability_not_secret_inputs():
    def fake_run(cmd, **kwargs):
        if cmd[:3] == ['ps', '-axo', 'comm=']:
            return _RunResult('/usr/local/bin/verge-mihomo\n/usr/local/bin/clash-verge-service\n')
        if cmd[0] == 'ifconfig':
            return _RunResult('utun6: flags=8051\n\tinet 198.18.0.1 --> 198.18.0.1\n')
        if cmd[0] == '/usr/bin/curl':
            return _RunResult('404', returncode=0)
        raise AssertionError(f'unexpected command: {cmd}')

    with patch.object(scan_mod, 'configured_ui_features', return_value={'network_doctor': True}), \
         patch.object(
             scan_mod.PLATFORM_ADAPTER,
             'system_proxy_output',
             return_value=(
                 True,
                 'HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7897\n'
                 'HTTPSEnable : 1\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 7897\n'
                 'SOCKSEnable : 1\nSOCKSProxy : 127.0.0.1\nSOCKSPort : 7897\n',
                 '',
             ),
         ), \
         patch.object(scan_mod.subprocess, 'run', side_effect=fake_run), \
         patch.object(scan_mod.socket, 'create_connection', return_value=_SocketStub()):
        status = scan_mod.get_network_status()

    assert status['ok'] is True
    assert status['verge_core']['running'] is True
    assert status['verge_service']['running'] is True
    assert 'clash_verge' not in status
    assert 'clashx_pro' not in status
    assert status['tun']['enabled'] is True
    assert status['tun']['interface'] == 'utun6'
    assert status['profiles']['verge_tun_global']['enabled'] is True
    assert status['profiles']['verge_tun_global']['label'] == '入口就绪'
    assert status['system_proxy']['primary_port'] == 7897
    assert status['checks']['github']['reachable'] is True
    assert status['checks']['feishu']['reachable'] is True
    assert status['checks']['imap_163']['reachable'] is True

#!/usr/bin/env python3
"""Public cold-start contracts for deployment paths and opt-in integrations."""

import importlib.util
from pathlib import Path
from unittest.mock import patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_optional_integrations', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_repo_root_defaults_to_cloned_repository():
    assert scan_mod.REPO_ROOT == _HERE.parent.resolve()


def test_default_deployment_paths_and_allowed_roots_stay_in_repo():
    config = scan_mod.load_config()
    paths = scan_mod.configured_deployment_paths(config)

    assert config['bind_host'] == '127.0.0.1'
    assert scan_mod._auth_mode(config) == 'token'
    assert config['auth']['local_bypass'] is False
    assert config['auth']['autologin'] is False
    assert paths['repo_root'] == str(scan_mod.REPO_ROOT)
    assert paths['workspace_root'] == str(scan_mod.REPO_ROOT)
    assert paths['data_root'] == str(scan_mod.REPO_ROOT / 'demo')
    assert all(
        root == scan_mod.REPO_ROOT or scan_mod.REPO_ROOT in root.parents
        for root in scan_mod._configured_open_allowed_roots(config)
    )


def test_unconfigured_optional_integrations_do_not_render_menu_entries():
    rendered = scan_mod.generate_html({
        'local_integrations': [],
        'ui_features': {},
    })

    assert '__KANBAN_OPTIONAL_LOCAL_TOOL_ITEMS__' not in rendered
    assert '__KANBAN_OPTIONAL_VIEW_ITEMS__' not in rendered
    assert 'data-local-tool="scenario-library"' not in rendered
    assert 'data-board-view="relationships"' not in rendered
    assert 'data-board-view="world"' not in rendered


def test_retired_personal_views_do_not_render_even_if_legacy_features_are_enabled():
    rendered = scan_mod.generate_html({
        'local_integrations': [],
        'ui_features': {
            'relationships': True,
            'world': True,
            'governance': False,
        },
    })

    assert 'data-board-view="relationships"' not in rendered
    assert 'data-board-view="world"' not in rendered
    assert '人脉与客户' not in rendered
    assert '我的世界' not in rendered


def test_configured_existing_local_integration_stays_off_public_menu(tmp_path):
    tool_dir = tmp_path / 'tool'
    tool_dir.mkdir()
    config = {
        'paths': {'workspace_root': str(tmp_path), 'data_root': str(tmp_path)},
        'open_allowed_roots': [str(tmp_path)],
        'integrations': {
            'local_tools': {
                'demo-tool': {
                    'enabled': True,
                    'name': 'Demo Tool',
                    'cwd': str(tool_dir),
                    'command': 'python3 -m http.server 3000',
                    'url': 'http://localhost:3000/',
                    'port': 3000,
                },
            },
        },
    }

    integrations = scan_mod.configured_local_integrations(config)
    rendered = scan_mod.generate_html({
        'local_integrations': integrations,
        'ui_features': {},
    })

    assert integrations == [{
        'id': 'demo-tool',
        'label': 'Demo Tool',
        'url': 'http://localhost:3000/',
    }]
    assert 'data-local-tool="demo-tool"' not in rendered


def test_missing_local_integration_directory_is_silently_hidden(tmp_path):
    config = {
        'paths': {'workspace_root': str(tmp_path)},
        'open_allowed_roots': [str(tmp_path)],
        'integrations': {
            'local_tools': {
                'missing-tool': {
                    'enabled': True,
                    'cwd': str(tmp_path / 'missing'),
                    'command': 'npm run dev',
                    'url': 'http://localhost:3000/',
                },
            },
        },
    }

    assert scan_mod.configured_local_integrations(config) == []


def test_unsupported_platform_hides_configured_local_integration(tmp_path):
    tool_dir = tmp_path / 'tool'
    tool_dir.mkdir()
    config = {
        'paths': {'workspace_root': str(tmp_path)},
        'open_allowed_roots': [str(tmp_path)],
        'integrations': {
            'local_tools': {
                'demo-tool': {
                    'enabled': True,
                    'cwd': str(tool_dir),
                    'command': 'python3 -m http.server 3000',
                    'url': 'http://localhost:3000/',
                },
            },
        },
    }
    logs = []
    unsupported = scan_mod.platform_adapter.get_platform_adapter('win32', logger=logs.append)

    with patch.object(scan_mod, 'PLATFORM_ADAPTER', unsupported):
        assert scan_mod.configured_local_integrations(config) == []
        assert scan_mod.configured_local_integrations(config) == []

    assert logs == ['本地工具启动在 win32 上不可用；1 个入口已隐藏']


def test_linux_hides_darwin_only_network_doctor(tmp_path):
    script = tmp_path / 'net-doctor.sh'
    script.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
    config = {'network_doctor': {'enabled': True, 'script': str(script)}}
    logs = []
    linux = scan_mod.platform_adapter.get_platform_adapter('linux', logger=logs.append)

    with patch.object(scan_mod, 'PLATFORM_ADAPTER', linux):
        features = scan_mod.configured_ui_features(config)

    assert features['network_doctor'] is False
    assert logs == ['macOS 网络医生在 linux 上不可用；入口已隐藏']


def test_relative_workdir_resolves_from_configured_workspace_root(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    config = {
        'paths': {'workspace_root': str(workspace)},
        'open_allowed_roots': [str(workspace)],
    }

    resolved, error = scan_mod.resolve_workdir('project-a', '', config=config)

    assert error is None
    assert resolved == workspace / 'project-a'


def test_optional_path_binding_rejects_paths_outside_allowed_roots(tmp_path):
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    config = {
        'paths': {'workspace_root': str(tmp_path)},
        'open_allowed_roots': [str(allowed)],
        'integrations': {
            'workspace_governance': {
                'enabled': True,
                'root': str(outside),
            },
        },
    }

    fallback = scan_mod._DISABLED_INTEGRATION_ROOT / 'workspace-governance'
    assert scan_mod._declared_integration_path(
        config, 'workspace_governance', 'root', fallback
    ) == fallback


def test_default_network_status_does_not_probe_machine_or_internet():
    with patch.object(scan_mod, '_read_system_proxy') as system_proxy, \
            patch.object(scan_mod, '_http_probe') as http_probe:
        payload = scan_mod.get_network_status()

    assert payload['ok'] is True
    assert payload['enabled'] is False
    system_proxy.assert_not_called()
    http_probe.assert_not_called()


def test_summarizer_providers_require_explicit_opt_in(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'should-not-enable-provider')
    deps = {'load_config': lambda: {}}

    assert scan_mod.canvas_seed._local_summarizer_settings({}) is None
    assert scan_mod.canvas_seed._deepseek_summarizer_settings(deps) is None

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('feishu_notify', _HERE / 'feishu_notify.py')
feishu_notify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feishu_notify)


def test_lark_cli_transport_sends_without_app_secret():
    cfg = feishu_notify.normalize_config({
        'feishu': {
            'transport': 'lark_cli',
            'lark_cli_path': '/opt/homebrew/bin/lark-cli',
            'lark_cli_profile': 'cli_profile',
            'lark_cli_as': 'bot',
            'member_open_ids': {'Owner': 'ou_owner'},
        }
    }, {})
    feishu_notify.set_config(cfg)

    with patch.object(feishu_notify.subprocess, 'run', return_value=subprocess.CompletedProcess(['lark-cli'], 0, '{}', '')) as run:
        warning = feishu_notify.notify_member_event('Owner', 'team_assigned', 'Title')

    assert warning is None
    argv = run.call_args.args[0]
    assert argv[:5] == ['/opt/homebrew/bin/lark-cli', 'im', '+messages-send', '--as', 'bot']
    assert '--user-id' in argv
    assert argv[argv.index('--user-id') + 1] == 'ou_owner'
    assert '--profile' in argv
    assert argv[argv.index('--profile') + 1] == 'cli_profile'
    assert 'app_secret' not in ' '.join(argv).lower()


def test_lark_cli_transport_reports_missing_member_mapping():
    cfg = feishu_notify.normalize_config({
        'feishu': {
            'transport': 'lark_cli',
            'member_open_ids': {},
        }
    }, {})
    feishu_notify.set_config(cfg)

    with patch.object(feishu_notify.subprocess, 'run') as run:
        warning = feishu_notify.notify_member_event('Owner', 'team_assigned', 'Title')

    assert warning == "成员 'Owner' 未配置飞书 open_id"
    run.assert_not_called()


def test_lark_cli_transport_sends_plain_text_with_stable_idempotency_key():
    cfg = feishu_notify.normalize_config({
        'feishu': {
            'transport': 'lark_cli',
            'member_open_ids': {'Owner': 'ou_owner'},
        }
    }, {})
    feishu_notify.set_config(cfg)

    with patch.object(feishu_notify.subprocess, 'run', return_value=subprocess.CompletedProcess(['lark-cli'], 0, '{}', '')) as run:
        warning = feishu_notify.notify_member_text('Owner', 'line 1\nline 2', 'attention_gate-daily-2026-07-10')

    assert warning is None
    argv = run.call_args.args[0]
    assert argv[argv.index('--text') + 1] == 'line 1\nline 2'
    assert argv[argv.index('--idempotency-key') + 1] == 'attention_gate-daily-2026-07-10'
    assert '--msg-type' not in argv

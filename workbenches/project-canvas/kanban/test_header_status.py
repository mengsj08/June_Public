import importlib.util
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE = HERE / 'static' / 'kanban' / 'modules' / 'header-status.js'


def load_scan_docs():
    spec = importlib.util.spec_from_file_location('scan_docs_header_status', HERE / 'scan-docs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_status_matches_runtime_commands():
    scan_docs = load_scan_docs()
    scan_docs.CLI_COMMANDS = {'present': ['true'], 'missing': ['definitely-not-a-real-kanban-cli']}
    data = scan_docs.get_data()
    assert data['cli_status']['configured'] == 2
    assert data['cli_status']['available'] == 1
    assert data['cli_status']['tools'] == [
        {'name': 'present', 'available': True},
        {'name': 'missing', 'available': False},
    ]


def test_doctor_mutations_require_confirmation():
    node = shutil.which('node')
    assert node, 'node is required'
    script = f"""
      import {{ doctorConfirmation }} from {MODULE.as_uri()!r};
      let prompts = 0;
      if (!doctorConfirmation('diagnose', () => {{ prompts += 1; return false; }})) throw new Error('diagnose blocked');
      if (prompts !== 0) throw new Error('diagnose prompted');
      if (doctorConfirmation('fix', () => {{ prompts += 1; return false; }})) throw new Error('fix bypassed denial');
      if (!doctorConfirmation('emergency', () => {{ prompts += 1; return true; }})) throw new Error('emergency ignored confirmation');
      if (prompts !== 2) throw new Error('mutation confirmation count mismatch');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_local_status_rollup_uses_worst_network_and_cli_health():
    node = shutil.which('node')
    assert node, 'node is required'
    script = f"""
      import {{ localStatusRollup, syncStatusTone }} from {MODULE.as_uri()!r};
      const healthyNetwork = {{ ok: true }};
      const healthyCli = {{ tools: [{{ name: 'claude', available: true }}, {{ name: 'codex', available: true }}] }};
      if (localStatusRollup(healthyNetwork, healthyCli).tone !== 'normal') throw new Error('healthy rollup failed');
      const brokenCli = {{ tools: [{{ name: 'claude', available: true }}, {{ name: 'codex', available: false }}] }};
      if (localStatusRollup(healthyNetwork, brokenCli).tone !== 'bad') throw new Error('CLI failure was hidden');
      const warningNetwork = {{ ok: true, checks: {{ github: {{ health: 'warn' }} }} }};
      if (localStatusRollup(warningNetwork, healthyCli).tone !== 'warn') throw new Error('network warning was hidden');
      if (localStatusRollup(healthyNetwork, healthyCli, {{ enabled: false, state: 'disabled' }}).tone !== 'normal') throw new Error('disabled sync lowered health');
      if (syncStatusTone({{ enabled: true, watcher_status: 'error' }}) !== 'bad') throw new Error('watcher error was hidden');
      if (localStatusRollup(healthyNetwork, healthyCli, {{ enabled: true, watcher_status: 'starting' }}).tone !== 'warn') throw new Error('watcher anomaly was hidden');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_header_has_one_local_status_chip_and_grouped_panel():
    html = (HERE / 'kanban.html').read_text(encoding='utf-8')
    module = MODULE.read_text(encoding='utf-8')
    assert html.count('class="hdr-status-chip') == 1
    assert 'aria-label="打开本机状态"' in html
    assert '<span>本机状态</span>' in html
    assert '<div class="hdr-network-title">本机状态</div>' in module
    assert 'hdr-status-group-title">网络' in module
    assert 'hdr-status-group-title">CLI' in module
    assert 'hdr-status-group-title">同步' in module
    assert 'Git 自动同步' in module
    assert 'id="sync-indicator"' not in html
    assert 'id="overflow-chk-sync-git"' in html

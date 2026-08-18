#!/usr/bin/env python3
"""
项目管理 Kanban - 交互服务器

用法：
    python3 shared/toolkit/kanban/scan-docs.py
    # 浏览器打开 http://localhost:8890
"""

import base64
import html
import hashlib
import hmac
import importlib.util
import mimetypes
import shutil
import os, re, json, sys, subprocess, time, threading, uuid, signal, socket, shlex, secrets, random, tempfile, queue, traceback
from fnmatch import fnmatch
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote, urljoin, quote
import urllib.request, urllib.error
try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

UTC = timezone.utc
html_module_escape = html.escape
MARKDOWN_WRITE_LOCK = threading.Lock()
CANVAS_WRITE_LOCK = threading.Lock()


class JsonBodyError(ValueError):
    pass


def _atomic_write_text(path, content):
    path = Path(path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            dir=str(path.parent),
            prefix=f'.{path.name}.',
            suffix='.tmp',
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        os.replace(str(tmp_path), str(path))
        if path.suffix.lower() == '.md':
            invalidate_scan_cache(path)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


_CLI_PATH_STATIC_BIN_DIRS = (
    '/opt/homebrew/bin',
    '/usr/local/bin',
    os.path.expanduser('~/.local/bin'),
)
_CLI_PATH_REQUIRED_TOOLS = ('claude', 'codex', 'node')


def _split_path_entries(path_value):
    return [entry for entry in str(path_value or '').split(os.pathsep) if entry]


def _dedupe_path_entries(entries):
    result = []
    seen = set()
    for entry in entries:
        if not entry:
            continue
        normalized = os.path.expanduser(str(entry))
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _login_shell_path_entries():
    try:
        proc = subprocess.run(
            ['zsh', '-lic', 'echo $PATH'],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    for line in reversed((proc.stdout or '').splitlines()):
        line = line.strip()
        if line:
            return _split_path_entries(line)
    return []


def _nvm_node_version_key(bin_dir):
    version = Path(bin_dir).parent.name.lstrip('v')
    parts = []
    for part in re.split(r'[^0-9]+', version):
        if part:
            parts.append(int(part))
    return (tuple(parts), str(bin_dir))


def _latest_nvm_node_bin():
    try:
        candidates = [
            path for path in (Path.home() / '.nvm' / 'versions' / 'node').glob('*/bin')
            if path.is_dir()
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return str(max(candidates, key=_nvm_node_version_key))


def _which_with_path(tool, entries):
    return shutil.which(tool, path=os.pathsep.join(entries))


def _resolved_cli_paths():
    resolved = {}
    for tool in _CLI_PATH_REQUIRED_TOOLS:
        found = shutil.which(tool)
        resolved[tool] = str(Path(found).resolve()) if found else None
    return resolved


def _augment_path_for_clis(emit_log=True):
    current_entries = _split_path_entries(os.environ.get('PATH', ''))
    candidate_entries = list(_CLI_PATH_STATIC_BIN_DIRS)
    candidate_entries.extend(_login_shell_path_entries())

    merged_for_probe = _dedupe_path_entries(candidate_entries + current_entries)
    if not _which_with_path('node', merged_for_probe):
        nvm_bin = _latest_nvm_node_bin()
        if nvm_bin:
            candidate_entries.append(nvm_bin)

    candidate_entries = _dedupe_path_entries(candidate_entries)
    current_entries = _split_path_entries(os.environ.get('PATH', ''))
    current_set = set(current_entries)
    prepend_entries = [entry for entry in candidate_entries if entry not in current_set]
    os.environ['PATH'] = os.pathsep.join(prepend_entries + current_entries)

    resolved = _resolved_cli_paths()
    if emit_log:
        for tool in _CLI_PATH_REQUIRED_TOOLS:
            found = resolved.get(tool)
            if found:
                print(f"  INFO PATH: {tool} -> {found}")
            else:
                print(f"  WARN PATH: 未找到 {tool}，AI 运行会失败，请确认安装/PATH")
    return resolved


def _cli_not_found_error(tool):
    return f'{tool} CLI 未找到：已在增强 PATH 中查找仍不可达，请确认已安装并在 PATH'

# ── 配置 ──────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_INSTALL_ROOT = _HERE.parent
REPO_ROOT = Path(
    os.environ.get('KANBAN_REPO_ROOT') or _INSTALL_ROOT
).expanduser().resolve(strict=False)
_STATIC_ROOT = _HERE / 'static'
_STATIC_ROOT_RESOLVED = _STATIC_ROOT.resolve()
_STATIC_MIME_OVERRIDES = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.map': 'application/json; charset=utf-8',
}
_SERVER_VERSION_CACHE = None
_SERVER_VERSION_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _format_server_version_time(timestamp=None):
    if timestamp is None:
        return datetime.now().strftime(_SERVER_VERSION_TIME_FORMAT)
    return datetime.fromtimestamp(timestamp).strftime(_SERVER_VERSION_TIME_FORMAT)


def get_server_version_info():
    global _SERVER_VERSION_CACHE
    if _SERVER_VERSION_CACHE is not None:
        return dict(_SERVER_VERSION_CACHE)

    try:
        proc = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        git_sha = (proc.stdout or '').strip() or 'nogit'
    except Exception:
        git_sha = 'nogit'

    try:
        code_mtime = _format_server_version_time(Path(__file__).resolve().stat().st_mtime)
    except OSError:
        code_mtime = _format_server_version_time()

    _SERVER_VERSION_CACHE = {
        'git_sha': git_sha,
        'code_mtime': code_mtime,
        'started_at': _format_server_version_time(),
    }
    return dict(_SERVER_VERSION_CACHE)


def _load_local_module(module_name, path, *, required=True):
    path = Path(path)
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"required local capability is missing: {path}")
        return None
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


feishu_notify = _load_local_module('kanban_feishu_notify', _HERE / 'feishu_notify.py')
network_doctor_panel = _load_local_module(
    'kanban_network_doctor_panel', _HERE / 'network_doctor_panel.py'
)
platform_adapter = _load_local_module(
    'kanban_platform_adapter', _HERE / 'platform_adapter.py'
)
PLATFORM_ADAPTER = platform_adapter.get_platform_adapter()
server_instance = _load_local_module('kanban_server_instance', _HERE / 'server_instance.py')
outbound_gate = _load_local_module(
    'kanban_outbound_gate', _HERE.parent / 'governance' / 'outbound_gate.py', required=False
)
governance_result_card = _load_local_module(
    'kanban_governance_result_card', _HERE.parent / 'governance' / 'governance_result_card.py', required=False
)
project_map = _load_local_module('kanban_project_map', _HERE / 'project_map.py')
project_canvas_reorganize = _load_local_module(
    'kanban_project_canvas_reorganize', _HERE / 'project_canvas_reorganize.py'
)
task_canvas = _load_local_module('kanban_task_canvas', _HERE / 'task_canvas.py')
canvas_event_ledger = _load_local_module('kanban_canvas_event_ledger', _HERE / 'canvas_event_ledger.py')
studio_static = _load_local_module('kanban_studio_static', _HERE / 'studio_static.py')
canvas_seed = _load_local_module('kanban_canvas_seed', _HERE / 'canvas_seed.py')
ai_run_guard = _load_local_module('kanban_ai_run_guard', _HERE / 'ai_run_guard.py')
ledger_query = _load_local_module('kanban_ledger_query', _HERE / 'ledger_query.py')
comment_import = _load_local_module('kanban_comment_import', _HERE / 'comment_import.py')
skill_invocation = _load_local_module('kanban_skill_invocation', _HERE / 'skill_invocation.py')
conversation_map = _load_local_module('kanban_conversation_map', _HERE / 'conversation_map.py')
conversation_project_graph = _load_local_module(
    'kanban_conversation_project_graph', _HERE / 'conversation_project_graph.py'
)
real_projects = _load_local_module('kanban_real_projects', _HERE / 'real_projects.py')
project_conversations = _load_local_module(
    'kanban_project_conversations', _HERE / 'project_conversations.py'
)
relationship_cards = _load_local_module('kanban_relationship_cards', _HERE / 'relationship_cards.py', required=False)
owner_world = _load_local_module('kanban_owner_world', _HERE / 'owner_world.py', required=False)
mario_levels = _load_local_module('kanban_mario_levels', _HERE / 'mario_levels.py', required=False)
mario_game_projection = _load_local_module('mario_game_projection', _HERE / 'mario_game_projection.py')
render_mario_game_map = _load_local_module(
    'kanban_render_mario_game_map', _HERE / 'render_mario_game_map.py'
)
task_document_links = _load_local_module('kanban_task_document_links', _HERE / 'task_document_links.py')
session_evidence_adapter = _load_local_module(
    'kanban_session_evidence_adapter', _HERE / 'session_evidence_adapter.py'
)
role_policy = _load_local_module('kanban_role_policy', _HERE / 'role_policy.py')
attention_gate = _load_local_module('kanban_attention_gate', _HERE / 'attention_gate.py')
attention_queue = _load_local_module('kanban_attention_queue', _HERE / 'attention_queue.py')
system_alerts = _load_local_module('kanban_system_alerts', _HERE / 'system_alerts.py', required=False)
review_cycle = _load_local_module('kanban_review_cycle', _HERE / 'review_cycle.py')
maintenance_cli = _load_local_module('kanban_maintenance_cli', _HERE / 'maintenance_cli.py')
promote_flow = _load_local_module('kanban_promote_flow', _HERE / 'promote_flow.py')
task_id_allocator = _load_local_module('kanban_task_id_allocator', _HERE / 'task_id_allocator.py')
agent_mail_maintenance = _load_local_module(
    'kanban_agent_mail_maintenance', _HERE / 'agent_mail_maintenance.py'
)
task_scan_cache = _load_local_module('kanban_task_scan_cache', _HERE / 'task_scan_cache.py')


def invalidate_scan_cache(path=None):
    """Invalidate cached task parsing after an in-process Markdown mutation."""
    task_scan_cache.invalidate(path, repo_root=REPO_ROOT)


def requires_owner_action(task):
    return attention_gate.requires_role_action(task, 'owner')

_DEFAULT_KM_CHAIN_STAGES = [
    {
        'key': 'km/source_intake',
        'title': '0. 外部情报入口',
        'responsibility': 'ai-owned',
        'role': 'Scientific_InfoHub、Stork、PubMed/Zotero 导出进入 RKO 前的候选源。',
        'question': '有哪些新东西值得进入研究消化链？',
        'kw': ['infohub', 'stork', 'pubmed', '外部情报', '入口', '候选源'],
    },
    {
        'key': 'km/zotero_master',
        'title': '1. Zotero 文献主库',
        'responsibility': 'ai-owned',
        'role': '元数据、collection、tag、citation key、linked PDF 路径的只读查重与定位层。',
        'question': '这篇文献是什么、在哪里、是否已有？',
        'kw': ['zotero', '快照', 'snapshot', 'citation', 'pdf', '事实源', '主库'],
    },
    {
        'key': 'km/triage_queue',
        'title': '2. Triage / Reading Queue',
        'responsibility': 'shared',
        'role': '把候选文献按主题、tier、优先级和全文可用性分流，先做 dry-run。',
        'question': '下一批该读哪些，哪些只能当背景？',
        'kw': ['triage', 'reading queue', '队列', '分流', 'dry-run', '周报', '登记'],
    },
    {
        'key': 'km/card_reading',
        'title': '3. Reading Log / Paper Card',
        'responsibility': 'shared',
        'role': '逐篇阅读后形成 canonical paper card 和 reading log。',
        'question': '这篇文献实际说明了什么，依据是全文还是摘要？',
        'kw': ['paper card', 'reading log', '卡片', '精读', '建卡', '筛选'],
    },
    {
        'key': 'km/evidence',
        'title': '4. Evidence Matrix',
        'responsibility': 'shared',
        'role': '把单篇文献映射到 claim、tier、basis、confidence 和 next action。',
        'question': '哪些 claim 被哪些证据支撑，强度和边界在哪里？',
        'kw': ['evidence', 'claim', 'tier', '证据', '矩阵', '分发'],
    },
    {
        'key': 'km/synthesis',
        'title': '5. Synthesis / Index / Concept',
        'responsibility': 'shared',
        'role': '主题索引、概念卡、方法卡、综述路线图与写作入口。',
        'question': '如何把证据组织成可复用的判断和写作结构？',
        'kw': ['synthesis', 'index', 'concept', '综述', '写作', '组会', 'handoff'],
    },
    {
        'key': 'km/ops',
        'title': '6. Ops / Automation',
        'responsibility': 'ai-owned',
        'role': '脚本、模板、规则和质量门槛，保证流程可审计、可复跑。',
        'question': '如何安全地刷新、检查和扩展知识系统？',
        'kw': ['ops', 'automation', 'script', 'template', 'lint', '自动化', '治理'],
    },
]

_DEFAULT_CHAINS = [
    {
        'key': 'km',
        'title': '知识管理链',
        'mark': 'KM',
        'provider': '',
        'sub': '外部情报 → Zotero 主库 → Triage 队列 → 阅读建卡 → 证据矩阵 → 综合写作 → 自动化治理',
        'stages': _DEFAULT_KM_CHAIN_STAGES,
    },
]

# 默认配置（无配置文件时的回退值）
_DEFAULTS = {
    'zhipu_api_key': '',
    'deepseek_api_key': '',
    'deepseek_api_url': 'https://api.deepseek.com/chat/completions',
    'deepseek_model': 'deepseek-chat',
    'ai_provider': 'deepseek',
    'paths': {
        'repo_root': '.',
        'workspace_root': '.',
        'data_root': 'demo',
    },
    'open_allowed_roots': ['.', 'demo'],
    'demo_mode': False,
    'canvas_ai': {'enabled': True},
    'canvas_path_rewrites': [],
    'canvas_studio_url': '/canvas',
    'studio_dist_dir': 'canvas-studio/dist',
    'conversation_maps_dir': '',
    # 评论分支耐久台账(KAN-111):user 消息永远全文;ai_content=digest 时 AI 消息只存摘要+指纹
    'comments_ledger': {'enabled': True, 'ai_content': 'digest', 'digest_chars': 2000},
    # Public cold-start: private workspace member bindings are intentionally omitted.
    'members': [],
    'ai_members': [],
    'roles': {
        'owner': {'actor': 'owner', 'member': ''},
        'operator': {'actor': 'operator', 'member': ''},
        'reviewer': {'actor': 'reviewer', 'member': ''},
    },
    'bind_host': '127.0.0.1',
    'allowed_hosts': [],
    'port': 8899,
    'team_kanban_url': 'http://localhost:8899/',
    'team_sync': {
        'enabled': False,
        'source': 'remote_api',
        'local_repo_path': '',
        'local_scan_dirs': ['project'],
        'target_user': '',
        'target_project': '个人调度',
        'pointer_project': '个人调度',
        'handoff_target_project': '',
        'auto_sync': True,
        'interval_seconds': 900,
        'auth_type': 'token',
        'token_header': 'X-Kanban-Token',
        'timeout_seconds': 8,
        'stale_days': 3,
        'due_soon_days': 3,
        'digest_path': 'shared/toolkit/kanban/.team-kanban-digest.json',
        'snapshot_path': 'shared/toolkit/kanban/.team-kanban-snapshot.json',
        'notify_state_path': 'shared/toolkit/kanban/.team-kanban-notify-state.json',
        'handoff_draft_dir': 'shared/toolkit/kanban/.team-handoff-drafts',
        'handoff_publish_enabled': False,
        'handoff_publish_remote': 'origin',
        'handoff_publish_branch': 'main',
        'handoff_publish_worktree_path': 'shared/toolkit/kanban/.team-handoff-publish/team-workspace',
        'handoff_publish_retry_rebase': True,
        'handoff_publish_github_base_url': '',
        'sync_state_path': '',
        'sync_task_manifest_path': '',
    },
    'scan_dirs': ['project'],
    # Optional deployment-local storage for the real-project registry and its
    # sidecars. Relative paths resolve from REPO_ROOT; blank keeps the legacy
    # project/个人调度/.real-projects location.
    'real_projects_dir': '',
    'research_boards_dir': '',
    'research_boards': [],
    'km_chain_data': '',
    'infoops_contract': '',
    'freshness_config': '',
    'chains': [],
    'dynamic_boards': [],
    'brainloop_scenarios_dir': '',
    # Optional sibling/workspace adapters are default-off. A deployment must
    # name each integration, enable it, and provide every local path it needs.
    'integrations': {
        'local_tools': {},
        'infoops': {'enabled': False},
        'workspace_governance': {'enabled': False, 'root': ''},
        'owner_world': {'enabled': False, 'source': ''},
        'relationships': {
            'enabled': False,
            'people_dir': '',
            'team_projection_dir': '',
        },
        'codex_sessions': {'enabled': False, 'roots': []},
        'agent_mail': {'enabled': False, 'cli': ''},
    },
    'skip_patterns': ['SKILL.md', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'LICENSE.md'],
    'ai_max_concurrent': 3,
    's3': {
        'bucket': '',
        'region': '',
        'access_key_id': '',
        'secret_access_key': '',
        'public_base_url': '',
        'upload_url': '',
    },
    'git_sync': {
        'enabled': False,
        'mode': 'desktop',
        'debounce_seconds': 15,
        'desktop_poll_seconds': 30,
        'git_lock_wait_seconds': 3,
        'preferred_remote': 'origin',
        'auto_set_upstream': True,
        'warn_large_file_mb': 10,
        'webhook_secret': '',
    },
    'network_doctor': {'enabled': False, 'script': ''},
    'tools': {
        'claude': {'command': 'claude --print --output-format json --dangerously-skip-permissions'},
        'codex': {'command': 'codex exec --yolo --json'},
    },
    'ai_profiles': {
        'quick_explain': {
            'tool': 'codex',
            'label': 'Codex Luna',
            'mode': 'read_only',
            'command': 'codex exec --model gpt-5.6-luna -c model_reasoning_effort="low" -c sandbox_mode="read-only" -c approval_policy="never" --json',
        },
        'deep_codex': {
            'tool': 'codex',
            'label': 'Codex GPT-5.6',
            'mode': 'read_only',
            'command': 'codex exec --model gpt-5.6-sol -c model_reasoning_effort="high" -c sandbox_mode="read-only" -c approval_policy="never" --json',
        },
        'scoped_write_codex': {
            'tool': 'codex',
            'label': 'Codex 定界执行',
            'mode': 'write',
            'command': 'codex exec --model gpt-5.6-sol -c model_reasoning_effort="high" '
                       '-c sandbox_mode="workspace-write" -c approval_policy="never" '
                       '-c sandbox_workspace_write.network_access=true --json',
        },
        'deep_claude': {
            'tool': 'claude',
            'label': 'Claude Sonnet 5',
            'mode': 'read_only',
            'command': 'claude --print --output-format json --model sonnet --effort high --permission-mode plan',
        },
        'review_codex': {
            'tool': 'codex',
            'label': 'Codex 关键复核',
            'mode': 'read_only',
            'command': 'codex exec --model gpt-5.6-sol -c model_reasoning_effort="xhigh" -c sandbox_mode="read-only" -c approval_policy="never" --json',
        },
        'review_claude': {
            'tool': 'claude',
            'label': 'Claude Opus 关键复核',
            'mode': 'read_only',
            'command': 'claude --print --output-format json --model opus --effort xhigh --permission-mode plan',
        },
        'execute_codex': {
            'tool': 'codex',
            'label': 'Codex 执行',
            'mode': 'write',
            'command': 'codex exec --model gpt-5.6-sol -c model_reasoning_effort="high" --yolo --json',
        },
        'execute_claude': {
            'tool': 'claude',
            'label': 'Claude 执行',
            'mode': 'write',
            'command': 'claude --print --output-format json --model opus --effort xhigh --dangerously-skip-permissions',
        },
    },
    'feishu': {
        'app_id': '',
        'app_secret': '',
        'kanban_base_url': '',
        'member_open_ids': {},
        'transport': 'api',
        'lark_cli_path': 'lark-cli',
        'lark_cli_profile': '',
        'lark_cli_as': 'bot',
    },
    'auth': {
        'mode': 'token',
        'token_file': '.kanban.auth-token',
        'local_bypass': False,
        'autologin': False,
        'bypass_user': '',
        'session_ttl_seconds': 604800,
    },
}

def _deep_merge(base, override):
    """深度合并两个字典，override 优先级更高。不修改 base。"""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result

def load_user_config():
    """加载用户配置文件（不与默认值合并）。"""
    user_cfg_path = REPO_ROOT / '.kanban.user.config.json'
    if not user_cfg_path.exists():
        return {}
    try:
        with open(user_cfg_path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"  警告: 无法加载 {user_cfg_path}: {e}")
        return {}


_S3_ENV_MAP = {
    'bucket': 'KANBAN_S3_BUCKET',
    'region': 'KANBAN_S3_REGION',
    'access_key_id': 'KANBAN_S3_ACCESS_KEY_ID',
    'secret_access_key': 'KANBAN_S3_SECRET_ACCESS_KEY',
    'public_base_url': 'KANBAN_S3_PUBLIC_BASE_URL',
    'upload_url': 'KANBAN_S3_UPLOAD_URL',
}


def _normalize_s3_config(config):
    """从配置文件读取 S3 配置，并对缺失字段回退到环境变量。"""
    raw_s3 = config.get('s3', {}) if isinstance(config, dict) else {}
    raw_s3 = raw_s3 if isinstance(raw_s3, dict) else {}
    normalized = {}
    for key, env_name in _S3_ENV_MAP.items():
        value = raw_s3.get(key) or os.environ.get(env_name, '')
        value = str(value).strip()
        if key in ('public_base_url', 'upload_url'):
            value = value.rstrip('/')
        normalized[key] = value
    return normalized


def _normalize_string_list(value):
    if not isinstance(value, list):
        return []
    normalized = []
    seen = set()
    for item in value:
        text = str(item or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


class ScanDirAllowlistError(RuntimeError):
    pass


def _scan_allowlist_path():
    return REPO_ROOT / '.kanban.scan-allowlist.json'


def _normalize_scan_dir_for_allowlist(value):
    raw = str(value or '').strip()
    if not raw:
        return '', None
    expanded = Path(os.path.expanduser(raw))
    candidate = expanded if expanded.is_absolute() else REPO_ROOT / expanded
    resolved = candidate.resolve(strict=False)
    try:
        display = str(resolved.relative_to(REPO_ROOT.resolve(strict=False)))
    except ValueError:
        display = str(resolved)
    return display.rstrip('/'), resolved


def _load_scan_allowlist():
    allowlist_path = _scan_allowlist_path()
    if not allowlist_path.exists():
        raise ScanDirAllowlistError(f'白名单文件缺失: {allowlist_path}')
    try:
        data = json.loads(allowlist_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScanDirAllowlistError(f'白名单文件不可读取: {allowlist_path} ({exc})') from exc
    entries = data.get('scan_dirs') if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ScanDirAllowlistError(f'白名单文件必须提供非空 scan_dirs 数组: {allowlist_path}')
    allowed = {}
    for item in entries:
        display, resolved = _normalize_scan_dir_for_allowlist(item)
        if not display or resolved is None:
            continue
        allowed[resolved] = display
    if not allowed:
        raise ScanDirAllowlistError(f'白名单文件没有有效 scan_dirs: {allowlist_path}')
    return allowed, allowlist_path


def validate_scan_dirs_against_allowlist(scan_dirs):
    if not isinstance(scan_dirs, list) or not all(isinstance(x, str) for x in scan_dirs):
        raise ScanDirAllowlistError('scan_dirs 必须是字符串数组')
    allowed, allowlist_path = _load_scan_allowlist()
    extra = []
    for item in scan_dirs:
        display, resolved = _normalize_scan_dir_for_allowlist(item)
        if not display or resolved not in allowed:
            extra.append(display or str(item))
    if extra:
        allowed_display = ', '.join(sorted(allowed.values()))
        extra_display = ', '.join(extra)
        raise ScanDirAllowlistError(
            f'scan_dirs 越界拒扫: {extra_display}; 白名单文件: {allowlist_path}; '
            f'允许: {allowed_display}'
        )
    return True


def _configured_scan_dirs(config):
    scan_dirs = config.get('scan_dirs', _DEFAULTS['scan_dirs']) if isinstance(config, dict) else _DEFAULTS['scan_dirs']
    validate_scan_dirs_against_allowlist(scan_dirs)
    return list(scan_dirs)


def _configured_scan_dirs_or_exit(config):
    try:
        return _configured_scan_dirs(config)
    except ScanDirAllowlistError as exc:
        print(f'scan_dirs 白名单拒扫: {exc}', file=sys.stderr)
        raise SystemExit(2) from exc


def _combined_assignee_members(human_members, ai_members):
    combined = []
    if isinstance(human_members, list):
        combined.extend(human_members)
    if isinstance(ai_members, list):
        combined.extend(ai_members)
    return _normalize_string_list(combined)


def _normalize_feishu_config(config):
    """从配置文件读取飞书配置，并对缺失字段回退到环境变量。"""
    return feishu_notify.normalize_config(config, os.environ)


def load_config():
    """加载并合并配置：默认值 ← .kanban.config.json ← .kanban.user.config.json"""
    config = dict(_DEFAULTS)

    configured_path = str(os.environ.get('KANBAN_CONFIG') or '').strip()
    project_cfg_path = Path(configured_path).expanduser() if configured_path else REPO_ROOT / '.kanban.config.json'
    if not project_cfg_path.is_absolute():
        project_cfg_path = REPO_ROOT / project_cfg_path
    if project_cfg_path.exists():
        try:
            with open(project_cfg_path, encoding='utf-8') as f:
                project_cfg = json.load(f)
            config = _deep_merge(config, project_cfg)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  警告: 无法加载 {project_cfg_path}: {e}")

    user_cfg = load_user_config()
    if user_cfg:
        # dynamic_boards/chains 是中心白名单配置，只允许项目配置声明；用户偏好文件不得注入可执行 provider 或链路来源。
        user_cfg = {key: val for key, val in user_cfg.items() if key not in ('dynamic_boards', 'chains')}
        config = _deep_merge(config, user_cfg)

    # 向后兼容：配置文件未指定 API key 时，回退到环境变量
    if not config.get('zhipu_api_key'):
        config['zhipu_api_key'] = os.environ.get('ZHIPU_API_KEY', '')
    if not config.get('deepseek_api_key'):
        config['deepseek_api_key'] = os.environ.get('DEEPSEEK_API_KEY', '')
    config['ai_members'] = _normalize_string_list(config.get('ai_members'))
    config['members'] = _normalize_string_list(config.get('members'))
    config['roles'] = role_policy.normalize_roles(config.get('roles'))
    config['s3'] = _normalize_s3_config(config)
    config['feishu'] = _normalize_feishu_config(config)

    return config


def _auth_config(config=None):
    source = config if isinstance(config, dict) else load_config()
    auth_cfg = source.get('auth') if isinstance(source.get('auth'), dict) else {}
    return auth_cfg


def _auth_bypass_user(auth_cfg, *, allow_legacy_user=False, default_first_member=False):
    user = str(auth_cfg.get('bypass_user') or '').strip()
    if not user and allow_legacy_user:
        user = str(auth_cfg.get('user') or '').strip()
    if not user and default_first_member and ALL_MEMBERS:
        user = ALL_MEMBERS[0]
    return user


def _session_actor(session, config=None):
    source = config if isinstance(config, dict) else load_config()
    member = (session or {}).get('user') if isinstance(session, dict) else ''
    return role_policy.actor_for_member(source.get('roles'), member)


def _configured_root(name, config=None):
    """Resolve a declared deployment root relative to the checked-out repo."""
    source = config if isinstance(config, dict) else load_config()
    paths = source.get('paths') if isinstance(source.get('paths'), dict) else {}
    defaults = _DEFAULTS.get('paths', {})
    raw = str(paths.get(name) or defaults.get(name) or '.').strip() or '.'
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve(strict=False)


def configured_deployment_paths(config=None):
    source = config if isinstance(config, dict) else load_config()
    return {
        name: str(_configured_root(name, source))
        for name in ('repo_root', 'workspace_root', 'data_root')
    }


def _configured_role_member(role, config=None):
    source = config if isinstance(config, dict) else load_config()
    return role_policy.member_for_role(source.get('roles'), role)

def parse_command_string(cmd_str):
    """将命令字符串解析为参数列表，正确处理引号。"""
    return shlex.split(cmd_str)


_AI_PROFILE_NAME_RE = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')


def normalize_ai_profiles(config):
    """Normalize configured AI profiles without exposing command strings to the browser."""
    source = config if isinstance(config, dict) else {}
    raw_profiles = source.get('ai_profiles') if isinstance(source.get('ai_profiles'), dict) else {}
    raw_tools = source.get('tools') if isinstance(source.get('tools'), dict) else {}
    profiles = {}
    for raw_name, raw_profile in raw_profiles.items():
        name = str(raw_name or '').strip()
        if not _AI_PROFILE_NAME_RE.fullmatch(name) or not isinstance(raw_profile, dict):
            continue
        tool = str(raw_profile.get('tool') or '').strip().lower()
        if tool not in {'claude', 'codex'}:
            continue
        tool_cfg = raw_tools.get(tool) if isinstance(raw_tools.get(tool), dict) else {}
        command = str(raw_profile.get('command') or tool_cfg.get('command') or '').strip()
        if not command:
            continue
        profiles[name] = {
            'tool': tool,
            'label': str(raw_profile.get('label') or name).strip()[:80],
            'mode': str(raw_profile.get('mode') or 'read_only').strip().lower(),
            'command': parse_command_string(command),
        }
    return profiles


def public_ai_profiles(profiles):
    return {
        name: {key: profile.get(key) for key in ('tool', 'label', 'mode')}
        for name, profile in (profiles or {}).items()
    }


def _ai_command_for_entry(tool, entry=None):
    profile_name = str((entry or {}).get('ai_profile') or '').strip()
    if profile_name:
        profile = AI_PROFILES.get(profile_name)
        if not profile or profile.get('tool') != tool:
            return None
        return list(profile.get('command') or [])
    command = CLI_COMMANDS.get(tool)
    return list(command) if command else None


def _default_ai_profile(tool, dialogue_origin='', *, has_custom_prompt=False):
    if dialogue_origin == 'selection_quick_explain':
        name = 'quick_explain'
    elif dialogue_origin in {'selection_side_chat', 'card_chat', 'canvas'}:
        # canvas 对话节点是问答面:默认只读 deep 档,写入必须显式请求 execute profile
        name = f'deep_{tool}'
    elif not has_custom_prompt:
        name = f'execute_{tool}'
    else:
        return ''
    return name if name in AI_PROFILES else ''


def resolve_ai_profile(tool, requested='', dialogue_origin='', *, has_custom_prompt=False):
    name = str(requested or '').strip()
    expected = _default_ai_profile(
        tool,
        dialogue_origin,
        has_custom_prompt=has_custom_prompt,
    )
    if not name:
        name = expected
    if not name:
        return '', ''
    if not _AI_PROFILE_NAME_RE.fullmatch(name):
        return '', 'AI profile 名称无效'
    profile = AI_PROFILES.get(name)
    if not profile:
        return '', f'未知 AI profile: {name}'
    if profile.get('tool') != tool:
        return '', f'AI profile {name} 不属于 {tool}'
    if dialogue_origin in {'selection_quick_explain', 'selection_side_chat', 'card_chat'}:
        if expected and name != expected:
            return '', f'{dialogue_origin} 只允许 profile {expected}'
    return name, ''

def normalize_due_date(value):
    """规范化 due_date：空白视为空，非空时必须是合法 YYYY-MM-DD。"""
    if value is None:
        return True, ''
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return True, ''
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return False, ''
    return True, value

def _load_git_sync_module():
    module_path = Path(__file__).resolve().parent / 'git-sync.py'
    spec = importlib.util.spec_from_file_location('kanban_git_sync', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_GIT_SYNC_MODULE = None

def get_git_sync_module():
    global _GIT_SYNC_MODULE
    if _GIT_SYNC_MODULE is None:
        _GIT_SYNC_MODULE = _load_git_sync_module()
    return _GIT_SYNC_MODULE

def _active_sync_manager():
    """Return the active sync manager."""
    return GIT_SYNC_MANAGER

def _sync_disabled_status(mode):
    status = {
        'enabled': False,
        'mode': mode,
        'state': 'disabled',
        'branch': None,
        'upstream': None,
        'ahead': 0,
        'behind': 0,
        'last_error': None,
        'updated_at': None,
    }
    if mode == 'git':
        status.update({
            'mode': 'desktop',
            'watcher_status': 'disabled',
            'pending_files_count': 0,
            'pending_paths': [],
            'last_warning': None,
        })
    return status

def _sync_status_payload():
    git_status = (
        GIT_SYNC_MANAGER.get_status_snapshot()
        if GIT_SYNC_MANAGER
        else _sync_disabled_status('git')
    )
    active_status = git_status
    payload = dict(active_status)
    payload['active_mode'] = 'git'
    payload['managers'] = {
        'git': git_status,
    }
    return payload

def _file_rev(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

# 模块级全局变量（由 main_serve() 从配置文件初始化）
SCAN_DIRS = _DEFAULTS['scan_dirs']
PORT = _DEFAULTS['port']
BIND_HOST = _DEFAULTS['bind_host']
ALLOWED_HOSTS = {'localhost', '127.0.0.1'}
ALL_MEMBERS = _DEFAULTS['members']
LOGIN_MEMBERS = []
ROLE_CONFIG = role_policy.normalize_roles(_DEFAULTS['roles'])
AI_MAX_CONCURRENT = _DEFAULTS['ai_max_concurrent']
ZHIPU_API_KEY = _DEFAULTS['zhipu_api_key']
ZHIPU_API_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
ZHIPU_MODEL = 'glm-5.1'
S3_CONFIG = dict(_DEFAULTS['s3'])
FEISHU_CONFIG = dict(_DEFAULTS['feishu'])
feishu_notify.set_config(FEISHU_CONFIG)
CLI_COMMANDS = {
    name: parse_command_string(cfg['command'])
    for name, cfg in _DEFAULTS['tools'].items()
}
AI_PROFILES = normalize_ai_profiles(_DEFAULTS)
CURRENT_MEMBER = ''
GIT_SYNC_MANAGER = None
TEAM_SYNC_MANAGER = None
_DYNAMIC_BOARD_LOCKS = {}
_DYNAMIC_BOARD_LOCKS_GUARD = threading.Lock()
_DYNAMIC_BOARD_LAST_RESULTS = {}
_DYNAMIC_BOARD_AUTO_RUNS = {}
_DYNAMIC_BOARD_AUTO_RUNS_GUARD = threading.Lock()
DYNAMIC_BOARD_AUTO_DEBOUNCE_SECONDS = 1800

_SYNC_WEBHOOK_PATH = '/api/sync/webhook'
_STATE_CHANGE_METHODS = frozenset({'POST', 'PUT', 'DELETE'})
_STATE_CHANGE_GUARD_EXEMPT_PATHS = frozenset({_SYNC_WEBHOOK_PATH})
_LOCAL_HOSTS = {'localhost', '127.0.0.1'}
_HEALTH_FINGERPRINT = 'project-canvas/health-v1'
_USER_CONFIG_ALLOWED_KEYS = {'tools'}
_USER_CONFIG_DENIED_KEYS = {
    'clash',
    'tag',
    'network_doctor',
    'auth',
    'open_allowed_roots',
    'km_chain_data',
    'infoops_contract',
    'freshness_config',
    'chains',
    'dynamic_boards',
    's3',
    'feishu',
    'brainloop_scenarios_dir',
    'members',
    'roles',
    'team_sync',
    'port',
    'scan_dirs',
    'paths',
    'integrations',
    'canvas_ai',
    'demo_mode',
    'conversation_maps_dir',
    'research_boards_dir',
    'research_boards',
}
_USER_CONFIG_DENIED_SUFFIXES = ('_api_url', '_api_key')
_OPEN_EXECUTABLE_SUFFIXES = {
    '.app',
    '.command',
    '.terminal',
    '.workflow',
    '.scpt',
    '.applescript',
    '.webloc',
}

# ── 认证（Auth）──────────────────────────────────────────
_sessions = {}         # token -> {"user": str, "created_at": float}
_login_attempts = {}   # ip -> {"count": int, "locked_until": float}
_quiz_tokens = {}      # quiz_token -> {"options": [str], "correct_indices": [int], "created_at": float}
AUTH_MODE = _DEFAULTS['auth']['mode']
AUTH_ACCESS_TOKEN = ''
AUTH_TOKEN_PATH = None


def _auth_mode(config=None):
    mode = str(_auth_config(config).get('mode') or _DEFAULTS['auth']['mode']).strip().lower()
    return mode if mode in {'token', 'quiz'} else _DEFAULTS['auth']['mode']


def _auth_token_path(config=None):
    auth_cfg = _auth_config(config)
    raw = str(auth_cfg.get('token_file') or _DEFAULTS['auth']['token_file']).strip()
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    if candidate.is_symlink():
        raise ValueError(f'拒绝使用符号链接 token 文件: {candidate}')
    candidate = candidate.resolve(strict=False)
    repo_root = REPO_ROOT.resolve(strict=False)
    if not _path_is_relative_to(candidate, repo_root):
        raise ValueError('auth.token_file 必须位于仓库内')
    return candidate


def _ensure_local_auth_token(config=None):
    """Create/read the local bearer secret with owner-only filesystem permissions."""
    path = _auth_token_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f'拒绝使用符号链接 token 文件: {path}')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = None
    if fd is not None:
        token = secrets.token_urlsafe(32)
        try:
            os.write(fd, (token + '\n').encode('utf-8'))
        finally:
            os.close(fd)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f'token 路径必须是仓库内普通文件: {path}')
    try:
        os.chmod(path, 0o600)
        token = path.read_text(encoding='utf-8').strip()
    except OSError as exc:
        raise ValueError(f'无法读取本地 token 文件 {path}: {exc}') from exc
    if len(token) < 32:
        raise ValueError(f'本地 token 文件无效或过短: {path}')
    return token, path


def _session_ttl_seconds():
    try:
        ttl = float(_auth_config().get('session_ttl_seconds', _DEFAULTS['auth']['session_ttl_seconds']))
    except (TypeError, ValueError):
        ttl = float(_DEFAULTS['auth']['session_ttl_seconds'])
    return ttl if ttl > 0 else float(_DEFAULTS['auth']['session_ttl_seconds'])


def _session_is_expired(session, now=None):
    if not isinstance(session, dict):
        return True
    created_at = session.get('created_at', 0)
    try:
        created_at = float(created_at)
    except (TypeError, ValueError):
        return True
    if created_at <= 0:
        return False
    now = time.time() if now is None else now
    return now - created_at > _session_ttl_seconds()


def _cleanup_expired_sessions(now=None):
    now = time.time() if now is None else now
    expired = [token for token, session in _sessions.items() if _session_is_expired(session, now)]
    for token in expired:
        _sessions.pop(token, None)


def _session_from_cookie_header(cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(';'):
        part = part.strip()
        if part.startswith('kanban_session='):
            token = part.split('=', 1)[1].strip()
            session = _sessions.get(token)
            if session and session.get('user') in ALL_MEMBERS and not _session_is_expired(session):
                return session
            return None
    return None

QUIZ_QUESTION = "关于 AI 的底层规律，下列说法正确的有（多选）："
QUIZ_OPTIONS = [
    ("凡是可以用 HTML 展示的最终都会用 HTML 展示", True),
    ("凡是可以做成 skill 的，最终都会变成 skill", True),
    ("AI 不能代替决策", True),
    ("凡是可以原生开发的，最终都会抛弃网页端", False),
    ("凡是 AI 能处理的工作，最终都会完全替代人", False),
    ("凡是可以封装成插件的，最终都会全部废弃不用", False),
    ("凡是低代码能实现的，最终都会回归原生代码", False),
    ("凡是自动化能落地的，最终都会取消人工审核", False),
    ("凡是复杂业务场景，最终都不适合做成 Skill", False),
    ("凡是移动端需求，最终都会脱离浏览器生态", False),
]
QUIZ_TIMEOUT = 60  # seconds

ALLOWED_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}
_AWS_ALGORITHM = 'AWS4-HMAC-SHA256'

# ── 文件分类（@文件引用功能）──────────────────────────────
_FILE_CATEGORIES = {
    '.md': 'document',
    '.py': 'code', '.js': 'code', '.ts': 'code', '.jsx': 'code', '.tsx': 'code',
    '.vue': 'code', '.go': 'code', '.rs': 'code', '.java': 'code', '.c': 'code',
    '.cpp': 'code', '.h': 'code', '.rb': 'code', '.php': 'code', '.swift': 'code',
    '.kt': 'code', '.sh': 'code', '.bash': 'code', '.sql': 'code', '.yaml': 'code',
    '.yml': 'code', '.toml': 'code', '.json': 'code', '.xml': 'code', '.html': 'code',
    '.css': 'code', '.scss': 'code', '.less': 'code', '.sass': 'code',
    '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image',
    '.webp': 'image', '.svg': 'image', '.bmp': 'image', '.ico': 'image',
    '.pdf': 'document', '.ppt': 'document', '.pptx': 'document', '.doc': 'document',
    '.docx': 'document', '.xls': 'document', '.xlsx': 'document', '.key': 'document',
    '.numbers': 'document',
}

def _classify_file(name, is_dir):
    if is_dir:
        return 'folder'
    ext = Path(name).suffix.lower()
    return _FILE_CATEGORIES.get(ext, 'other')

# ── AI CLI 配置 ─────────────────────────────────────────
_ai_semaphore = None  # 在 main_serve() 中初始化
_ai_runs = {}  # run_id → { proc, thread, path, tool, status, started_at }
_ai_runs_lock = threading.Lock()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def service_actions(self):
        repo_root = getattr(self, 'kanban_repo_root', None)
        port = getattr(self, 'kanban_port', None)
        if repo_root is not None and port is not None:
            server_instance.ensure_pidfile_owner(repo_root, port)
        now = time.monotonic()
        if now - getattr(self, '_last_orphan_reconcile_at', 0.0) >= 2.0:
            self._last_orphan_reconcile_at = now
            _reconcile_orphaned_runs()

# ── 项目编号生成 ──────────────────────────────────────

# 常用汉字拼音首字母映射（覆盖项目名常用字）
_PINYIN_MAP = {
    '本': 'B', '地': 'D', '看': 'K', '板': 'B', '项': 'X', '目': 'M',
    '工': 'G', '作': 'Z', '台': 'T', '客': 'K', '户': 'H', '管': 'G',
    '理': 'L', '系': 'X', '统': 'T', '服': 'F', '务': 'W', '平': 'P',
    '数': 'S', '据': 'J', '中': 'Z', '心': 'X', '运': 'Y', '营': 'Y',
    '产': 'C', '品': 'P', '设': 'S', '计': 'J', '开': 'K', '发': 'F',
    '测': 'C', '试': 'S', '部': 'B', '署': 'S', '监': 'J', '控': 'K',
    '报': 'B', '表': 'B', '分': 'F', '析': 'X', '用': 'Y', '文': 'W',
    '档': 'D', '配': 'P', '置': 'Z', '安': 'A', '全': 'Q', '网': 'W',
    '络': 'L', '接': 'J', '口': 'K', '前': 'Q', '端': 'D', '后': 'H',
    '移': 'Y', '动': 'D', '桌': 'Z', '面': 'M', '智': 'Z', '回': 'H',
    '科': 'K', '技': 'J', '团': 'T', '队': 'D', '任': 'R', '编': 'B',
    '码': 'M', '新': 'X', '建': 'J', '创': 'C', '业': 'Y', '销': 'X',
    '售': 'S', '市': 'S', '场': 'C', '内': 'N', '容': 'R', '营': 'Y',
    '助': 'Z', '手': 'S', '学': 'X', '习': 'X', '教': 'J', '程': 'C',
    '电': 'D', '商': 'S', '物': 'W', '流': 'L', '支': 'Z', '付': 'F',
    '订': 'D', '单': 'D', '库': 'K', '存': 'C', '供': 'G', '应': 'Y',
    '链': 'L', '资': 'Z', '源': 'Y', '信': 'X', '息': 'X', '消': 'X',
    '通': 'T', '知': 'Z', '日': 'R', '志': 'Z', '权': 'Q', '限': 'X',
}

def get_project_code_prefix(project_name):
    """
    从项目名生成3字母前缀编码。
    按字符出现顺序取前3个有效字母：
    - 英文字母：直接取大写
    - 中文字符：取拼音首字母
    - 非字母字符（-、数字等）：跳过

    示例：
      Hermes -> HER
      Sell-What -> SEL
      team-card -> TEA
      本地kanban -> BDK
      Polo-工作台 -> POL
    """
    result = []
    for ch in project_name:
        if len(result) >= 3:
            break
        if ch.isascii() and ch.isalpha():
            result.append(ch.upper())
        elif ch in _PINYIN_MAP:
            result.append(_PINYIN_MAP[ch])
        elif '\u4e00' <= ch <= '\u9fff':
            # 未知汉字用 X 占位
            result.append('X')
        # 其他字符（-、空格、数字）跳过

    # 不足3位用 X 补齐
    while len(result) < 3:
        result.append('X')

    return ''.join(result[:3])


DISPATCH_PROJECT_NAMES = {'个人调度', '场景库运营'}
ACTIVE_TASK_STATUSES = {'todo', 'in-progress', 'review'}

TASK_FAMILY_PREFIXES = {
    'kanban': 'KAN',
    'governance': 'GOV',
    'documents': 'DOC',
    'skill': 'SKL',
    'knowledge': 'KMO',
    'chain': 'CHN',
    'scenario': 'SCN',
    'research': 'RSH',
    'ops': 'OPS',
    'legacy': 'XXX',
}

TASK_FAMILY_ALIASES = {
    'kanban': 'kanban',
    'board': 'kanban',
    '治理': 'governance',
    'governance': 'governance',
    'gov': 'governance',
    'documents': 'documents',
    'doc': 'documents',
    'doctor': 'documents',
    'skill': 'skill',
    'skills': 'skill',
    'skl': 'skill',
    'knowledge': 'knowledge',
    'km': 'knowledge',
    'kmo': 'knowledge',
    'infoops': 'knowledge',
    'chain': 'chain',
    'chains': 'chain',
    'chn': 'chain',
    'scenario': 'scenario',
    'scene': 'scenario',
    'scn': 'scenario',
    'research': 'research',
    'rsh': 'research',
    'ops': 'ops',
    'operation': 'ops',
    'legacy': 'legacy',
    'unclassified': 'legacy',
    'xxx': 'legacy',
}


def normalize_task_family(value):
    key = str(value or '').strip()
    if not key:
        return ''
    return TASK_FAMILY_ALIASES.get(key.lower(), TASK_FAMILY_ALIASES.get(key, key.lower()))


def _task_text_blob(*values):
    parts = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return ' '.join(parts).lower()


def is_dispatch_project(project_name):
    return str(project_name or '').strip() in DISPATCH_PROJECT_NAMES


def infer_task_family(project_name, *, title='', body='', workdir='', tags=None, domain='', stage='', task_family=''):
    """Infer the stable task family used for personal dispatch task IDs."""
    explicit = normalize_task_family(task_family)
    if explicit:
        return explicit

    project = str(project_name or '').strip()
    if project == '场景库运营':
        return 'scenario'

    if not is_dispatch_project(project):
        return ''

    stage_text = str(stage or '').strip().lower()
    domain_text = str(domain or '').strip().lower()
    tags_text = _task_text_blob(tags)
    text = _task_text_blob(project, title, body, workdir, tags, domain, stage)

    if stage_text.startswith(('governance/', 'security/')):
        return 'governance'
    if stage_text.startswith(('km/', 'infoops/')):
        return 'knowledge'
    if stage_text.startswith(('meeting/', 'content/', 'team/')):
        return 'chain'
    if stage_text.startswith('scenario/'):
        return 'scenario'
    if stage_text.startswith('research/'):
        return 'research'
    if stage_text.startswith('ops/'):
        return 'ops'

    domain_family = normalize_task_family(domain_text)
    if domain_family in ('governance', 'knowledge', 'scenario', 'research', 'documents', 'skill', 'ops'):
        return domain_family

    if any(token in tags_text for token in ('meeting-chain', 'content-chain', 'chains', '链路梳理')):
        if domain_text == 'knowledge' or stage_text.startswith(('km/', 'infoops/')):
            return 'knowledge'
        return 'chain'
    if any(token in tags_text for token in ('km', 'knowledge', 'infoops', 'zotero', 'reading', 'triage')):
        return 'knowledge'
    if any(token in tags_text for token in ('governance', 'security', '命名', '规则')):
        return 'governance'
    if any(token in tags_text for token in ('scenario', '场景')):
        return 'scenario'
    if any(token in tags_text for token in ('research', '科研')):
        return 'research'
    if any(token in tags_text for token in ('skill', 'skills', 'skill-board', 'skillboard')):
        return 'skill'

    if 'meeting-chain' in text or 'content-chain' in text or '会议链' in text or '团队链' in text or '内容链' in text or '信息路由链' in text or '链路梳理' in text:
        if 'km 知识管理链' in text or '知识管理链' in text or 'knowledgemanagement' in text:
            return 'knowledge'
        return 'chain'
    if '/skills/' in text or text.endswith('/skills') or 'skillboard' in text or 'skill-board' in text or 'skill治理' in text or 'skill 注册' in text:
        return 'skill'
    if 'documents体检' in text or 'documents 体检' in text or '工作区体检' in text or 'scan_governance' in text or 'documents-doctor' in text:
        return 'documents'
    if 'knowledgemanagement' in text or 'infoops' in text or 'zotero' in text or 'stork' in text or 'km_' in text or 'km ' in text or '知识管理' in text:
        return 'knowledge'
    if 'researchlab' in text or 'researchprojects' in text or 'research-advisory' in text or '研究方法' in text or '科研' in text:
        return 'research'
    if '会议链' in text or '团队链' in text or '内容链' in text or '信息路由链' in text or '链路梳理' in text or 'meeting-chain' in text or 'content-chain' in text:
        return 'chain'
    if 'scenario' in text or '场景库' in text or '场景运营' in text or 'brainloop-lite/scenarios' in text:
        return 'scenario'
    if 'uu远程' in text or 'terminal' in text or 'remote-control' in text or 'automation-control-plane' in text or '自动化控制' in text:
        return 'ops'
    if 'governance' in text or '治理' in text or '命名' in text or '规则' in text or '验收标准' in text or 'security' in text:
        return 'governance'
    if 'shared/toolkit/kanban' in text or 'kanban-personal' in text or '调度台' in text or '看板' in text or 'landing' in text:
        return 'kanban'
    return 'legacy'


def task_prefix_for(project_name, *, title='', body='', workdir='', tags=None, domain='', stage='', task_family=''):
    family = infer_task_family(
        project_name,
        title=title,
        body=body,
        workdir=workdir,
        tags=tags,
        domain=domain,
        stage=stage,
        task_family=task_family,
    )
    if family:
        return TASK_FAMILY_PREFIXES.get(family, TASK_FAMILY_PREFIXES['legacy'])
    return get_project_code_prefix(project_name)


def infer_execution_profile(workdir='', *, task_family=''):
    """Map a real execution directory to a coarse trust/execution profile."""
    family = normalize_task_family(task_family)
    raw = str(workdir or '').strip()
    text = raw.lower()
    if not raw:
        return ''
    if raw.startswith(('project/', 'demo/', 'shared/', 'landing/')):
        return 'kanban'
    if '/skills/' in text or text.endswith('/skills'):
        return 'skills'
    if 'knowledgemanagement' in text:
        return 'knowledge'
    if 'researchlab' in text:
        return 'research'
    if '/taskspace' in text:
        return 'taskspace'
    if 'shape-of-thought' in text or 'team-workspace' in text:
        return 'team_workspace'
    if '/ai-agent-hub/kanban-personal' in text:
        return 'kanban'
    if '/ai-agent-hub/' in text:
        return 'ai_agent_hub'
    if text.startswith('~/documents'):
        return 'documents'
    if family == 'skill':
        return 'skills'
    if family in ('kanban', 'governance'):
        return 'kanban'
    return 'external_repo'


# ── 状态文件管理（task_id 计数器）──────────────────────

STATE_FILE = Path(__file__).resolve().parent / '.kanban-state.json'

def load_state():
    """加载状态文件。不存在或损坏则返回空计数器。"""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        pass
    return {'version': 1, 'counters': {}}

def save_state(state):
    """原子写入状态文件：先写临时文件再 rename，防止写入中途崩溃导致损坏。"""
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(str(tmp), str(STATE_FILE))

def rebuild_state_from_tasks(all_docs):
    """从现有任务的 task_id 重建状态文件计数器（用于状态丢失恢复）。"""
    counters = {}
    for doc in all_docs:
        code = doc.get('task_id', '')
        if not code:
            continue
        # 解析 task_id: "HER-1" -> prefix="HER", seq=1
        m = re.match(r'^([A-Z]{3})-(\d+)$', code)
        if not m:
            continue
        prefix, seq = m.group(1), int(m.group(2))
        if prefix not in counters or seq > counters[prefix]:
            counters[prefix] = seq
    return {'version': 1, 'counters': counters}

def ensure_counters_in_sync(all_docs, state):
    """确保计数器 >= 每个前缀的实际最大 task_id，防止手动创建导致的计数器漂移。"""
    counters = state.get('counters', {})

    # 扫描所有 task_id，找到每个前缀的最大序号
    actual_max = {}
    for doc in all_docs:
        code = doc.get('task_id', '')
        if not code:
            continue
        m = re.match(r'^([A-Z]{3})-(\d+)$', code)
        if not m:
            continue
        prefix, seq = m.group(1), int(m.group(2))
        if prefix not in actual_max or seq > actual_max[prefix]:
            actual_max[prefix] = seq

    # 将落后于实际的计数器提升到实际最大值
    bumped = 0
    for prefix, max_seq in actual_max.items():
        if counters.get(prefix, 0) < max_seq:
            counters[prefix] = max_seq
            bumped += 1

    # 移除幽灵计数器（无对应任务文件的前缀）
    phantoms = 0
    for prefix in list(counters.keys()):
        if prefix not in actual_max:
            del counters[prefix]
            phantoms += 1

    state['counters'] = counters
    return bumped, phantoms


# ── task_id 回填与冲突处理 ──────────────────────────

def backfill_task_ids(all_docs, state):
    """
    扫描所有任务，对缺少 task_id 的自动分配并写回 YAML。
    按项目分组，项目内按 created 日期排序，从计数器当前值+1 开始分配。
    """
    from collections import defaultdict
    by_project = defaultdict(list)
    for doc in all_docs:
        by_project[doc.get('project', '')].append(doc)

    counters = dict(state.get('counters', {}))
    backfilled = 0

    for project_name, project_tasks in by_project.items():
        # 按 created 日期排序，相同日期按文件名排序
        sorted_tasks = sorted(project_tasks, key=lambda t: (t.get('created', ''), t.get('filename', '')))

        for task in sorted_tasks:
            if task.get('task_id'):
                continue  # 已有 task_id，跳过
            family = infer_task_family(
                project_name,
                title=task.get('title', ''),
                workdir=task.get('workdir', ''),
                tags=task.get('tags'),
                domain=task.get('domain', ''),
                stage=task.get('stage', ''),
                task_family=task.get('task_family', ''),
            )
            prefix = task_prefix_for(
                project_name,
                title=task.get('title', ''),
                workdir=task.get('workdir', ''),
                tags=task.get('tags'),
                domain=task.get('domain', ''),
                stage=task.get('stage', ''),
                task_family=family,
            )
            # 分配新序号
            seq = counters.get(prefix, 0) + 1
            code = f"{prefix}-{seq}"
            counters[prefix] = seq

            # 写回 YAML frontmatter
            ok, _ = update_frontmatter_field(task['path'], 'task_id', code)
            if ok:
                task['task_id'] = code
                if family and is_dispatch_project(project_name) and not task.get('task_family'):
                    update_frontmatter_field(task['path'], 'task_family', family)
                    task['task_family'] = family
                profile = infer_execution_profile(task.get('workdir', ''), task_family=family)
                if profile and is_dispatch_project(project_name) and not task.get('execution_profile'):
                    update_frontmatter_field(task['path'], 'execution_profile', profile)
                    task['execution_profile'] = profile
                backfilled += 1

    state['counters'] = counters
    return backfilled

def backfill_workdirs(all_docs):
    """为缺少 workdir 的任务补填默认值 project/{项目名}/。"""
    backfilled = 0
    for doc in all_docs:
        if doc.get('workdir'):
            continue
        project = doc.get('project', '')
        if not project:
            continue
        default_workdir = f"project/{project}/"
        ok, _ = update_frontmatter_field(doc['path'], 'workdir', default_workdir)
        if ok:
            doc['workdir'] = default_workdir
            backfilled += 1
    return backfilled

def resolve_conflicts(all_docs, state):
    """
    检测并解决 task_id 冲突：同一前缀+序号出现多次时，
    按文件系统创建时间（st_ctime）排序，最早的保留，其余重新分配。
    """
    from collections import defaultdict
    by_code = defaultdict(list)
    for doc in all_docs:
        code = doc.get('task_id', '')
        if code:
            by_code[code].append(doc)

    counters = dict(state.get('counters', {}))
    resolved = 0

    for code, docs in by_code.items():
        if len(docs) <= 1:
            continue
        # 冲突！按文件创建时间排序，最早的保留
        docs.sort(key=lambda d: os.path.getmtime(REPO_ROOT / d['path']))
        for doc in docs[1:]:
            # 重新分配
            prefix = task_prefix_for(
                doc.get('project', ''),
                title=doc.get('title', ''),
                workdir=doc.get('workdir', ''),
                tags=doc.get('tags'),
                domain=doc.get('domain', ''),
                stage=doc.get('stage', ''),
                task_family=doc.get('task_family', ''),
            )
            seq = counters.get(prefix, 0) + 1
            new_code = f"{prefix}-{seq}"
            counters[prefix] = seq
            ok, _ = update_frontmatter_field(doc['path'], 'task_id', new_code)
            if ok:
                doc['task_id'] = new_code
                resolved += 1

    state['counters'] = counters
    return resolved

# ── Frontmatter 解析 ──────────────────────────────────

def extract_frontmatter(content):
    for pat in [r'^---\s*\n(.*?)\n---', r'^--\s*\n(.*?)\n--']:
        m = re.match(pat, content, re.DOTALL)
        if m:
            return parse_yaml_lite(m.group(1)), m.group(0)
    return None, None

def parse_yaml_lite(text):
    result = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('[') and val.endswith(']'):
            items = [x.strip().strip("'\"") for x in val[1:-1].split(',')]
            result[key] = [x for x in items if x]
        elif val.startswith('|') or val.startswith('>'):
            continue
        elif val.lower() in ('true', 'false'):
            result[key] = val.lower() == 'true'
        else:
            result[key] = val.strip("'\"")
    return result

_FRONTMATTER_FIELD_ORDER = {
    'title': 0,
    'task_id': 1,
    'legacy_id': 2,
    'task_family': 3,
    'execution_profile': 4,
    'workdir': 5,
    'created': 6,
    'updated': 7,
    'assignee': 8,
    'priority': 9,
    'status': 10,
    'status_changed_at': 11,
    'due_date': 12,
    'tags': 13,
    'kind': 14,
    'domain': 15,
    'stage': 16,
    'source': 17,
    'remote_url': 18,
    'team_path': 19,
    'scenario_slug': 20,
    'promoted_to': 21,
    'promoted_from': 22,
    'team_handoff_status': 23,
    'team_handoff_url': 24,
    'next_action': 25,
    'canvas_ref': 26,
    'canvas_schema': 27,
    'canvas_updated': 28,
    'landing_page': 29,
    'landing_updated': 30,
}


def status_changed_at_for_frontend(fm):
    raw = str((fm or {}).get('status_changed_at') or '').strip()
    if raw:
        return raw, False
    fallback = str((fm or {}).get('created') or (fm or {}).get('updated') or '').strip()
    return fallback, True

DEFAULT_TASK_BODY_TEMPLATE = """## 背景 / 来源
- 来源：
- 为什么现在做：

## 要做什么
（一句话目标 + 明确动作）

## 输入与材料
- workdir:
- 入口文件 / 链接:
- 约束 / 不要碰:

## 完成标准
- [ ] 输出物明确
- [ ] 验证方式明确
- [ ] 执行结果已回填，必要时交接到团队板 / 场景库

## 执行结果
待回填。"""

def _frontmatter_insert_index(lines, field):
    """计算新字段在 frontmatter block 中的插入位置。"""
    if len(lines) < 2:
        return len(lines)
    target_order = _FRONTMATTER_FIELD_ORDER.get(field, 999)
    insert_at = len(lines) - 1
    for idx, line in enumerate(lines[1:-1], start=1):
        m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
        if not m:
            continue
        existing_order = _FRONTMATTER_FIELD_ORDER.get(m.group(1), 999)
        if existing_order <= target_order:
            insert_at = idx + 1
    return insert_at

def infer_task_domain(fm, *, project='', path=''):
    """Return a stable business domain for task-specific dashboard views."""
    explicit = str(fm.get('domain') or '').strip()
    if explicit:
        return explicit

    tags = fm.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    tag_text = ' '.join(str(x).lower() for x in tags)
    haystack = ' '.join([
        str(project or ''),
        str(path or ''),
        str(fm.get('workdir') or ''),
        str(fm.get('title') or ''),
        str(fm.get('next_action') or ''),
    ]).lower()

    if '场景库运营' in str(project) or 'scenario' in tag_text or '场景库' in tag_text or fm.get('scenario_slug'):
        return 'scenario'
    if 'shape-of-thought' in haystack or 'team-workspace' in haystack or 'handoff-team' in haystack:
        return 'team'
    if 'knowledgemanagement' in haystack or 'zotero' in haystack or 'stork' in haystack or 'sih' in haystack or 'km' in tag_text:
        return 'knowledge'
    if 'researchlab' in haystack or 'researchprojects' in haystack or 'research' in tag_text or '科研' in tag_text:
        return 'research'
    if 'governance' in tag_text or 'security' in tag_text or '治理' in haystack or 'scan_governance' in haystack:
        return 'governance'
    return 'personal'

# ── 文件重命名与引用更新 ──────────────────────────────

def _title_to_slug(title):
    """将标题转换为文件名 slug（与 create_document 保持一致）"""
    slug = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-')
    return slug or 'task'

def _iter_markdown_files():
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        yield from base.rglob('*.md')

def _iter_project_dirs():
    """Yield project directories from SCAN_DIRS.

    Historical config used scan_dirs as parent buckets, e.g. "project".
    Personal dispatch can point scan_dirs at project leaves, e.g.
    "project/个人调度". Support both forms.
    """
    seen = set()
    for scan_dir in SCAN_DIRS:
        target = REPO_ROOT / scan_dir
        if not target.exists() or not target.is_dir():
            continue
        child_dirs = [
            p for p in sorted(target.iterdir())
            if p.is_dir() and not p.name.startswith('.') and p.name != 'vendor'
        ]
        has_direct_md = any(p.is_file() and p.suffix == '.md' for p in target.iterdir())
        if has_direct_md or not child_dirs:
            resolved = target.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield target
        for project_dir in child_dirs:
            resolved = project_dir.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield project_dir

def _collect_reference_updates(old_path):
    """收集包含 [[old_path]] 的 Markdown 文件及其内容。"""
    old_pattern = '[[' + old_path + ']]'
    matches = []
    for fpath in _iter_markdown_files():
        content = fpath.read_text(encoding='utf-8')
        if old_pattern in content:
            matches.append((fpath, content))
    return matches

def _write_reference_updates(reference_files, old_path, new_path):
    """写入已收集的引用替换，返回更新过的 repo 相对路径列表。"""
    old_pattern = '[[' + old_path + ']]'
    new_pattern = '[[' + new_path + ']]'
    updated = []
    for fpath, content in reference_files:
        new_content = content.replace(old_pattern, new_pattern)
        if new_content == content:
            continue
        _atomic_write_text(fpath, new_content)
        updated.append(str(fpath.relative_to(REPO_ROOT)))
    return updated

def _update_all_references(old_path, new_path):
    """扫描所有 .md 文件，将 [[old_path]] 替换为 [[new_path]]"""
    reference_files = _collect_reference_updates(old_path)
    return _write_reference_updates(reference_files, old_path, new_path)

def _rename_task_file(old_rel_path, new_rel_path):
    """重命名任务文件并更新所有 [[path]] 引用。返回 (ok, msg, updated_refs)"""
    old_abs = REPO_ROOT / old_rel_path
    new_abs = REPO_ROOT / new_rel_path
    if not old_abs.exists():
        return False, f"文件不存在: {old_rel_path}", []
    if old_abs == new_abs:
        return True, "文件名未变", []
    if new_abs.exists():
        return False, f"目标文件已存在: {new_rel_path}", []
    try:
        reference_files = _collect_reference_updates(old_rel_path)
    except OSError as e:
        return False, f"扫描引用失败: {e}", []
    new_abs.parent.mkdir(parents=True, exist_ok=True)
    try:
        old_abs.rename(new_abs)
        invalidate_scan_cache(old_abs)
        invalidate_scan_cache(new_abs)
    except OSError as e:
        return False, f"重命名失败: {e}", []
    updated_refs = []
    try:
        updated_refs = _write_reference_updates(reference_files, old_rel_path, new_rel_path)
    except OSError as e:
        for updated_path in updated_refs:
            try:
                updated_abs = REPO_ROOT / updated_path
                content = updated_abs.read_text(encoding='utf-8')
                content = content.replace('[[' + new_rel_path + ']]', '[[' + old_rel_path + ']]')
                _atomic_write_text(updated_abs, content)
            except OSError:
                pass
        rollback_msg = ''
        try:
            if new_abs.exists() and not old_abs.exists():
                new_abs.rename(old_abs)
                invalidate_scan_cache(new_abs)
                invalidate_scan_cache(old_abs)
                rollback_msg = "，已回滚文件名"
        except OSError as rollback_err:
            rollback_msg = f"，回滚文件名失败: {rollback_err}"
        return False, f"更新引用失败: {e}{rollback_msg}", []
    return True, new_rel_path, updated_refs

def _build_task_filename(task_id, title):
    """构建任务文件名: {task_id}_{slug}.md"""
    slug = _title_to_slug(title)
    return f"{task_id}_{slug}.md"

# ── Frontmatter 写回 ──────────────────────────────────

# DECISION_LOG 自动喂养钩子（keystone）——把卡过 gate 的状态流转写成草稿行，
# Owner 批量追认后转正。决策 2026-06-17（class:行为追踪，混合制）见 governance/DECISION_LOG.md。
DECISION_LOG_DRAFT_MARKER = '## 自动草稿（待 Owner 追认）'


def _decision_log_path():
    """从 REPO_ROOT 运行时解析，使路径跟随配置/测试的临时根（测试根无此文件→钩子静默跳过）。"""
    return REPO_ROOT / 'shared' / 'toolkit' / 'governance' / 'DECISION_LOG.md'


def _estimate_undo_cost(fm):
    """从卡的 responsibility/safety 估撤销代价档（what-is-a-human-decision 的四档）。"""
    safety = str(fm.get('safety') or '').strip().lower()
    resp = str(fm.get('responsibility') or '').strip().lower()
    if safety in ('irreversible', 'external'):
        return '无界'
    if resp == 'pi-gated' or safety == 'mutating':
        return '高'
    if resp == 'ai-owned' and safety in ('read-only', 'reversible', ''):
        return '低'
    return '中'


def _classify_status_gate(old_status, new_status):
    """判定一次状态流转是否过 gate，返回 (class_tag, 动作标签) 或 None（不记账）。"""
    old_s = str(old_status or '').strip().lower()
    new_s = str(new_status or '').strip().lower()
    if old_s == new_s:
        return None
    if old_s == 'review' and new_s == 'done':
        return ('验收', '验收通过')
    if old_s == 'review' and new_s in ('todo', 'in-progress'):
        return ('验收', '验收打回')
    if new_s == 'done' and old_s in ('todo', 'in-progress'):
        return ('执行批准', '完成')
    return None


_DECISION_LOG_DRAFT_INTRO = '> 钩子自动产，Owner 追认后移入下方正式「决策行」并去掉 `auto-`/`[待追认]`。'


def _append_decision_log_draft(line):
    """把一行草稿加进 DECISION_LOG 的「待追认」区（倒序，最新在上）。
    确定性重建该区（marker→intro→bullets），自动清占位/修排版；幂等。
    账本缺失时静默跳过——保护真账本，使测试/未初始化环境不被污染。"""
    log_path = _decision_log_path()
    anchor = '## 决策行'
    with MARKDOWN_WRITE_LOCK:
        if not log_path.exists():
            return
        text = log_path.read_text(encoding='utf-8')
        if DECISION_LOG_DRAFT_MARKER in text:
            before, _, after = text.partition(DECISION_LOG_DRAFT_MARKER)
            if anchor in after:
                section_body, _, tail = after.partition(anchor)
                tail = anchor + tail
            else:
                section_body, tail = after, ''
            existing = [ln for ln in section_body.split('\n') if ln.strip().startswith('- ')]
            bullets = '\n'.join([line] + existing)
            new_section = f"{DECISION_LOG_DRAFT_MARKER}\n\n{_DECISION_LOG_DRAFT_INTRO}\n\n{bullets}\n\n"
            new_text = before + new_section + tail
        else:
            section = f"{DECISION_LOG_DRAFT_MARKER}\n\n{_DECISION_LOG_DRAFT_INTRO}\n\n{line}\n\n"
            if anchor in text:
                idx = text.index(anchor)
                new_text = text[:idx] + section + text[idx:]
            else:
                new_text = text.rstrip('\n') + '\n\n' + section
        _atomic_write_text(log_path, new_text)


def _append_machine_action_log(line):
    """Append a machine audit receipt without polluting Owner's pending queue."""
    log_path = _decision_log_path()
    if not log_path.is_file():
        return False
    with MARKDOWN_WRITE_LOCK:
        text = log_path.read_text(encoding='utf-8')
        marker = '## 机器动作（审计，不占 Owner 待批）'
        formal = '## 决策行'
        entry = str(line).rstrip()
        if marker in text:
            head, tail = text.split(marker, 1)
            new_text = f"{head}{marker}\n\n{entry}\n{tail.lstrip()}"
        elif formal in text:
            head, tail = text.split(formal, 1)
            new_text = f"{head.rstrip()}\n\n{marker}\n\n{entry}\n\n{formal}{tail}"
        else:
            new_text = f"{text.rstrip()}\n\n{marker}\n\n{entry}\n"
        _atomic_write_text(log_path, new_text)
    return True


def _record_status_decision_draft(filepath, fm, old_status, new_status):
    """Record a status transition as machine evidence, never as a Owner decision.

    Status alone cannot prove who decided. Human decisions require an explicit
    decision row; this hook stays an auditable observation only.
    """
    gate = _classify_status_gate(old_status, new_status)
    if not gate:
        return
    class_tag, action = gate
    task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
    title = str(fm.get('title') or '').strip()
    undo = _estimate_undo_cost(fm)
    today = datetime.now().strftime('%Y-%m-%d')
    title_part = f"《{title}》" if title else ''
    line = (
        f"- {today} · class:auto-{class_tag} · [状态观察] {action} {task_id}{title_part} · "
        f"撤销:{undo} · 来源:看板状态钩子({old_status or '∅'}→{new_status})"
    )
    _append_machine_action_log(line)


# 执行前 gate（待拍板后派 AI 执行）识别——与前端 render-board.js 的
# isConsolePreExecutionGateTask 保持同一口径，确保自动验收排除的与控制台排除的是同一批。
_PRE_EXEC_GATE_RE = re.compile(
    r'通过后\s*派|通过后[^，。；;]*执行|待\s*PI\s*审核方案|重点拍板|PI\s*决策点|拍板[^，。；;]*执行|方案[^，。；;]*通过后',
    re.IGNORECASE,
)


def _console_routing_text(fm):
    tags = fm.get('tags')
    tags_text = ' '.join(tags) if isinstance(tags, list) else str(tags or '')
    parts = [fm.get('next_action'), fm.get('title'), fm.get('display_title'),
             fm.get('task_id'), fm.get('source'), tags_text]
    return ' '.join(str(p or '') for p in parts)


def _is_auto_acceptance_eligible(fm):
    """验收自动通过资格（决策 2026-06-17「按 responsibility 切」）：
    仅显式 ai-owned + safety read-only/reversible，且不是执行前 gate。
    缺字段一律不自动通过（保守：宁可上呈，不误自决）。"""
    resp = str(fm.get('responsibility') or '').strip().lower()
    safety = str(fm.get('safety') or '').strip().lower()
    human_gate = str(fm.get('human_gate') or '').strip().lower()
    if human_gate in ('true', 'yes', '1', 'on'):
        return False
    if resp != 'ai-owned':
        return False
    if safety not in ('read-only', 'reversible'):
        return False
    if _PRE_EXEC_GATE_RE.search(_console_routing_text(fm)):
        return False
    return True


def _record_auto_acceptance(fm):
    """机器自动验收通过 → 独立 class:auto-验收机决 落账。
    与 Owner 的待追认 class:auto-验收 分开，避免污染「同向≥3→冒泡委托」的压缩计数。"""
    task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
    title = str(fm.get('title') or '').strip()
    today = datetime.now().strftime('%Y-%m-%d')
    title_part = f"《{title}》" if title else ''
    line = (
        f"- {today} · class:auto-验收机决 · [机器自决] 自动验收通过 {task_id}{title_part} · "
        f"撤销:低 · 来源:看板自动验收(ai-owned+reversible，非 Owner 选择)"
    )
    _append_machine_action_log(line)


def _stamp_acceptance(filepath, accepted_role, config=None):
    """Stamp acceptance with the configured actor for an explicit role."""
    role = str(accepted_role or '').strip().lower()
    if role not in role_policy.ROLE_NAMES:
        return
    source = config if isinstance(config, dict) else load_config()
    who = role_policy.actor_for_role(source.get('roles'), role)
    today = datetime.now().strftime('%Y-%m-%d')
    update_frontmatter_field(filepath, 'accepted_role', role, _suppress_decision_log=True)
    update_frontmatter_field(filepath, 'accepted_by', who, _suppress_decision_log=True)
    update_frontmatter_field(filepath, 'accepted_at', today, _suppress_decision_log=True)


def _record_attention_gate_acceptance(fm, reason=''):
    """人闸真 review 后代收通过 → 独立 class:人闸验收 落账（单行）。
    与 Owner 待追认区、auto-验收机决 三类分明，保住压缩计数纯净。
    这不进 Owner 的「待追认」决策语义——它是人闸已执行的验收动作记录。"""
    task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
    title = str(fm.get('title') or '').strip()
    today = datetime.now().strftime('%Y-%m-%d')
    title_part = f"《{title}》" if title else ''
    reason_part = f" · review:{str(reason).strip()[:120]}" if reason else ''
    line = (
        f"- {today} · class:人闸验收 · [人闸代收] 超时经真 review 通过 {task_id}{title_part} · "
        f"撤销:低 · 来源:验收超时窗口(Owner 未手动验收，人闸 review 后代收){reason_part}"
    )
    _append_machine_action_log(line)


def update_frontmatter_field(filepath, field, value, _suppress_decision_log=False):
    """更新 .md 文件中 YAML frontmatter 的某个字段。
    当 field 为 title 时，同时重命名文件并更新所有引用。
    返回 (ok, msg) 或 (ok, msg, new_path) 当文件被重命名时。"""
    if field == 'title' and (not value or not value.strip()):
        return False, "标题不能为空"
    if field == 'due_date':
        ok, normalized = normalize_due_date(value)
        if not ok:
            return False, "截止日期格式无效，必须为 YYYY-MM-DD"
        if not normalized:
            return False, "截止日期不能为空"
        value = normalized

    with MARKDOWN_WRITE_LOCK:
        fpath = REPO_ROOT / filepath
        if not fpath.exists():
            return False, "文件不存在"
        content = fpath.read_text(encoding='utf-8')
        fm, fm_block = extract_frontmatter(content)
        if not fm_block:
            return False, "无 frontmatter"

        old_title = fm.get('title', '')
        old_field_value = fm.get(field, '')
        old_status_value = str(fm.get('status') or '').strip()
        status_fm_snapshot = dict(fm)
        pending_new_path = None
        if field == 'title':
            task_id = fm.get('task_id', '')
            if task_id:
                new_filename = _build_task_filename(task_id, value)
                old_path = Path(filepath)
                pending_new_path = str(old_path.parent / new_filename)
                if pending_new_path != filepath and (REPO_ROOT / pending_new_path).exists():
                    return False, f"目标文件已存在: {pending_new_path}"

        # 构建新的 frontmatter
        lines = fm_block.split('\n')
        found = False
        new_lines = []
        for line in lines:
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
            if m and m.group(1) == field:
                new_lines.append(f"{field}: {value}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines = list(lines)
            new_lines.insert(_frontmatter_insert_index(lines, field), f"{field}: {value}")

        # 同时更新 updated 字段；status 真实变更时记录状态变更日，供真停滞信号使用。
        today = datetime.now().strftime('%Y-%m-%d')
        status_changed_value = today if field == 'status' and str(value).strip() != old_status_value else ''
        # 进入 review 时打 review_since 时间戳（KAN-200 验收超时窗口的起点；
        # 用完整 ISO 时间戳而非纯日期，因为超时阈值以小时计，日期粒度太粗）。
        review_since_value = ''
        if (field == 'status'
                and str(value).strip().lower() == 'review'
                and old_status_value.lower() != 'review'):
            review_since_value = datetime.now().astimezone().isoformat(timespec='seconds')
        final_lines = []
        updated_found = False
        status_changed_found = False
        review_since_found = False
        for line in new_lines:
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
            if m and m.group(1) == 'updated':
                final_lines.append(f"updated: {today}")
                updated_found = True
            elif status_changed_value and m and m.group(1) == 'status_changed_at':
                final_lines.append(f"status_changed_at: {status_changed_value}")
                status_changed_found = True
            elif review_since_value and m and m.group(1) == 'review_since':
                final_lines.append(f"review_since: {review_since_value}")
                review_since_found = True
            else:
                final_lines.append(line)
        if not updated_found:
            final_lines.insert(-1, f"updated: {today}")
        if status_changed_value and not status_changed_found:
            final_lines.insert(_frontmatter_insert_index(final_lines, 'status_changed_at'), f"status_changed_at: {status_changed_value}")
        if review_since_value and not review_since_found:
            final_lines.insert(_frontmatter_insert_index(final_lines, 'review_since'), f"review_since: {review_since_value}")

        new_fm = '\n'.join(final_lines)
        new_content = new_fm + content[len(fm_block):]
        _atomic_write_text(fpath, new_content)

        # title 变更时重命名文件
        if field == 'title' and pending_new_path and pending_new_path != filepath:
            ok, msg, _ = _rename_task_file(filepath, pending_new_path)
            if not ok:
                try:
                    rollback_lines = []
                    for line in final_lines:
                        m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
                        if m and m.group(1) == 'title':
                            rollback_lines.append(f"title: {old_title}")
                        else:
                            rollback_lines.append(line)
                    rollback_content = '\n'.join(rollback_lines) + content[len(fm_block):]
                    _atomic_write_text(fpath, rollback_content)
                except OSError as e:
                    return False, f"文件重命名失败且标题回滚失败: {msg}; {e}"
                return False, "文件重命名失败，标题已回滚: " + msg
            _lineage_record_frontmatter_change(
                pending_new_path,
                field,
                old_field_value,
                value,
                old_path=filepath,
            )
            return True, "OK", pending_new_path

    _lineage_record_frontmatter_change(filepath, field, old_field_value, value)

    # keystone 钩子：状态过 gate → 写 DECISION_LOG 草稿（锁已释放，失败不阻断状态更新）
    if field == 'status':
        new_status_value = str(value).strip()
        if not _suppress_decision_log:
            try:
                _record_status_decision_draft(
                    filepath, status_fm_snapshot, old_status_value, new_status_value
                )
            except Exception:
                pass
        # 验收自动通过（决策 2026-06-17）：进入 review 且 ai-owned+reversible+非执行前 gate
        # → 直接推进到 done，机器自决落账，不进「等我验收」泳道占用 Owner 注意力。
        if (new_status_value.lower() == 'review'
                and old_status_value.lower() != 'review'
                and not _suppress_decision_log
                and _is_auto_acceptance_eligible(status_fm_snapshot)):
            try:
                update_frontmatter_field(filepath, 'status', 'done', _suppress_decision_log=True)
                _record_auto_acceptance(status_fm_snapshot)
            except Exception:
                pass

    return True, "OK"

def update_task_body(filepath, new_body):
    """更新任务的 Markdown 正文，保留 frontmatter 不变。"""
    with MARKDOWN_WRITE_LOCK:
        fpath = REPO_ROOT / filepath
        if not fpath.exists():
            return False, "文件不存在"
        content = fpath.read_text(encoding='utf-8')
        fm, fm_block = extract_frontmatter(content)
        if not fm_block:
            return False, "未找到 frontmatter"
        body = content[len(fm_block):]
        body_prefix = body[:len(body) - len(body.lstrip('\r\n'))]
        new_fm = _update_frontmatter_updated_block(fm_block)
        new_content = new_fm + body_prefix + new_body
        _atomic_write_text(fpath, new_content)
    return True, "OK"

def _read_task_file(filepath):
    fpath = REPO_ROOT / filepath
    if not fpath.exists():
        return None, '文件不存在'
    raw = fpath.read_text(encoding='utf-8')
    fm, fm_block = extract_frontmatter(raw)
    if not fm_block:
        return None, '未找到 frontmatter'
    body = raw[len(fm_block):]
    body_prefix = body[:len(body) - len(body.lstrip('\r\n'))]
    current_body = body[len(body_prefix):]
    return {
        'path': fpath,
        'raw': raw,
        'frontmatter': fm,
        'frontmatter_block': fm_block,
        'body_prefix': body_prefix,
        'body': current_body,
        'rev': _file_rev(raw),
    }, None

def _update_frontmatter_updated_block(fm_block):
    today = datetime.now().strftime('%Y-%m-%d')
    fm_lines = fm_block.split('\n')
    updated_fm_lines = []
    updated_found = False
    for line in fm_lines:
        m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
        if m and m.group(1) == 'updated':
            updated_fm_lines.append(f"updated: {today}")
            updated_found = True
        else:
            updated_fm_lines.append(line)
    if not updated_found:
        updated_fm_lines.insert(-1, f"updated: {today}")
    return '\n'.join(updated_fm_lines)

def _write_task_file(task_file, body_text):
    new_fm = _update_frontmatter_updated_block(task_file['frontmatter_block'])
    new_content = new_fm + task_file['body_prefix'] + body_text
    _atomic_write_text(task_file['path'], new_content)
    return new_content

def _git_merge_file(base_text, current_text, new_text):
    with tempfile.TemporaryDirectory(prefix='kanban-merge-') as tmpdir:
        tmpdir_path = Path(tmpdir)
        current_path = tmpdir_path / 'current.md'
        base_path = tmpdir_path / 'base.md'
        new_path = tmpdir_path / 'new.md'
        current_path.write_text(current_text, encoding='utf-8')
        base_path.write_text(base_text, encoding='utf-8')
        new_path.write_text(new_text, encoding='utf-8')
        proc = subprocess.run(
            ['git', 'merge-file', '-p', str(current_path), str(base_path), str(new_path)],
            capture_output=True,
            text=True,
        )
        merged = proc.stdout
        if proc.returncode in (0, 1):
            return merged, proc.returncode == 0, None
        return None, False, proc.stderr.strip() or 'git merge-file 失败'

def update_task_body_with_merge(filepath, new_body, base_rev=None, base_body=None):
    with MARKDOWN_WRITE_LOCK:
        task_file, err = _read_task_file(filepath)
        if not task_file:
            return {'ok': False, 'message': err}, 404 if err == '文件不存在' else 400
        if not base_rev or base_rev == task_file['rev']:
            new_raw = _write_task_file(task_file, new_body)
            return {
                'ok': True,
                'message': 'OK',
                'rev': _file_rev(new_raw),
                'merged': False,
                'conflict': False,
            }, 200
        merged, clean, merge_err = _git_merge_file(base_body or '', task_file['body'], new_body)
        if merge_err:
            return {'ok': False, 'message': merge_err}, 500
        if clean:
            new_raw = _write_task_file(task_file, merged)
            return {
                'ok': True,
                'message': 'OK',
                'rev': _file_rev(new_raw),
                'merged': True,
                'conflict': False,
                'body': merged,
            }, 200
        return {
            'ok': False,
            'message': '检测到远端更新，自动合并后仍有冲突',
            'conflict': True,
            'merged': True,
            'body': merged,
            'current_body': task_file['body'],
            'rev': task_file['rev'],
        }, 409

def _find_markdown_section(body, title):
    pattern = re.compile(r'(?m)^##\s+' + re.escape(str(title or '').strip()) + r'\s*\n')
    match = pattern.search(body or '')
    if not match:
        return None
    next_match = re.search(r'(?m)^##\s+', (body or '')[match.end():])
    section_end = match.end() + next_match.start() if next_match else len(body or '')
    return {
        'start': match.start(),
        'content_start': match.end(),
        'end': section_end,
    }

_ACCEPTANCE_CHECKBOX_RE = re.compile(r'^(\s*[-*+]\s+\[)([ xX])(\]\s*)(.*)$')

def _split_line_ending(line):
    if line.endswith('\r\n'):
        return line[:-2], '\r\n'
    if line.endswith('\n') or line.endswith('\r'):
        return line[:-1], line[-1:]
    return line, ''

def update_acceptance_checkbox(filepath, index, expected_text, checked):
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        return {'ok': False, 'message': 'index 无效'}, 400
    if not isinstance(checked, bool):
        return {'ok': False, 'message': 'checked 必须为布尔值'}, 400
    expected = str(expected_text or '').strip()
    with MARKDOWN_WRITE_LOCK:
        task_file, err = _read_task_file(filepath)
        if not task_file:
            return {'ok': False, 'message': err}, 404 if err == '文件不存在' else 400
        section = _find_markdown_section(task_file['body'], '完成标准')
        if not section:
            return {'ok': False, 'message': '未找到完成标准段'}, 404
        section_text = task_file['body'][section['content_start']:section['end']]
        lines = section_text.splitlines(keepends=True)
        checkbox_pos = 0
        updated = False
        for line_idx, line in enumerate(lines):
            line_text, line_ending = _split_line_ending(line)
            match = _ACCEPTANCE_CHECKBOX_RE.match(line_text)
            if not match:
                continue
            if checkbox_pos == index:
                current_text = match.group(4).strip()
                if current_text != expected:
                    return {
                        'ok': False,
                        'message': '完成标准已变化，请刷新后重试',
                        'expected_text': current_text,
                    }, 409
                marker = 'x' if checked else ' '
                lines[line_idx] = f"{match.group(1)}{marker}{match.group(3)}{match.group(4)}{line_ending}"
                updated = True
                break
            checkbox_pos += 1
        if not updated:
            return {'ok': False, 'message': '完成标准 index 越界'}, 400
        new_section_text = ''.join(lines)
        new_body = (
            task_file['body'][:section['content_start']]
            + new_section_text
            + task_file['body'][section['end']:]
        )
        new_raw = _write_task_file(task_file, new_body)
        return {
            'ok': True,
            'message': 'OK',
            'checked': checked,
            'index': index,
            'rev': _file_rev(new_raw),
        }, 200

def _format_markdown_section(title, section_markdown):
    text = str(section_markdown or '').strip('\n').rstrip()
    if text:
        return f"## {title}\n{text}\n\n"
    return f"## {title}\n\n"

def _append_execution_result_trace(body, trace_line):
    section = _find_markdown_section(body, '执行结果')
    if not section:
        prefix = body.rstrip()
        if prefix:
            prefix += '\n\n'
        return prefix + '## 执行结果\n' + trace_line + '\n'
    before = body[:section['content_start']]
    section_body = body[section['content_start']:section['end']].rstrip()
    after = body[section['end']:]
    replacement = ''
    if section_body:
        replacement = section_body + '\n'
    replacement += trace_line + '\n\n'
    return before + replacement + after

def update_acceptance_section(filepath, section_markdown, user=''):
    with MARKDOWN_WRITE_LOCK:
        task_file, err = _read_task_file(filepath)
        if not task_file:
            return {'ok': False, 'message': err}, 404 if err == '文件不存在' else 400
        section = _find_markdown_section(task_file['body'], '完成标准')
        if not section:
            return {'ok': False, 'message': '未找到完成标准段'}, 404
        replacement = _format_markdown_section('完成标准', section_markdown)
        next_body = task_file['body'][:section['start']] + replacement + task_file['body'][section['end']:]
        today = datetime.now().strftime('%Y-%m-%d')
        actor = str(user or '').strip() or 'unknown'
        next_body = _append_execution_result_trace(next_body, f'- 标准修订:{today} by {actor}')
        new_raw = _write_task_file(task_file, next_body)
        return {
            'ok': True,
            'message': 'OK',
            'rev': _file_rev(new_raw),
            'body': next_body,
        }, 200

# 卡级「给 AI 的常驻说明」：写进卡 .md 正文的一个固定段，每次 AI 执行自动提到 prompt 最前。
CARD_NOTE_TITLE = '给 AI 的常驻说明'


def _extract_card_note(body):
    """从卡正文里取出『给 AI 的常驻说明』段文本（不含标题），无则空串。"""
    section = _find_markdown_section(body or '', CARD_NOTE_TITLE)
    if not section:
        return ''
    return (body or '')[section['content_start']:section['end']].strip()


def update_card_note_section(filepath, note_text):
    """新增/更新/清空卡里的『给 AI 的常驻说明』段（原子写）。空文本=删除该段。"""
    text = str(note_text or '').strip()
    with MARKDOWN_WRITE_LOCK:
        task_file, err = _read_task_file(filepath)
        if not task_file:
            return {'ok': False, 'message': err}, 404 if err == '文件不存在' else 400
        body = task_file['body']
        section = _find_markdown_section(body, CARD_NOTE_TITLE)
        if section:
            if text:
                replacement = _format_markdown_section(CARD_NOTE_TITLE, text)
                next_body = body[:section['start']] + replacement + body[section['end']:]
            else:
                next_body = (body[:section['start']] + body[section['end']:]).lstrip('\n')
        elif text:
            # 放到正文最前，便于阅读；prompt 拼装会另行提取，不依赖物理位置。
            next_body = _format_markdown_section(CARD_NOTE_TITLE, text) + body.lstrip('\n')
        else:
            next_body = body
        new_raw = _write_task_file(task_file, next_body)
        return {'ok': True, 'message': 'OK', 'rev': _file_rev(new_raw), 'ai_note': text}, 200

SKILL_DECISION_LEDGER_TITLE = 'Skill 决策台账'

def _update_skill_decision_ledger(filepath, lines):
    """Replace the visible decision ledger section while preserving the task brief."""
    text = '\n'.join(str(x).strip() for x in lines if str(x).strip())
    with MARKDOWN_WRITE_LOCK:
        task_file, err = _read_task_file(filepath)
        if not task_file:
            return False, err
        body = task_file['body']
        section = _find_markdown_section(body, SKILL_DECISION_LEDGER_TITLE)
        replacement = _format_markdown_section(SKILL_DECISION_LEDGER_TITLE, text)
        next_body = (body[:section['start']] + replacement + body[section['end']:]
                     if section else replacement + body.lstrip('\n'))
        _write_task_file(task_file, next_body)
    return True, 'OK'

def _skill_decision_docs():
    return [doc for doc in scan_all() if str(doc.get('proposal_id') or '').strip()]

def _decision_invocation_for(payload, proposal_id):
    for invocation in payload.get('invocations', []) if isinstance(payload.get('invocations'), list) else []:
        params = invocation.get('params') if isinstance(invocation, dict) else None
        if isinstance(params, dict) and str(params.get('proposalId') or '') == proposal_id:
            return invocation
    return None

def sync_skill_decision_cards(payload):
    """Project skill-state decisions to one real card per proposal id."""
    decisions = payload.get('needs_decision') if isinstance(payload, dict) else []
    decisions = decisions if isinstance(decisions, list) else []
    existing = {str(doc.get('proposal_id')): doc for doc in _skill_decision_docs()}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        # v1.2 decision proposals only. Legacy needs_decision rows remain display-only.
        if 'proposal_revision' not in decision or not decision.get('evidence_hash'):
            continue
        proposal_id = skill_invocation.proposal_key(decision)
        if not proposal_id:
            continue
        revision = int(decision.get('proposal_revision') or 0)
        doc = existing.get(proposal_id)
        if not doc:
            card_hint = decision.get('card') if isinstance(decision.get('card'), dict) else {}
            ok, rel_path, _task_id = create_document(
                '个人调度', decision.get('question') or proposal_id,
                card_hint.get('assignee') or _configured_role_member('owner') or 'Unassigned',
                'P0' if decision.get('severity') == '🔴' else 'P1',
                task_family='skill',
            )
            if not ok:
                continue
            doc = {'path': rel_path, 'proposal_revision': 0}
            existing[proposal_id] = doc
            for field, value in (('proposal_id', proposal_id), ('human_gate', 'true'),
                                 ('attention_scope', 'owner'), ('responsibility', 'pi-gated'),
                                 ('source', f'skill-state/{proposal_id}')):
                update_frontmatter_field(rel_path, field, value)
        rel_path = doc.get('path')
        if revision >= int(doc.get('proposal_revision') or 0):
            for field, value in (('proposal_revision', revision),
                                 ('evidence_hash', decision.get('evidence_hash') or ''),
                                 ('decision_phase', decision.get('decision_phase') or ''),
                                 ('review_url', decision.get('review_url') or ''),
                                 ('decision_state', 'pending'), ('status', 'review'),
                                 ('human_gate', 'true'), ('attention_scope', 'owner'),
                                 ('responsibility', 'pi-gated'),
                                 ('next_action', decision.get('next_action') or decision.get('question') or '请 Owner 拍板')):
                update_frontmatter_field(rel_path, field, value)
            invocation = _decision_invocation_for(payload, proposal_id)
            lines = [f'- proposal: `{proposal_id}` · revision: {revision}',
                     f'- Owner 唯一需做动作：{decision.get("next_action") or decision.get("question") or "请拍板"}']
            if decision.get('why'): lines.append(f'- 原因：{decision.get("why")}')
            if decision.get('review_url'): lines.append(f'- 直接查看：{decision.get("review_url")}')
            if invocation: lines.append(f'- 可执行动作：{invocation.get("label") or invocation.get("id")}')
            _update_skill_decision_ledger(rel_path, lines)
    updates = payload.get('decision_card_updates') if isinstance(payload, dict) else []
    updates = updates if isinstance(updates, list) else []
    for update in updates:
        if not isinstance(update, dict) or update.get('attention_state') == 'pending':
            continue
        proposal_id = skill_invocation.proposal_key(update)
        doc = existing.get(proposal_id)
        if not doc:
            title = update.get('question') or f"Skill HITL：{update.get('skill_name') or proposal_id}"
            ok, rel_path, _task_id = create_document(
                '个人调度', title, 'Owner', 'P1', task_family='skill',
            )
            if not ok:
                continue
            doc = {'path': rel_path, 'proposal_revision': 0}
            existing[proposal_id] = doc
            for field, value in (
                ('proposal_id', proposal_id),
                ('source', f'skill-state/{proposal_id}'),
                ('human_gate', 'false'),
                ('attention_scope', 'backstage'),
                ('responsibility', 'ai-owned'),
            ):
                update_frontmatter_field(rel_path, field, value)
        rel_path = doc['path']
        phase = str(update.get('decision_phase') or '')
        closed = update.get('attention_state') == 'closed'
        for field, value in (
            ('proposal_revision', int(update.get('proposal_revision') or 0)),
            ('evidence_hash', update.get('evidence_hash') or ''),
            ('decision_phase', phase),
            ('review_url', update.get('review_url') or ''),
            ('decision_state', 'auto_closed' if closed else phase),
            ('status', 'done' if closed else 'doing'),
            ('human_gate', 'false'),
            ('attention_scope', 'backstage'),
            ('responsibility', 'pi-gated' if closed else 'ai-owned'),
            ('next_action', update.get('next_action') or ('本轮评测已结束' if closed else '等待后台执行')),
        ):
            update_frontmatter_field(rel_path, field, value, _suppress_decision_log=field == 'status')
        _update_skill_decision_ledger(rel_path, [
            f'- proposal: `{proposal_id}` · revision: {update.get("proposal_revision", "")}',
            f'- 当前阶段：**{phase or "已结束"}**',
            f'- 当前责任：{"本轮已结束" if closed else "AI 后台继续；无需 Owner 动作"}',
            *([f'- 下次直接查看：{update.get("review_url")}'] if update.get('review_url') else []),
        ])
    signals = payload.get('auto_close') if isinstance(payload, dict) else []
    signals = signals if isinstance(signals, list) else []
    for signal in signals:
        proposal_id = skill_invocation.proposal_key(signal) if isinstance(signal, dict) else str(signal)
        doc = existing.get(proposal_id)
        if doc:
            update_frontmatter_field(doc['path'], 'decision_state', 'auto_closed')
            update_frontmatter_field(doc['path'], 'status', 'done', _suppress_decision_log=True)
            _update_skill_decision_ledger(doc['path'], [f'- proposal: `{proposal_id}`', '- 上游复核通过，已自动结卡。'])

def persist_skill_invocation_result(invocation, result):
    params = invocation.get('params') if isinstance(invocation, dict) else {}
    proposal_id = str(params.get('proposalId') or '').strip() if isinstance(params, dict) else ''
    doc = next((x for x in _skill_decision_docs() if str(x.get('proposal_id')) == proposal_id), None)
    if not doc:
        return
    rel_path = doc['path']; outcome = result.get('outcome') or 'failed'
    update_frontmatter_field(rel_path, 'decision_state', outcome)
    update_frontmatter_field(rel_path, 'decision_result', str(result.get('message') or outcome).replace('\n', ' '))
    if outcome in {'stale', 'failed'}:
        update_frontmatter_field(rel_path, 'status', 'review')
        update_frontmatter_field(rel_path, 'human_gate', 'true')
        update_frontmatter_field(rel_path, 'attention_scope', 'owner')
        update_frontmatter_field(rel_path, 'responsibility', 'pi-gated')
        update_frontmatter_field(rel_path, 'next_action', result.get('message') or '重新确认当前提案')
    elif outcome == 'accepted':
        update_frontmatter_field(rel_path, 'status', 'doing')
        update_frontmatter_field(rel_path, 'human_gate', 'false')
        update_frontmatter_field(rel_path, 'attention_scope', 'backstage')
        update_frontmatter_field(rel_path, 'responsibility', 'ai-owned')
        update_frontmatter_field(rel_path, 'next_action', '等待 Skill Board 执行并原生复核')
    _update_skill_decision_ledger(rel_path, [
        f'- proposal: `{proposal_id}` · revision: {params.get("proposalRevision", "")}',
        f'- 最近执行结果：**{outcome}** — {result.get("message") or outcome}',
        f'- Owner 唯一需做动作：{result.get("message") if outcome in {"stale", "failed"} else "等待 Skill Board 执行并原生复核"}',
    ])


def _apply_card_ai_note_to_prompt(raw):
    """把卡里『给 AI 的常驻说明』段提到 prompt 最前作为优先指令；段内以 /skill 开头则展开该 skill。"""
    section = _find_markdown_section(raw or '', CARD_NOTE_TITLE)
    if not section:
        return raw
    note = (raw or '')[section['content_start']:section['end']].strip()
    if not note:
        return raw
    raw_wo_note = (raw[:section['start']] + raw[section['end']:])
    skill_info = _parse_skill_command(note)
    if skill_info:
        instruction = _build_skill_augmented_prompt(skill_info['skill'], skill_info['args'], note)
    else:
        instruction = (
            '<执行备注>\n'
            '以下是用户对本卡的常驻执行说明，请在执行前优先阅读并遵循：\n'
            f'{note}\n'
            '</执行备注>'
        )
    return instruction + '\n\n---\n\n' + raw_wo_note


def append_ai_result_to_task_file(filepath, output, tool='ai', timestamp=''):
    with MARKDOWN_WRITE_LOCK:
        fpath = REPO_ROOT / filepath
        if not fpath.exists():
            return False, '文件不存在'
        raw = fpath.read_text(encoding='utf-8')
        ts = str(timestamp or '')[:16].replace('T', ' ')
        separator = f'\n\n<!-- ai-result: {tool} {ts} -->\n\n'
        fm, fm_block = extract_frontmatter(raw)
        if fm_block:
            new_raw = _update_frontmatter_updated_block(fm_block) + raw[len(fm_block):] + separator + str(output or '')
        else:
            new_raw = raw + separator + str(output or '')
        _atomic_write_text(fpath, new_raw)
        return True, 'OK'

def resolve_workdir(workdir_value, task_path, config=None):
    """解析 workdir 字段为绝对路径，并限制在可信根内。"""
    source = config if isinstance(config, dict) else load_config()
    workspace_root = _configured_root('workspace_root', source)
    if not workdir_value:
        resolved = REPO_ROOT / Path(task_path).parent
    else:
        expanded = os.path.expanduser(workdir_value)
        if os.path.isabs(expanded):
            resolved = Path(expanded)
        else:
            resolved = workspace_root / expanded
    real_resolved = Path(os.path.realpath(resolved))
    allowed_roots = _workdir_allowed_roots(source)
    if not _path_in_allowed_roots(real_resolved, allowed_roots):
        roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
        return None, f'workdir 不在可信根内: {workdir_value or str(resolved)} (allowed roots: {roots_text})'
    return real_resolved, None

def _coerce_workdir_to_cwd(resolved_workdir, config=None):
    """将已解析 workdir 转换为可传给 AI 子进程的 cwd。"""
    if not resolved_workdir:
        return None, 'workdir 无效'
    cwd_path = Path(resolved_workdir)
    if cwd_path.exists() and cwd_path.is_file():
        parent = Path(os.path.realpath(os.path.dirname(str(cwd_path))))
        allowed_roots = _workdir_allowed_roots(config)
        if not _path_in_allowed_roots(parent, allowed_roots):
            roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
            return None, f'workdir 指向文件，但其父目录不在可信根内: {parent} (allowed roots: {roots_text})'
        return parent, None
    return cwd_path, None

def _path_is_relative_to(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def _configured_open_allowed_roots(config=None):
    source = config if isinstance(config, dict) else load_config()
    raw_roots = source.get('open_allowed_roots', _DEFAULTS['open_allowed_roots'])
    if not isinstance(raw_roots, list):
        raw_roots = []
    roots = []
    for raw in raw_roots:
        value = str(raw or '').strip()
        if not value:
            continue
        expanded = os.path.expanduser(value)
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        roots.append(Path(os.path.realpath(candidate)))
    return roots

def _workdir_allowed_roots(config=None):
    return _configured_open_allowed_roots(config)

def _path_in_allowed_roots(path, allowed_roots):
    return any(_path_is_relative_to(path, root) for root in allowed_roots)

def _reject_open_executable_target(target):
    return target.suffix.lower() in _OPEN_EXECUTABLE_SUFFIXES

def _is_denied_user_config_key(key):
    lowered = str(key or '').lower()
    return lowered in _USER_CONFIG_DENIED_KEYS or lowered.endswith(_USER_CONFIG_DENIED_SUFFIXES)

def build_safe_user_config_update(body, existing_cfg=None):
    """Return a sanitized user config write for UI preferences only."""
    if not isinstance(body, dict):
        body = {}
    existing = existing_cfg if isinstance(existing_cfg, dict) else {}
    rejected = []
    for key in body:
        if key in _USER_CONFIG_ALLOWED_KEYS:
            continue
        rejected.append(str(key) if _is_denied_user_config_key(key) else str(key))
    if rejected:
        return None, f'不允许写入配置键: {", ".join(sorted(rejected))}'

    if not body:
        return None, None

    merged_cfg = {
        key: val for key, val in existing.items()
        if key not in ('user', 'tools')
    }
    if 'tools' in body:
        raw_tools = body.get('tools')
        raw_tools = raw_tools if isinstance(raw_tools, dict) else {}
        clean_tools = {
            name: cfg for name, cfg in raw_tools.items()
            if isinstance(cfg, dict) and cfg.get('command')
        }
        if clean_tools:
            merged_cfg['tools'] = clean_tools
    return merged_cfg, None

def resolve_open_target(path_value, config=None):
    value = str(path_value or '').strip()
    if not value:
        return None, '缺少 path', 400

    expanded = os.path.expanduser(value)
    requested = Path(expanded)
    if requested.is_absolute():
        target = Path(os.path.realpath(expanded))
        allowed_roots = _configured_open_allowed_roots(config)
        if not _path_in_allowed_roots(target, allowed_roots):
            roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
            return None, f'绝对路径不在可信根内: {value} (allowed roots: {roots_text})', 403
        if _reject_open_executable_target(target):
            return None, '拒绝打开可执行类型', 400
        if not target.exists():
            return None, f'文件不存在: {value}', 404
        return target, None, 200

    repo_root = REPO_ROOT.resolve()
    target = (REPO_ROOT / value).resolve()
    if not _path_is_relative_to(target, repo_root):
        return None, '相对路径越界，必须位于仓库内', 403
    if _reject_open_executable_target(target):
        return None, '拒绝打开可执行类型', 400
    if not target.exists():
        return None, f'文件不存在: {value}', 404
    return target, None, 200

def _configured_project_dir(project):
    """Resolve an existing project leaf, or the legacy ``project`` bucket.

    New cards must stay visible to the current deployment.  In particular, a
    demo card under ``demo/projects/<slug>`` must derive its child beside that
    card instead of silently creating an unscanned ``project/<slug>`` tree.
    """
    name = str(project or '').strip()
    if not name or name in {'.', '..'} or Path(name).name != name:
        return None
    matches = [path for path in _iter_project_dirs() if path.name == name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None
    for raw_scan_dir in SCAN_DIRS:
        scan_path = Path(str(raw_scan_dir or '').strip())
        if scan_path.as_posix().rstrip('/') == 'project':
            return REPO_ROOT / 'project' / name
    return None


def create_document(
    project,
    title,
    assignee,
    priority,
    body='',
    workdir=None,
    due_date=None,
    promoted_from=None,
    task_family=None,
    execution_profile=None,
    legacy_id=None,
    project_ref=None,
    project_role=None,
):
    """创建新任务（.md 文件），自动分配 task_id"""
    ok, normalized_due_date = normalize_due_date(due_date)
    if not ok:
        return False, "截止日期格式无效，必须为 YYYY-MM-DD", ''
    if not title or not title.strip():
        return False, "标题不能为空", ''
    with MARKDOWN_WRITE_LOCK:
        today = datetime.now().strftime('%Y-%m-%d')
        proj_dir = _configured_project_dir(project)
        if proj_dir is None:
            return False, "项目不在 scan_dirs 范围内或名称不唯一", ''
        if workdir is None:
            project_rel = proj_dir.resolve(strict=False).relative_to(REPO_ROOT.resolve(strict=False))
            workdir = project_rel.as_posix().rstrip('/') + '/'
        normalized_family = infer_task_family(
            project,
            title=title,
            body=body,
            workdir=workdir,
            task_family=task_family,
        )
        normalized_profile = str(execution_profile or '').strip() or infer_execution_profile(
            workdir,
            task_family=normalized_family,
        )
        normalized_project_ref = str(project_ref or '').replace('\r', ' ').replace('\n', ' ').strip()
        if normalized_project_ref and not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}', normalized_project_ref):
            return False, "project_ref 格式无效", ''
        normalized_project_role = str(project_role or '').replace('\r', ' ').replace('\n', ' ').strip().lower()
        if normalized_project_ref and not normalized_project_role:
            normalized_project_role = real_projects.DEFAULT_PROJECT_ROLE
        if normalized_project_role and normalized_project_role not in real_projects.PROJECT_ROLES:
            return False, "project_role 格式无效", ''
        if normalized_project_role and not normalized_project_ref:
            return False, "project_role 必须与 project_ref 同时使用", ''

        # 分配 task_id（在生成文件名之前）
        prefix = task_prefix_for(
            project,
            title=title,
            body=body,
            workdir=workdir,
            task_family=normalized_family,
        )
        state = load_state()
        counters = state.get('counters', {})
        seq = task_id_allocator.next_task_sequence(
            REPO_ROOT,
            prefix,
            counters.get(prefix, 0),
        )
        task_id = f"{prefix}-{seq}"

        # 生成文件名: {task_id}_{slug}.md
        filename = _build_task_filename(task_id, title)
        if not proj_dir.exists():
            proj_dir.mkdir(parents=True)
        filepath = proj_dir / filename
        if filepath.exists():
            return False, f"文件已存在: {filename}", ''

        if not body:
            body = DEFAULT_TASK_BODY_TEMPLATE
        due_date_line = f"due_date: {normalized_due_date}\n" if normalized_due_date else ''
        promoted_from_value = str(promoted_from or '').replace('\r', ' ').replace('\n', ' ').strip()
        promoted_from_line = f"promoted_from: {promoted_from_value}\n" if promoted_from_value else ''
        legacy_id_value = str(legacy_id or '').replace('\r', ' ').replace('\n', ' ').strip()
        legacy_id_line = f"legacy_id: {legacy_id_value}\n" if legacy_id_value else ''
        task_family_line = ''
        execution_profile_line = ''
        project_ref_line = f"project_ref: {normalized_project_ref}\n" if normalized_project_ref else ''
        project_role_line = f"project_role: {normalized_project_role}\n" if normalized_project_role else ''
        if normalized_family and (is_dispatch_project(project) or task_family):
            task_family_line = f"task_family: {normalized_family}\n"
        if normalized_profile and (is_dispatch_project(project) or execution_profile):
            execution_profile_line = f"execution_profile: {normalized_profile}\n"

        content = f"""---
title: {title}
task_id: {task_id}
{legacy_id_line}{task_family_line}{execution_profile_line}workdir: {workdir}
created: {today}
updated: {today}
assignee: {assignee}
priority: {priority}
status: todo
kind: task
{project_ref_line}{project_role_line}{due_date_line}tags: []
{promoted_from_line}---

{body}
"""
        _atomic_write_text(filepath, content)

        # 更新状态文件计数器
        counters[prefix] = seq
        state['counters'] = counters
        save_state(state)

        rel_path = str(filepath.relative_to(REPO_ROOT))
        _lineage_record_card_created(rel_path, {
            'title': title,
            'task_id': task_id,
            'workdir': workdir,
            'assignee': assignee,
            'priority': priority,
            'status': 'todo',
            'project_ref': normalized_project_ref,
            'project_role': normalized_project_role,
            'promoted_from': promoted_from_value,
        })
        return True, rel_path, task_id


PROMOTE_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')
SCENARIO_SKELETON_SECTIONS = [
    '场景解决什么问题',
    '适合谁',
    '输入材料',
    'AI处理流程',
    '输出物',
    '验收标准',
    '可复用判断',
    '来源说明',
]

def _single_line_scalar(value):
    return str(value or '').replace('\r', ' ').replace('\n', ' ').strip()

# ── 晋升流已搬 promote_flow.py（单体手术第2批，MONOLITH_MAP 领地②）——委托桩 ──

PROMOTE_FILL_NON_DRAFT_ERROR = promote_flow.PROMOTE_FILL_NON_DRAFT_ERROR


def promote_task_to_scenario(path, slug):
    return promote_flow.promote_task_to_scenario(_maintenance_env(), path, slug)


def promote_fill_preview(path):
    return promote_flow.promote_fill_preview(_maintenance_env(), path)


def write_promote_fill(path, preview):
    return promote_flow.write_promote_fill(_maintenance_env(), path, preview)


def _redact_prompt_local_paths(text):
    return promote_flow._redact_prompt_local_paths(text)


def _build_scenario_draft(slug, source_fm):
    return promote_flow._build_scenario_draft(_maintenance_env(), slug, source_fm)


def _normalize_scenario_sections(text):
    return promote_flow._normalize_scenario_sections(_maintenance_env(), text)


def _build_promote_fill_messages(slug, task_file):
    return promote_flow._build_promote_fill_messages(_maintenance_env(), slug, task_file)


def _llm_provider_settings(provider):
    provider_name = str(provider or '').strip().lower()
    config = load_config()
    if provider_name == 'zhipu':
        return {
            'provider': provider_name,
            'url': config.get('zhipu_api_url') or ZHIPU_API_URL,
            'key': config.get('zhipu_api_key') or '',
            'model': config.get('zhipu_model') or ZHIPU_MODEL,
            'key_hint': 'zhipu_api_key / ZHIPU_API_KEY',
            'extra_payload': {'thinking': {'type': 'disabled'}},
        }, None
    if provider_name == 'deepseek':
        return {
            'provider': provider_name,
            'url': config.get('deepseek_api_url') or _DEFAULTS['deepseek_api_url'],
            'key': config.get('deepseek_api_key') or '',
            'model': config.get('deepseek_model') or _DEFAULTS['deepseek_model'],
            'key_hint': 'deepseek_api_key / DEEPSEEK_API_KEY',
            'extra_payload': {},
        }, None
    return None, f'不支持的 AI provider: {provider}'

def _llm_chat(provider, messages, max_tokens=1024, temperature=0.7):
    """Call an OpenAI-compatible chat completion provider with 3 retries."""
    settings, err = _llm_provider_settings(provider)
    if err:
        return False, err
    if not settings['key']:
        return False, f"未配置 {settings['provider']} AI 服务密钥 ({settings['key_hint']})"
    if not isinstance(messages, list) or not messages:
        return False, 'messages 不能为空'

    payload_data = {
        'model': settings['model'],
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }
    payload_data.update(settings.get('extra_payload') or {})
    payload = json.dumps(payload_data, ensure_ascii=False).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {settings['key']}",
    }

    for attempt in range(3):
        try:
            req = urllib.request.Request(settings['url'], data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                content = (((result.get('choices') or [{}])[0]).get('message') or {}).get('content')
                if not content:
                    return False, '模型返回空内容'
                return True, content.strip()
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode('utf-8', errors='replace').strip()
            except Exception:
                error_body = ''
            detail = f'HTTP {e.code}'
            if error_body:
                detail = f'{detail}: {error_body}'
            if 400 <= e.code < 500:
                return False, f"{settings['provider']} AI 调用失败: {detail}"
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return False, f"{settings['provider']} AI 调用失败: {detail}"
        except (urllib.error.URLError, socket.timeout, KeyError, IndexError, AttributeError, TypeError, json.JSONDecodeError) as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return False, f"{settings['provider']} AI 调用失败: {e}"

    return False, f"{settings['provider']} AI 调用失败"

# ── AI 标题生成 ────────────────────────────────────────

def generate_title_with_ai(body_text):
    """调用配置的 AI provider 生成任务标题，带 3 次重试"""
    config = load_config()
    provider = config.get('ai_provider') or _DEFAULTS['ai_provider']

    snippet = body_text[:200].strip()
    if not snippet:
        return False, '正文为空，无法生成标题'

    prompt = f'请根据以下任务内容，生成一个简洁的任务标题，不超过20个字。只输出标题文本，不要加引号或其他符号：\n\n{snippet}'
    ok, content = _llm_chat(provider, [{'role': 'user', 'content': prompt}], max_tokens=1024, temperature=0.7)
    if not ok:
        return False, content
    title = content.strip('"\'""''')
    if len(title) > 20:
        title = title[:20]
    return True, title

# ── 文档扫描 ──────────────────────────────────────────

def list_projects():
    """列出 project/ 下所有子文件夹（文件夹名 = 项目名）"""
    return [p.name for p in _iter_project_dirs()]

def _should_skip(filepath, skip_patterns):
    """检查文件名或相对路径是否匹配 skip_patterns（fnmatch glob 模式）。"""
    name = filepath.name
    rel = str(filepath.relative_to(REPO_ROOT))
    for pat in skip_patterns:
        if fnmatch(name, pat) or fnmatch(rel, pat):
            return True
    return False

def scan_all():
    """扫描所有项目文件夹内的 .md 文件（每个文件夹 = 项目，每个 .md = 任务）"""
    skip_patterns = load_config().get('skip_patterns', [])
    return task_scan_cache.scan_projects(
        REPO_ROOT,
        list(_iter_project_dirs()),
        skip_patterns=skip_patterns,
        should_skip=_should_skip,
        parse_file=_parse_task_document,
    )


def _parse_task_document(fpath, project_name):
    """Parse one candidate task file; task_scan_cache owns reuse and invalidation."""
    try:
        content = fpath.read_text(encoding='utf-8')
    except Exception:
        return None
    if '{' in content[:200]:
        return None
    fm, _ = extract_frontmatter(content)
    if not fm:
        return None
    doc = {
        'path': str(fpath.relative_to(REPO_ROOT)),
        'filename': fpath.name,
        'project': project_name,
        **fm,
    }
    status_changed_at, inferred = status_changed_at_for_frontend(fm)
    doc['status_changed_at'] = status_changed_at
    doc['status_changed_at_inferred'] = inferred
    doc['domain'] = infer_task_domain(fm, project=project_name, path=doc['path'])
    return doc


def _task_id_prefix(task_id):
    m = re.match(r'^([A-Z]{3})-\d+$', str(task_id or '').strip())
    return m.group(1) if m else ''


def _read_doc_body(doc):
    try:
        content = (REPO_ROOT / doc['path']).read_text(encoding='utf-8')
    except (KeyError, OSError, UnicodeDecodeError):
        return ''
    _, fm_block = extract_frontmatter(content)
    if fm_block:
        return content[len(fm_block):]
    return content


def infer_task_family_for_doc(doc, *, include_body=True):
    body = _read_doc_body(doc) if include_body else ''
    return infer_task_family(
        doc.get('project', ''),
        title=doc.get('title', ''),
        body=body,
        workdir=doc.get('workdir', ''),
        tags=doc.get('tags'),
        domain=doc.get('domain', ''),
        stage=doc.get('stage', ''),
        task_family=doc.get('task_family', ''),
    )


def _naming_issue_base(doc, issue_type, severity):
    family = normalize_task_family(doc.get('task_family', ''))
    task_id = str(doc.get('task_id') or '').strip()
    return {
        'type': issue_type,
        'severity': severity,
        'path': doc.get('path', ''),
        'project': doc.get('project', ''),
        'title': doc.get('title', ''),
        'status': doc.get('status', ''),
        'task_id': task_id,
        'task_id_prefix': _task_id_prefix(task_id),
        'task_family': family,
    }


def _task_ref(doc):
    return {
        'path': doc.get('path', ''),
        'title': doc.get('title', ''),
        'status': doc.get('status', ''),
    }


def _duplicate_task_id_issues(docs):
    by_task_id = {}
    for doc in docs:
        task_id = str(doc.get('task_id') or '').strip()
        if not task_id:
            continue
        by_task_id.setdefault(task_id, []).append(doc)

    issues = []
    for task_id, matches in sorted(by_task_id.items()):
        if len(matches) <= 1:
            continue
        paths = [m.get('path', '') for m in matches]
        issues.append({
            'type': 'duplicate_task_id',
            'severity': 'error',
            'task_id': task_id,
            'paths': paths,
            'conflicts': [_task_ref(m) for m in matches],
        })
    return issues


def _legacy_task_id_collision_issues(docs):
    by_task_id = {}
    for doc in docs:
        task_id = str(doc.get('task_id') or '').strip()
        if task_id:
            by_task_id.setdefault(task_id, []).append(doc)

    issues = []
    for doc in docs:
        legacy_id = str(doc.get('legacy_id') or '').strip()
        if not legacy_id:
            continue
        matches = by_task_id.get(legacy_id, [])
        if not matches:
            continue
        issue = _naming_issue_base(doc, 'legacy_task_id_collision', 'warning')
        issue.update({
            'legacy_id': legacy_id,
            'colliding_task_id_paths': [m.get('path', '') for m in matches],
            'collisions': [_task_ref(m) for m in matches],
            'message': 'legacy_id 与现行 task_id 碰撞；真迁移应保证 legacy_id 不再对应现行卡号',
        })
        issues.append(issue)
    return issues


def _execution_result_section_text(doc):
    body = _read_doc_body(doc)
    section = _find_markdown_section(body, '执行结果')
    if not section:
        return '', False
    return body[section['content_start']:section['end']], True


def _clean_execution_result_line(line):
    text = str(line or '').strip()
    text = re.sub(r'^(?:[-*+]\s+|>\s+)+', '', text).strip()
    text = re.sub(r'^\[[ xX]\]\s+', '', text).strip()
    return text


def _is_execution_result_placeholder_line(line):
    text = _clean_execution_result_line(line)
    if not text:
        return True
    bare = text.strip('()（）[]【】 ')
    if re.match(r'^待\s*回填[。.!！?？]*$', bare, re.I):
        return True
    if re.match(r'^(?:TODO|TBD)(?:[:：]?\s*(?:待回填|执行结果)?)?$', bare, re.I):
        return True
    if re.match(r'^(?:N/A|NA)$', bare, re.I):
        return True
    if not re.search(r'Codex', bare, re.I) or '回填' not in bare:
        return False
    if re.match(r'^Codex\s*回填[:：]?\s*$', bare, re.I):
        return True
    template_markers = (
        '待', '将', '完成后', '稍后', '模板', '占位',
        '每个', '实现与文件', '测试命令', '未决项',
    )
    return any(marker in bare for marker in template_markers)


def _is_empty_execution_result_text(text):
    stripped = str(text or '').strip()
    if not stripped:
        return True
    lines = [_clean_execution_result_line(line) for line in stripped.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return True
    return all(_is_execution_result_placeholder_line(line) for line in lines)


# ── 维护命令群已搬 maintenance_cli.py（单体手术第1批，MONOLITH_MAP 领地①）——委托桩 ──

class _MaintenanceEnv:
    """维护命令群的活依赖代理：属性访问即取本模块 globals() 现值。
    不走 sys.modules（测试用 importlib 裸加载时不注册模块名）。"""

    def __getattr__(self, name):
        return globals()[name]


_MAINTENANCE_ENV = _MaintenanceEnv()


def _maintenance_env():
    return _MAINTENANCE_ENV


def build_naming_lint_report(all_docs=None, *, active_only=True, include_body=True):
    return maintenance_cli.build_naming_lint_report(
        _maintenance_env(), all_docs, active_only=active_only, include_body=include_body)


def format_naming_lint_report(report):
    return maintenance_cli.format_naming_lint_report(_maintenance_env(), report)


_OWNERSHIP_AI_ASSIGNEES = {'ai', 'agent', 'codex', 'claude', 'workbuddy', 'machine'}
_OWNERSHIP_AI_RUNTIME_RE = re.compile(
    r'扫描|scan|lint|探针|probe|生成|刷新|回填|测试|验证|去重|预筛|统计|账本|ledger|'
    r'matrix\.probe|skill-state|治理后台|自治理后台|规则落账|命名|脚本|script|'
    r'read-?only|reversible',
    re.IGNORECASE,
)
_OWNERSHIP_HUMAN_DECISION_RE = re.compile(
    r'Owner\s*(确认|判断|选择|决定|拍板|审核|授权)|PI\s*(确认|判断|选择|决定|拍板|审核|授权)|'
    r'需要.{0,8}(确认|判断|选择|决定|拍板|审核|授权)|'
    r'是否|取舍|路线|策略|优先级|对外文案|客户判断|人工判断',
    re.IGNORECASE,
)
_OWNERSHIP_RECORD_RE = re.compile(
    r'记录卡|留档|已发生|recorded|retrospective|复盘记录|会话总结',
    re.IGNORECASE,
)
_DONE_CARD_COMPLETION_SECTION_RE = re.compile(
    r'(?m)^##\s*(完成标准|验证|交付|Owner\s*确认摘要|PI\s*确认摘要)\b',
    re.IGNORECASE,
)
_DONE_CARD_BRIEF_SECTION_RE = re.compile(
    r'(?m)^##\s*(背景\s*/\s*来源|要做什么|输入与材料|执行结果)\b',
    re.IGNORECASE,
)


def _ownership_text(doc):
    tags = doc.get('tags')
    tags_text = ' '.join(str(tag or '') for tag in tags) if isinstance(tags, list) else str(tags or '')
    parts = [
        doc.get('title'),
        doc.get('display_title'),
        doc.get('task_id'),
        doc.get('next_action'),
        doc.get('source'),
        doc.get('stage'),
        doc.get('workdir'),
        doc.get('safety'),
        tags_text,
    ]
    return _governance_noise_text(' '.join(str(part or '') for part in parts))


def _ownership_owner_visible_reasons(doc):
    reasons = []
    responsibility = str(doc.get('responsibility') or '').strip().lower()
    assignee = str(doc.get('assignee') or '').strip().lower()
    if responsibility in {'pi-gated', 'human-gated', 'owner-gated'}:
        reasons.append(f'responsibility:{responsibility}')
    if assignee in {'owner', 'jun'}:
        reasons.append('assignee:owner')
    return reasons


def _ownership_ai_owned_reversible_reasons(doc):
    reasons = []
    responsibility = str(doc.get('responsibility') or '').strip().lower()
    assignee = str(doc.get('assignee') or '').strip().lower()
    safety = str(doc.get('safety') or '').strip().lower()
    text = _ownership_text(doc)

    if responsibility in {'ai-owned', 'machine-owned'}:
        reasons.append(f'responsibility:{responsibility}')
    if assignee in _OWNERSHIP_AI_ASSIGNEES:
        reasons.append(f'assignee:{assignee}')
    if safety in {'read-only', 'reversible'}:
        reasons.append(f'safety:{safety}')
    if _OWNERSHIP_AI_RUNTIME_RE.search(text):
        reasons.append('runtime_signal')
    if str(doc.get('status') or '').strip().lower() == 'done' and _OWNERSHIP_RECORD_RE.search(text):
        reasons.append('record_signal')
    return reasons


def _frontmatter_date(value):
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', str(value or '').strip())
    return match.group(1) if match else ''


def _done_card_backstage_reasons(doc):
    reasons = []
    explicit_fields = {
        'audience': {'backstage', '后台', 'internal', 'internal-ledger', 'ledger'},
        'visibility': {'backstage', '后台', 'internal', 'internal-ledger', 'ledger'},
        'owner_visible': {'false', 'no', '0'},
    }
    for field, allowed in explicit_fields.items():
        value = str(doc.get(field) or '').strip().lower()
        if value in allowed:
            reasons.append(f'{field}:{value}')
    return reasons


def _done_card_owner_visible_record_reasons(doc):
    reasons = []
    kind = str(doc.get('kind') or '').strip().lower()
    if kind == 'record':
        reasons.append('kind:record')
    for field in ('audience', 'visibility'):
        value = str(doc.get(field) or '').strip().lower()
        if value in {'owner', 'pi', 'review', 'owner-visible', 'pi-visible'}:
            reasons.append(f'{field}:{value}')
    if str(doc.get('needs_review') or '').strip().lower() in {'true', 'yes', '1'}:
        reasons.append('needs_review:true')
    if str(doc.get('requires_acceptance') or '').strip().lower() in {'true', 'yes', '1'}:
        reasons.append('requires_acceptance:true')
    return reasons


def _done_card_has_completion_structure(doc):
    body = _read_doc_body(doc)
    if not body:
        return False
    return bool(_DONE_CARD_COMPLETION_SECTION_RE.search(body) and _DONE_CARD_BRIEF_SECTION_RE.search(body))


def _git_review_status_presence(path):
    """Return True/False when git can prove review presence/absence, None when unknown."""
    if not path:
        return None
    try:
        proc = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'log', '--format=%H', '--', path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commits = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not commits:
        return None
    for sha in commits:
        try:
            diff = subprocess.run(
                ['git', '-C', str(REPO_ROOT), 'show', sha, '--', path],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if diff.returncode != 0:
            continue
        if re.search(r'^\+\s*status:\s*review\s*$', diff.stdout, re.MULTILINE):
            return True
    return False


def _done_at_creation_issue(doc):
    if str(doc.get('status') or '').strip().lower() != 'done':
        return None, _done_card_backstage_reasons(doc)

    backstage_reasons = _done_card_backstage_reasons(doc)
    if backstage_reasons:
        return None, backstage_reasons

    visible_record_reasons = _done_card_owner_visible_record_reasons(doc)
    if not visible_record_reasons:
        return None, []

    has_completion_structure = _done_card_has_completion_structure(doc)
    if not has_completion_structure:
        return None, []

    reasons = []
    created_date = _frontmatter_date(doc.get('created'))
    changed_date = _frontmatter_date(doc.get('status_changed_at'))
    changed_inferred = bool(doc.get('status_changed_at_inferred'))
    if created_date and changed_date and created_date == changed_date and not changed_inferred:
        reasons.append('status_changed_at_same_day_as_created')
        reasons.append('completion_or_delivery_brief_structure')
        reasons.extend(visible_record_reasons)

    responsibility = str(doc.get('responsibility') or '').strip().lower()
    review_presence = _git_review_status_presence(doc.get('path', ''))
    if review_presence is False and responsibility in {'ai-owned', 'machine-owned'}:
        reasons.append('git_history_has_no_review_status')
        reasons.append(f'responsibility:{responsibility}')
        reasons.extend(visible_record_reasons)

    if not reasons:
        return None, []

    return {
        'type': 'done_at_creation_owner_visible',
        'severity': 'error',
        'path': doc.get('path', ''),
        'project': doc.get('project', ''),
        'task_id': doc.get('task_id') or doc.get('legacy_id') or '',
        'title': doc.get('title') or doc.get('display_title') or '',
        'status': doc.get('status') or '',
        'created': doc.get('created') or '',
        'status_changed_at': doc.get('status_changed_at') or '',
        'responsibility': doc.get('responsibility') or '',
        'audience': doc.get('audience') or doc.get('visibility') or '',
        'reasons': reasons,
        'recommendation': '要 Owner 看见/验收的记录先落 status: review；纯后台台账需显式 audience: backstage',
    }, []


def _is_suspected_ownership_misopen(doc):
    if not _ownership_owner_visible_reasons(doc):
        return False, []
    hard_gate = _governance_noise_hard_gate_signals(doc)
    if hard_gate:
        return False, []
    text = _ownership_text(doc)
    if _PRE_EXEC_GATE_RE.search(text) or _OWNERSHIP_HUMAN_DECISION_RE.search(text):
        return False, []
    ai_reasons = _ownership_ai_owned_reversible_reasons(doc)
    if 'runtime_signal' in ai_reasons or any(reason.startswith(('assignee:', 'safety:', 'responsibility:ai-owned', 'responsibility:machine-owned')) for reason in ai_reasons):
        return True, ai_reasons
    return False, []


def _ownership_issue(doc, ai_reasons):
    return {
        'type': 'suspected_false_open',
        'severity': 'warning',
        'path': doc.get('path', ''),
        'project': doc.get('project', ''),
        'task_id': doc.get('task_id') or doc.get('legacy_id') or '',
        'title': doc.get('title') or doc.get('display_title') or '',
        'status': doc.get('status') or '',
        'assignee': doc.get('assignee') or '',
        'responsibility': doc.get('responsibility') or '',
        'safety': doc.get('safety') or '',
        'owner_visible_reasons': _ownership_owner_visible_reasons(doc),
        'ai_owned_reversible_reasons': ai_reasons,
        'recommendation': '改为 ai-owned + read-only/reversible，或保留 Owner gate 并补充硬门槛证据',
    }


def build_ownership_lint_report(all_docs=None, *, active_only=True, dispatch_only=True):
    """Read-only lint for ownership false-open and done-at-creation visibility escapes."""
    docs = list(all_docs) if all_docs is not None else scan_all()
    checked = []
    done_checked = []
    skipped_inactive = 0
    skipped_non_dispatch = 0
    for doc in docs:
        if dispatch_only and not is_dispatch_project(doc.get('project', '')):
            skipped_non_dispatch += 1
            continue
        status = str(doc.get('status') or '').strip().lower()
        if status == 'done':
            done_checked.append(doc)
        if active_only and status not in ACTIVE_TASK_STATUSES:
            skipped_inactive += 1
            continue
        checked.append(doc)

    issues = []
    backstage_done_exempted = 0
    owner_visible_checked = 0
    for doc in checked:
        if _ownership_owner_visible_reasons(doc):
            owner_visible_checked += 1
        suspected, ai_reasons = _is_suspected_ownership_misopen(doc)
        if suspected:
            issues.append(_ownership_issue(doc, ai_reasons))

    for doc in done_checked:
        issue, backstage_reasons = _done_at_creation_issue(doc)
        if backstage_reasons:
            backstage_done_exempted += 1
        if issue:
            issues.append(issue)

    checked_count = len(checked)
    suspected_count = len([issue for issue in issues if issue.get('type') == 'suspected_false_open'])
    done_escape_count = len([issue for issue in issues if issue.get('type') == 'done_at_creation_owner_visible'])
    summary = {
        'checked_active_cards': checked_count,
        'checked_done_cards': len(done_checked),
        'owner_visible_checked': owner_visible_checked,
        'suspected_misopened': suspected_count,
        'done_at_creation_owner_visible': done_escape_count,
        'backstage_done_exempted': backstage_done_exempted,
        'total_issues': len(issues),
        'misopen_rate_all': (suspected_count / checked_count) if checked_count else 0,
        'misopen_rate_owner_visible': (suspected_count / owner_visible_checked) if owner_visible_checked else 0,
        'skipped_inactive_cards': skipped_inactive,
        'skipped_non_dispatch_cards': skipped_non_dispatch,
    }
    return {
        'ok': len(issues) == 0,
        'scope': {
            'scan_dirs': list(SCAN_DIRS),
            'dispatch_only': dispatch_only,
            'dispatch_projects': sorted(DISPATCH_PROJECT_NAMES),
            'active_only': active_only,
            'active_statuses': sorted(ACTIVE_TASK_STATUSES),
            'hard_gate_policy': 'suspected false-open is suppressed when send/publish/spend/delete/move/permission/external/pre-exec/human-decision signals exist',
            'done_visibility_policy': 'CONVENTION hard rule 7: Owner-visible records must pass review before done; pure backstage ledgers must declare audience: backstage (or visibility: backstage / owner_visible: false)',
        },
        'summary': summary,
        'issues': issues,
    }


def format_ownership_lint_report(report):
    summary = report.get('summary') or {}
    suspected = summary.get('suspected_misopened', 0)
    done_escapes = summary.get('done_at_creation_owner_visible', 0)
    checked = summary.get('checked_active_cards', 0)
    done_checked = summary.get('checked_done_cards', 0)
    owner_visible = summary.get('owner_visible_checked', 0)
    all_rate = summary.get('misopen_rate_all', 0) * 100
    owner_rate = summary.get('misopen_rate_owner_visible', 0) * 100
    lines = [
        (
            f"归属 lint: suspected_false_open {suspected}/{checked} "
            f"({all_rate:.1f}% active dispatch; {suspected}/{owner_visible} = {owner_rate:.1f}% Owner-visible); "
            f"done_at_creation_owner_visible {done_escapes}/{done_checked} done dispatch"
        )
    ]
    lines.append("done 豁免规则: 纯后台台账需显式 audience: backstage（或 visibility: backstage / owner_visible: false）。")
    if not report.get('issues'):
        lines.append("未发现活跃 dispatch 卡疑似误开给 Owner。")
        return '\n'.join(lines)
    for issue in report['issues']:
        if issue.get('type') == 'done_at_creation_owner_visible':
            reasons = ','.join(issue.get('reasons') or [])
            lines.append(
                f"- [ERROR] {issue.get('task_id') or '(no task_id)'} {issue.get('path')}: "
                f"done-at-creation visibility escape ({reasons})"
            )
        else:
            reasons = ','.join(issue.get('ai_owned_reversible_reasons') or [])
            gates = ','.join(issue.get('owner_visible_reasons') or [])
            lines.append(
                f"- [WARN] {issue.get('task_id') or '(no task_id)'} {issue.get('path')}: "
                f"{gates} but {reasons}"
            )
    return '\n'.join(lines)


_GRILL_IN_PROGRESS_STATUSES = {'in-progress', 'in_progress', 'in progress', 'inprogress', 'doing'}


def build_grill_lint_report(all_docs=None, *, dispatch_only=True):
    """Read-only lint for Owner execution cards entering progress without a completed grill."""
    docs = list(all_docs) if all_docs is not None else scan_all()
    candidates = []
    missing = 0
    pending = 0
    for doc in docs:
        if dispatch_only and not is_dispatch_project(doc.get('project', '')):
            continue
        assignee = str(doc.get('assignee') or '').strip().lower()
        status = str(doc.get('status') or '').strip().lower()
        if assignee not in {'owner', 'jun'} or status not in _GRILL_IN_PROGRESS_STATUSES:
            continue
        grill_status = str(doc.get('grill_status') or '').strip()
        if not grill_status:
            issue = 'missing_grill_status'
            missing += 1
        elif grill_status.lower() == 'pending':
            issue = 'pending_grill'
            pending += 1
        else:
            continue
        candidates.append({
            'task_id': doc.get('task_id') or doc.get('legacy_id') or '',
            'path': doc.get('path', ''),
            'issue': issue,
        })
    checked = sum(
        1 for doc in docs
        if (not dispatch_only or is_dispatch_project(doc.get('project', '')))
        and str(doc.get('assignee') or '').strip().lower() in {'owner', 'jun'}
        and str(doc.get('status') or '').strip().lower() in _GRILL_IN_PROGRESS_STATUSES
    )
    candidates.sort(key=lambda item: (item['task_id'], item['path']))
    return {
        'ok': not candidates,
        'checked_owner_execution_cards': checked,
        'missing_grill_status': missing,
        'pending_grill': pending,
        'candidates': candidates,
    }


def format_grill_lint_report(report):
    lines = [
        'Owner 执行卡 grill lint: '
        f"checked {report.get('checked_owner_execution_cards', 0)}, "
        f"missing {report.get('missing_grill_status', 0)}, "
        f"pending {report.get('pending_grill', 0)}"
    ]
    if not report.get('candidates'):
        lines.append('未发现进行中但 grill 闸未完成的 Owner 执行卡。')
    else:
        for item in report['candidates']:
            lines.append(f"- {item.get('task_id') or '(no task_id)'} {item.get('path')}: {item.get('issue')}")
    return '\n'.join(lines)


def backfill_active_task_families(all_docs=None):
    """Backfill task_family for active dispatch cards when inference is confident."""
    docs = list(all_docs) if all_docs is not None else scan_all()
    result = {'updated': [], 'needs_confirmation': [], 'errors': []}
    for doc in docs:
        if not is_dispatch_project(doc.get('project', '')):
            continue
        if str(doc.get('status') or '').strip() not in ACTIVE_TASK_STATUSES:
            continue
        if normalize_task_family(doc.get('task_family', '')):
            continue
        inferred = infer_task_family_for_doc(doc, include_body=True)
        if not inferred or inferred == 'legacy':
            result['needs_confirmation'].append({
                'path': doc.get('path', ''),
                'task_id': doc.get('task_id', ''),
                'title': doc.get('title', ''),
            })
            continue
        ok, msg = update_frontmatter_field(doc['path'], 'task_family', inferred)[:2]
        if ok:
            doc['task_family'] = inferred
            result['updated'].append({
                'path': doc.get('path', ''),
                'task_id': doc.get('task_id', ''),
                'task_family': inferred,
            })
        else:
            result['errors'].append({
                'path': doc.get('path', ''),
                'task_id': doc.get('task_id', ''),
                'error': msg,
            })
    return result


def _git_file_author(rel_path):
    """Return the first-commit author for a file, or empty string."""
    try:
        proc = subprocess.run(
            ['git', 'log', '--diff-filter=A', '--format=%an', '--', rel_path],
            capture_output=True, text=True, timeout=3,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode == 0:
            name = proc.stdout.strip().split('\n')[0].strip()
            return name if name else ''
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ''

def search_all_files(query='', project='', offset=0, limit=50, category=''):
    """搜索 SCAN_DIRS 下所有文件和目录，支持空查询、项目优先和分页。"""
    query = str(query or '')
    project = str(project or '').strip().strip('/')
    category = str(category or '').strip()
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 50

    qlower = query.lower()
    skip_patterns = load_config().get('skip_patterns', [])
    _all_docs = scan_all()
    task_paths = set()
    task_assignees = {}
    task_search_text = {}
    for doc in _all_docs:
        p = doc.get('path', '')
        if p and doc.get('task_id') and p.endswith('.md'):
            task_paths.add(p)
            task_search_text[p] = _task_text_blob(
                doc.get('task_id', ''),
                doc.get('legacy_id', ''),
                doc.get('title', ''),
            )
            if doc.get('assignee'):
                task_assignees[p] = doc['assignee']
    seen = set()
    results = []

    def _matches(name, rel, extra=''):
        if not qlower:
            return True
        return qlower in name.lower() or qlower in rel.lower() or qlower in str(extra or '').lower()

    def _add(name, rel, is_dir):
        if rel in seen:
            return
        seen.add(rel)
        ext = '' if is_dir else Path(name).suffix.lower()
        is_task = (not is_dir) and rel in task_paths
        ftype = 'folder' if is_dir else ('task' if is_task else _classify_file(name, False))
        if ftype == 'task' and not is_task:
            ftype = 'document'
        results.append({
            'name': name,
            'path': rel,
            'type': ftype,
            'ext': ext,
            'is_task': is_task,
            'is_dir': is_dir,
        })

    for d in SCAN_DIRS:
        target = REPO_ROOT / d
        if not target.exists():
            continue
        for root, dirs, files in os.walk(target):
            dirs[:] = [
                x for x in dirs
                if not x.startswith('.')
                and x != 'vendor'
                and not (skip_patterns and _should_skip(Path(root) / x, skip_patterns))
            ]
            for dirname in dirs:
                dpath = Path(root) / dirname
                rel = str(dpath.relative_to(REPO_ROOT))
                if skip_patterns and _should_skip(dpath, skip_patterns):
                    continue
                if _matches(dirname, rel):
                    _add(dirname, rel, True)
            for f in files:
                if f.startswith('.'):
                    continue
                fpath = Path(root) / f
                rel = str(fpath.relative_to(REPO_ROOT))
                if skip_patterns and _should_skip(fpath, skip_patterns):
                    continue
                if _matches(f, rel, task_search_text.get(rel, '')):
                    _add(f, rel, False)

    project_prefix = f"project/{project}/" if project else ''

    def _sort_key(item):
        name = item['name'].lower()
        path = item['path'].lower()
        in_project = bool(project_prefix and item['path'].startswith(project_prefix))
        project_rank = 0 if in_project else 1
        if name == qlower:
            match_rank = 0
        elif qlower and name.startswith(qlower):
            match_rank = 1
        elif qlower and qlower in name:
            match_rank = 2
        elif qlower and qlower in path:
            match_rank = 3
        else:
            match_rank = 4
        return (project_rank, match_rank, name, path)

    results.sort(key=_sort_key)
    category_counts = {}
    for item in results:
        category_counts[item['type']] = category_counts.get(item['type'], 0) + 1
    all_total = len(results)
    if category and category != 'all':
        results = [item for item in results if item['type'] == category]
    total = len(results)
    page = results[offset:offset + limit]
    for item in page:
        if item['is_task']:
            item['author'] = task_assignees.get(item['path'], '')
        elif not item['is_dir'] and item['type'] != 'folder':
            item['author'] = _git_file_author(item['path'])
        if not item['is_dir']:
            try:
                mt = os.path.getmtime(REPO_ROOT / item['path'])
                item['mtime'] = datetime.fromtimestamp(mt).strftime('%Y-%m-%d %H:%M')
            except OSError:
                pass
    return page, total, all_total, category_counts

def get_data():
    all_docs = scan_all()
    real_project_projection, _real_project_status = real_projects.build_projection(
        _real_projects_deps(all_docs)
    )
    project_posture = real_projects.build_project_posture(real_project_projection)
    project_names = list_projects()
    config = load_config()
    user_cfg = load_user_config()
    user_tools = user_cfg.get('tools', {}) if isinstance(user_cfg.get('tools'), dict) else {}
    cli_tools = []
    for name, command in CLI_COMMANDS.items():
        executable = command[0] if command else ''
        available = bool(executable and (
            (os.path.isabs(executable) and os.access(executable, os.X_OK))
            or shutil.which(executable)
        ))
        cli_tools.append({'name': name, 'available': available})
    ai_members = config.get('ai_members') or []
    assignee_members = _combined_assignee_members(ALL_MEMBERS, ai_members)
    members = sorted(set(
        d.get('assignee', '') for d in all_docs if d.get('assignee')
    ))
    active_projects = len(set(
        d.get('project') for d in all_docs
        if d.get('project') and d.get('status', 'todo') != 'done'
    ))

    # task_id 直接从 YAML frontmatter 读取
    for doc in all_docs:
        code = doc.get('task_id', '')
        # 生成看板显示标题: [HER-1]Title
        title = doc.get('display_title') or doc.get('title', doc.get('filename', ''))
        doc['display_title'] = f"[{code}]{title}" if code else title

    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'stats': {
            'total_tasks': len(all_docs),
            'projects': len(project_names),
            'active_projects': active_projects,
            'members': len(members),
        },
        'tasks': all_docs,
        'project_posture': project_posture,
        # Full evidence/detail payload remains for the secondary project index.
        # The dispatch console consumes project_posture only.
        'real_projects': real_project_projection,
        'members': members,
        'login_members': LOGIN_MEMBERS,
        'project_names': project_names,
        'all_members': assignee_members,
        'ai_members': ai_members,
        'team_kanban_url': config.get('team_kanban_url') or _DEFAULTS['team_kanban_url'],
        'canvas_studio_url': config.get('canvas_studio_url') or _DEFAULTS['canvas_studio_url'],
        'team_digest': load_team_kanban_digest(config),
        'team_handoff': _team_handoff_options(config),
        'chains': configured_chains(config),
        'research_boards': discover_research_boards(config),
        'deployment_paths': configured_deployment_paths(config),
        'local_integrations': configured_local_integrations(config),
        'ui_features': configured_ui_features(config),
        'default_tools': {name: cfg['command'] for name, cfg in _DEFAULTS['tools'].items()},
        'ai_profiles': public_ai_profiles(normalize_ai_profiles(config)),
        'user_tool_overrides': {
            name: cfg['command']
            for name, cfg in user_tools.items()
            if isinstance(cfg, dict) and cfg.get('command')
        },
        'cli_status': {
            'available': sum(1 for tool in cli_tools if tool['available']),
            'configured': len(cli_tools),
            'tools': cli_tools,
        },
        'git_sync': _sync_status_payload(),
        'team_sync': TEAM_SYNC_MANAGER.snapshot() if TEAM_SYNC_MANAGER else {'enabled': False},
    }


def get_attention_gate_summary():
    return {'ok': False, 'enabled': False, 'reason': 'optional attention summary capability is not installed'}


def get_attention_gate_duty_panel():
    return {'ok': False, 'enabled': False, 'reason': 'optional duty capability is not installed'}


def get_attention_gate_context():
    return {'ok': False, 'enabled': False, 'reason': 'optional context capability is not installed'}


def get_task_detail(path=None, code=None):
    """
    获取单个任务的完整详情（frontmatter 解析 + 原始内容）。

    参数:
        path: 任务文件的相对路径 (如 "project/Hermes/sample-task.md")
        code: 任务编号 (如 "HER-1")

    返回:
        (dict, int) — 成功时返回 ({ok: True, task: {...}}, 200)
        失败时返回 ({ok: False, error: "..."}, 状态码)
    """
    from urllib.parse import unquote

    if not path and not code:
        return {'ok': False, 'error': '缺少参数'}, 400

    # 如果通过 code 查询，从 frontmatter 中的 task_id / legacy_id 查找
    if code and not path:
        all_docs = scan_all()
        matched_path = None
        for doc in all_docs:
            if doc.get('task_id') == code or doc.get('legacy_id') == code:
                matched_path = doc['path']
                break
        if not matched_path:
            return {'ok': False, 'error': '文件不存在'}, 404
        path = matched_path

    # 安全检查：防止路径遍历
    decoded_path = unquote(path)
    if '..' in decoded_path or decoded_path.startswith('/'):
        return {'ok': False, 'error': '非法路径'}, 400

    filepath = REPO_ROOT / decoded_path
    if not filepath.exists():
        return {'ok': False, 'error': '文件不存在'}, 404

    file_data, err = _read_task_file(decoded_path)
    if not file_data:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
    raw = file_data['raw']
    fm = file_data['frontmatter']
    body = file_data['body']

    # 从当前 scan_dirs 项目叶子推导 project，兼容 project/* 与 demo/projects/*。
    project = _get_project_name_from_path(decoded_path)
    filename = Path(decoded_path).name

    # 获取 task_id（直接从 frontmatter 读取）
    task_id = fm.get('task_id', '')
    status_changed_at, status_changed_inferred = status_changed_at_for_frontend(fm)

    # 构建标准化的字段
    task = {
        'path': decoded_path,
        'filename': filename,
        'project': project,
        'title': fm.get('title', ''),
        'workdir': fm.get('workdir', ''),
        'source_path': fm.get('source_path', ''),
        'source': fm.get('source', ''),
        'stage': fm.get('stage', ''),
        'status': fm.get('status', 'todo'),
        'kind': fm.get('kind', 'task'),
        'domain': infer_task_domain(fm, project=project, path=decoded_path),
        'priority': fm.get('priority', 'medium'),
        'assignee': fm.get('assignee', ''),
        'created': fm.get('created', ''),
        'updated': fm.get('updated', ''),
        'status_changed_at': status_changed_at,
        'status_changed_at_inferred': status_changed_inferred,
        'due_date': fm.get('due_date', ''),
        'tags': fm.get('tags', []),
        'scenario_slug': fm.get('scenario_slug', ''),
        'promoted_to': fm.get('promoted_to', ''),
        'promoted_from': fm.get('promoted_from', ''),
        'remote_url': fm.get('remote_url', ''),
        'team_path': fm.get('team_path', ''),
        'team_handoff_status': fm.get('team_handoff_status', ''),
        'team_handoff_url': fm.get('team_handoff_url', ''),
        'next_action': fm.get('next_action', ''),
        'ai_note': _extract_card_note(body),
        'task_id': task_id,
        'body': body,
        'raw': raw,
        'rev': file_data['rev'],
    }
    for key, value in fm.items():
        if key not in task:
            task[key] = value

    return {'ok': True, 'task': task}, 200


def get_mario_level(task_path='', level_id=''):
    if mario_levels is None:
        return {'ok': False, 'available': False, 'error': 'Mario level module unavailable'}, 404
    registration = mario_levels.get_registration(level_id=level_id) if level_id else None
    if level_id and not registration:
        return {'ok': False, 'available': False, 'error': 'Mario level not found'}, 404
    if registration:
        task_result, status = get_task_detail(code=registration['task_id'])
    else:
        task_result, status = get_task_detail(path=task_path)
    if status != 200:
        return task_result, status
    result, build_status = mario_levels.build_level(task_result['task'], {
        'repo_root': REPO_ROOT,
        'documents_root': DOCUMENTS_ROOT,
    }, level_id=level_id or None)
    if build_status == 200 and result.get('level') and registration and registration.get('game_projection_path'):
        result['level']['game_map_url'] = (
            '/api/mario-game-map?level_id=' + quote(str(registration['level_id']), safe='')
        )
    return result, build_status


def get_mario_game_map_html(level_id=''):
    if mario_levels is None:
        return '<main><h1>Mario 人物地图不可用</h1></main>', 404
    registration = mario_levels.get_registration(level_id=level_id)
    if not registration or not registration.get('game_projection_path'):
        return '<main><h1>Mario 人物地图不可用</h1></main>', 404
    result, status = get_mario_level(level_id=level_id)
    if status != 200 or not result.get('ok') or not result.get('level'):
        message = str(result.get('error') or result.get('message') or '来源读取失败')
        return f'<main><h1>Mario 人物地图生成失败</h1><p>{html.escape(message)}</p></main>', status
    projection = mario_game_projection.build_game_projection(result['level'])
    fragment = render_mario_game_map.render_fragment(projection)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(str(projection.get("subject", {}).get("label") or "Mario"))} · Mario 人物地图</title>'
        '<style>html,body{margin:0;min-height:100%;background:#f7f9fc}</style></head>'
        f'<body>{fragment}</body></html>'
    ), 200


def get_mario_surface_feed(origin=''):
    levels = []
    failures = []
    if mario_levels is None:
        return {'ok': True, 'status': 'healthy', 'surfaces': [], 'failure_count': 0}, 200
    registry, _ = mario_levels.list_levels()
    for descriptor in registry.get('levels', []):
        registration = mario_levels.get_registration(level_id=descriptor.get('level_id'))
        task_result, status = get_task_detail(code=descriptor.get('task_id'))
        if status != 200 or not task_result.get('ok'):
            failures.append({
                'registration': registration,
                'message': task_result.get('error') or task_result.get('message') or '任务来源读取失败，不能按空结果处理',
            })
            continue
        result, build_status = mario_levels.build_level(task_result['task'], {
            'repo_root': REPO_ROOT,
            'documents_root': DOCUMENTS_ROOT,
        }, level_id=descriptor.get('level_id'))
        if build_status != 200 or not result.get('available'):
            failures.append({
                'registration': registration,
                'message': result.get('error') or '关卡投影失败，不能按空结果处理',
            })
            continue
        levels.append(result['level'])
    return mario_levels.build_surface_feed(levels, failures, origin=origin)


_LANDING_REFRESH_PROMPT_MAX_CHARS = 120000


def _text_for_prompt(text, max_chars=_LANDING_REFRESH_PROMPT_MAX_CHARS):
    text = str(text or '')
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f'\n\n[内容过长，已截断 {omitted} 字；执行前必须从磁盘重新读取完整文件。]'


def _build_landing_refresh_prompt(task_path, task_raw, landing_page, landing_html, workdir_value):
    today = datetime.now().strftime('%Y-%m-%d')
    return f"""你是本地执行 Agent，当前工作目录已经由看板按任务卡 workdir 校验并设置。

第一性原理：
- 任务卡 = 事实源。
- 状态页 = 给人看的可读快照。
- 你的目标是把 `landing_page` 指向的 HTML 刷新到与当前任务卡和项目实际状态一致，并让漂移可见性重新归零。

本次绑定事实：
- 任务卡路径：{task_path}
- landing_page：{landing_page}
- 任务卡 workdir 字段：{workdir_value or '(空，按任务卡所在目录解析)'}
- 今天日期：{today}

必须读取和核对：
- 本提示词内附的任务卡 frontmatter + 正文；如有疑问，以磁盘上的 `{task_path}` 为准。
- 本提示词内附的现有 `{landing_page}` HTML；写入前必须从磁盘再次读取完整 HTML。
- 项目 README / CLAUDE / AGENTS / 配置模板（例如 README.md、CLAUDE.md、AGENTS.md、.kanban.config.example.json、kanban.env.example，存在才读）。
- 相关 state JSON、生成脚本、必要测试 / lint / 运行摘要；只使用能复核的本地事实。

必须排除：
- `.env`、token、cookie、API key、chat_id、浏览器资料、私有日志原文。
- 未核实客户材料与会议正文。
- 不可复核的记忆数字。
- 过期路径或历史测试卡，除非明确标注为历史证据。

读者与表达：
- 读者是 Owner、同事，以及可能的对外展示对象。
- 页面要可读、可视、不抽象；对外语境中性化。
- HTML 中不要写入内部绝对路径、密钥、token、app id、chat_id 或会议正文。

产物边界：
- 只重写 `{landing_page}` 指向的 HTML。
- 不修改任务卡正文、frontmatter 或无关文件。
- 不做后台自动刷新、首页最近状态页、skill 化或模板分类。

<task_card path="{task_path}">
{_text_for_prompt(task_raw)}
</task_card>

<existing_landing_page path="{landing_page}">
{_text_for_prompt(landing_html)}
</existing_landing_page>
"""


def _build_landing_review_prompt(task_path, task_raw, landing_page, landing_html, workdir_value):
    today = datetime.now().strftime('%Y-%m-%d')
    return f"""你是本地看板的 Landing page 归属校验 Agent。当前工作目录已经由看板按任务卡 workdir 校验并设置。

第一性原理：
- 任务卡 = 事实源。
- landing_page = 这张任务卡自己的给人看的项目状态页。
- 示例页、别的项目页、历史页面、能力样例页，不能冒充当前任务卡自己的状态页。
- 代码只负责安全读取路径；语义归属必须由你基于证据判断。

本次绑定事实：
- 任务卡路径：{task_path}
- landing_page：{landing_page}
- 任务卡 workdir 字段：{workdir_value or '(空，按任务卡所在目录解析)'}
- 今天日期：{today}

你必须做的判断：
1. 这个 HTML 的标题、H1、主体叙事、关键路径，讲的是不是当前任务卡自己的项目。
2. HTML 中引用的 task_id、任务卡标题、事实源路径，是否与当前任务卡一致。
3. 它是否只是当前任务卡正文里的“样例页”，而不是本卡自己的 landing_page。
4. 页面状态、next_action、完成情况，是否与任务卡最新状态明显冲突。
5. 是否出现不应进入状态页的敏感材料：`.env`、token、cookie、API key、chat_id、浏览器资料、私有日志原文、未核实客户材料、会议正文。

输出固定格式，禁止自由发挥：

## 结论
绿灯 / 黄灯 / 红灯 三选一，并用一句小白能懂的话说明。

## 证据
- 任务卡证据：列出 task_id、标题、当前目标。
- HTML 证据：列出 title/H1/页面自述/引用路径中最关键的 2-4 条。
- 冲突或一致性判断：说明为什么是绿灯、黄灯或红灯。

## 建议动作
- 如果绿灯：说明可以继续使用。
- 如果黄灯：说明需要人工确认什么。
- 如果红灯：说明应该改成哪个页面，或应该新建/更新哪个页面。

边界：
- 只审查，不修改任何文件。
- 不运行删除、提交、推送、发送消息、上传、联网搜索等动作。
- 不输出密钥、token、chat_id 或私有正文；如发现，只按“存在敏感材料风险”描述。

<task_card path="{task_path}">
{_text_for_prompt(task_raw)}
</task_card>

<landing_page_html path="{landing_page}">
{_text_for_prompt(landing_html)}
</landing_page_html>
"""


def _prepare_landing_prompt(path, prompt_builder):
    decoded_path = unquote(str(path or ''))
    if '..' in decoded_path or decoded_path.startswith('/'):
        return {'ok': False, 'error': '非法路径'}, 400
    task_file, err = _read_task_file(decoded_path)
    if not task_file:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
    fm = task_file['frontmatter']
    landing_page = str(fm.get('landing_page') or '').strip()
    if not landing_page:
        return {'ok': False, 'error': '缺少 landing_page'}, 400

    landing_target, landing_err, landing_status = resolve_open_target(landing_page)
    if landing_err:
        return {'ok': False, 'error': landing_err}, landing_status
    if landing_target.suffix.lower() not in ('.html', '.htm'):
        return {'ok': False, 'error': 'landing_page 必须指向 HTML 文件'}, 400
    try:
        landing_html = landing_target.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        return {'ok': False, 'error': f'读取 landing_page 失败: {exc}'}, 400

    workdir_value = fm.get('workdir', '') if fm else ''
    cwd_path, cwd_err = resolve_workdir(workdir_value, decoded_path)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    if not cwd_path.exists():
        return {'ok': False, 'error': 'workdir_not_found', 'workdir': str(cwd_path)}, 400
    if 'codex' not in CLI_COMMANDS:
        return {'ok': False, 'error': 'Codex 未配置'}, 400

    prompt = prompt_builder(
        decoded_path,
        task_file['raw'],
        landing_page,
        landing_html,
        workdir_value,
    )
    return {
        'ok': True,
        'path': decoded_path,
        'landing_page': landing_page,
        'workdir': workdir_value,
        'prompt': prompt,
    }, 200


def _prepare_landing_refresh(path):
    return _prepare_landing_prompt(path, _build_landing_refresh_prompt)


def _prepare_landing_review(path):
    return _prepare_landing_prompt(path, _build_landing_review_prompt)


CANVAS_SCHEMA = 'kanban.canvas/v1'
CANVAS_MAX_BYTES = 512 * 1024
CANVAS_GENERATOR = 'kanban-concus-lite-v1'
_CANVAS_ID_SAFE_RE = re.compile(r'[^A-Za-z0-9_.-]+')
_CANVAS_SECRETISH_RE = re.compile(r'(\.env|secret|token|credential|cookie|key)', re.I)


def _canvas_slug(value, fallback='item'):
    text = str(value or '').strip() or fallback
    text = _CANVAS_ID_SAFE_RE.sub('-', text).strip('-._')
    return text or fallback


def _canvas_allowed_roots(config=None):
    roots = list(_configured_open_allowed_roots(config))
    repo_root = REPO_ROOT.resolve()
    if not any(root == repo_root for root in roots):
        roots.append(repo_root)
    return roots


def _canvas_rel_for_task(task_rel_path, fm):
    task_path = Path(str(task_rel_path or ''))
    parts = task_path.parts
    if task_path.suffix.lower() != '.md':
        return None, 'Canvas 只支持 Markdown 任务卡'
    task_id = str((fm or {}).get('task_id') or task_path.stem).strip()
    task_key = _canvas_slug(task_id, task_path.stem)
    if len(parts) >= 3 and parts[0] == 'project':
        return str(task_path.parent / '.canvas' / task_key / 'main.canvas.json'), None
    task_abs = (REPO_ROOT / task_path).resolve(strict=False)
    data_root = _configured_root('data_root')
    if not _path_is_relative_to(task_abs, data_root):
        return None, 'Canvas 任务卡必须位于 project/ 或配置的 data_root 内'
    return str(task_path.parent / '.canvas' / task_key / 'main.canvas.json'), None


def _resolve_canvas_ref(task_rel_path, fm):
    default_rel, err = _canvas_rel_for_task(task_rel_path, fm)
    if err:
        return None, '', err, 400
    raw_ref = str((fm or {}).get('canvas_ref') or (fm or {}).get('canvas_json') or '').strip()
    canvas_rel = raw_ref or default_rel
    if canvas_rel.startswith('{') or canvas_rel.startswith('['):
        return None, canvas_rel, 'canvas_ref 只允许文件指针，不允许内联 JSON', 400
    if '..' in canvas_rel or canvas_rel.startswith('/'):
        return None, canvas_rel, '非法 canvas_ref', 400
    rel_path = Path(canvas_rel)
    task_parts = Path(task_rel_path).parts
    if rel_path.suffix.lower() != '.json':
        return None, canvas_rel, 'canvas_ref 必须指向 JSON 文件', 400
    target = (REPO_ROOT / rel_path).resolve()
    try:
        target.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None, canvas_rel, '非法 canvas_ref', 400
    parts = rel_path.parts
    if task_parts and task_parts[0] == 'project':
        if len(parts) < 5 or parts[0] != 'project' or parts[2] != '.canvas':
            return None, canvas_rel, 'canvas_ref 必须位于 project/<项目>/.canvas/ 下', 400
        if len(task_parts) >= 2 and parts[1] != task_parts[1]:
            return None, canvas_rel, 'canvas_ref 必须与任务卡位于同一项目目录', 400
    else:
        data_root = _configured_root('data_root')
        task_abs = (REPO_ROOT / task_rel_path).resolve(strict=False)
        if not _path_is_relative_to(task_abs, data_root) or not _path_is_relative_to(target, data_root):
            return None, canvas_rel, 'demo canvas_ref 必须位于配置的 data_root 内', 400
    return target, str(rel_path), '', 200


def _dedupe_paths(paths):
    seen = set()
    out = []
    for path in paths:
        if not path:
            continue
        try:
            real = Path(os.path.realpath(path))
        except (OSError, TypeError, ValueError):
            continue
        key = str(real)
        if key in seen:
            continue
        seen.add(key)
        out.append(real)
    return out


def _canvas_path_candidate_roots(task_abs_path, fm, config=None):
    roots = []
    workdir_value = str((fm or {}).get('workdir') or '').strip()
    if workdir_value:
        workdir, err = resolve_workdir(workdir_value, str(task_abs_path.relative_to(REPO_ROOT.resolve())), config)
        if not err and workdir:
            roots.append(workdir)
            registry = workdir / 'sources' / 'source-registry.jsonl'
            roots.extend(_canvas_source_registry_roots([registry]))
    related_paths = fm.get('related_paths') if isinstance(fm.get('related_paths'), list) else []
    registry_paths = [Path(os.path.expanduser(str(path))) for path in related_paths if str(path).endswith('source-registry.jsonl')]
    roots.extend(_canvas_source_registry_roots(registry_paths))
    roots.extend([task_abs_path.parent, REPO_ROOT.resolve()])
    roots.extend(_canvas_allowed_roots(config))
    return _dedupe_paths(roots)


def _canvas_source_registry_roots(registry_paths):
    roots = []
    for registry_path in registry_paths:
        try:
            path = Path(os.path.expanduser(str(registry_path))).resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_path = str(item.get('source_path') or '').strip()
            if not source_path:
                continue
            candidate = Path(os.path.expanduser(source_path))
            roots.append(candidate if candidate.is_dir() else candidate.parent)
    return roots


def _canvas_filename_matches(filename, roots, limit=20):
    if not filename or '/' in filename or '\\' in filename:
        return []
    matches = []
    skipped = {'.git', 'node_modules', 'vendor', '.venv', '.deps', '.workbuddy', '__pycache__'}
    for root in roots:
        if len(matches) >= limit:
            break
        try:
            root = Path(root).resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if not root.exists() or not root.is_dir():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skipped and not d.startswith('.')]
            if filename in files or filename in dirs:
                matches.append(Path(current) / filename)
                if len(matches) >= limit:
                    break
    return matches


def _canvas_known_rewrite(path, config=None):
    text = str(path)
    source = config if isinstance(config, dict) else load_config()
    rewrites = source.get('canvas_path_rewrites') or []
    if not isinstance(rewrites, list):
        rewrites = []
    for item in rewrites:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        old, new = (str(item[0] or '').rstrip(os.sep), str(item[1] or '').rstrip(os.sep))
        if not old or not new:
            continue
        if text == old or text.startswith(old + os.sep):
            return Path(new + text[len(old):])
    return None


def resolve_canvas_source_ref(path_value, task_abs_path, fm=None, *, kind='file', config=None):
    value = str(path_value or '').strip()
    result = {
        'kind': kind or 'file',
        'path': value,
        'status': 'missing',
        'resolved_path': '',
        'candidates': [],
        'reason': '',
        'allowed_roots': [],
        'searched_roots': [],
    }
    if not value:
        result['status'] = 'missing'
        result['reason'] = 'empty_path'
        return result
    if re.match(r'^https?://', value, re.I):
        result['kind'] = 'url'
        result['status'] = 'resolved'
        result['resolved_path'] = value
        return result

    allowed_roots = _canvas_allowed_roots(config)
    result['allowed_roots'] = [str(path) for path in allowed_roots]
    candidates = []
    corrected_from = ''
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        candidates.append(Path(expanded))
        rewritten = _canvas_known_rewrite(expanded, config)
        if rewritten:
            candidates.append(rewritten)
            corrected_from = expanded
    else:
        rel = Path(value)
        roots = _canvas_path_candidate_roots(task_abs_path, fm or {}, config)
        result['searched_roots'] = [str(path) for path in roots[:12]]
        for root in roots:
            candidates.append(root / rel)
        if len(rel.parts) == 1:
            candidates.extend(_canvas_filename_matches(value, roots[:12]))

    existing = []
    forbidden = []
    for candidate in _dedupe_paths(candidates):
        if candidate.exists():
            if _path_in_allowed_roots(candidate, allowed_roots):
                existing.append(candidate)
            else:
                forbidden.append(candidate)
    result['candidates'] = [str(path) for path in existing[:5]]
    if len(existing) == 1:
        resolved = existing[0]
        result['status'] = 'corrected' if corrected_from and str(resolved) != corrected_from else 'resolved'
        result['resolved_path'] = str(resolved)
        if corrected_from:
            result['reason'] = f'known_rewrite:{corrected_from}'
        return result
    if len(existing) > 1:
        result['status'] = 'ambiguous'
        result['reason'] = 'multiple_candidates'
        return result
    if forbidden:
        result['status'] = 'forbidden'
        result['reason'] = 'outside_allowed_roots'
        result['candidates'] = [str(path) for path in forbidden[:5]]
        return result
    result['status'] = 'missing'
    result['reason'] = 'not_found'
    return result


def _canvas_source_ref(kind, path_value, task_abs_path, fm=None, **extra):
    resolved = resolve_canvas_source_ref(path_value, task_abs_path, fm, kind=kind)
    source_ref = {
        'kind': resolved['kind'],
        'path': str(path_value or '').strip(),
        'resolved_path': resolved.get('resolved_path') or '',
        'status': resolved.get('status') or 'missing',
    }
    if resolved.get('reason'):
        source_ref['reason'] = resolved['reason']
    if resolved.get('candidates'):
        source_ref['candidates'] = resolved['candidates']
    if resolved.get('allowed_roots'):
        source_ref['allowed_roots'] = resolved['allowed_roots']
    if resolved.get('searched_roots'):
        source_ref['searched_roots'] = resolved['searched_roots']
    for key, value in extra.items():
        if value not in (None, ''):
            source_ref[key] = value
    return source_ref


def _canvas_short_text(value, limit=260):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '…'


def _canvas_basename(path_value):
    text = str(path_value or '').strip().rstrip('/\\')
    if not text:
        return ''
    if re.match(r'^https?://', text, re.I):
        return text.split('//', 1)[-1].split('/', 1)[0]
    return Path(os.path.expanduser(text)).name or text


def _canvas_file_type_label(path_value):
    suffix = Path(str(path_value or '')).suffix.lower()
    return {
        '.md': 'Markdown 文档',
        '.markdown': 'Markdown 文档',
        '.py': 'Python 脚本',
        '.js': 'JavaScript 文件',
        '.ts': 'TypeScript 文件',
        '.tsx': 'React 组件',
        '.jsx': 'React 组件',
        '.json': 'JSON 数据/配置',
        '.jsonl': 'JSONL 事件流',
        '.yaml': 'YAML 配置',
        '.yml': 'YAML 配置',
        '.html': 'HTML 页面',
        '.css': '样式文件',
        '.csv': 'CSV 表格',
        '.txt': '文本文件',
        '.pdf': 'PDF 文档',
        '.png': '图片',
        '.jpg': '图片',
        '.jpeg': '图片',
        '.mov': '视频',
        '.mp4': '视频',
    }.get(suffix, '文件')


def _canvas_preview_from_file(resolved_path):
    path = Path(str(resolved_path or ''))
    if not path.is_file() or _CANVAS_SECRETISH_RE.search(path.name):
        return '', ''
    if path.suffix.lower() not in {
        '.md', '.markdown', '.txt', '.py', '.js', '.ts', '.tsx', '.jsx',
        '.json', '.jsonl', '.yaml', '.yml', '.html', '.css', '.csv',
    }:
        return '', ''
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')[:12000]
    except OSError:
        return '', ''
    title = ''
    preview = ''
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped in ('---', '```'):
            continue
        if not title and stripped.startswith('#'):
            title = stripped.lstrip('#').strip()
            continue
        if not preview:
            preview = stripped
        if title and preview:
            break
    return _canvas_short_text(title, 80), _canvas_short_text(preview, 180)


def _canvas_ref_display(kind, path_value, task_abs_path, fm, source_ref, *, role='', label=''):
    role_text = str(role or '').strip()
    source_kind = str((source_ref or {}).get('kind') or kind or 'file')
    fallback = str(label or '').strip() or _canvas_basename(path_value) or source_kind
    title = fallback
    summary = ''

    if source_kind == 'card':
        task_id = str((fm or {}).get('task_id') or task_abs_path.stem).strip()
        card_title = str((fm or {}).get('title') or task_id).strip()
        title = f'{task_id} 任务卡' if task_id else card_title
        status = str((fm or {}).get('status') or '').strip()
        assignee = str((fm or {}).get('assignee') or '').strip()
        next_action = str((fm or {}).get('next_action') or '').strip()
        parts = [f'当前任务事实源: {card_title}']
        if status:
            parts.append(f'状态 {status}')
        if assignee:
            parts.append(f'负责人 {assignee}')
        if next_action:
            parts.append(f'下一步: {_canvas_short_text(next_action, 120)}')
        summary = '；'.join(parts)
    elif source_kind == 'dir':
        title = fallback if fallback != 'workdir' else (_canvas_basename(path_value) or '工作目录')
        summary = f'目录: {_canvas_short_text(path_value, 160)}。通常承载本卡的执行材料、代码或产出。'
    elif source_kind == 'url':
        title = fallback
        summary = f'网页链接: {_canvas_short_text(path_value, 180)}。'
    else:
        resolved_path = (source_ref or {}).get('resolved_path') or ''
        base = _canvas_basename(path_value) or fallback
        type_label = _canvas_file_type_label(resolved_path or path_value)
        file_title, preview = _canvas_preview_from_file(resolved_path)
        title = file_title or base
        summary_parts = [f'{type_label}: {base}']
        if preview:
            summary_parts.append(f'可见开头: {preview}')
        status = str((source_ref or {}).get('status') or '')
        if status in ('missing', 'ambiguous', 'forbidden'):
            summary_parts.append(f'当前解析状态: {status}')
        summary = '；'.join(summary_parts)

    relation_note = {
        'card': '这是当前画布的起点；其它节点都是围绕这张任务卡组织的事实。',
        'workdir': '来自卡片 frontmatter 的 workdir；通常是 AI 执行和查证的默认工作区。',
        'source_path': '来自卡片 frontmatter 的 source_path；通常是本卡要处理或复核的原始材料。',
        'landing_page': '来自卡片 frontmatter 的 landing_page；通常是本卡对应的展示/状态页面。',
        'related_path': '来自卡片 frontmatter 的 related_paths；卡片明确把它列为相关材料。',
        'body': '来自任务卡正文；用于让画布保留这张卡的文字意图。',
    }.get(role_text, '来自任务卡记录；可按连线作为下游节点的上下文。')

    return {
        'kind': source_kind,
        'title': _canvas_short_text(title, 90),
        'summary': _canvas_short_text(summary, 360),
        'relation_note': relation_note,
    }


def _canvas_ref_node(node_id, label, kind, path_value, task_abs_path, fm, x, y, *, role='', **extra):
    source_ref = _canvas_source_ref(kind, path_value, task_abs_path, fm, **extra)
    display = _canvas_ref_display(kind, path_value, task_abs_path, fm, source_ref, role=role, label=label)
    source_ref.setdefault('label', display['title'])
    metadata = {'role': role} if role else {}
    return {
        'id': _canvas_slug(node_id),
        'type': 'ref',
        'position': {'x': int(x), 'y': int(y)},
        'data': {
            'kind': display['kind'],
            'label': display['title'],
            'title': display['title'],
            'summary': display['summary'],
            'relation_note': display['relation_note'],
            'readonly': True,
            'source_ref': source_ref,
            'metadata': metadata,
        },
    }


def _canvas_text_node(node_id, label, text, x, y):
    return {
        'id': _canvas_slug(node_id),
        'type': 'note',
        'position': {'x': int(x), 'y': int(y)},
        'data': {
            'label': str(label or '').strip(),
            'text': str(text or '').strip(),
            'canvas_native': True,
        },
    }


def _frontmatter_block_list_values(fm_block, key):
    values = []
    in_target = False
    key_re = re.compile(r'^(\w[\w-]*)\s*:\s*(.*)$')
    for raw_line in str(fm_block or '').splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        match = key_re.match(stripped)
        if match:
            in_target = match.group(1) == key
            inline = match.group(2).strip()
            if in_target and inline.startswith('[') and inline.endswith(']'):
                values.extend(x.strip().strip("'\"") for x in inline[1:-1].split(',') if x.strip())
            continue
        if in_target:
            item = re.match(r'^\s*-\s+(.+?)\s*$', line)
            if item:
                values.append(item.group(1).strip().strip("'\""))
                continue
            if stripped:
                in_target = False
    return values


def _canvas_existing_positions(existing_canvas):
    positions = {}
    for node in (existing_canvas or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get('id') or '').strip()
        pos = node.get('position')
        if node_id and isinstance(pos, dict):
            positions[node_id] = {
                'x': int(float(pos.get('x') or 0)),
                'y': int(float(pos.get('y') or 0)),
            }
    return positions


def _canvas_apply_existing_positions(nodes, existing_canvas):
    positions = _canvas_existing_positions(existing_canvas)
    if not positions:
        return nodes
    for node in nodes:
        pos = positions.get(node.get('id'))
        if pos:
            node['position'] = pos
    return nodes


def _canvas_edge(edge_id, source, target, label='上下文'):
    return {
        'id': _canvas_slug(edge_id),
        'source': source,
        'target': target,
        'type': 'default',
        'label': label,
    }


def _canvas_merge_with_existing(generated_nodes, generated_edges, existing_canvas):
    """画布轻编排:刷新生成节点内容,保留用户手工节点与连线。"""
    if not existing_canvas:
        return generated_nodes, generated_edges
    generated_ids = {str(node.get('id') or '') for node in generated_nodes}
    existing_nodes = []
    for node in (existing_canvas or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get('id') or '')
        if node_id and node_id not in generated_ids:
            existing_nodes.append(node)

    seen_edges = set()
    edges = []
    for edge in (existing_canvas or {}).get('edges') or []:
        if not isinstance(edge, dict):
            continue
        key = str(edge.get('id') or f"{edge.get('source')}->{edge.get('target')}")
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(edge)
    for edge in generated_edges:
        key = str(edge.get('id') or f"{edge.get('source')}->{edge.get('target')}")
        pair = (str(edge.get('source') or ''), str(edge.get('target') or ''))
        if key in seen_edges or any((str(e.get('source') or ''), str(e.get('target') or '')) == pair for e in edges):
            continue
        seen_edges.add(key)
        edges.append(edge)
    return generated_nodes + existing_nodes, edges


def _canvas_status_counts(canvas):
    counts = {'resolved': 0, 'corrected': 0, 'missing': 0, 'ambiguous': 0, 'forbidden': 0}
    for node in (canvas or {}).get('nodes') or []:
        if not isinstance(node, dict):
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref') if isinstance(data.get('source_ref'), dict) else None
        if not ref:
            continue
        status = str(ref.get('status') or 'missing')
        counts[status] = counts.get(status, 0) + 1
    return counts


def _read_existing_canvas(canvas_path):
    if not canvas_path.exists():
        return None, ''
    try:
        raw = canvas_path.read_text(encoding='utf-8')
        return json.loads(raw), ''
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f'读取 canvas 失败: {exc}'


def _canvas_rev(canvas):
    if not isinstance(canvas, dict):
        return ''
    return _stable_json_hash(canvas)


def _generate_canvas_for_task(task_rel_path, existing_canvas=None, *, force=False):
    task_file, err = _read_task_file(task_rel_path)
    if not task_file:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
    fm = task_file['frontmatter'] or {}
    task_abs = (REPO_ROOT / task_rel_path).resolve()
    task_id = str(fm.get('task_id') or task_abs.stem).strip()
    title = str(fm.get('title') or task_id).strip()
    nodes = [
        _canvas_ref_node('card', f'{task_id} 任务卡', 'card', task_rel_path, task_abs, fm, 0, 0, role='card', line=1),
    ]
    edges = []
    warnings = []
    workdir = str(fm.get('workdir') or '').strip()
    if workdir:
        nodes.append(_canvas_ref_node('workdir', 'workdir', 'dir', workdir, task_abs, fm, 280, 0, role='workdir'))
        edges.append(_canvas_edge('edge-card-workdir', 'card', 'workdir'))
    source_path = str(fm.get('source_path') or '').strip()
    if source_path:
        nodes.append(_canvas_ref_node('source-path', 'source_path', 'file', source_path, task_abs, fm, 560, 0, role='source_path'))
        edges.append(_canvas_edge('edge-card-source-path', 'card', 'source-path'))
    landing_page = str(fm.get('landing_page') or '').strip()
    if landing_page:
        nodes.append(_canvas_ref_node('landing-page', 'landing_page', 'file', landing_page, task_abs, fm, 560, 180, role='landing_page'))
        edges.append(_canvas_edge('edge-card-landing-page', 'card', 'landing-page'))
    related_paths = fm.get('related_paths') if isinstance(fm.get('related_paths'), list) else []
    if not related_paths:
        related_paths = _frontmatter_block_list_values(task_file.get('frontmatter_block'), 'related_paths')
    for idx, rel_path in enumerate(related_paths[:8]):
        node_id = f'related-{idx + 1}'
        nodes.append(_canvas_ref_node(
            node_id,
            f'related_path {idx + 1}',
            'file',
            rel_path,
            task_abs,
            fm,
            280 + (idx % 2) * 280,
            180 + (idx // 2) * 150,
            role='related_path',
        ))
        edges.append(_canvas_edge(f'edge-card-{node_id}', 'card', node_id))
    for node in nodes:
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref') if isinstance(data.get('source_ref'), dict) else None
        if not ref:
            continue
        status = str(ref.get('status') or '')
        if status in ('missing', 'ambiguous', 'forbidden'):
            warnings.append({
                'node_id': node.get('id'),
                'status': status,
                'source_ref': {
                    'kind': ref.get('kind'),
                    'path': ref.get('path'),
                    'reason': ref.get('reason'),
                },
            })

    if existing_canvas and not force:
        _canvas_apply_existing_positions(nodes, existing_canvas)
        nodes, edges = _canvas_merge_with_existing(nodes, edges, existing_canvas)
    now = datetime.now().replace(microsecond=0).isoformat()
    canvas = {
        'schema': CANVAS_SCHEMA,
        'id': _canvas_slug(task_id),
        'name': title,
        'scope': {
            'type': 'card',
            'task_id': task_id,
            'task_path': task_rel_path,
        },
        'nodes': nodes,
        'edges': edges,
        'viewport': (existing_canvas or {}).get('viewport') or {'x': 0, 'y': 0, 'zoom': 1},
        'metadata': {
            'generator': CANVAS_GENERATOR,
            'generated_at': now,
            'source_updated': str(fm.get('updated') or ''),
            'path_status_counts': _canvas_status_counts({'nodes': nodes}),
            'warnings': warnings,
        },
        'timestamps': {
            'createdAt': ((existing_canvas or {}).get('timestamps') or {}).get('createdAt') or now,
            'updatedAt': now,
        },
    }
    return {'ok': True, 'canvas': canvas, 'warnings': warnings}, 200


def validate_canvas_payload(canvas, task_rel_path):
    if not isinstance(canvas, dict):
        return 'canvas 必须是对象'
    encoded = json.dumps(canvas, ensure_ascii=False)
    if len(encoded.encode('utf-8')) > CANVAS_MAX_BYTES:
        return 'canvas 超过大小限制'
    if canvas.get('schema') != CANVAS_SCHEMA:
        return f'canvas schema 必须是 {CANVAS_SCHEMA}'
    if 'userId' in canvas:
        return 'canvas 不允许包含 userId'
    nodes = canvas.get('nodes')
    edges = canvas.get('edges', [])
    if not isinstance(nodes, list) or len(nodes) > 200:
        return 'nodes 必须是长度不超过 200 的数组'
    if not isinstance(edges, list) or len(edges) > 400:
        return 'edges 必须是长度不超过 400 的数组'
    task_abs = (REPO_ROOT / task_rel_path).resolve()
    task_file, err = _read_task_file(task_rel_path)
    if not task_file:
        return err or '任务卡不存在'
    fm = task_file.get('frontmatter') or {}
    for node in nodes:
        if not isinstance(node, dict):
            return 'node 必须是对象'
        pos = node.get('position')
        if not isinstance(pos, dict) or 'x' not in pos or 'y' not in pos:
            return 'node.position 必须包含 x/y'
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref')
        if node.get('type') == 'ref':
            if not isinstance(ref, dict):
                return 'ref 节点必须带 source_ref'
            resolved = resolve_canvas_source_ref(ref.get('path'), task_abs, fm, kind=ref.get('kind') or 'file')
            if resolved.get('status') == 'forbidden':
                return 'source_ref 不在允许根内'
            ref['status'] = resolved.get('status') or 'missing'
            ref['resolved_path'] = resolved.get('resolved_path') or ''
            if resolved.get('reason'):
                ref['reason'] = resolved['reason']
            if resolved.get('candidates'):
                ref['candidates'] = resolved['candidates']
            else:
                ref.pop('candidates', None)
            ref['allowed_roots'] = resolved.get('allowed_roots') or []
            ref['searched_roots'] = resolved.get('searched_roots') or []
    return ''


def _canvas_with_fresh_source_refs(canvas, task_rel_path, fm):
    """Re-resolve refs on read so moving a file into an allowed root repairs reload."""
    refreshed = json.loads(json.dumps(canvas, ensure_ascii=False))
    task_abs = (REPO_ROOT / task_rel_path).resolve()
    for node in refreshed.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'ref':
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ref = data.get('source_ref') if isinstance(data.get('source_ref'), dict) else None
        if not ref:
            continue
        resolved = resolve_canvas_source_ref(ref.get('path'), task_abs, fm, kind=ref.get('kind') or 'file')
        for key in ('status', 'resolved_path', 'reason', 'candidates', 'allowed_roots', 'searched_roots'):
            value = resolved.get(key)
            if value not in (None, '', []):
                ref[key] = value
            else:
                ref.pop(key, None)
    metadata = refreshed.get('metadata')
    if not isinstance(metadata, dict):
        metadata = {}
        refreshed['metadata'] = metadata
    metadata['path_status_counts'] = _canvas_status_counts(refreshed)
    return refreshed


def resolve_canvas_ref_for_task(task_path_value, source_path, kind='file'):
    _task_path, rel_path, err, status = _resolve_active_task_card_path(task_path_value)
    if err:
        return {'ok': False, 'error': err}, status
    task_file, read_err = _read_task_file(rel_path)
    if not task_file:
        return {'ok': False, 'error': read_err}, 404 if read_err == '文件不存在' else 400
    resolved = resolve_canvas_source_ref(
        source_path,
        (REPO_ROOT / rel_path).resolve(),
        task_file.get('frontmatter') or {},
        kind=kind or 'file',
    )
    return {'ok': True, 'source_ref': resolved}, 200


def _verified_canvas_context_entries(entries, task_rel_path, fm):
    verified = []
    task_abs = (REPO_ROOT / task_rel_path).resolve()
    for raw in entries if isinstance(entries, list) else []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        path_value = str(item.get('path') or '').strip()
        if path_value:
            resolved = resolve_canvas_source_ref(
                path_value, task_abs, fm, kind=item.get('kind') or 'file'
            )
            item.update({
                'status': resolved.get('status') or 'missing',
                'resolved_path': resolved.get('resolved_path') or '',
            })
        else:
            item['status'] = 'resolved'
        verified.append(item)
    return verified


CANVAS_EVENTS_SCHEMA = 'kanban.canvas-events/v1'


def _canvas_audit_event(actor, event, **fields):
    payload = {
        'v': 1,
        'schema': CANVAS_EVENTS_SCHEMA,
        'ts': datetime.now().replace(microsecond=0).isoformat(),
        'actor': str(actor or 'owner'),
        'event': event,
    }
    payload.update(fields)
    return payload


def _canvas_diff_events(old_canvas, new_canvas, actor):
    """构图事件账(Owner 2026-07-03:「我放的动作也需要可追踪的链」)。
    在唯一写入口做落盘差分推导事件——不靠客户端上报,推导不了假。
    只记语义事件(增删节点/连线/正文变更/绑定会话);布局只记"挪了几个",坐标是画布自有噪音。"""
    now = datetime.now().replace(microsecond=0).isoformat()
    base = {'v': 1, 'schema': CANVAS_EVENTS_SCHEMA, 'ts': now, 'actor': str(actor or 'owner')}

    def _index(c):
        nodes = {str(n.get('id')): n for n in (c or {}).get('nodes', []) if isinstance(n, dict) and n.get('id')}
        edges = {}
        for e in (c or {}).get('edges', []) if isinstance((c or {}).get('edges', []), list) else []:
            if isinstance(e, dict):
                key = str(e.get('id') or f"{e.get('source')}->{e.get('target')}")
                edges[key] = e
        return nodes, edges

    old_nodes, old_edges = _index(old_canvas)
    new_nodes, new_edges = _index(new_canvas)
    events = []
    for nid in sorted(new_nodes.keys() - old_nodes.keys()):
        node = new_nodes[nid]
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        ev = dict(base, event='node_added', node_id=nid, node_type=str(node.get('type') or ''),
                  origin=str(data.get('origin') or 'generated'),
                  label=str(data.get('label') or data.get('title') or data.get('content') or '')[:120])
        ref = data.get('source_ref')
        if isinstance(ref, dict):
            ev['source_ref'] = {
                'kind': ref.get('kind'),
                'path': ref.get('path'),
                'run_id': ref.get('run_id'),
                'task_id': ref.get('task_id'),
                'label': ref.get('label'),
            }
        events.append(ev)
    for nid in sorted(old_nodes.keys() - new_nodes.keys()):
        node = old_nodes[nid]
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        events.append(dict(base, event='node_removed', node_id=nid,
                           node_type=str(node.get('type') or ''),
                           label=str(data.get('label') or data.get('title') or '')[:120]))
    moved = 0
    for nid in sorted(new_nodes.keys() & old_nodes.keys()):
        old_n, new_n = old_nodes[nid], new_nodes[nid]
        old_d = old_n.get('data') if isinstance(old_n.get('data'), dict) else {}
        new_d = new_n.get('data') if isinstance(new_n.get('data'), dict) else {}
        old_c, new_c = str(old_d.get('content') or ''), str(new_d.get('content') or '')
        if old_c != new_c:
            events.append(dict(base, event='node_content_changed', node_id=nid,
                               content_len=len(new_c),
                               content_sha256=hashlib.sha256(new_c.encode('utf-8')).hexdigest()[:16]))
        old_summary, new_summary = str(old_d.get('summary') or ''), str(new_d.get('summary') or '')
        if old_summary != new_summary:
            new_meta = new_d.get('metadata') if isinstance(new_d.get('metadata'), dict) else {}
            events.append(dict(base, event='node_summary_changed', node_id=nid,
                               summary_len=len(new_summary),
                               summary_sha256=hashlib.sha256(new_summary.encode('utf-8')).hexdigest()[:16],
                               provider=str(new_meta.get('local_summary_provider') or '')))
        old_relation, new_relation = str(old_d.get('relation_note') or ''), str(new_d.get('relation_note') or '')
        if old_relation != new_relation:
            events.append(dict(base, event='node_relation_note_changed', node_id=nid,
                               relation_note_len=len(new_relation),
                               relation_note_sha256=hashlib.sha256(new_relation.encode('utf-8')).hexdigest()[:16]))
        old_meta = old_d.get('metadata') if isinstance(old_d.get('metadata'), dict) else {}
        new_meta = new_d.get('metadata') if isinstance(new_d.get('metadata'), dict) else {}
        old_summary_status = (
            str(old_meta.get('local_summary_status') or ''),
            str(old_meta.get('local_summary_error') or ''),
            str(old_meta.get('local_summary_updated_at') or ''),
        )
        new_summary_status = (
            str(new_meta.get('local_summary_status') or ''),
            str(new_meta.get('local_summary_error') or ''),
            str(new_meta.get('local_summary_updated_at') or ''),
        )
        if old_summary_status != new_summary_status:
            events.append(dict(base, event='node_summary_status_changed', node_id=nid,
                               summary_status=new_summary_status[0],
                               summary_error=new_summary_status[1],
                               provider=str(new_meta.get('local_summary_provider') or '')))
        old_hidden = bool(old_n.get('hidden') or old_d.get('hidden'))
        new_hidden = bool(new_n.get('hidden') or new_d.get('hidden'))
        if old_hidden != new_hidden:
            events.append(dict(base, event='node_hidden' if new_hidden else 'node_shown',
                               node_id=nid,
                               node_type=str(new_n.get('type') or ''),
                               hidden=new_hidden))
        if str(old_d.get('run_id') or '') != str(new_d.get('run_id') or '') and new_d.get('run_id'):
            ref = new_d.get('source_ref') if isinstance(new_d.get('source_ref'), dict) else {}
            events.append(dict(
                base, event='node_bound', node_id=nid, run_id=str(new_d.get('run_id')),
                node_type=str(new_n.get('type') or ''),
                source_ref={
                    'kind': ref.get('kind'),
                    'path': ref.get('path'),
                    'run_id': ref.get('run_id') or new_d.get('run_id'),
                    'task_id': ref.get('task_id'),
                    'label': ref.get('label'),
                },
            ))
        if old_n.get('position') != new_n.get('position'):
            moved += 1
        old_ref = old_d.get('source_ref') if isinstance(old_d.get('source_ref'), dict) else {}
        new_ref = new_d.get('source_ref') if isinstance(new_d.get('source_ref'), dict) else {}
        old_ref_key = (
            str(old_ref.get('kind') or ''),
            str(old_ref.get('path') or ''),
            str(old_ref.get('resolved_path') or ''),
            str(old_ref.get('status') or ''),
        )
        new_ref_key = (
            str(new_ref.get('kind') or ''),
            str(new_ref.get('path') or ''),
            str(new_ref.get('resolved_path') or ''),
            str(new_ref.get('status') or ''),
        )
        if old_ref_key != new_ref_key:
            events.append(dict(
                base,
                event='node_source_ref_changed',
                node_id=nid,
                node_type=str(new_n.get('type') or ''),
                source_ref={
                    'kind': new_ref.get('kind'),
                    'path': new_ref.get('path'),
                    'resolved_path': new_ref.get('resolved_path'),
                    'status': new_ref.get('status'),
                    'label': new_ref.get('label'),
                },
            ))
    for key in sorted(new_edges.keys() - old_edges.keys()):
        e = new_edges[key]
        events.append(dict(base, event='edge_added', source=str(e.get('source') or ''), target=str(e.get('target') or '')))
    for key in sorted(old_edges.keys() - new_edges.keys()):
        e = old_edges[key]
        events.append(dict(base, event='edge_removed', source=str(e.get('source') or ''), target=str(e.get('target') or '')))
    if moved:
        events.append(dict(base, event='layout_moved', count=moved))
    return events


def _canvas_events_append(canvas_path, events):
    """事件账追加；调用方必须检查 False 并返回部分保存错误。"""
    return canvas_event_ledger.append_events(canvas_path, events, lock=_LEDGER_LOCK)


def _canvas_events_read_report(canvas_path):
    return canvas_event_ledger.read_events(canvas_path)


def _canvas_events_read(canvas_path):
    return _canvas_events_read_report(canvas_path)['events']


def _save_canvas_for_task(task_rel_path, canvas, actor='owner', base_rev=None):
    expected_rev = str(base_rev or '').strip()
    with CANVAS_WRITE_LOCK:
        task_file, err = _read_task_file(task_rel_path)
        if not task_file:
            return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
        fm = task_file['frontmatter'] or {}
        canvas_path, canvas_rel, ref_err, status = _resolve_canvas_ref(task_rel_path, fm)
        if ref_err:
            return {'ok': False, 'error': ref_err}, status
        prev_canvas, _prev_err = _read_existing_canvas(canvas_path)
        current_rev = _canvas_rev(prev_canvas)
        if expected_rev and expected_rev != current_rev:
            event = _canvas_audit_event(
                actor,
                'canvas_save_rejected',
                reason='base_rev_mismatch',
                conflict=True,
                base_rev=expected_rev,
                current_rev=current_rev,
                canvas_ref=canvas_rel,
            )
            _canvas_events_append(canvas_path, [event])
            return {
                'ok': False,
                'error': 'canvas 基线已过期',
                'message': 'canvas 基线已过期，请重拉最新画布后再保存',
                'conflict': True,
                'base_rev': expected_rev,
                'current_rev': current_rev,
                'canvas_rev': current_rev,
                'rev': current_rev,
                'canvas_ref': canvas_rel,
                'canvas_updated': str(fm.get('canvas_updated') or ''),
                'canvas': prev_canvas,
                'path_status_counts': _canvas_status_counts(prev_canvas),
            }, 409
        validation_err = validate_canvas_payload(canvas, task_rel_path)
        if validation_err:
            return {'ok': False, 'error': validation_err}, 400
        now = datetime.now().replace(microsecond=0).isoformat()
        metadata = canvas.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
            canvas['metadata'] = metadata
        metadata['path_status_counts'] = _canvas_status_counts(canvas)
        timestamps = canvas.get('timestamps')
        if not isinstance(timestamps, dict):
            timestamps = {}
            canvas['timestamps'] = timestamps
        timestamps.setdefault('createdAt', now)
        timestamps['updatedAt'] = now
        canvas_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(canvas_path, json.dumps(canvas, ensure_ascii=False, indent=2) + '\n')
        new_rev = _canvas_rev(canvas)
        canvas_events = _canvas_diff_events(prev_canvas, canvas, actor)
        if not expected_rev:
            canvas_events.insert(0, _canvas_audit_event(
                actor,
                'canvas_saved',
                no_base=True,
                reason='missing_base_rev',
                current_rev=current_rev,
                canvas_rev=new_rev,
                canvas_ref=canvas_rel,
            ))
        if not _canvas_events_append(canvas_path, canvas_events):
            return canvas_event_ledger.partial_save_error(canvas_rel, new_rev, canvas), 500
        lineage_ok = _lineage_record_canvas_events(task_rel_path, canvas_events, canvas_rel, actor=actor)
        today = datetime.now().strftime('%Y-%m-%d')
        for field, value in (
            ('canvas_ref', canvas_rel),
            ('canvas_schema', CANVAS_SCHEMA),
            ('canvas_updated', today),
        ):
            ok, msg = update_frontmatter_field(task_rel_path, field, value)[:2]
            if not ok:
                return {'ok': False, 'error': f'{field} 回写失败: {msg}'}, 500
        result = {
            'ok': True,
            'canvas_ref': canvas_rel,
            'canvas_updated': today,
            'canvas_rev': new_rev,
            'rev': new_rev,
            'canvas': canvas,
            'path_status_counts': _canvas_status_counts(canvas),
        }
        if not lineage_ok:
            result['lineage_warning'] = '血缘台账写入失败'
        return result, 200


def get_canvas_for_task(path):
    task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    task_file, read_err = _read_task_file(rel_path)
    if not task_file:
        return {'ok': False, 'error': read_err}, 404 if read_err == '文件不存在' else 400
    fm = task_file['frontmatter'] or {}
    canvas_path, canvas_rel, ref_err, ref_status = _resolve_canvas_ref(rel_path, fm)
    if ref_err:
        return {'ok': False, 'error': ref_err}, ref_status
    canvas, load_err = _read_existing_canvas(canvas_path)
    if load_err:
        return {'ok': False, 'error': load_err, 'canvas_ref': canvas_rel}, 400
    if not canvas:
        return {
            'ok': True,
            'exists': False,
            'canvas_ref': canvas_rel,
            'canvas_schema': CANVAS_SCHEMA,
            'canvas_updated': str(fm.get('canvas_updated') or ''),
            'canvas_rev': '',
            'rev': '',
        }, 200
    rev = _canvas_rev(canvas)
    canvas = _canvas_with_fresh_source_refs(canvas, rel_path, fm)
    return {
        'ok': True,
        'exists': True,
        'canvas_ref': canvas_rel,
        'canvas_updated': str(fm.get('canvas_updated') or ''),
        'canvas_rev': rev,
        'rev': rev,
        'canvas': canvas,
        'path_status_counts': _canvas_status_counts(canvas),
    }, 200


def generate_canvas_for_task(path, *, force=False, base_rev=None):
    task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    task_file, read_err = _read_task_file(rel_path)
    if not task_file:
        return {'ok': False, 'error': read_err}, 404 if read_err == '文件不存在' else 400
    canvas_path, _canvas_rel, ref_err, ref_status = _resolve_canvas_ref(rel_path, task_file['frontmatter'] or {})
    if ref_err:
        return {'ok': False, 'error': ref_err}, ref_status
    existing_canvas = None
    if canvas_path.exists() and not force:
        existing_canvas, load_err = _read_existing_canvas(canvas_path)
        if load_err:
            return {'ok': False, 'error': load_err}, 400
    generated, gen_status = _generate_canvas_for_task(rel_path, existing_canvas, force=force)
    if not generated.get('ok'):
        return generated, gen_status
    result, save_status = _save_canvas_for_task(rel_path, generated['canvas'], actor='generate', base_rev=base_rev)
    if generated.get('warnings') and isinstance(result, dict):
        result['warnings'] = generated['warnings']
    return result, save_status


def canvas_existing_seed_intent(path):
    task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return '', {'ok': False, 'error': err}, status
    task_file, read_err = _read_task_file(rel_path)
    if not task_file:
        return '', {'ok': False, 'error': read_err}, 404 if read_err == '文件不存在' else 400
    canvas_path, _canvas_rel, ref_err, ref_status = _resolve_canvas_ref(rel_path, task_file['frontmatter'] or {})
    if ref_err:
        return '', {'ok': False, 'error': ref_err}, ref_status
    existing_canvas, load_err = _read_existing_canvas(canvas_path)
    if load_err:
        return '', {'ok': False, 'error': load_err}, 400
    if not existing_canvas:
        return '', {'ok': True}, 200
    metadata = existing_canvas.get('metadata') if isinstance(existing_canvas.get('metadata'), dict) else {}
    meta = existing_canvas.get('meta') if isinstance(existing_canvas.get('meta'), dict) else {}
    intent = str(metadata.get('seed_intent') or meta.get('seed_intent') or '').strip()
    return intent, {'ok': True}, 200


def put_canvas_for_task(path, canvas, actor='owner', base_rev=None):
    task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    return _save_canvas_for_task(rel_path, canvas, actor=actor, base_rev=base_rev)


def _canvas_seed_deps():
    return {
        'repo_root': REPO_ROOT,
        'canvas_schema': CANVAS_SCHEMA,
        'resolve_active_task_card_path': _resolve_active_task_card_path,
        'read_task_file': _read_task_file,
        'resolve_workdir': resolve_workdir,
        'load_config': load_config,
        'llm_chat': _llm_chat,
        'frontmatter_block_list_values': _frontmatter_block_list_values,
        'get_canvas_for_task': get_canvas_for_task,
        'put_canvas_node': lambda body: ledger_query.put_canvas_node(_ledger_query_deps(), body),
    }


_DEMO_CANVAS_AI_MESSAGE = 'Demo 模式未配置 AI provider；此动作不可用，当前画布保持不变。'


def _canvas_ai_enabled(config=None):
    source = config if isinstance(config, dict) else load_config()
    settings = source.get('canvas_ai') if isinstance(source.get('canvas_ai'), dict) else {}
    return settings.get('enabled') is not False


def _canvas_ai_unavailable(path, *, action, include_canvas=False):
    config = load_config()
    if _canvas_ai_enabled(config):
        return None
    _task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    payload = {
        'ok': True,
        'available': False,
        'demo_mode': bool(config.get('demo_mode')),
        'action': action,
        'path': rel_path,
        'message': _DEMO_CANVAS_AI_MESSAGE,
    }
    if include_canvas:
        current, current_status = get_canvas_for_task(rel_path)
        if current_status != 200:
            return current, current_status
        payload.update(current)
        payload.update({
            'ok': True,
            'available': False,
            'demo_mode': bool(config.get('demo_mode')),
            'action': action,
            'message': _DEMO_CANVAS_AI_MESSAGE,
        })
    return payload, 200


def infer_canvas_seed_intent(path):
    unavailable = _canvas_ai_unavailable(path, action='seed_intent')
    if unavailable is not None:
        return unavailable
    return canvas_seed.infer_seed_intent(_canvas_seed_deps(), path)


def enqueue_canvas_seed(path, intent, *, tool='codex'):
    unavailable = _canvas_ai_unavailable(path, action='seed_run')
    if unavailable is not None:
        return unavailable
    tool_name = str(tool or 'codex').strip() or 'codex'
    if tool_name not in CLI_COMMANDS:
        return {'ok': False, 'error': '无效工具'}, 400
    actor = tool_name if tool_name in {'codex', 'claude'} else 'codex'
    deps = _canvas_seed_deps()
    task_path, rel_path, err, status = _resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    task_file, read_err = _read_task_file(rel_path)
    if not task_file:
        return {'ok': False, 'error': read_err}, 404 if read_err == '文件不存在' else 400
    clean_intent = str(intent or '').strip()
    seed_dedupe_key = 'canvas-seed:' + hashlib.sha256(
        json.dumps({
            'path': rel_path,
            'intent': clean_intent,
            'tool': tool_name,
        }, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:24]
    active_seed = _queue_find_active_by_dedupe_key(seed_dedupe_key)
    if active_seed:
        current_canvas, current_status = get_canvas_for_task(rel_path)
        if current_status != 200:
            current_canvas = {}
        return {
            'ok': True,
            'run_id': active_seed.get('id'),
            'path': rel_path,
            'intent': clean_intent,
            'raw_intent': clean_intent,
            'execution_brief': ((current_canvas.get('canvas') or {}).get('metadata') or {}).get('execution_brief'),
            'queue': 'ai-run',
            'stage': 'judgment_queued',
            'stage_label': '生成执行中',
            'deduplicated': True,
            'canvas_ref': current_canvas.get('canvas_ref'),
            'canvas_rev': current_canvas.get('canvas_rev') or current_canvas.get('rev'),
            'canvas': current_canvas.get('canvas'),
        }, 200
    fm = task_file.get('frontmatter') or {}
    canvas_path, _canvas_rel, ref_err, ref_status = _resolve_canvas_ref(rel_path, fm)
    if ref_err:
        return {'ok': False, 'error': ref_err}, ref_status
    existing_canvas, load_err = _read_existing_canvas(canvas_path)
    if load_err:
        return {'ok': False, 'error': load_err}, 400
    prepared, status = canvas_seed.build_seed_skeleton(
        deps,
        rel_path,
        intent,
        existing_canvas=existing_canvas,
    )
    if not prepared.get('ok'):
        return prepared, status
    saved, save_status = put_canvas_for_task(rel_path, prepared['canvas'], actor='generate')
    if not saved.get('ok'):
        return saved, save_status
    fm = task_file.get('frontmatter') or {}
    workdir_value = fm.get('workdir', '') if fm else ''
    cwd_path, cwd_err = resolve_workdir(workdir_value, rel_path)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    if cwd_path and not cwd_path.exists():
        return {'ok': False, 'error': 'workdir_not_found', 'workdir': str(cwd_path)}, 400
    judgment_prompt = canvas_seed.build_judgment_prompt(
        rel_path,
        saved.get('canvas') or prepared['canvas'],
        prepared.get('intent') or intent,
        actor=actor,
    )
    now = datetime.now().replace(microsecond=0).isoformat()
    canvas_rev = str(saved.get('canvas_rev') or saved.get('rev') or '')
    entry_id = _queue_add_entry(
        tool_name,
        rel_path,
        workdir_value,
        prompt_override=judgment_prompt,
        metadata={
            'canvas_seed': {
                'intent': prepared.get('intent'),
                'raw_intent': prepared.get('raw_intent'),
                'execution_brief': prepared.get('execution_brief'),
                'recipe': prepared.get('recipe'),
                'prompt_version': canvas_seed.CANVAS_SEED_V2_PROMPT_VERSION,
                'queued_at': now,
                'stage': 'judgment_queued',
                'skeleton_rev': canvas_rev,
            }
        },
        dedupe_key=seed_dedupe_key,
    )
    seed_message = {
        'role': 'user',
        'content': f"seed v0.2 骨架已出；请只做一次组织判断: {prepared.get('intent', '')}",
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'author': 'Canvas Studio',
    }
    current_seed_entry = _queue_get_entry(entry_id) or {}
    if not any(
        str(message.get('content') or '') == seed_message['content']
        and str(message.get('author') or '') == 'Canvas Studio'
        for message in (current_seed_entry.get('messages') or [])
        if isinstance(message, dict)
    ):
        _queue_append_message(entry_id, seed_message, ledger_fields={
            'prompt_audit_version': canvas_seed.CANVAS_SEED_V2_PROMPT_VERSION,
            'prompt_source': 'canvas_seed_v0.2_judgment',
            'raw_prompt': judgment_prompt,
        })
    _queue_consume_next()
    canvas_seed.start_local_summary_backfill(deps, rel_path)
    summary_counts = canvas_seed.seed_summary_counts((saved.get('canvas') or {}).copy())
    return {
        'ok': True,
        'run_id': entry_id,
        'path': rel_path,
        'intent': prepared.get('intent'),
        'raw_intent': prepared.get('raw_intent'),
        'execution_brief': prepared.get('execution_brief'),
        'recipe': prepared.get('recipe'),
        'queue': 'ai-run',
        'stage': 'skeleton_ready',
        'stage_label': '骨架已出',
        'canvas_ref': saved.get('canvas_ref'),
        'canvas_rev': canvas_rev,
        'canvas': saved.get('canvas'),
        'summary_counts': summary_counts,
    }, 200


def _ledger_query_deps():
    return {
        'repo_root': REPO_ROOT,
        'scan_all': scan_all,
        'read_task_file': _read_task_file,
        'resolve_canvas_ref': _resolve_canvas_ref,
        'read_existing_canvas': _read_existing_canvas,
        'canvas_rev': _canvas_rev,
        'canvas_schema': CANVAS_SCHEMA,
        'canvas_write_lock': CANVAS_WRITE_LOCK,
        'canvas_status_counts': _canvas_status_counts,
        'validate_canvas_payload': validate_canvas_payload,
        'canvas_audit_event': _canvas_audit_event,
        'canvas_diff_events': _canvas_diff_events,
        'canvas_events_append': _canvas_events_append,
        'canvas_event_append_failure': canvas_event_ledger.partial_save_error,
        'lineage_record_canvas_events': _lineage_record_canvas_events,
        'update_frontmatter_field': update_frontmatter_field,
    }


def _comment_import_deps():
    return {
        'repo_root': REPO_ROOT,
        'resolve_active_task_card_path': _resolve_active_task_card_path,
        'read_task_file': _read_task_file,
        'ledger_lock': _LEDGER_LOCK,
    }


def _task_document_link_deps():
    return {
        'read_task_file': _read_task_file,
        'frontmatter_block_list_values': _frontmatter_block_list_values,
        'allowed_roots': _configured_open_allowed_roots(),
        'write_lock': MARKDOWN_WRITE_LOCK,
    }


def _project_map_deps():
    return {
        'repo_root': REPO_ROOT,
        'scan_all': scan_all,
        'canvas_schema': CANVAS_SCHEMA,
        'canvas_max_bytes': CANVAS_MAX_BYTES,
        'canvas_events_schema': CANVAS_EVENTS_SCHEMA,
        'canvas_write_lock': CANVAS_WRITE_LOCK,
        'canvas_slug': _canvas_slug,
        'canvas_ref_display': _canvas_ref_display,
        'canvas_status_counts': _canvas_status_counts,
        'resolve_canvas_source_ref': resolve_canvas_source_ref,
        'read_existing_canvas': _read_existing_canvas,
        'canvas_rev': _canvas_rev,
        'canvas_audit_event': _canvas_audit_event,
        'canvas_diff_events': _canvas_diff_events,
        'canvas_events_append': _canvas_events_append,
        'canvas_events_read': _canvas_events_read,
        'canvas_events_read_report': _canvas_events_read_report,
        'canvas_event_append_failure': canvas_event_ledger.partial_save_error,
        'atomic_write_text': _atomic_write_text,
        'normalize_task_family': normalize_task_family,
        'task_family_prefixes': TASK_FAMILY_PREFIXES,
        'list_real_projects': get_real_projects,
    }


def get_project_map_canvas(scope):
    return project_map.get_project_map(scope, _project_map_deps())


def generate_project_map_canvas(scope, *, force=False, base_rev=None):
    return project_map.generate_project_map(scope, _project_map_deps(), force=force, base_rev=base_rev)


def put_project_map_canvas(scope, canvas, actor='owner', base_rev=None):
    return project_map.put_project_map(scope, canvas, _project_map_deps(), actor=actor, base_rev=base_rev)


def get_project_map_canvas_events(scope):
    return project_map.get_project_map_events(scope, _project_map_deps())


def get_project_map_canvas_versions(scope, *, version_id=''):
    return project_map.list_project_map_versions(
        scope,
        _project_map_deps(),
        version_id=version_id,
    )


def get_task_canvas_versions(path, *, version_id=''):
    current, status = get_canvas_for_task(path)
    if status != 200:
        return current, status
    return {
        'ok': True,
        'available': False,
        'scope': f'card:{path}',
        'path': path,
        'canvas_ref': current.get('canvas_ref') or '',
        'canvas_rev': current.get('canvas_rev') or '',
        'requested_version': str(version_id or ''),
        'versions': [],
        'message': '任务卡画布暂不提供历史版本；请使用“变更”查看事件记录。',
    }, 200


def restore_project_map_canvas_version(scope, version_id, *, actor='owner', base_rev=None):
    return project_map.restore_project_map_version(
        scope,
        version_id,
        _project_map_deps(),
        actor=actor,
        base_rev=base_rev,
    )


def list_project_map_canvases():
    return project_map.list_project_maps(_project_map_deps())


def list_task_canvases():
    deps = dict(_project_map_deps())
    deps['canvas_rel_for_task'] = _canvas_rel_for_task
    return task_canvas.list_task_canvases(deps)


def _conversation_map_deps():
    return {
        'repo_root': REPO_ROOT,
        'load_config': load_config,
        'default_conversation_maps_dir': _DEFAULTS['conversation_maps_dir'],
        'canvas_schema': CANVAS_SCHEMA,
        'canvas_max_bytes': CANVAS_MAX_BYTES,
        'canvas_events_schema': CANVAS_EVENTS_SCHEMA,
        'canvas_write_lock': CANVAS_WRITE_LOCK,
        'canvas_slug': _canvas_slug,
        'canvas_status_counts': _canvas_status_counts,
        'resolve_canvas_source_ref': resolve_canvas_source_ref,
        'read_existing_canvas': _read_existing_canvas,
        'canvas_rev': _canvas_rev,
        'canvas_audit_event': _canvas_audit_event,
        'canvas_diff_events': _canvas_diff_events,
        'canvas_events_append': _canvas_events_append,
        'canvas_events_read': _canvas_events_read,
        'canvas_events_read_report': _canvas_events_read_report,
        'canvas_event_append_failure': canvas_event_ledger.partial_save_error,
        'atomic_write_text': _atomic_write_text,
    }


def _conversation_project_graph_deps():
    return {
        'repo_root': REPO_ROOT,
        'maps_root': lambda: conversation_map._maps_root(_conversation_map_deps()),
        'scan_tasks': _scan_project_graph_tasks,
        'queue_snapshot': _queue_snapshot,
        'list_conversation_maps': list_conversation_map_manifests,
        'get_conversation_map': get_conversation_map_manifest,
        'write_lock': MARKDOWN_WRITE_LOCK,
    }


def _real_projects_deps(tasks=None):
    config = load_config()
    deps = {
        'repo_root': REPO_ROOT,
        'runtime_root': REPO_ROOT / '.real-project-state',
        'scan_tasks': scan_all if tasks is None else lambda: tasks,
        'roles': config.get('roles'),
        'owner_action_needed': requires_owner_action,
        'update_task_project_ref': lambda path, project_ref: update_frontmatter_field(
            path, 'project_ref', project_ref
        ),
        'update_task_project_role': lambda path, project_role: update_frontmatter_field(
            path, 'project_role', project_role
        ),
        'write_lock': MARKDOWN_WRITE_LOCK,
    }
    configured_dir = str(config.get('real_projects_dir') or '').strip()
    if configured_dir:
        storage_dir = Path(configured_dir).expanduser()
        deps.update({
            'registry_rel': storage_dir / 'projects.json',
            'events_rel': storage_dir / 'events.jsonl',
            'project_state_rel': storage_dir / 'project-state.generated.json',
            'project_actions_rel': storage_dir / 'project-actions.generated.json',
        })
    return deps


def get_real_projects(*, include_archived=False):
    projection, status = real_projects.build_projection(_real_projects_deps())
    return real_projects.filter_archived_projects(
        projection, include_archived=include_archived
    ), status


def _project_conversation_deps():
    return {
        'repo_root': REPO_ROOT,
        'write_lock': MARKDOWN_WRITE_LOCK,
    }


def get_project_materials(project_ref):
    return project_conversations.list_materials(_project_conversation_deps(), project_ref)


def link_project_conversation(payload):
    return project_conversations.link_conversation(_project_conversation_deps(), payload or {})


def unlink_project_conversation(payload):
    return project_conversations.unlink_conversation(_project_conversation_deps(), payload or {})


def get_project_posture():
    projection, status = get_real_projects()
    if status != 200:
        return real_projects.build_project_posture(projection), status
    return real_projects.build_project_posture(projection), 200


def refresh_real_project(project_ref):
    return real_projects.refresh_project(_real_projects_deps(), str(project_ref or '').strip())


def append_real_project_feedback(payload, *, actor='unspecified'):
    actor = str(actor or 'unspecified').strip()[:40]
    return real_projects.append_checkpoint_feedback(_real_projects_deps(), payload or {}, actor=actor)


def register_real_project(payload, *, actor='unspecified'):
    actor = str(actor or 'unspecified').strip()[:40]
    return real_projects.register_project(_real_projects_deps(), payload or {}, actor=actor)


def update_real_project(payload, *, actor='unspecified'):
    actor = str(actor or 'unspecified').strip()[:40]
    return real_projects.update_project(_real_projects_deps(), payload or {}, actor=actor)


def assign_task_to_real_project(payload, *, actor='unspecified'):
    actor = str(actor or 'unspecified').strip()[:40]
    return real_projects.assign_task(_real_projects_deps(), payload or {}, actor=actor)


def validate_real_project_ref(project_ref):
    return real_projects.get_registered_project(_real_projects_deps(), project_ref)


def enqueue_project_canvas_reorganize(project_ref):
    prepared, status = project_canvas_reorganize.prepare_run(
        REPO_ROOT,
        project_ref,
        validate_real_project_ref,
    )
    if status != 200 or not prepared.get('ok'):
        return prepared, status

    active = _queue_find_active_by_dedupe_key(prepared['dedupe_key'])
    if active:
        return {
            'ok': True,
            'run_id': active.get('id'),
            'status': active.get('status'),
            'project_ref': prepared['project_ref'],
            'queue': 'ai-run',
            'deduplicated': True,
        }, 200

    entry_id = _queue_add_entry(
        prepared['tool'],
        prepared['path'],
        prepared['workdir'],
        prompt_override=prepared['prompt'],
        metadata=prepared['metadata'],
        dedupe_key=prepared['dedupe_key'],
        ai_profile=prepared['profile'],
    )
    _queue_consume_next()
    entry = _queue_get_entry(entry_id) or {}
    return {
        'ok': True,
        'run_id': entry_id,
        'status': entry.get('status') or 'queued',
        'project_ref': prepared['project_ref'],
        'queue': 'ai-run',
        'deduplicated': False,
    }, 200


def _scan_project_graph_tasks():
    tasks = scan_all()
    for task in tasks:
        if isinstance(task.get('related_paths'), list):
            continue
        task_file, _err = _read_task_file(str(task.get('path') or ''))
        if not task_file:
            continue
        task['related_paths'] = _frontmatter_block_list_values(
            task_file.get('frontmatter_block'), 'related_paths'
        )
    return tasks


def _session_evidence_deps():
    config = load_config()
    return {
        'agent_mail_cli': _declared_integration_path(
            config,
            'agent_mail',
            'cli',
            _DISABLED_INTEGRATION_ROOT / 'agent-mail/am.py',
        ),
        'list_conversation_maps': list_conversation_map_manifests,
    }


def list_conversation_map_manifests():
    return conversation_map.list_conversation_maps(_conversation_map_deps())


def get_conversation_map_manifest(path):
    return conversation_map.get_conversation_map(path, _conversation_map_deps())


def get_conversation_map_canvas(scope):
    return conversation_map.get_conversation_map_canvas(scope, _conversation_map_deps())


def generate_conversation_map_canvas(scope, *, force=False, base_rev=None):
    return conversation_map.generate_conversation_map_canvas(
        scope,
        _conversation_map_deps(),
        force=force,
        base_rev=base_rev,
    )


def put_conversation_map_canvas(scope, canvas, actor='owner', base_rev=None):
    return conversation_map.put_conversation_map_canvas(
        scope,
        canvas,
        _conversation_map_deps(),
        actor=actor,
        base_rev=base_rev,
    )


def get_conversation_map_canvas_events(scope):
    return conversation_map.get_conversation_map_events(scope, _conversation_map_deps())


def _canvas_studio_url_for_path(path):
    base = str(load_config().get('canvas_studio_url') or _DEFAULTS['canvas_studio_url']).strip().rstrip('/')
    if not base:
        base = _DEFAULTS['canvas_studio_url']
    path_value = str(path or '').strip()
    if not path_value:
        return base + '/'
    return base + '/?path=' + quote(path_value, safe='')


def _guess_static_content_type(path_obj):
    suffix = path_obj.suffix.lower()
    content_type = _STATIC_MIME_OVERRIDES.get(suffix)
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(str(path_obj))
    if not guessed:
        return 'application/octet-stream'
    if guessed.startswith('text/') or guessed in ('application/javascript', 'application/json'):
        return guessed + '; charset=utf-8'
    return guessed


def build_canvas_view_html(path):
    title = 'Canvas Studio'
    studio_href = _public_html_escape(_canvas_studio_url_for_path(path))
    path_label = _public_html_escape(str(path or '未指定任务卡'))
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f6f7f9;color:#172033;letter-spacing:0}}
.shell{{max-width:760px;margin:0 auto;padding:48px 24px}}
.panel{{padding:24px;border:1px solid #dce1e8;border-radius:8px;background:#fff;box-shadow:0 14px 36px rgba(24,34,53,.08)}}
h1{{margin:0 0 12px;font-size:22px;line-height:1.25}}p{{margin:0 0 14px;font-size:14px;line-height:1.65;color:#4c5666}}
code{{display:block;margin:14px 0;padding:10px 12px;border:1px solid #dce1e8;border-radius:7px;background:#f6f7f9;color:#172033;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}
.btn{{display:inline-flex;align-items:center;justify-content:center;min-height:38px;padding:0 14px;border:1px solid #172033;border-radius:7px;background:#172033;color:#fff;font-weight:800;text-decoration:none}}
</style>
<div class="shell">
  <section class="panel">
    <h1>Context Canvas 查看器已归档</h1>
    <p>旧的看板内置画布查看器已经从运行路径下线。任务卡仍是事实源，完整关系图请在 Canvas Studio 按需打开。</p>
    <code>{path_label}</code>
    <a class="btn" href="{studio_href}">在 Canvas Studio 打开</a>
  </section>
</div>
</html>""", 200


GOVERNANCE_NOISE_REVIEW_PROMPT_REL = 'shared/toolkit/governance/prompts/governance-noise-review.md'
GOVERNANCE_NOISE_REVIEW_VERSION = 'governance-noise-review/v2'
_DISABLED_INTEGRATION_ROOT = REPO_ROOT / '.kanban-data' / 'disabled-integrations'
DOCUMENTS_ROOT = REPO_ROOT
DOCUMENTS_GOVERNANCE_ROOT = _DISABLED_INTEGRATION_ROOT / 'workspace-governance'
OWNER_WORLD_SOURCE = _DISABLED_INTEGRATION_ROOT / 'owner-world.json'


def get_owner_world():
    """Return the UI-safe, read-only projection of Owner's compiled world."""
    if owner_world is None:
        return {'ok': True, 'enabled': False, 'items': []}
    return owner_world.build_projection(OWNER_WORLD_SOURCE)
DOCUMENTS_GOVERNANCE_LATEST = DOCUMENTS_GOVERNANCE_ROOT / 'latest'
DOCUMENTS_GOVERNANCE_SELF_CHECK = DOCUMENTS_GOVERNANCE_ROOT / 'self-check'
DOCUMENTS_GOVERNANCE_RUNS = DOCUMENTS_GOVERNANCE_ROOT / 'runs'
GOVERNANCE_HEALTHCHECK_JSON = DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.json'
GOVERNANCE_HEALTHCHECK_REPORT = DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.md'
GOVERNANCE_NOISE_REVIEW_PACKET = DOCUMENTS_GOVERNANCE_SELF_CHECK / 'input.latest.generated.json'
GOVERNANCE_NOISE_REVIEW_LEDGER = DOCUMENTS_GOVERNANCE_SELF_CHECK / 'results.jsonl'
GOVERNANCE_NOISE_REVIEW_ROUTES = [
    'keep-visible',
    'background',
    'merge',
    'false-positive',
    'probe',
    'owner-gate',
    'park',
]
GOVERNANCE_NOISE_REVIEW_METRIC_FIELDS = [
    'confidence',
    'p_wrong',
    'cost_to_undo',
    'cost_to_interrupt',
    'reversibility',
    'evidence_strength',
]
GOVERNANCE_NOISE_REVIEW_REPORTS = [
    GOVERNANCE_HEALTHCHECK_REPORT,
    DOCUMENTS_GOVERNANCE_RUNS / '2026-06-18-2029' / 'WORKSPACE_GOVERNANCE_FULL_SCAN.generated.md',
    DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_STATUS.generated.md',
    DOCUMENTS_ROOT / 'WORKSPACE_STATUS.generated.md',
]


def get_governance_healthcheck_status():
    json_path = Path(GOVERNANCE_HEALTHCHECK_JSON)
    report_path = Path(GOVERNANCE_HEALTHCHECK_REPORT)
    if not json_path.exists():
        return {
            'ok': True,
            'latest': None,
            'json_path': str(json_path),
            'json_exists': False,
            'report_path': str(report_path),
            'report_exists': report_path.exists(),
        }
    try:
        payload = json.loads(json_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            'ok': False,
            'error': f'读取治理体检状态失败: {exc}',
            'json_path': str(json_path),
            'json_exists': True,
            'report_path': str(report_path),
            'report_exists': report_path.exists(),
        }
    parsed = payload.get('parsed') if isinstance(payload.get('parsed'), dict) else {}
    status_signals = parsed.get('status_signals') if isinstance(parsed.get('status_signals'), dict) else {}
    commands = payload.get('commands') if isinstance(payload.get('commands'), list) else []
    failed = [cmd for cmd in commands if isinstance(cmd, dict) and cmd.get('returncode') not in (0, None)]
    signal_count = status_signals.get('count') if isinstance(status_signals.get('count'), int) else 0
    if failed:
        health = '异常'
    elif signal_count:
        health = '有信号'
    else:
        health = '正常'
    latest = {
        'generated_at': payload.get('generated_at') or parsed.get('generated_at') or '',
        'health': health,
        'signal_count': signal_count,
        'signals': status_signals.get('lines') if isinstance(status_signals.get('lines'), list) else [],
        'probe': parsed.get('probe') if isinstance(parsed.get('probe'), dict) else {},
        'responsibility': parsed.get('responsibility') if isinstance(parsed.get('responsibility'), dict) else {},
        'auto_accept_count': parsed.get('auto_accept_count'),
        'compression_count': parsed.get('compression_count'),
        'command_count': len(commands),
        'failed_command_count': len(failed),
        'report_path': str(report_path),
        'report_exists': report_path.exists(),
        'json_path': str(json_path),
    }
    return {
        'ok': True,
        'latest': latest,
        'json_path': str(json_path),
        'json_exists': True,
        'report_path': str(report_path),
        'report_exists': report_path.exists(),
    }


def _governance_noise_text(value):
    return str(value or '').replace('\n', ' ').strip()


def _governance_noise_candidate_signals(task):
    if not task or str(task.get('status') or 'todo').strip().lower() == 'done':
        return []
    signals = []
    family = str(task.get('task_family') or '').strip().lower()
    domain = str(task.get('domain') or '').strip().lower()
    stage = str(task.get('stage') or '').strip().lower()
    source = str(task.get('source') or '').strip().lower()
    task_id = str(task.get('task_id') or task.get('legacy_id') or '').strip()
    tags = ' '.join(str(tag or '').strip().lower() for tag in (task.get('tags') or []))
    text = _governance_noise_text(' '.join([
        task.get('title') or '',
        task.get('display_title') or '',
        task.get('next_action') or '',
        task.get('path') or '',
        tags,
    ])).lower()
    if family in {'governance', 'documents', 'skill'}:
        signals.append(f'task_family:{family}')
    if re.match(r'^(GOV|DOC|SKL)-\d+', task_id, re.I):
        signals.append('task_id_prefix')
    if domain == 'governance' or 'governance' in tags or 'security' in tags:
        signals.append('domain_or_tag')
    if stage.startswith(('governance/', 'security/')):
        signals.append('stage')
    if source.startswith(('documents-doctor/', 'governance/')):
        signals.append('source')
    if re.search(r'治理|documents.?体检|doc-health|scan_governance|matrix\.probe|decision_log|skill-state|探针|压缩触发', text, re.I):
        signals.append('keyword')
    return signals


def _is_governance_noise_candidate(task):
    return bool(_governance_noise_candidate_signals(task))


def _governance_noise_hard_gate_signals(task):
    text = _governance_noise_text(' '.join([
        task.get('title') or '',
        task.get('display_title') or '',
        task.get('next_action') or '',
        task.get('source') or '',
        task.get('stage') or '',
        task.get('safety') or '',
        ' '.join(str(tag or '') for tag in (task.get('tags') or [])),
    ])).lower()
    checks = [
        ('send_or_publish', r'发送|发布|上线|公开|send|publish|deploy'),
        ('spend', r'花钱|付费|购买|预算|spend|pay|purchase|budget'),
        ('delete_or_move', r'删除|移动|归档|delete|remove|move|archive'),
        ('permission_or_secret', r'权限|凭证|密钥|token|cookie|secret|credential|permission'),
        ('external_commitment', r'对外|客户|团队承诺|external|customer|commitment'),
    ]
    return [name for name, pattern in checks if re.search(pattern, text, re.I)]


def _governance_noise_default_attention(task):
    responsibility = str(task.get('responsibility') or '').strip().lower()
    assignee = str(task.get('assignee') or '').strip().lower()
    status = str(task.get('status') or '').strip().lower()
    hard_gate_signals = _governance_noise_hard_gate_signals(task)
    reasons = []
    if responsibility in {'pi-gated', 'human-gated', 'owner-gated'}:
        reasons.append('responsibility_pi_gated')
    if assignee in {'owner', 'jun'}:
        reasons.append('assignee_owner')
    if status == 'review' and responsibility not in {'ai-owned', 'machine-owned'}:
        reasons.append('review_without_ai_owned')
    reasons.extend(hard_gate_signals)
    return {
        'visible_to_owner_by_default': bool(reasons),
        'hard_gate_signals': hard_gate_signals,
        'attention_reasons': reasons,
    }


def _governance_noise_task_record(task):
    attention = _governance_noise_default_attention(task)
    return {
        'path': task.get('path') or '',
        'id': task.get('task_id') or task.get('legacy_id') or '',
        'title': task.get('title') or task.get('display_title') or task.get('filename') or '',
        'status': task.get('status') or '',
        'assignee': task.get('assignee') or '',
        'responsibility': task.get('responsibility') or '',
        'safety': task.get('safety') or '',
        'source': task.get('source') or '',
        'stage': task.get('stage') or '',
        'next_action': task.get('next_action') or '',
        'candidate_signals': _governance_noise_candidate_signals(task),
        **attention,
    }


def _governance_noise_task_records(limit=80):
    records = []
    for task in scan_all():
        signals = _governance_noise_candidate_signals(task)
        if not signals:
            continue
        records.append(_governance_noise_task_record(task))
        if len(records) >= limit:
            break
    return records


def _governance_noise_task_rows(limit=80):
    rows = []
    for record in _governance_noise_task_records(limit=limit):
        fields = dict(record)
        fields['candidate_signals'] = ','.join(record.get('candidate_signals') or [])
        fields['attention_reasons'] = ','.join(record.get('attention_reasons') or [])
        fields['hard_gate_signals'] = ','.join(record.get('hard_gate_signals') or [])
        row = ' | '.join(f'{key}: {_governance_noise_text(value)}' for key, value in fields.items() if value)
        rows.append('- ' + row)
    return rows


def _governance_noise_report_records(max_chars=18000):
    records = []
    for path in GOVERNANCE_NOISE_REVIEW_REPORTS:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        excerpt = _text_for_prompt(text, max_chars)
        records.append({
            'path': str(path),
            'char_count': len(text),
            'excerpt_char_count': len(excerpt),
            'truncated': len(excerpt) < len(text),
            'excerpt': excerpt,
        })
    decision_log = REPO_ROOT / 'shared' / 'toolkit' / 'governance' / 'DECISION_LOG.md'
    if decision_log.exists():
        try:
            text = decision_log.read_text(encoding='utf-8')
            excerpt = _text_for_prompt(text, 12000)
            records.append({
                'path': str(decision_log),
                'char_count': len(text),
                'excerpt_char_count': len(excerpt),
                'truncated': len(excerpt) < len(text),
                'excerpt': excerpt,
            })
        except (OSError, UnicodeDecodeError):
            pass
    return records


def _governance_noise_report_blocks(max_chars=18000):
    blocks = []
    for record in _governance_noise_report_records(max_chars=max_chars):
        blocks.append(f"### {record['path']}\n\n{record['excerpt']}")
    return blocks


def _stable_json_hash(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _build_governance_noise_review_packet():
    candidates = _governance_noise_task_records()
    reports = _governance_noise_report_records()
    visible_by_default = sum(1 for item in candidates if item.get('visible_to_owner_by_default'))
    hard_gate_hint_count = sum(1 for item in candidates if item.get('hard_gate_signals'))
    return {
        'schema': 'workspace_governance_self_check_input/v1',
        'prompt_version': GOVERNANCE_NOISE_REVIEW_VERSION,
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'repo_root': str(REPO_ROOT),
        'source': 'kanban-governance-self-check-button',
        'contract': {
            'chain': 'cron deterministic sensing -> agent delta judgment -> human key decisions',
            'threshold': 'P(wrong) * cost_to_undo > cost_to_interrupt',
            'routes': GOVERNANCE_NOISE_REVIEW_ROUTES,
            'metric_fields': GOVERNANCE_NOISE_REVIEW_METRIC_FIELDS,
            'hard_boundaries': [
                'send',
                'publish',
                'spend',
                'delete',
                'permission-change',
                'credential-handling',
                'external-commitment',
                'irreversible-side-effect',
            ],
            'feedback_fields_for_future_calibration': [
                'route_suggested',
                'route_final_by_owner',
                'accepted',
                'error_type',
                'threshold_adjustment',
            ],
        },
        'summary': {
            'candidate_total': len(candidates),
            'owner_visible_before': len(candidates),
            'visible_by_default_hint_count': visible_by_default,
            'hard_gate_hint_count': hard_gate_hint_count,
            'report_count': len(reports),
        },
        'candidates': candidates,
        'reports': reports,
    }


def _write_governance_noise_review_packet(packet):
    path = Path(GOVERNANCE_NOISE_REVIEW_PACKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(packet, ensure_ascii=False, indent=2) + '\n')
    return path


def _append_governance_noise_review_ledger(record):
    path = Path(GOVERNANCE_NOISE_REVIEW_LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault('ts', datetime.now().astimezone().isoformat(timespec='seconds'))
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n')


def _extract_first_json_object(text):
    text = str(text or '')
    fenced_blocks = re.findall(r'```(?:json|JSON)\s*(\{.*?\})\s*```', text, flags=re.S)
    decoder = json.JSONDecoder()
    for block in reversed(fenced_blocks):
        try:
            obj, _ = decoder.raw_decode(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    for match in re.finditer(r'\{', text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _record_governance_noise_review_result(run_id, entry, ai_content, parsed, duration_ms):
    metadata = entry.get('metadata') if isinstance(entry, dict) else None
    if not isinstance(metadata, dict) or metadata.get('kind') != 'governance_noise_review':
        return None
    metrics = _extract_first_json_object(ai_content)
    parse_error = None
    if metrics is None:
        parse_error = 'no_fenced_json_metrics'
        metrics = {}
    else:
        required = {
            'candidate_total',
            'owner_visible_before',
            'owner_visible_after',
            'reduced_count',
            'reduction_rate',
            'bucket_counts',
            'low_confidence_count',
            'items',
        }
        missing = sorted(required - set(metrics.keys()))
        if missing:
            parse_error = 'missing_fields:' + ','.join(missing)
    try:
        _append_governance_noise_review_ledger({
            'event': 'result',
            'run_id': run_id,
            'prompt_version': metadata.get('prompt_version'),
            'packet_path': metadata.get('packet_path'),
            'packet_hash': metadata.get('packet_hash'),
            'candidate_total_at_request': metadata.get('candidate_total'),
            'duration_ms': duration_ms,
            'model': parsed.get('model'),
            'input_tokens': parsed.get('input_tokens'),
            'output_tokens': parsed.get('output_tokens'),
            'metrics': metrics,
            'parse_error': parse_error,
        })
    except OSError as exc:
        return f'治理自检样本账本写入失败: {exc}'
    return parse_error


def _governance_noise_review_ledger_events(limit=10):
    path = Path(GOVERNANCE_NOISE_REVIEW_LEDGER)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    events = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
        if len(events) >= limit:
            break
    return list(reversed(events))


def get_governance_noise_review_status():
    queue = _queue_snapshot()
    entries = [
        dict(entry)
        for entry in queue.get('entries', [])
        if entry.get('path') == GOVERNANCE_NOISE_REVIEW_PROMPT_REL
        or (isinstance(entry.get('metadata'), dict) and entry.get('metadata', {}).get('kind') == 'governance_noise_review')
    ]
    entries.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
    with _ai_runs_lock:
        for entry in entries:
            if entry.get('status') == 'running' and entry.get('id') in _ai_runs:
                elapsed = int((time.time() - _ai_runs[entry['id']].get('started_at', time.time())) * 1000)
                entry['elapsed_ms'] = elapsed
    latest = entries[0] if entries else None
    ledger_events = _governance_noise_review_ledger_events()
    latest_metrics = None
    latest_parse_error = None
    if latest:
        run_id = latest.get('id')
        for event in reversed(ledger_events):
            if event.get('event') == 'result' and event.get('run_id') == run_id:
                latest_metrics = event.get('metrics')
                latest_parse_error = event.get('parse_error')
                break
    if latest:
        output = latest.get('output') or latest.get('error') or ''
        latest['output_excerpt'] = _text_for_prompt(output, 800) if output else ''
        latest['metrics'] = latest_metrics
        latest['parse_error'] = latest_parse_error
    return {
        'ok': True,
        'latest': latest,
        'active': bool(latest and latest.get('status') in _ACTIVE_QUEUE_STATUSES),
        'packet_path': str(GOVERNANCE_NOISE_REVIEW_PACKET),
        'packet_exists': Path(GOVERNANCE_NOISE_REVIEW_PACKET).exists(),
        'ledger_path': str(GOVERNANCE_NOISE_REVIEW_LEDGER),
        'ledger_exists': Path(GOVERNANCE_NOISE_REVIEW_LEDGER).exists(),
        'ledger_events': ledger_events,
    }


def _build_governance_noise_review_prompt(packet=None):
    prompt_path = REPO_ROOT / GOVERNANCE_NOISE_REVIEW_PROMPT_REL
    try:
        raw_template = prompt_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raw_template = '# 治理噪音自检 Agent\n\n请对当前治理项做二次分流，减少 Owner 的治理注意力消耗。'
    _fm, fm_block = extract_frontmatter(raw_template)
    template_body = raw_template[len(fm_block):].strip() if fm_block else raw_template.strip()
    packet = packet or _build_governance_noise_review_packet()
    task_rows = []
    for record in packet.get('candidates') or []:
        fields = dict(record)
        fields['candidate_signals'] = ','.join(record.get('candidate_signals') or [])
        fields['attention_reasons'] = ','.join(record.get('attention_reasons') or [])
        fields['hard_gate_signals'] = ','.join(record.get('hard_gate_signals') or [])
        row = ' | '.join(f'{key}: {_governance_noise_text(value)}' for key, value in fields.items() if value)
        task_rows.append('- ' + row)
    report_blocks = [
        f"### {record['path']}\n\n{record['excerpt']}"
        for record in (packet.get('reports') or [])
    ]
    packet_excerpt = json.dumps({
        key: value for key, value in packet.items()
        if key != 'reports'
    }, ensure_ascii=False, indent=2)
    return f"""{template_body}

## Runtime Context

- 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
- 仓库：{REPO_ROOT}
- Prompt anchor：{GOVERNANCE_NOISE_REVIEW_PROMPT_REL}
- Prompt version：{GOVERNANCE_NOISE_REVIEW_VERSION}
- 自检输入快照：{GOVERNANCE_NOISE_REVIEW_PACKET}
- 自检样本账本：{GOVERNANCE_NOISE_REVIEW_LEDGER}
- 这次动作来自看板治理自治模块的“自检”按钮。
- 思考原则：cron → agent → human 成本级联；只有 `P(wrong) × cost-to-undo > cost-to-interrupt` 的事项才升级给 Owner。
- 指标 schema：candidate_total, owner_visible_before, owner_visible_after, reduced_count, reduction_rate, bucket_counts, low_confidence_count, confidence, p_wrong, cost_to_undo, cost_to_interrupt, reversibility, evidence_strength。
- 固定分流标签：keep-visible / background / merge / false-positive / probe / owner-gate / park。
- 你输出后，后端会自动回收到 generated JSONL 样本账本：系统会尝试解析 `## 机器可读指标` 中的 fenced json；请确保 JSON 可解析。
- 不要写文件；输入快照和样本账本由看板后端负责。

## 自检输入快照摘要

```json
{packet_excerpt}
```

## 当前治理模块候选项

{chr(10).join(task_rows) if task_rows else '- 当前看板扫描范围内没有活动治理候选项。'}

## 最新生成态报告摘录

{chr(10).join(report_blocks) if report_blocks else '- 未找到生成态报告；请只基于当前治理候选项判断。'}
"""


def enqueue_governance_noise_review():
    if 'codex' not in CLI_COMMANDS:
        return {'ok': False, 'error': 'Codex 未配置'}, 400
    prompt_rel = GOVERNANCE_NOISE_REVIEW_PROMPT_REL
    prompt_file = REPO_ROOT / prompt_rel
    if not prompt_file.exists():
        return {'ok': False, 'error': '治理自检 prompt 不存在'}, 404
    try:
        raw = prompt_file.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        return {'ok': False, 'error': f'读取治理自检 prompt 失败: {exc}'}, 400
    fm, _ = extract_frontmatter(raw)
    workdir_value = str((fm or {}).get('workdir') or '.').strip() or '.'
    cwd_path, cwd_err = resolve_workdir(workdir_value, prompt_rel)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
    if cwd_err:
        return {'ok': False, 'error': cwd_err}, 400
    if not cwd_path.exists():
        return {'ok': False, 'error': 'workdir_not_found', 'workdir': str(cwd_path)}, 400
    packet = _build_governance_noise_review_packet()
    packet_hash = _stable_json_hash(packet)
    packet_path = _write_governance_noise_review_packet(packet)
    prompt = _build_governance_noise_review_prompt(packet=packet)
    metadata = {
        'kind': 'governance_noise_review',
        'prompt_version': GOVERNANCE_NOISE_REVIEW_VERSION,
        'packet_path': str(packet_path),
        'packet_hash': packet_hash,
        'candidate_total': packet.get('summary', {}).get('candidate_total', 0),
        'owner_visible_before': packet.get('summary', {}).get('owner_visible_before', 0),
    }
    entry_id = _queue_add_entry('codex', prompt_rel, workdir_value, prompt_override=prompt, metadata=metadata)
    try:
        _append_governance_noise_review_ledger({
            'event': 'request',
            'run_id': entry_id,
            **metadata,
        })
    except OSError:
        pass
    _queue_consume_next()
    candidate_total = packet.get('summary', {}).get('candidate_total', 0)
    return {
        'ok': True,
        'run_id': entry_id,
        'tool': 'codex',
        'path': prompt_rel,
        'candidate_total': candidate_total,
        'packet_path': str(packet_path),
        'ledger_path': str(GOVERNANCE_NOISE_REVIEW_LEDGER),
        'message': f'治理自检已交给 Codex CLI · 候选 {candidate_total} 项',
    }, 200


INFOOPS_XHS_DRAFT_TASK_ID = 'infoops_sih_xhs_draft_ai'
INFOOPS_SIH_DAILY_FETCH_TASK_ID = 'infoops_sih_daily_fetch_ai'
INFOOPS_CONTENT_QUEUE_PATH = _DISABLED_INTEGRATION_ROOT / 'infoops/content-queue.md'
INFOOPS_XHS_ARTICLE_DIR = _DISABLED_INTEGRATION_ROOT / 'infoops/articles'
INFOOPS_XHS_CONTENT_CARD_DIR = _DISABLED_INTEGRATION_ROOT / 'infoops/content-cards'
PUBLICAI4S_CONTENT_DRAFTS_DIR = _DISABLED_INTEGRATION_ROOT / 'infoops/public-drafts'
SIH_DAILY_REPORTS_DIR = _DISABLED_INTEGRATION_ROOT / 'infoops/daily-reports'
CODEX_SESSION_DIRS = []
_AUTOMATION_DAYS = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}


def _declared_integration_path(config, integration_name, field, fallback):
    settings = _integration_settings(config, integration_name)
    if settings.get('enabled') is not True:
        return Path(fallback)
    raw = str(settings.get(field) or '').strip()
    if not raw:
        return Path(fallback)
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = _configured_root('workspace_root', config) / candidate
    candidate = candidate.resolve(strict=False)
    if not _path_in_allowed_roots(candidate, _configured_open_allowed_roots(config)):
        return Path(fallback)
    return candidate


def _configure_optional_integration_paths(config):
    """Bind legacy adapters only to explicitly enabled, allowlisted paths."""
    global DOCUMENTS_ROOT, DOCUMENTS_GOVERNANCE_ROOT, DOCUMENTS_GOVERNANCE_LATEST
    global DOCUMENTS_GOVERNANCE_SELF_CHECK, DOCUMENTS_GOVERNANCE_RUNS
    global GOVERNANCE_HEALTHCHECK_JSON, GOVERNANCE_HEALTHCHECK_REPORT
    global GOVERNANCE_NOISE_REVIEW_PACKET, GOVERNANCE_NOISE_REVIEW_LEDGER
    global GOVERNANCE_NOISE_REVIEW_REPORTS, OWNER_WORLD_SOURCE
    global INFOOPS_CONTENT_QUEUE_PATH, INFOOPS_XHS_ARTICLE_DIR
    global INFOOPS_XHS_CONTENT_CARD_DIR, PUBLICAI4S_CONTENT_DRAFTS_DIR
    global SIH_DAILY_REPORTS_DIR, CODEX_SESSION_DIRS

    DOCUMENTS_ROOT = _configured_root('workspace_root', config)
    governance_fallback = _DISABLED_INTEGRATION_ROOT / 'workspace-governance'
    DOCUMENTS_GOVERNANCE_ROOT = _declared_integration_path(
        config, 'workspace_governance', 'root', governance_fallback
    )
    DOCUMENTS_GOVERNANCE_LATEST = DOCUMENTS_GOVERNANCE_ROOT / 'latest'
    DOCUMENTS_GOVERNANCE_SELF_CHECK = DOCUMENTS_GOVERNANCE_ROOT / 'self-check'
    DOCUMENTS_GOVERNANCE_RUNS = DOCUMENTS_GOVERNANCE_ROOT / 'runs'
    GOVERNANCE_HEALTHCHECK_JSON = DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.json'
    GOVERNANCE_HEALTHCHECK_REPORT = DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_GOVERNANCE_HEALTHCHECK.generated.md'
    GOVERNANCE_NOISE_REVIEW_PACKET = DOCUMENTS_GOVERNANCE_SELF_CHECK / 'input.latest.generated.json'
    GOVERNANCE_NOISE_REVIEW_LEDGER = DOCUMENTS_GOVERNANCE_SELF_CHECK / 'results.jsonl'
    GOVERNANCE_NOISE_REVIEW_REPORTS = [
        GOVERNANCE_HEALTHCHECK_REPORT,
        DOCUMENTS_GOVERNANCE_LATEST / 'WORKSPACE_STATUS.generated.md',
    ]
    OWNER_WORLD_SOURCE = _declared_integration_path(
        config, 'owner_world', 'source', _DISABLED_INTEGRATION_ROOT / 'owner-world.json'
    )

    infoops_fallback = _DISABLED_INTEGRATION_ROOT / 'infoops'
    INFOOPS_CONTENT_QUEUE_PATH = _declared_integration_path(config, 'infoops', 'content_queue', infoops_fallback / 'content-queue.md')
    INFOOPS_XHS_ARTICLE_DIR = _declared_integration_path(config, 'infoops', 'article_dir', infoops_fallback / 'articles')
    INFOOPS_XHS_CONTENT_CARD_DIR = _declared_integration_path(config, 'infoops', 'content_card_dir', infoops_fallback / 'content-cards')
    PUBLICAI4S_CONTENT_DRAFTS_DIR = _declared_integration_path(config, 'infoops', 'public_drafts_dir', infoops_fallback / 'public-drafts')
    SIH_DAILY_REPORTS_DIR = _declared_integration_path(config, 'infoops', 'daily_reports_dir', infoops_fallback / 'daily-reports')

    session_settings = _integration_settings(config, 'codex_sessions')
    CODEX_SESSION_DIRS = []
    if session_settings.get('enabled') is True and isinstance(session_settings.get('roots'), list):
        for raw in session_settings['roots']:
            candidate = Path(os.path.expanduser(str(raw or '').strip()))
            if not candidate.is_absolute():
                candidate = _configured_root('workspace_root', config) / candidate
            candidate = candidate.resolve(strict=False)
            if candidate.is_dir() and _path_in_allowed_roots(candidate, _configured_open_allowed_roots(config)):
                CODEX_SESSION_DIRS.append(candidate)


def _safe_toml_load(path_obj):
    if not path_obj.exists() or not path_obj.is_file():
        return {}
    try:
        raw = path_obj.read_bytes()
        if tomllib:
            data = tomllib.loads(raw.decode('utf-8'))
        else:
            data = {}
            for line in raw.decode('utf-8', errors='replace').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"')
                if key in {'id', 'kind', 'name', 'status', 'rrule', 'model', 'reasoning_effort', 'execution_environment'}:
                    data[key] = value
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sanitize_automation_text(value, limit=220):
    text = str(value or '').strip()
    if not text:
        return ''
    text = re.sub(r'\b(cli|oc|om)_[A-Za-z0-9_-]+\b', '[已隐藏目标ID]', text)
    text = re.sub(r'(?i)(api[_-]?key|token|secret|credential|auth|app[_-]?secret)\s*[:=]\s*\S+', r'\1=[已隐藏]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    return text


def _parse_rrule(rrule):
    parts = {}
    for chunk in str(rrule or '').split(';'):
        if '=' not in chunk:
            continue
        key, value = chunk.split('=', 1)
        parts[key.strip().upper()] = value.strip()
    return parts


def _rrule_label(rrule):
    parts = _parse_rrule(rrule)
    hour = int(parts.get('BYHOUR') or 0)
    minute = int(parts.get('BYMINUTE') or 0)
    when = f'{hour:02d}:{minute:02d}'
    if parts.get('FREQ') == 'DAILY':
        return f'每天 {when}'
    if parts.get('FREQ') == 'WEEKLY':
        day_names = {'MO': '周一', 'TU': '周二', 'WE': '周三', 'TH': '周四', 'FR': '周五', 'SA': '周六', 'SU': '周日'}
        days = [day_names.get(d, d) for d in parts.get('BYDAY', '').split(',') if d]
        return f'每{" / ".join(days)} {when}' if days else f'每周 {when}'
    return str(rrule or '')


def _next_occurrences(rrule, *, now=None, days=7):
    now = now or datetime.now()
    parts = _parse_rrule(rrule)
    try:
        hour = int(parts.get('BYHOUR') or 0)
        minute = int(parts.get('BYMINUTE') or 0)
    except ValueError:
        hour, minute = 0, 0
    freq = parts.get('FREQ')
    occurrences = []
    for offset in range(days + 1):
        day = now.date() + timedelta(days=offset)
        if freq == 'WEEKLY':
            bydays = [d for d in parts.get('BYDAY', '').split(',') if d]
            if bydays and day.weekday() not in {_AUTOMATION_DAYS.get(d) for d in bydays}:
                continue
        elif freq != 'DAILY':
            if offset != 0:
                continue
        candidate = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
        if candidate <= now:
            continue
        occurrences.append({
            'run_at': candidate.isoformat(timespec='minutes'),
            'date': candidate.strftime('%Y-%m-%d'),
            'time': candidate.strftime('%H:%M'),
            'day_label': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][candidate.weekday()],
        })
    return occurrences


def _extract_latest_memory_summary(memory_path):
    if not memory_path.exists() or not memory_path.is_file():
        return None, None, 0
    try:
        text = memory_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None, None, 0
    blocks = re.split(r'\n(?=##\s+)', text)
    latest_block = blocks[-1] if blocks else text
    lines = [line.strip('- ').strip() for line in latest_block.splitlines() if line.strip()]
    last_checked = None
    for line in lines:
        match = re.search(r'Last checked[:：]\s*(.+)$', line, re.I)
        if match:
            last_checked = _sanitize_automation_text(match.group(1), 80)
            break
        match = re.search(r'运行时间[:：]\s*(.+)$', line)
        if match:
            last_checked = _sanitize_automation_text(match.group(1), 80)
            break
    summary_lines = []
    for line in lines:
        if line.startswith('##'):
            continue
        if 'Last checked' in line:
            continue
        summary_lines.append(_sanitize_automation_text(line, 180))
        if len(summary_lines) >= 3:
            break
    return ' '.join([x for x in summary_lines if x]) or None, last_checked, len(text)


def _latest_automation_session(automation_id, name):
    latest = None
    markers = [f'Automation ID: {automation_id}', f'Automation: {name}']
    for root in CODEX_SESSION_DIRS:
        if not root.exists():
            continue
        try:
            files = sorted(root.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:300]
        except OSError:
            continue
        for path_obj in files:
            try:
                text = path_obj.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            if not any(marker and marker in text for marker in markers):
                continue
            session_id = ''
            session_ts = None
            first = text.splitlines()[0] if text else ''
            try:
                data = json.loads(first)
                payload = data.get('payload', {})
                session_id = payload.get('id', '')
                session_ts = payload.get('timestamp') or data.get('timestamp')
            except Exception:
                pass
            item = {
                'session_id': session_id,
                'timestamp': session_ts,
                'path': str(path_obj),
            }
            if latest is None:
                latest = item
            break
    return latest


def _automation_health(status, summary):
    if status != 'ACTIVE':
        return '已停用'
    if not summary:
        return '暂无记录'
    text = summary
    if re.search(r'需要用户确认|等待用户确认|awaits user confirmation|needs user confirmation|requires user confirmation', text, re.I):
        return '需确认'
    if re.search(r'部分完成|partial', text, re.I):
        return '部分完成'
    if re.search(r'failed|失败|异常|error|exit code|Could not resolve|curl exit', text, re.I):
        return '异常'
    if re.search(r'succeeded|成功|sent|exited 0|正常', text, re.I):
        return '正常'
    return '部分完成'


def _automation_reason(automation_id, name, status, summary, memory_exists):
    if status != 'ACTIVE':
        if automation_id == 'wiki':
            return '飞书 Wiki 每日同步已合并进 team-workspace，独立任务已停用。'
        return '任务已停用，不再进入主档期。'
    if summary:
        return summary
    if not memory_exists:
        return '任务已配置，暂无实施摘要。'
    return '暂无可解析的最近实施结论。'


def _automation_output_link(label, path_value, kind='artifact'):
    path_text = _sanitize_automation_text(path_value, 500)
    if not path_text:
        return None
    return {'label': label, 'path': path_text, 'kind': kind}


def _automation_links_from_output(output):
    links = []
    if not isinstance(output, dict):
        return links
    direct = _automation_output_link('产物', output.get('path'))
    if direct:
        links.append(direct)
    tail = str(output.get('stdout_tail') or '').strip()
    if not tail or tail[0] not in '{[':
        return links
    try:
        parsed = json.loads(tail)
    except Exception:
        return links
    if not isinstance(parsed, dict):
        return links
    for label, key, kind in (
        ('结果', 'result_md', 'report'),
        ('结果', 'result_markdown', 'report'),
        ('结果', 'result_json', 'json'),
        ('结果', 'sync_result_json', 'json'),
        ('队列', 'queue_jsonl', 'json'),
        ('目录', 'output_dir', 'folder'),
    ):
        link = _automation_output_link(label, parsed.get(key), kind)
        if link:
            links.append(link)
    return links


def _automation_result_timestamp(result):
    if not isinstance(result, dict):
        return 0.0
    raw = str(result.get('finished_at') or result.get('started_at') or '').strip()
    if not raw:
        return 0.0
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _newer_automation_result(primary, secondary):
    if not primary:
        return secondary
    if not secondary:
        return primary
    if _automation_result_timestamp(secondary) > _automation_result_timestamp(primary):
        return secondary
    return primary


def _markdown_table_cells(line):
    text = str(line or '').strip()
    if not text.startswith('|') or not text.endswith('|'):
        return []
    return [cell.strip() for cell in text.strip('|').split('|')]


def _strip_markdown_inline(value):
    text = str(value or '').strip()
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_infoops_xhs_title(title):
    text = _strip_markdown_inline(title)
    text = re.sub(r'^小红书(?:草稿箱|草稿|已发)?[：:]\s*', '', text)
    return text.strip()


def _read_text_quiet(path_obj, limit=None):
    try:
        text = Path(path_obj).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return text[:limit] if limit else text


def _infoops_quote_meta(text, key):
    pattern = re.compile(rf'^>\s*{re.escape(key)}\s*:\s*(.+?)\s*$', re.M)
    match = pattern.search(text or '')
    if not match:
        return ''
    return _strip_markdown_inline(match.group(1)).rstrip('/')


def _path_mtime_iso(paths):
    mtimes = []
    for raw in paths:
        if not raw:
            continue
        try:
            path_obj = Path(raw)
            if path_obj.exists():
                mtimes.append(path_obj.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return ''
    return datetime.fromtimestamp(max(mtimes)).astimezone().isoformat(timespec='seconds')


def _find_infoops_xhs_note(date_text, title):
    date_key = str(date_text or '').replace('-', '')
    if not date_key or not INFOOPS_XHS_ARTICLE_DIR.exists():
        return None, ''
    try:
        candidates = sorted(
            INFOOPS_XHS_ARTICLE_DIR.glob(f'{date_key}_xhs-*.md'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None, ''
    title_key = _normalize_infoops_xhs_title(title)
    fallback = (None, '')
    for path_obj in candidates:
        text = _read_text_quiet(path_obj, limit=20000)
        if fallback[0] is None:
            fallback = (path_obj, text)
        if title_key and title_key in text:
            return path_obj, text
    return fallback


def _find_infoops_xhs_card(date_text, title, note_path=None):
    if note_path:
        name = note_path.name.replace('-draft-note.md', '-content-card.md')
        candidate = INFOOPS_XHS_CONTENT_CARD_DIR / name
        if candidate.exists():
            return candidate, _read_text_quiet(candidate, limit=20000)
    date_key = str(date_text or '').replace('-', '')
    if not date_key or not INFOOPS_XHS_CONTENT_CARD_DIR.exists():
        return None, ''
    try:
        candidates = sorted(
            INFOOPS_XHS_CONTENT_CARD_DIR.glob(f'{date_key}_xhs-*.md'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None, ''
    title_key = _normalize_infoops_xhs_title(title)
    fallback = (None, '')
    for path_obj in candidates:
        text = _read_text_quiet(path_obj, limit=20000)
        if fallback[0] is None:
            fallback = (path_obj, text)
        if title_key and title_key in text:
            return path_obj, text
    return fallback


def _infoops_xhs_daily_json_path(date_text):
    date_text = str(date_text or '').strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
        return None
    daily_dir = SIH_DAILY_REPORTS_DIR / date_text
    date_key = date_text.replace('-', '')
    for name in (
        f'public_xhs_shortlist_{date_key}.json',
        'daily_fetch_summary.json',
        'daily_items.jsonl',
    ):
        candidate = daily_dir / name
        if candidate.exists():
            return candidate
    return None


def _infoops_xhs_health(status):
    normalized = str(status or '').strip().lower()
    if normalized in {'saved-draft', 'posted', 'done'}:
        return '正常'
    if normalized in {'draft', 'triage', 'review'}:
        return '需确认'
    return '部分完成'


def _infoops_xhs_queue_rows():
    if not INFOOPS_CONTENT_QUEUE_PATH.exists() or not INFOOPS_CONTENT_QUEUE_PATH.is_file():
        return []
    rows = []
    text = _read_text_quiet(INFOOPS_CONTENT_QUEUE_PATH)
    for line in text.splitlines():
        cells = _markdown_table_cells(line)
        if len(cells) < 9:
            continue
        if cells[0] in {'日期', '---'} or set(cells[0]) == {'-'}:
            continue
        date_text = _strip_markdown_inline(cells[0])
        title = _strip_markdown_inline(cells[1])
        source = _strip_markdown_inline(cells[2])
        status = _strip_markdown_inline(cells[8]).lower()
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
            continue
        if 'sih-daily-intelligence' not in source:
            continue
        if '小红书' not in title and 'xhs' not in title.lower():
            continue
        if status not in {'saved-draft', 'draft', 'posted'}:
            continue
        rows.append({
            'date': date_text,
            'title': title,
            'source': source,
            'product': _strip_markdown_inline(cells[6]),
            'next_step': _strip_markdown_inline(cells[7]),
            'status': status,
        })
    return rows


def _infoops_xhs_external_latest_result(item):
    if str((item or {}).get('id') or '') != INFOOPS_XHS_DRAFT_TASK_ID:
        return None
    rows = _infoops_xhs_queue_rows()
    if not rows:
        return None
    row = rows[0]
    note_path, note_text = _find_infoops_xhs_note(row['date'], row['title'])
    card_path, card_text = _find_infoops_xhs_card(row['date'], row['title'], note_path)
    package_value = _infoops_quote_meta(note_text, 'package') or _infoops_quote_meta(card_text, 'package')
    case_id = _infoops_quote_meta(note_text, 'case_id') or _infoops_quote_meta(card_text, 'case_id')
    package_path = Path(package_value).expanduser() if package_value else None
    if (not package_path or not package_path.exists()) and case_id:
        candidate = PUBLICAI4S_CONTENT_DRAFTS_DIR / case_id
        if candidate.exists():
            package_path = candidate
    daily_json = _infoops_xhs_daily_json_path(row['date'])
    evidence_paths = [INFOOPS_CONTENT_QUEUE_PATH, note_path, card_path]
    if package_path:
        evidence_paths.append(package_path / 'README.md' if package_path.is_dir() else package_path)
    finished_at = _path_mtime_iso(evidence_paths)
    if not finished_at:
        return None

    normalized_title = _normalize_infoops_xhs_title(row['title'])
    output_links = []
    for label, path_obj, kind in (
        ('队列', INFOOPS_CONTENT_QUEUE_PATH, 'report'),
        ('结果', card_path, 'report'),
        ('目录', package_path, 'folder'),
        ('源JSON', daily_json, 'json'),
    ):
        link = _automation_output_link(label, str(path_obj) if path_obj else '', kind)
        if link:
            output_links.append(link)

    return {
        'ok': True,
        'task_id': INFOOPS_XHS_DRAFT_TASK_ID,
        'status': 'completed',
        'health': _infoops_xhs_health(row['status']),
        'started_at': '',
        'finished_at': finished_at,
        'reason': _sanitize_automation_text(f"内容链最新产物：{row['status']} · {normalized_title}", 220),
        'last_run_json': str(daily_json) if daily_json else '',
        'last_run_md': str(note_path) if note_path else str(INFOOPS_CONTENT_QUEUE_PATH),
        'pending_json': '',
        'legacy_json': '',
        'legacy_md': '',
        'source': 'infoops-content-chain',
        'actions': {
            'needs_agent_summary': False,
            'needs_attention': row['status'] == 'draft',
            'preflight': False,
            'external_evidence': True,
        },
        'outputs': [{
            'label': 'infoops_content_chain',
            'returncode': 0,
            'path': str(package_path) if package_path else '',
        }],
        'output_links': output_links[:8],
    }


def _latest_sih_daily_report_dir():
    if not SIH_DAILY_REPORTS_DIR.exists() or not SIH_DAILY_REPORTS_DIR.is_dir():
        return None
    try:
        candidates = [
            path for path in SIH_DAILY_REPORTS_DIR.iterdir()
            if path.is_dir()
            and re.match(r'^\d{4}-\d{2}-\d{2}$', path.name)
            and (path / 'daily_fetch_summary.json').exists()
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name, reverse=True)[0]


def _count_jsonl_lines(path_obj):
    try:
        with Path(path_obj).open('r', encoding='utf-8', errors='replace') as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _read_json_quiet(path_obj):
    try:
        data = json.loads(Path(path_obj).read_text(encoding='utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sih_daily_external_latest_result(item):
    if str((item or {}).get('id') or '') != INFOOPS_SIH_DAILY_FETCH_TASK_ID:
        return None
    daily_dir = _latest_sih_daily_report_dir()
    if not daily_dir:
        return None
    date_text = daily_dir.name
    summary_path = daily_dir / 'daily_fetch_summary.json'
    failures_path = daily_dir / 'daily_fetch_failures.json'
    items_path = daily_dir / 'daily_items.jsonl'
    briefing_path = daily_dir / f'daily_briefing_{date_text}.md'
    news_overview_path = daily_dir / f'daily_news_overview_{date_text}.md'
    self_read_path = daily_dir / 'self_read' / 'index.html'
    summary = _read_json_quiet(summary_path)
    records = summary.get('records')
    try:
        records = int(records)
    except (TypeError, ValueError):
        records = _count_jsonl_lines(items_path)
    failures = summary.get('failures')
    try:
        failures = int(failures)
    except (TypeError, ValueError):
        failures = 0
    checks = summary.get('checks')
    try:
        checks = int(checks)
    except (TypeError, ValueError):
        checks = 0
    degraded = bool(summary.get('degraded'))
    health = '部分完成' if degraded or failures else '正常'
    status_label = 'degraded' if degraded else 'complete'
    finished_at = _path_mtime_iso([summary_path, items_path, briefing_path, news_overview_path, self_read_path])
    if not finished_at:
        return None
    reason_bits = [f"SIH daily {date_text}", f"{records} 条"]
    if checks:
        reason_bits.append(f"抓取 {checks - failures}/{checks}")
    if degraded or failures:
        reason_bits.append(f"{status_label} · 失败 {failures}")
    else:
        reason_bits.append('抓取完成')
    output_links = []
    for label, path_obj, kind in (
        ('报告', briefing_path, 'report'),
        ('新闻', news_overview_path, 'report'),
        ('JSON', summary_path, 'json'),
        ('失败', failures_path, 'json'),
        ('结果', items_path, 'json'),
        ('自读页', self_read_path, 'report'),
        ('目录', daily_dir, 'folder'),
    ):
        link = _automation_output_link(label, str(path_obj) if path_obj and path_obj.exists() else '', kind)
        if link:
            output_links.append(link)
    return {
        'ok': True,
        'task_id': INFOOPS_SIH_DAILY_FETCH_TASK_ID,
        'status': 'completed',
        'health': health,
        'started_at': _sanitize_automation_text(summary.get('generated_at'), 80),
        'finished_at': finished_at,
        'reason': _sanitize_automation_text(' · '.join(reason_bits), 220),
        'last_run_json': str(summary_path),
        'last_run_md': str(briefing_path) if briefing_path.exists() else '',
        'pending_json': '',
        'legacy_json': '',
        'legacy_md': '',
        'source': 'sih-daily-reports',
        'actions': {
            'needs_agent_summary': False,
            'needs_attention': False,
            'preflight': False,
            'external_evidence': True,
        },
        'outputs': [{
            'label': 'sih_daily_reports',
            'returncode': 0,
            'path': str(daily_dir),
        }],
        'output_links': output_links[:8],
    }


def _external_automation_latest_result(item):
    latest = _infoops_xhs_external_latest_result(item)
    latest = _newer_automation_result(latest, _sih_daily_external_latest_result(item))
    return latest


def _compact_automation_latest_result(item, cache):
    path_raw = str((item or {}).get('last_run_json') or '').strip()
    if not path_raw:
        return None
    if path_raw in cache:
        return cache[path_raw]
    path_obj = Path(path_raw).expanduser()
    try:
        if not path_obj.exists() or not path_obj.is_file():
            cache[path_raw] = None
            return None
        data = json.loads(path_obj.read_text(encoding='utf-8'))
    except Exception:
        cache[path_raw] = None
        return None
    if not isinstance(data, dict):
        cache[path_raw] = None
        return None

    outputs = []
    output_links = []
    seen_links = set()
    for raw in (data.get('outputs') or [])[:8]:
        if not isinstance(raw, dict):
            continue
        compact = {
            'label': _sanitize_automation_text(raw.get('label'), 80),
            'returncode': raw.get('returncode'),
        }
        path_value = _sanitize_automation_text(raw.get('path'), 500)
        if path_value:
            compact['path'] = path_value
        outputs.append(compact)
        for link in _automation_links_from_output(raw):
            key = (link.get('label'), link.get('path'))
            if key in seen_links:
                continue
            seen_links.add(key)
            output_links.append(link)

    actions = data.get('actions') if isinstance(data.get('actions'), dict) else {}
    latest = {
        'ok': bool(data.get('ok')),
        'task_id': _sanitize_automation_text(data.get('task_id'), 120),
        'status': _sanitize_automation_text(data.get('status'), 80),
        'health': _sanitize_automation_text(data.get('health'), 80),
        'started_at': _sanitize_automation_text(data.get('started_at'), 80),
        'finished_at': _sanitize_automation_text(data.get('finished_at'), 80),
        'reason': _sanitize_automation_text(data.get('reason'), 220),
        'last_run_json': _sanitize_automation_text(data.get('last_run_json') or path_raw, 500),
        'last_run_md': _sanitize_automation_text(data.get('last_run_md'), 500),
        'pending_json': _sanitize_automation_text(data.get('pending_json'), 500),
        'legacy_json': _sanitize_automation_text(data.get('legacy_json'), 500),
        'legacy_md': _sanitize_automation_text(data.get('legacy_md'), 500),
        'actions': {
            str(key): value if isinstance(value, bool) else _sanitize_automation_text(value, 120)
            for key, value in actions.items()
        },
        'outputs': outputs,
        'output_links': output_links[:8],
    }
    summary = data.get('summary_result')
    if isinstance(summary, dict):
        latest['summary_result'] = {
            'ok': bool(summary.get('ok')),
            'review_output': _sanitize_automation_text(summary.get('review_output'), 500),
        }
    cache[path_raw] = latest
    return latest


def _attach_automation_latest_results(payload):
    cache = {}
    for key in ('active', 'inactive'):
        for item in payload.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            latest = _compact_automation_latest_result(item, cache)
            latest = _newer_automation_result(latest, _external_automation_latest_result(item))
            if latest:
                item['latest_result'] = latest
                if latest.get('source') in {'infoops-content-chain', 'sih-daily-reports'}:
                    if latest.get('health'):
                        item['health'] = latest['health']
                    if latest.get('reason'):
                        item['reason'] = latest['reason']
                    if latest.get('finished_at'):
                        item['last_checked'] = latest['finished_at']
    return payload


def _governance_result_card_deps():
    return {
        'scan_all': scan_all,
        'create_document': create_document,
        'update_frontmatter_field': update_frontmatter_field,
        'update_task_body': update_task_body,
        'read_task_body': _read_doc_body,
    }


def _is_local_port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex(('127.0.0.1', int(port))) == 0
    except Exception:
        return False


def _wait_for_local_port(port, timeout_seconds=10):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_local_port_open(port):
            return True
        time.sleep(0.25)
    return False


def _configured_bridge_targets(config=None):
    source = config if isinstance(config, dict) else load_config()
    integrations = source.get('integrations') if isinstance(source.get('integrations'), dict) else {}
    raw_targets = integrations.get('local_tools') if isinstance(integrations.get('local_tools'), dict) else {}
    allowed_roots = _configured_open_allowed_roots(source)
    targets = {}
    for target_id, raw in raw_targets.items():
        target_id = str(target_id or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', target_id) or not isinstance(raw, dict):
            continue
        if raw.get('enabled') is not True:
            continue
        cwd_raw = str(raw.get('cwd') or '').strip()
        command = str(raw.get('command') or '').strip()
        url = str(raw.get('url') or '').strip()
        if not cwd_raw or not command or not re.match(r'^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|$)', url):
            continue
        cwd = Path(os.path.expanduser(cwd_raw))
        if not cwd.is_absolute():
            cwd = _configured_root('workspace_root', source) / cwd
        cwd = cwd.resolve(strict=False)
        if not cwd.is_dir() or not _path_in_allowed_roots(cwd, allowed_roots):
            continue
        target = {
            'id': target_id,
            'name': str(raw.get('name') or target_id).strip() or target_id,
            'url': url,
            'cwd': cwd,
            'command': command,
            'open_browser': raw.get('open_browser') is not False,
        }
        try:
            port = int(raw.get('port') or 0)
        except (TypeError, ValueError):
            port = 0
        if 0 < port <= 65535:
            target['port'] = port
        url_file_raw = str(raw.get('url_file') or '').strip()
        if url_file_raw:
            url_file = Path(os.path.expanduser(url_file_raw))
            if not url_file.is_absolute():
                url_file = _configured_root('data_root', source) / url_file
            target['url_file'] = url_file.resolve(strict=False)
        targets[target_id] = target
    return targets


def configured_local_integrations(config=None):
    if not PLATFORM_ADAPTER.capabilities().get('process_launch'):
        configured = _configured_bridge_targets(config)
        if configured:
            PLATFORM_ADAPTER.log_degradation(
                'process_launch_hidden',
                f'本地工具启动在 {PLATFORM_ADAPTER.name} 上不可用；{len(configured)} 个入口已隐藏',
            )
        return []
    return [
        {
            'id': target_id,
            'label': target['name'],
            'url': target['url'],
        }
        for target_id, target in _configured_bridge_targets(config).items()
    ]


def _integration_settings(config, name):
    integrations = config.get('integrations') if isinstance(config, dict) and isinstance(config.get('integrations'), dict) else {}
    value = integrations.get(name)
    return value if isinstance(value, dict) else {}


def _enabled_existing_path(config, integration_name, field, *, directory=False):
    settings = _integration_settings(config, integration_name)
    if settings.get('enabled') is not True:
        return None
    raw = str(settings.get(field) or '').strip()
    if not raw:
        return None
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = _configured_root('workspace_root', config) / candidate
    candidate = candidate.resolve(strict=False)
    if directory and not candidate.is_dir():
        return None
    if not directory and not candidate.is_file():
        return None
    return candidate


def configured_ui_features(config=None):
    source = config if isinstance(config, dict) else load_config()
    relationship_settings = _integration_settings(source, 'relationships')
    relationships = (
        relationship_settings.get('enabled') is True
        and _enabled_existing_path(source, 'relationships', 'people_dir', directory=True) is not None
    )
    governance = _enabled_existing_path(
        source, 'workspace_governance', 'root', directory=True
    ) is not None
    owner_world_source = _enabled_existing_path(source, 'owner_world', 'source')
    doctor_cfg = source.get('network_doctor') if isinstance(source.get('network_doctor'), dict) else {}
    platform_proxy_available = PLATFORM_ADAPTER.capabilities().get('system_proxy') is True
    network_doctor = bool(
        doctor_cfg.get('enabled') is True
        and platform_proxy_available
        and network_doctor_panel.availability(doctor_cfg).get('available')
    )
    if doctor_cfg.get('enabled') is True and not platform_proxy_available:
        PLATFORM_ADAPTER.log_degradation(
            'network_doctor_hidden',
            f'macOS 网络医生在 {PLATFORM_ADAPTER.name} 上不可用；入口已隐藏',
        )
    return {
        'relationships': bool(relationships),
        'governance': bool(governance),
        'world': owner_world_source is not None,
        'network_doctor': network_doctor,
    }


def _read_skill_board_url(target):
    url_file = target.get('url_file')
    if url_file and url_file.exists():
        try:
            url = url_file.read_text(encoding='utf-8').strip()
            match = re.match(r'^https?://(?:127\.0\.0\.1|localhost):(\d+)', url)
            if match and _is_local_port_open(int(match.group(1))):
                return url
        except Exception:
            pass
    return ''


def launch_bridge_target(target_id):
    target = _configured_bridge_targets().get(target_id)
    if not target:
        return {'ok': False, 'error': '未知桥接入口'}, 404

    if target.get('url_file'):
        existing_url = _read_skill_board_url(target)
        if existing_url:
            return {'ok': True, 'name': target['name'], 'url': existing_url, 'status': 'already_running', 'open_browser': True}, 200
        cwd = target.get('cwd')
        if not cwd or not cwd.exists():
            return {'ok': False, 'error': f'{target["name"]} 项目目录不存在: {cwd}'}, 404
        launched, launch_error = PLATFORM_ADAPTER.launch_command(target['command'], cwd)
        if not launched:
            return {'ok': False, 'error': launch_error or '本地工具启动适配器不可用'}, 503
        deadline = time.time() + 15  # align with launcher.py wait_for_port(15s)
        while time.time() < deadline:
            url = _read_skill_board_url(target)
            if url:
                return {'ok': True, 'name': target['name'], 'url': url, 'status': 'started', 'open_browser': False}, 200
            time.sleep(0.4)
        return {'ok': True, 'name': target['name'], 'url': target['url'], 'status': 'starting', 'open_browser': False}, 200

    port = target.get('port')
    if port and _is_local_port_open(port):
        return {'ok': True, 'name': target['name'], 'url': target['url'], 'status': 'already_running', 'open_browser': True}, 200

    cwd = target.get('cwd')
    if not cwd or not cwd.exists():
        return {'ok': False, 'error': f'{target["name"]} 项目目录不存在: {cwd}'}, 404
    launched, launch_error = PLATFORM_ADAPTER.launch_command(target['command'], cwd)
    if not launched:
        return {'ok': False, 'error': launch_error or '本地工具启动适配器不可用'}, 503
    status = 'started' if port and _wait_for_local_port(port, timeout_seconds=12) else 'starting'
    return {
        'ok': True,
        'name': target['name'],
        'url': target['url'],
        'status': status,
        'open_browser': target.get('open_browser', True),
    }, 200


def get_bridge_status():
    status = {}
    for target_id, target in _configured_bridge_targets().items():
        if target.get('url_file'):
            status[target_id] = bool(_read_skill_board_url(target))
            continue
        port = target.get('port')
        status[target_id] = bool(port and _is_local_port_open(port))
    return status


def _network_label(ok, good_text='可达', bad_text='不可达'):
    return good_text if ok else bad_text


def _process_running(pattern):
    try:
        proc = subprocess.run(
            ['ps', '-axo', 'comm='],
            capture_output=True,
            text=True,
            timeout=3,
        )
        compiled = re.compile(pattern)
        return any(compiled.search(line.strip()) for line in (proc.stdout or '').splitlines())
    except Exception:
        return False


def _network_process_status(pattern):
    running = _process_running(pattern)
    return {
        'running': running,
        'label': _network_label(running, good_text='运行中', bad_text='未运行'),
        'health': 'good' if running else 'inactive',
    }


def _network_services():
    return PLATFORM_ADAPTER.network_services()


def _disable_system_proxy():
    return PLATFORM_ADAPTER.disable_system_proxy()


def _quit_app_bundle(bundle_id):
    return PLATFORM_ADAPTER.quit_app_bundle(bundle_id)


def _open_app_bundle(bundle_id, app_path=''):
    return PLATFORM_ADAPTER.open_app_bundle(bundle_id, app_path)


def _open_path_in_desktop(target):
    """Best-effort desktop open through the selected platform adapter."""
    return PLATFORM_ADAPTER.open_path(target)


def _network_profile_verge_tun_global(status):
    core_running = bool((status.get('verge_core') or {}).get('running'))
    service_running = bool((status.get('verge_service') or {}).get('running'))
    tun_enabled = bool((status.get('tun') or {}).get('enabled'))
    proxy = status.get('system_proxy') or {}
    proxy_enabled = bool(proxy.get('enabled'))
    checks = status.get('checks') or {}
    transport_ok = any((check or {}).get('health') == 'good' for check in checks.values())
    if core_running and service_running and (tun_enabled or proxy_enabled) and transport_ok:
        return {
            'enabled': True,
            'label': '入口就绪',
            'health': 'good',
            'summary': 'Clash Verge 正在接管流量（TUN 或系统代理）且真实传输通过；深度健康需运行网络医生',
            'deep_check_required': True,
        }
    missing = []
    if not core_running:
        missing.append('Verge core 未运行')
    if not service_running:
        missing.append('Verge service 未运行')
    if not (tun_enabled or proxy_enabled):
        missing.append('TUN 与 macOS 系统代理均未接管')
    if not transport_ok:
        missing.append('真实传输未通过')
    return {
        'enabled': False,
        'label': '需调整',
        'health': 'warn' if core_running or service_running or tun_enabled else 'bad',
        'summary': '；'.join(missing) if missing else '需运行网络医生',
        'deep_check_required': True,
    }


def _tun_status_from_ifconfig(output):
    active_interface = ''
    active_address = ''
    current_interface = ''
    for line in str(output or '').splitlines():
        interface_match = re.match(r'^\s*([A-Za-z0-9]+):\s', line)
        if interface_match:
            current_interface = interface_match.group(1)
            continue
        address_match = re.search(r'\binet\s+(198\.18\.\d+\.\d+)\b', line)
        if address_match and current_interface.startswith('utun'):
            active_interface = current_interface
            active_address = address_match.group(1)
            break
    if active_interface:
        return {
            'enabled': True,
            'label': '已启用',
            'health': 'good',
            'summary': f'{active_interface} · {active_address}',
            'interface': active_interface,
            'address': active_address,
        }
    return {
        'enabled': False,
        'label': '未检测',
        'health': 'inactive',
        'summary': '未检测到 198.18.x TUN',
        'interface': '',
        'address': '',
    }


def _read_tun_status():
    try:
        proc = subprocess.run(
            ['ifconfig'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return _tun_status_from_ifconfig(proc.stdout or '')
    except Exception:
        status = _tun_status_from_ifconfig('')
        status.update({
            'label': '需确认',
            'health': 'warn',
            'summary': '读取失败',
        })
        return status


def _proxy_value(raw):
    raw = str(raw or '').strip()
    if not raw:
        return ''
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _proxy_int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _parse_scutil_proxy(output):
    parsed = {}
    for line in str(output or '').splitlines():
        match = re.match(r'\s*([A-Za-z0-9]+)\s*:\s*(.*?)\s*$', line)
        if not match:
            continue
        parsed[match.group(1)] = _proxy_value(match.group(2))
    return parsed


def _proxy_channel(parsed, prefix):
    enabled = _proxy_int(parsed.get(f'{prefix}Enable')) == 1
    host = str(parsed.get(f'{prefix}Proxy') or '').strip()
    port = _proxy_int(parsed.get(f'{prefix}Port'))
    return {
        'enabled': enabled,
        'host': host if enabled else '',
        'port': port if enabled else None,
    }


def _system_proxy_from_scutil(output):
    parsed = _parse_scutil_proxy(output)
    channels = {
        'http': _proxy_channel(parsed, 'HTTP'),
        'https': _proxy_channel(parsed, 'HTTPS'),
        'socks': _proxy_channel(parsed, 'SOCKS'),
    }
    enabled_channels = [name for name, item in channels.items() if item['enabled']]
    ports = sorted({item['port'] for item in channels.values() if item['enabled'] and item['port']})
    hosts = sorted({item['host'] for item in channels.values() if item['enabled'] and item['host']})
    enabled = bool(enabled_channels)
    consistent = enabled and len(ports) == 1 and len(hosts) <= 1
    full = len(enabled_channels) == 3
    if full and consistent:
        label = '已启用'
        health = 'good'
        summary = '三路同端口'
    elif enabled:
        label = '部分启用'
        health = 'warn'
        summary = '需确认端口'
    else:
        label = '未启用'
        health = 'inactive'
        summary = '未检测到代理'
    return {
        'enabled': enabled,
        'label': label,
        'health': health,
        'summary': summary,
        'consistent': consistent,
        'primary_port': ports[0] if len(ports) == 1 else None,
        'ports': ports,
        'channels': channels,
    }


def _read_system_proxy():
    ok, output, error = PLATFORM_ADAPTER.system_proxy_output()
    if not ok:
        status = _system_proxy_from_scutil('')
        status.update({
            'label': '不可用',
            'health': 'inactive',
            'summary': error or '当前平台不支持系统代理读取',
        })
        return status
    return _system_proxy_from_scutil(output)


def _curl_proxy_args(system_proxy):
    channels = (system_proxy or {}).get('channels') or {}
    for key in ('https', 'http'):
        item = channels.get(key) or {}
        if item.get('enabled') and item.get('host') and item.get('port'):
            return ['--proxy', f"http://{item['host']}:{item['port']}"]
    socks = channels.get('socks') or {}
    if socks.get('enabled') and socks.get('host') and socks.get('port'):
        return ['--socks5-hostname', f"{socks['host']}:{socks['port']}"]
    return []


def _http_probe(url, system_proxy=None, timeout_seconds=8):
    cmd = [
        '/usr/bin/curl',
        '-I',
        '-L',
        '--max-time',
        str(timeout_seconds),
        '-sS',
        '-o',
        '/dev/null',
        '-w',
        '%{http_code}',
    ]
    cmd.extend(_curl_proxy_args(system_proxy))
    cmd.append(url)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 2,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - started) * 1000)
        return {
            'reachable': False,
            'label': '不可达',
            'health': 'bad',
            'latency_ms': elapsed,
            'error': 'timeout',
        }
    except Exception:
        return {
            'reachable': False,
            'label': '不可达',
            'health': 'bad',
            'latency_ms': None,
            'error': 'request failed',
        }
    elapsed = int((time.monotonic() - started) * 1000)
    match = re.search(r'(\d{3})\s*$', proc.stdout or '')
    status_code = int(match.group(1)) if match else None
    reachable = proc.returncode == 0 and bool(status_code)
    result = {
        'reachable': reachable,
        'label': _network_label(reachable),
        'health': 'good' if reachable else 'bad',
        'latency_ms': elapsed,
        'status_code': status_code,
    }
    if not reachable:
        result['error'] = 'no response' if not status_code else 'request failed'
    return result


def _tcp_probe(host, port, timeout_seconds=8):
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            pass
    except socket.timeout:
        elapsed = int((time.monotonic() - started) * 1000)
        return {
            'reachable': False,
            'label': '不可达',
            'health': 'bad',
            'latency_ms': elapsed,
            'error': 'timeout',
        }
    except OSError:
        elapsed = int((time.monotonic() - started) * 1000)
        return {
            'reachable': False,
            'label': '不可达',
            'health': 'bad',
            'latency_ms': elapsed,
            'error': 'connect failed',
        }
    elapsed = int((time.monotonic() - started) * 1000)
    return {
        'reachable': True,
        'label': '可达',
        'health': 'good',
        'latency_ms': elapsed,
    }


def get_network_status():
    config = load_config()
    doctor_config = config.get('network_doctor') if isinstance(config.get('network_doctor'), dict) else {}
    if not configured_ui_features(config).get('network_doctor'):
        return {'ok': True, 'enabled': False, 'doctor': network_doctor_panel.availability(doctor_config)}
    system_proxy = _read_system_proxy()
    tun_status = _read_tun_status()
    status = {
        'ok': True,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'verge_core': _network_process_status(r'(^|/)verge-mihomo$'),
        'verge_service': _network_process_status(r'(^|/)clash-verge-service$'),
        'tun': tun_status,
        'system_proxy': system_proxy,
        'checks': {
            'github': _http_probe('https://github.com', system_proxy),
            'feishu': _http_probe('https://open.feishu.cn', system_proxy),
            'imap_163': _tcp_probe('imap.163.com', 993),
        },
        'doctor': network_doctor_panel.availability(doctor_config),
    }
    status['profiles'] = {
        'verge_tun_global': _network_profile_verge_tun_global(status),
    }
    return status



_CHAIN_RESPONSIBILITIES = {'ai-owned', 'pi-gated', 'shared'}


def _normalize_chain_stage(raw):
    if not isinstance(raw, dict):
        return None
    key = str(raw.get('key') or '').strip()
    if not key:
        return None
    title = str(raw.get('title') or key).strip()
    responsibility = str(raw.get('responsibility') or 'shared').strip()
    if responsibility not in _CHAIN_RESPONSIBILITIES:
        responsibility = 'shared'
    kw_raw = raw.get('kw')
    if kw_raw is None:
        kw_raw = raw.get('keywords')
    kw = [str(item).strip().lower() for item in kw_raw] if isinstance(kw_raw, list) else []
    stage = {
        'key': key,
        'title': title,
        'responsibility': responsibility,
        'kw': [item for item in kw if item],
    }
    for field in ('role', 'question'):
        value = str(raw.get(field) or '').strip()
        if value:
            stage[field] = value
    return stage


def _normalize_chain(raw):
    if not isinstance(raw, dict):
        return None
    key = str(raw.get('key') or '').strip()
    if not key or not re.fullmatch(r'[A-Za-z0-9_.-]+', key):
        return None
    stages = []
    for item in raw.get('stages') if isinstance(raw.get('stages'), list) else []:
        stage = _normalize_chain_stage(item)
        if stage:
            stages.append(stage)
    if not stages:
        return None
    chain = {
        'key': key,
        'title': str(raw.get('title') or key).strip(),
        'mark': str(raw.get('mark') or key[:2].upper()).strip(),
        'sub': str(raw.get('sub') or '').strip(),
        'provider': str(raw.get('provider') or '').strip(),
        'stages': stages,
    }
    state_path = str(raw.get('state_path') or '').strip()
    if state_path:
        chain['state_path'] = state_path
    return chain


def configured_chains(config=None):
    config = config if isinstance(config, dict) else load_config()
    raw_chains = config.get('chains')
    if not isinstance(raw_chains, list):
        raw_chains = _DEFAULT_CHAINS
    chains = []
    seen = set()
    for raw in raw_chains:
        chain = _normalize_chain(raw)
        if not chain or chain['key'] in seen:
            continue
        chains.append(chain)
        seen.add(chain['key'])
    return chains


def _find_configured_chain(chain_id, config=None):
    chain_id = str(chain_id or '').strip()
    for chain in configured_chains(config):
        if chain.get('key') == chain_id:
            return chain
    return None


def _chain_state_path(chain, config):
    provider_id = str(chain.get('provider') or '').strip()
    if provider_id:
        provider = _find_dynamic_provider(provider_id, config)
        if provider and provider.get('invalid'):
            return None, provider.get('error') or f'{provider_id}: provider 无效'
        if provider:
            artifacts = provider.get('artifacts') if isinstance(provider.get('artifacts'), dict) else {}
            state_path = artifacts.get('state_path')
            if state_path:
                return Path(state_path), None
            return None, f'{provider_id}: state_path 缺失'

    raw_path = str(chain.get('state_path') or '').strip()
    if not raw_path and chain.get('key') == 'km':
        raw_path = str(config.get('km_chain_data') or _DEFAULTS['km_chain_data'])
    if not raw_path:
        return None, 'chain state_path/provider 未配置'
    candidate = Path(os.path.expanduser(raw_path))
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate, None


def _normalize_chain_state_stages(raw_stages):
    """Accept legacy stage maps and skill-state/v1 stage arrays."""
    if isinstance(raw_stages, dict):
        stage_map = {}
        stage_list = []
        for key, value in raw_stages.items():
            stage_key = str(key or '').strip()
            if not stage_key:
                continue
            item = dict(value) if isinstance(value, dict) else {'value': value}
            item.setdefault('key', stage_key)
            stage_map[stage_key] = item
            stage_list.append(item)
        return stage_map, stage_list
    if isinstance(raw_stages, list):
        stage_map = {}
        stage_list = []
        for value in raw_stages:
            if not isinstance(value, dict):
                continue
            stage_key = str(value.get('key') or '').strip()
            if not stage_key:
                continue
            item = dict(value)
            stage_map[stage_key] = item
            stage_list.append(item)
        return stage_map, stage_list
    return {}, []


def _normalize_chain_state_payload(data):
    payload = dict(data)
    stage_map, stage_list = _normalize_chain_state_stages(payload.get('stages'))
    payload['stage_map'] = stage_map
    payload['stage_list'] = stage_list
    payload.setdefault('schema_version', 'skill-state/v1')
    payload.setdefault('view_kind', 'chain')
    payload.setdefault('pending', [])
    payload.setdefault('needs_decision', [])
    payload.setdefault('invocations', [])
    if not isinstance(payload.get('health'), dict):
        ok = payload.get('ok')
        state = 'ok' if ok is not False else 'error'
        payload['health'] = {
            'state': state,
            'summary': str(payload.get('summary') or '').strip(),
            'kpis': payload.get('kpis') if isinstance(payload.get('kpis'), list) else [],
        }
    else:
        health = dict(payload['health'])
        if 'kpis' not in health and isinstance(payload.get('kpis'), list):
            health['kpis'] = payload.get('kpis')
        payload['health'] = health
    return payload


def load_chain_data(chain_id, config=None):
    """读配置链路的 state 快照；缺失或损坏时返回 ok:False，前端降级为纯卡片形态。"""
    config = config if isinstance(config, dict) else load_config()
    chain_id = str(chain_id or '').strip()
    if not chain_id or not re.fullmatch(r'[A-Za-z0-9_.-]+', chain_id):
        return {'ok': False, 'error': 'chain id 缺失或非法'}
    chain = _find_configured_chain(chain_id, config)
    if not chain:
        return {'ok': False, 'error': 'unknown chain id'}
    path, err = _chain_state_path(chain, config)
    if err:
        return {'ok': False, 'chain': chain, 'error': err}
    label = path.name or 'chain state'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'ok': False, 'chain': chain, 'error': f'{label} 不存在'}
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'chain': chain, 'error': f'{label} 无法解析: {exc}'}
    if not isinstance(data, dict):
        return {'ok': False, 'chain': chain, 'error': f'{label} 格式错误（需为对象）'}
    payload = _normalize_chain_state_payload(data)
    if not payload.get('stage_map'):
        return {'ok': False, 'chain': chain, 'error': f'{label} 格式错误（需含 stages 对象或数组）'}
    payload['ok'] = True
    payload['chain'] = chain
    sync_skill_decision_cards(payload)
    return payload


def load_km_chain_data(config=None):
    """兼容旧调用：读取配置中的 km 链。"""
    return load_chain_data('km', config)


def _configured_readonly_json_path(raw_path, config=None):
    """Resolve a configured read-only JSON path under open_allowed_roots."""
    config = config if isinstance(config, dict) else load_config()
    value = str(raw_path or '').strip()
    if not value:
        return None, 'JSON path 未配置'
    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = Path(os.path.realpath(candidate))
    allowed_roots = _configured_open_allowed_roots(config)
    if allowed_roots and not _path_in_allowed_roots(candidate, allowed_roots):
        return None, 'JSON path 不在 open_allowed_roots 内'
    if candidate.suffix.lower() != '.json':
        return None, 'JSON path 必须指向 .json 文件'
    return candidate, None



def _dynamic_board_lock(provider_id):
    with _DYNAMIC_BOARD_LOCKS_GUARD:
        lock = _DYNAMIC_BOARD_LOCKS.get(provider_id)
        if lock is None:
            lock = threading.Lock()
            _DYNAMIC_BOARD_LOCKS[provider_id] = lock
        return lock


def _dynamic_board_running(provider_id):
    lock = _dynamic_board_lock(provider_id)
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


def _dynamic_command(raw):
    if isinstance(raw, list) and raw and all(isinstance(part, (str, int, float)) for part in raw):
        return [str(part) for part in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            return shlex.split(raw)
        except ValueError:
            return []
    return []


def _dynamic_int(value, default, *, minimum=0, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _resolve_config_path(path_value, config, field_name):
    value = str(path_value or '').strip()
    if not value:
        return None, f'{field_name} 缺失'
    expanded = os.path.expanduser(value)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    target = Path(os.path.realpath(str(candidate)))
    allowed_roots = _configured_open_allowed_roots(config)
    if not _path_in_allowed_roots(target, allowed_roots):
        roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
        return None, f'{field_name} 不在可信根内: {value} (allowed roots: {roots_text})'
    return target, None


def _load_freshness_config(config):
    path, err = _resolve_config_path(config.get('freshness_config'), config, 'freshness_config')
    if err:
        return {}, err
    if not path.exists() or not path.is_file():
        return {}, f'freshness_config 不存在: {path}'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f'freshness_config 无法解析: {exc}'
    if not isinstance(data, dict):
        return {}, 'freshness_config 格式错误'
    return data, None


def _freshness_days_from_key(raw, config, provider_id):
    fallback = _dynamic_int(raw.get('freshness_days'), 7, minimum=0, maximum=3660)
    key = str(raw.get('freshness_key') or '').strip()
    if not key:
        return fallback, '', None

    table, err = _load_freshness_config(config)
    if err:
        return fallback, key, f'{provider_id}: {err}'
    thresholds = table.get('thresholds') if isinstance(table.get('thresholds'), dict) else {}
    entry = thresholds.get(key)
    if isinstance(entry, dict):
        value = entry.get('days')
    else:
        value = entry
    if value is None:
        return fallback, key, f'{provider_id}: freshness_key 未定义: {key}'
    return _dynamic_int(value, fallback, minimum=0, maximum=3660), key, None


def _resolve_dynamic_path(path_value, workdir, config, field_name):
    value = str(path_value or '').strip()
    if not value:
        return None, f'{field_name} 缺失'
    expanded = os.path.expanduser(value)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(workdir) / candidate
    target = Path(os.path.realpath(str(candidate)))
    allowed_roots = _configured_open_allowed_roots(config)
    if not _path_in_allowed_roots(target, allowed_roots):
        roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
        return None, f'{field_name} 不在可信根内: {value} (allowed roots: {roots_text})'
    if _reject_open_executable_target(target):
        return None, f'{field_name} 指向拒绝打开的可执行类型'
    return target, None


def _normalize_dynamic_provider(raw, config=None):
    config = config if isinstance(config, dict) else load_config()
    if not isinstance(raw, dict):
        return None, 'provider 必须是对象'
    provider_id = str(raw.get('id') or '').strip()
    if not provider_id or not re.fullmatch(r'[A-Za-z0-9_.-]+', provider_id):
        return None, 'provider id 缺失或非法'
    title = str(raw.get('title') or provider_id).strip()
    raw_workdir = str(raw.get('workdir') or '').strip()
    if not raw_workdir:
        return None, f'{provider_id}: workdir 缺失'
    workdir = Path(os.path.realpath(os.path.expanduser(raw_workdir)))
    allowed_roots = _configured_open_allowed_roots(config)
    if not _path_in_allowed_roots(workdir, allowed_roots):
        roots_text = ', '.join(str(root) for root in allowed_roots) or '未配置'
        return None, f'{provider_id}: workdir 不在可信根内: {raw_workdir} (allowed roots: {roots_text})'
    if not workdir.exists() or not workdir.is_dir():
        return None, f'{provider_id}: workdir 不存在或不是目录: {raw_workdir}'

    command = _dynamic_command(raw.get('command'))
    if not command:
        return None, f'{provider_id}: command 缺失或非法'
    if 'env' not in raw or not isinstance(raw.get('env'), dict):
        return None, f'{provider_id}: env 缺失或非法'
    env = {str(k): str(v) for k, v in raw.get('env', {}).items()}

    artifacts = raw.get('artifacts')
    if not isinstance(artifacts, dict):
        return None, f'{provider_id}: artifacts 缺失或非法'
    output_path, err = _resolve_dynamic_path(artifacts.get('output_path'), workdir, config, 'output_path')
    if err:
        return None, f'{provider_id}: {err}'
    state_path, err = _resolve_dynamic_path(artifacts.get('state_path'), workdir, config, 'state_path')
    if err:
        return None, f'{provider_id}: {err}'
    log_path, err = _resolve_dynamic_path(artifacts.get('log_path'), workdir, config, 'log_path')
    if err:
        return None, f'{provider_id}: {err}'

    surfaces = raw.get('surfaces')
    surfaces = [str(item).strip() for item in surfaces] if isinstance(surfaces, list) else []
    surfaces = [item for item in surfaces if item]
    freshness_days, freshness_key, freshness_err = _freshness_days_from_key(raw, config, provider_id)
    if freshness_err:
        return None, freshness_err
    return {
        'id': provider_id,
        'title': title,
        'workdir': workdir,
        'command': command,
        'env': env,
        'timeout_seconds': _dynamic_int(raw.get('timeout_seconds'), 300, minimum=1, maximum=7200),
        'freshness_days': freshness_days,
        'freshness_key': freshness_key,
        'surfaces': surfaces,
        'artifacts': {
            'output_path': output_path,
            'state_path': state_path,
            'log_path': log_path,
            'stdout_excerpt_chars': _dynamic_int(artifacts.get('stdout_excerpt_chars'), 2000, minimum=0, maximum=20000),
            'stderr_excerpt_chars': _dynamic_int(artifacts.get('stderr_excerpt_chars'), 2000, minimum=0, maximum=20000),
        },
    }, None


def _configured_dynamic_providers(config=None):
    config = config if isinstance(config, dict) else load_config()
    raw_providers = config.get('dynamic_boards')
    if not isinstance(raw_providers, list):
        raw_providers = []
    providers = []
    seen = set()
    for raw in raw_providers:
        provider, err = _normalize_dynamic_provider(raw, config)
        if provider and provider['id'] not in seen:
            providers.append(provider)
            seen.add(provider['id'])
        else:
            provider_id = raw.get('id') if isinstance(raw, dict) else ''
            providers.append({
                'id': str(provider_id or 'invalid-provider'),
                'title': str(provider_id or 'Invalid provider'),
                'invalid': True,
                'error': err or 'provider 重复或非法',
            })
    return providers


def _find_dynamic_provider(provider_id, config=None):
    provider_id = str(provider_id or '').strip()
    for provider in _configured_dynamic_providers(config):
        if provider.get('id') == provider_id:
            return provider
    return None


def _read_dynamic_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f'state 无法解析: {exc}'
    if not isinstance(data, dict):
        return None, 'state 格式错误'
    return data, None


def _parse_dynamic_datetime(value):
    text = str(value or '').strip()
    if not text:
        return None
    candidates = [text, text.replace('Z', '+00:00')]
    if re.match(r'^\d{4}-\d{2}-\d{2} ', text):
        candidates.append(text.replace(' ', 'T', 1))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return parsed
        except ValueError:
            pass
    for fmt in ('%Y-%m-%d %H:%M:%S %z', '%Y-%m-%d %H:%M:%S'):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return parsed
        except ValueError:
            pass
    return None


def _dynamic_generated_at(provider, state):
    generated_at = state.get('generated_at') if isinstance(state, dict) else None
    if generated_at:
        return str(generated_at), 'state'
    output_path = provider['artifacts']['output_path']
    try:
        return datetime.fromtimestamp(output_path.stat().st_mtime).astimezone().isoformat(timespec='seconds'), 'mtime'
    except OSError:
        return None, None


def _dynamic_provider_status(provider):
    if provider.get('invalid'):
        return {
            'id': provider.get('id'),
            'title': provider.get('title'),
            'ok': False,
            'running': False,
            'is_stale': True,
            'last_error': provider.get('error'),
        }
    artifacts = provider['artifacts']
    state, state_error = _read_dynamic_state(artifacts['state_path'])
    generated_at, generated_source = _dynamic_generated_at(provider, state)
    parsed_at = _parse_dynamic_datetime(generated_at)
    age_days = None
    if parsed_at:
        age_days = round((datetime.now(parsed_at.tzinfo) - parsed_at).total_seconds() / 86400, 2)
    output_exists = artifacts['output_path'].exists()
    state_exists = artifacts['state_path'].exists()
    is_stale = True
    if age_days is not None:
        is_stale = age_days > provider['freshness_days']
    elif output_exists:
        is_stale = False
    last = _DYNAMIC_BOARD_LAST_RESULTS.get(provider['id'], {})
    with _DYNAMIC_BOARD_AUTO_RUNS_GUARD:
        last_auto = _DYNAMIC_BOARD_AUTO_RUNS.get(provider['id'])
    return {
        'id': provider['id'],
        'title': provider['title'],
        'ok': state_error is None,
        'running': _dynamic_board_running(provider['id']),
        'is_stale': is_stale,
        'freshness_days': provider['freshness_days'],
        'freshness_key': provider.get('freshness_key') or '',
        'generated_at': generated_at,
        'generated_at_source': generated_source,
        'age_days': age_days,
        'summary': state.get('summary') if isinstance(state, dict) else '',
        'sources': state.get('sources') if isinstance(state, dict) and isinstance(state.get('sources'), list) else [],
        'surfaces': provider['surfaces'],
        'last_error': last.get('error') or state_error,
        'last_run_at': last.get('completed_at'),
        'last_auto_run_at': last_auto.get('attempted_at') if isinstance(last_auto, dict) else '',
        'auto_run_debounce_seconds': DYNAMIC_BOARD_AUTO_DEBOUNCE_SECONDS,
        'artifacts': {
            'output_path': str(artifacts['output_path']),
            'state_path': str(artifacts['state_path']),
            'log_path': str(artifacts['log_path']),
            'output_exists': output_exists,
            'state_exists': state_exists,
            'log_exists': artifacts['log_path'].exists(),
        },
    }


def get_dynamic_boards(config=None):
    providers = _configured_dynamic_providers(config)
    return {'ok': True, 'providers': [_dynamic_provider_status(provider) for provider in providers]}


def _dynamic_auto_run_debounce(provider_id):
    now_monotonic = time.monotonic()
    now_text = datetime.now().astimezone().isoformat(timespec='seconds')
    with _DYNAMIC_BOARD_AUTO_RUNS_GUARD:
        last = _DYNAMIC_BOARD_AUTO_RUNS.get(provider_id)
        if isinstance(last, dict):
            elapsed = now_monotonic - float(last.get('monotonic') or 0)
            if elapsed < DYNAMIC_BOARD_AUTO_DEBOUNCE_SECONDS:
                return {
                    'debounced': True,
                    'attempted_at': last.get('attempted_at') or '',
                    'retry_after_seconds': int(DYNAMIC_BOARD_AUTO_DEBOUNCE_SECONDS - elapsed),
                }
        _DYNAMIC_BOARD_AUTO_RUNS[provider_id] = {
            'monotonic': now_monotonic,
            'attempted_at': now_text,
        }
    return {'debounced': False, 'attempted_at': now_text, 'retry_after_seconds': 0}


def _dynamic_excerpt(text, max_chars):
    if not text or max_chars <= 0:
        return ''
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _write_dynamic_run_log(provider, result):
    log_path = provider['artifacts']['log_path']
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"provider: {provider['id']}",
            f"started_at: {result.get('started_at')}",
            f"completed_at: {result.get('completed_at')}",
            f"cwd: {provider['workdir']}",
            f"returncode: {result.get('returncode')}",
            f"status: {result.get('status')}",
            "",
            "stdout:",
            result.get('stdout_excerpt') or '',
            "",
            "stderr:",
            result.get('stderr_excerpt') or '',
            "",
        ]
        log_path.write_text('\n'.join(lines), encoding='utf-8')
    except OSError as exc:
        result['log_error'] = str(exc)


def _run_dynamic_provider(provider, *, auto=False):
    if auto:
        debounce = _dynamic_auto_run_debounce(provider['id'])
        if debounce.get('debounced'):
            return {
                'ok': True,
                'skipped': True,
                'reason': 'debounced',
                'provider': _dynamic_provider_status(provider),
                'auto_run': debounce,
            }, 200
    lock = _dynamic_board_lock(provider['id'])
    if not lock.acquire(blocking=False):
        if auto:
            return {
                'ok': True,
                'skipped': True,
                'reason': 'already_running',
                'provider': _dynamic_provider_status(provider),
            }, 200
        return {'ok': False, 'status': 'already_running', 'error': 'provider already running'}, 409
    started_at = datetime.now().astimezone().isoformat(timespec='seconds')
    started = time.monotonic()
    result = {
        'started_at': started_at,
        'status': 'running',
        'returncode': None,
        'stdout_excerpt': '',
        'stderr_excerpt': '',
    }
    try:
        env = os.environ.copy()
        env.update(provider['env'])
        proc = subprocess.run(
            provider['command'],
            cwd=str(provider['workdir']),
            env=env,
            capture_output=True,
            text=True,
            timeout=provider['timeout_seconds'],
        )
        result.update({
            'returncode': proc.returncode,
            'stdout_excerpt': _dynamic_excerpt(proc.stdout, provider['artifacts']['stdout_excerpt_chars']),
            'stderr_excerpt': _dynamic_excerpt(proc.stderr, provider['artifacts']['stderr_excerpt_chars']),
            'status': 'completed' if proc.returncode == 0 else 'error',
        })
        if proc.returncode != 0:
            result['error'] = f'command failed with exit code {proc.returncode}'
    except subprocess.TimeoutExpired as exc:
        result.update({
            'status': 'timeout',
            'error': f'command timed out after {provider["timeout_seconds"]}s',
            'stdout_excerpt': _dynamic_excerpt(exc.stdout or '', provider['artifacts']['stdout_excerpt_chars']),
            'stderr_excerpt': _dynamic_excerpt(exc.stderr or '', provider['artifacts']['stderr_excerpt_chars']),
        })
    except FileNotFoundError:
        result.update({'status': 'error', 'error': f'command not found: {provider["command"][0]}'})
    except Exception as exc:
        result.update({'status': 'error', 'error': str(exc)})
    finally:
        result['completed_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
        result['duration_ms'] = int((time.monotonic() - started) * 1000)
        _write_dynamic_run_log(provider, result)
        _DYNAMIC_BOARD_LAST_RESULTS[provider['id']] = {
            'completed_at': result['completed_at'],
            'status': result['status'],
            'error': result.get('error'),
        }
        lock.release()
    status = _dynamic_provider_status(provider)
    payload = {'ok': result['status'] == 'completed', 'provider': status, 'run': result}
    if result.get('error'):
        payload['error'] = result['error']
    return payload, (200 if payload['ok'] else 500)


def run_dynamic_board(provider_id, config=None, *, auto=False):
    provider = _find_dynamic_provider(provider_id, config)
    if not provider:
        return {'ok': False, 'error': 'unknown provider id'}, 404
    if provider.get('invalid'):
        return {'ok': False, 'error': provider.get('error') or 'invalid provider'}, 400
    return _run_dynamic_provider(provider, auto=auto)



GOVERNANCE_MATRIX_PATH = Path(__file__).resolve().parent.parent / 'governance' / 'matrix.json'
GOVERNANCE_PROBE_PATH = Path(__file__).resolve().parent.parent / 'governance' / 'matrix.probe.json'


def load_governance_matrix():
    """治理巡检矩阵（G1-G7 × 活跃工作区），数据为 state 类，由治理审计核验后更新。"""
    try:
        data = json.loads(GOVERNANCE_MATRIX_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'ok': False, 'error': 'matrix.json 不存在'}
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'error': f'matrix.json 无法解析: {exc}'}
    if not isinstance(data, dict) or not isinstance(data.get('rules'), list):
        return {'ok': False, 'error': 'matrix.json 格式错误（需含 rules 列表）'}
    return {'ok': True, **data}


def load_agent_mail_maintenance():
    """治理页「基建维护台账」数据源：仅委托读取显式配置的目录。

    薄封装——业务逻辑（读 maintenance.jsonl / 扫 inbox 孤儿死信 / 数 watcher runs、
    缺文件优雅降级）全在 agent_mail_maintenance.py 模块，本函数只做委托。"""
    config = load_config()
    settings = _integration_settings(config, 'agent_mail')
    home = _declared_integration_path(
        config,
        'agent_mail',
        'home',
        _DISABLED_INTEGRATION_ROOT / 'agent-mail',
    )
    if settings.get('enabled') is not True or not home.is_dir():
        return {'ok': True, 'enabled': False, 'events': [], 'counts': {}}
    try:
        return agent_mail_maintenance.load_maintenance_overview(home=home)
    except Exception as exc:  # noqa: BLE001 - 台账读取失败也不能拖垮 GET
        return {'ok': False, 'error': f'维护台账读取失败: {exc}'}


def load_governance_probe():
    """治理探针矩阵（生成态），只读展示；不得覆盖正式 matrix.json。"""
    try:
        data = json.loads(GOVERNANCE_PROBE_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'ok': False, 'error': 'matrix.probe.json 不存在'}
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'error': f'matrix.probe.json 无法解析: {exc}'}
    if not isinstance(data, dict) or not isinstance(data.get('rules'), list):
        return {'ok': False, 'error': 'matrix.probe.json 格式错误（需含 rules 列表）'}
    return {'ok': True, **data}


# ── 维护命令群其余部分已搬 maintenance_cli.py（单体手术第1批）——委托桩 ──

def archive_done_tasks(days=7):
    return maintenance_cli.archive_done_tasks(_maintenance_env(), days=days)


def _infer_card_labels(fm, *, project='', path=''):
    return maintenance_cli._infer_card_labels(_maintenance_env(), fm, project=project, path=path)


def _is_novel_build(fm):
    return maintenance_cli._is_novel_build(fm)


def _build_prior_art_prompt(fm):
    return maintenance_cli._build_prior_art_prompt(fm)


def infer_responsibility_labels(dry_run=True):
    return maintenance_cli.infer_responsibility_labels(_maintenance_env(), dry_run=dry_run)


def spawn_prior_art_cards(dry_run=False, project='个人调度'):
    return maintenance_cli.spawn_prior_art_cards(_maintenance_env(), dry_run=dry_run, project=project)


def spawn_prior_art_for_card(path):
    return maintenance_cli.spawn_prior_art_for_card(_maintenance_env(), path)


def detect_compression_candidates(min_count=3, dry_run=True):
    return maintenance_cli.detect_compression_candidates(_maintenance_env(), min_count=min_count, dry_run=dry_run)


def sweep_auto_accept_reviews(dry_run=False):
    return maintenance_cli.sweep_auto_accept_reviews(_maintenance_env(), dry_run=dry_run)


# ── KAN-200 人闸验收超时代收 ─────────────────────────────────────────────

def _acceptance_timeout_hours(config=None):
    """验收超时阈值（小时），配置键 acceptance.timeout_hours，默认 48。"""
    source = config if isinstance(config, dict) else load_config()
    acc = source.get('acceptance') if isinstance(source.get('acceptance'), dict) else {}
    try:
        hours = float(acc.get('timeout_hours', 48))
    except (TypeError, ValueError):
        hours = 48.0
    return hours if hours > 0 else 48.0


def _review_age_hours(fm):
    """卡在 review 停了多少小时。优先用 review_since(ISO)，回退 status_changed_at / updated(纯日期)。
    返回 (hours, source)；解析不出返回 (None, '')。"""
    for field, src in (('review_since', 'review_since'),
                       ('status_changed_at', 'status_changed_at'),
                       ('updated', 'updated')):
        raw = str(fm.get(field) or '').strip()
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            try:
                dt = datetime.strptime(raw, '%Y-%m-%d')
            except ValueError:
                continue
        now = datetime.now().astimezone() if dt.tzinfo else datetime.now()
        delta = now - dt
        return delta.total_seconds() / 3600.0, src
    return None, ''


def _claude_cmd_from_config(config=None):
    """从 config tools.claude 解析出 claude 命令 list（CLI 场景 CLI_COMMANDS 未初始化时用）。"""
    source = config if isinstance(config, dict) else load_config()
    tools = source.get('tools') if isinstance(source.get('tools'), dict) else {}
    claude_cfg = tools.get('claude') if isinstance(tools.get('claude'), dict) else {}
    cmd_str = claude_cfg.get('command') or ''
    if not cmd_str:
        return None
    return parse_command_string(cmd_str)


def _append_attention_gate_review_note(path, task_id, reason):
    """人闸 review 判 fail 时，把拒收意见追加进卡片正文（进 Owner 视野，不静默）。"""
    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    note = (
        f"\n\n<!-- attention_gate-review {today} -->\n\n"
        f"## 人闸 review 意见（代收被拒）\n\n"
        f"- 时间：{today}\n"
        f"- 裁决：fail（未通过真 review，留在 review 等 Owner）\n"
        f"- 理由（可证伪，带证据指针）：{str(reason).strip()}\n"
    )
    data, err = _read_task_file(path)
    if err or not data:
        return False
    new_body = (data.get('body') or '') + note
    ok, _ = update_task_body(path, new_body)
    return ok


def sweep_attention_gate_accept(dry_run=False, config=None, logger=None):
    """KAN-200：每日扫超时未验收的 review 卡 → 人闸真 review 后代收/打回。

    流程（每张卡）：
      1. 只看 status==review 的卡。
      2. 资格红线：沿用 _is_auto_acceptance_eligible（ai-owned + reversible/read-only，
         非执行前 gate；缺字段一律跳过）——不可逆/pi-gated/决策类永不代收，留 Owner。
      3. 超时判定：review 停留 ≥ acceptance.timeout_hours（默认 48h）才处理，未超时跳过。
      4. 真 review：跑 claude CLI 逐条核完成标准 → pass/fail。
         - pass → status:done + accepted_by:attention_gate + class:人闸验收 落账。
         - fail → 留 review + 追加拒收意见 + acceptance_flag:attention_gate-rejected（进 Owner 视野）。
         - review 没跑成（CLI 缺失/超时/非零退出）→ 视为无法裁决，不代收，留 Owner。

    返回 rows: [{path, task_id, action, verdict, reason, age_hours}]。
    dry_run 只报「假如现在执行会代收/打回哪些」，不写盘、不跑 claude。
    """
    log = logger or (lambda *_a, **_k: None)
    cfg = config if isinstance(config, dict) else load_config()
    timeout_hours = _acceptance_timeout_hours(cfg)
    claude_cmd = _claude_cmd_from_config(cfg)
    rows = []
    for doc in scan_all():
        if str(doc.get('status') or '').strip().lower() != 'review':
            continue
        path = doc.get('path')
        if not path:
            continue
        fpath = REPO_ROOT / path
        if not fpath.exists():
            continue
        try:
            fm, _ = extract_frontmatter(fpath.read_text(encoding='utf-8'))
        except OSError:
            continue
        # 资格红线：不合格（含缺字段/pi-gated/执行前 gate）一律不碰。
        if not _is_auto_acceptance_eligible(fm):
            continue
        # 已被人闸打回过的卡不重复跑（等 Owner 处理）。
        if str(fm.get('acceptance_flag') or '').strip().lower() == 'attention_gate-rejected':
            continue
        age_hours, age_src = _review_age_hours(fm)
        if age_hours is None or age_hours < timeout_hours:
            continue
        task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
        title = str(fm.get('title') or '').strip()
        if dry_run:
            rows.append({'path': path, 'task_id': task_id, 'action': 'would-review',
                         'verdict': None, 'reason': f'超时 {age_hours:.1f}h(源:{age_src})≥{timeout_hours}h，将跑真 review',
                         'age_hours': age_hours})
            continue
        # 跑真 review（需完整正文）。
        data, err = _read_task_file(path)
        body = (data.get('body') if data else '') or ''
        if not str(fm.get('workdir') or '').strip():
            review_cwd, cwd_error = fpath.parent.resolve(), None
        else:
            resolved_workdir, workdir_error = resolve_workdir(fm.get('workdir'), path, cfg)
            review_cwd, cwd_error = _coerce_workdir_to_cwd(resolved_workdir, cfg) if not workdir_error else (None, workdir_error)
        if cwd_error or not review_cwd or not Path(review_cwd).exists():
            rows.append({'path': path, 'task_id': task_id, 'action': 'review-failed',
                         'verdict': None, 'reason': cwd_error or 'review workdir missing', 'age_hours': age_hours})
            continue
        result = {
            'ok': False,
            'error': 'optional reviewer capability is not installed in the public core',
        }
        if not result.get('ok'):
            log(f"  [人闸验收] {task_id} review 未跑成，留 Owner：{result.get('error')}")
            rows.append({'path': path, 'task_id': task_id, 'action': 'review-failed',
                         'verdict': None, 'reason': result.get('error') or '', 'age_hours': age_hours})
            continue
        verdict = result.get('verdict')
        reason = result.get('reason') or ''
        if verdict == 'pass':
            if update_frontmatter_field(path, 'status', 'done', _suppress_decision_log=True)[0]:
                _stamp_acceptance(path, 'reviewer', cfg)
                _record_attention_gate_acceptance(fm, reason)
                log(f"  [人闸验收] {task_id} 真 review 通过 → 代收 done")
                rows.append({'path': path, 'task_id': task_id, 'action': 'accepted',
                             'verdict': 'pass', 'reason': reason, 'age_hours': age_hours})
        else:
            _append_attention_gate_review_note(path, task_id, reason)
            update_frontmatter_field(path, 'acceptance_flag', 'attention_gate-rejected', _suppress_decision_log=True)
            log(f"  [人闸验收] {task_id} 真 review 未过 → 留 review + 打回标记")
            rows.append({'path': path, 'task_id': task_id, 'action': 'rejected',
                         'verdict': 'fail', 'reason': reason, 'age_hours': age_hours})
    return rows


def backfill_review_since(dry_run=False):
    """存量 review 卡回填 review_since：用 git log 找该文件最近一次 status:review 变更时间；
    找不到用卡片 updated 兜底，并在值旁注来源(git|updated)。已有 review_since 的跳过。
    返回 rows: [(path, value, source)]。"""
    rows = []
    for doc in scan_all():
        if str(doc.get('status') or '').strip().lower() != 'review':
            continue
        path = doc.get('path')
        if not path:
            continue
        fpath = REPO_ROOT / path
        if not fpath.exists():
            continue
        try:
            fm, _ = extract_frontmatter(fpath.read_text(encoding='utf-8'))
        except OSError:
            continue
        if str(fm.get('review_since') or '').strip():
            continue
        value, source = _git_last_review_transition(path)
        if not value:
            value = str(fm.get('updated') or '').strip()
            source = 'updated'
        if not value:
            continue
        stamped = f"{value} ({source})"
        rows.append((path, value, source))
        if not dry_run:
            update_frontmatter_field(path, 'review_since', stamped, _suppress_decision_log=True)
    return rows


def _git_last_review_transition(path):
    """用 git log 找某卡文件最近一次引入 `status: review` 的提交时间(ISO)。
    返回 (iso_datetime, 'git') 或 ('', '')。"""
    try:
        proc = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'log', '--format=%H %cI', '--', path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return '', ''
    if proc.returncode != 0:
        return '', ''
    commits = [ln.split(' ', 1) for ln in proc.stdout.splitlines() if ln.strip()]
    # commits 已按新→旧；找最近一次「该提交把 status 改成 review」。
    for entry in commits:
        if len(entry) != 2:
            continue
        sha, cdate = entry[0], entry[1]
        try:
            diff = subprocess.run(
                ['git', '-C', str(REPO_ROOT), 'show', f'{sha}', '--', path],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if diff.returncode != 0:
            continue
        if re.search(r'^\+\s*status:\s*review\s*$', diff.stdout, re.MULTILINE):
            return cdate, 'git'
    return '', ''


def _resolve_active_task_card_path(path_value):
    candidate, err = _safe_repo_path(path_value)
    if err:
        return None, '', err, 400
    if candidate.suffix.lower() != '.md':
        return None, '', '仅支持任务卡文件', 400
    if not candidate.exists() or not candidate.is_file():
        return None, '', '文件不存在', 404

    try:
        rel_path = str(candidate.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return None, '', '非法路径', 400

    for doc in scan_all():
        try:
            if (REPO_ROOT / doc.get('path', '')).resolve() == candidate:
                return candidate, rel_path, '', 200
        except (OSError, TypeError, ValueError):
            continue
    return None, rel_path, '路径不在 scan_dirs 范围内或不是活动任务卡', 403


def archive_task_card(path_value):
    """把单张活动任务卡软删到所在项目 .archive/，不提供硬删除能力。"""
    with MARKDOWN_WRITE_LOCK:
        src, rel_path, err, status = _resolve_active_task_card_path(path_value)
        if err:
            return {'ok': False, 'error': err}, status
        archive_dir = src.parent / '.archive'
        dest = archive_dir / src.name
        if dest.exists():
            return {'ok': False, 'error': '归档目标已存在'}, 409
        try:
            archive_dir.mkdir(exist_ok=True)
            os.replace(src, dest)
            invalidate_scan_cache(src)
            invalidate_scan_cache(dest)
        except OSError as exc:
            return {'ok': False, 'error': f'归档失败: {exc}'}, 500
        archived_rel = str(dest.relative_to(REPO_ROOT.resolve()))
        lineage_ok = _lineage_record_archive(rel_path, archived_rel)
        result = {
            'ok': True,
            'path': rel_path,
            'archived_path': archived_rel,
        }
        if not lineage_ok:
            result['lineage_warning'] = '血缘台账写入失败'
        return result, 200


TEAM_KANBAN_SOURCE_PREFIX = 'team-kanban/'
TEAM_KANBAN_ACTIVE_STATUSES = {'todo', 'in-progress', 'review'}


def _team_sync_config(config=None):
    source = config if isinstance(config, dict) else load_config()
    raw_sync = source.get('team_sync') if isinstance(source.get('team_sync'), dict) else {}
    sync = dict(_DEFAULTS['team_sync'])
    sync.update(raw_sync)
    sync['_owner_member'] = role_policy.member_for_role(source.get('roles'), 'owner')
    sync['team_kanban_url'] = str(source.get('team_kanban_url') or _DEFAULTS['team_kanban_url']).strip()
    return sync


def _team_target_user(sync_cfg):
    return str(sync_cfg.get('target_user') or sync_cfg.get('_owner_member') or '').strip()


def _team_pointer_project(sync_cfg):
    value = str(sync_cfg.get('pointer_project') or sync_cfg.get('personal_project') or '个人调度').strip()
    return value or '个人调度'


def _team_handoff_default_project(sync_cfg):
    value = str(
        sync_cfg.get('handoff_target_project')
        or sync_cfg.get('target_team_project')
        or sync_cfg.get('target_project')
        or ''
    ).strip()
    return value


def _team_sync_state_path(sync_cfg, key):
    default_value = _DEFAULTS['team_sync'].get(key, '')
    raw_value = str(sync_cfg.get(key) or default_value).strip()
    path = Path(os.path.expanduser(raw_value))
    if not path.is_absolute():
        path = REPO_ROOT / path
    resolved = path.resolve()
    repo_root = REPO_ROOT.resolve()
    if not _path_is_relative_to(resolved, repo_root):
        fallback = (REPO_ROOT / default_value).resolve()
        return fallback
    return resolved


def _team_sync_optional_path(sync_cfg, key):
    raw_value = str(sync_cfg.get(key) or '').strip()
    if not raw_value:
        return None
    path = Path(os.path.expanduser(raw_value))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        return path.resolve()
    except OSError:
        return path


def _team_int(value, default, minimum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(minimum, result)
    return result


def _team_sync_auth_headers(sync_cfg):
    token = str(sync_cfg.get('token') or '').strip()
    cookie = str(sync_cfg.get('cookie') or '').strip()
    auth_type = str(sync_cfg.get('auth_type') or '').strip().lower()
    headers = {'Accept': 'application/json'}
    if auth_type == 'cookie':
        if not cookie:
            return None
        headers['Cookie'] = cookie
        return headers
    if token:
        header_name = str(sync_cfg.get('token_header') or _DEFAULTS['team_sync']['token_header']).strip()
        headers[header_name or _DEFAULTS['team_sync']['token_header']] = token
        return headers
    if cookie:
        headers['Cookie'] = cookie
        return headers
    return None


def _team_sync_source(sync_cfg):
    source = str(sync_cfg.get('source') or '').strip().lower().replace('-', '_')
    if source in ('local', 'local_repo', 'local_files'):
        return 'local_repo'
    if source in ('remote', 'remote_api', 'api'):
        return 'remote_api'
    if str(sync_cfg.get('local_repo_path') or '').strip():
        return 'local_repo'
    return 'remote_api'


def _team_local_repo_path(sync_cfg):
    raw_value = str(sync_cfg.get('local_repo_path') or '').strip()
    if not raw_value:
        return None, 'missing_local_repo'
    path = Path(os.path.expanduser(raw_value))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        resolved = path.resolve()
    except OSError:
        return None, 'missing_local_repo'
    if not resolved.exists() or not resolved.is_dir():
        return None, 'missing_local_repo'
    return resolved, ''


def _team_git_last_commit(repo_path):
    try:
        proc = subprocess.run(
            ['git', '-C', str(repo_path), 'log', '-1', '--format=%cI'],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return None, f'git_error:{exc}'
    if proc.returncode != 0:
        return None, 'git_log_failed'
    stamp = (proc.stdout or '').strip()
    parsed = _parse_dynamic_datetime(stamp)
    return parsed, '' if parsed else 'git_log_empty'


def _team_read_json_file(path):
    if not path:
        return None, 'missing_path'
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, json.JSONDecodeError):
        return None, 'invalid'
    return data if isinstance(data, dict) else None, '' if isinstance(data, dict) else 'invalid'


def _team_manifest_status(sync_cfg):
    path = _team_sync_optional_path(sync_cfg, 'sync_task_manifest_path')
    if not path:
        return '', ''
    data, err = _team_read_json_file(path)
    if err or not data:
        return '', err
    return str(data.get('status') or '').strip().upper(), ''


def _team_runtime_finished_at(data):
    if not isinstance(data, dict):
        return None
    for key in ('run_finished_at', 'finished_at', 'generated_at'):
        parsed = _parse_dynamic_datetime(data.get(key))
        if parsed:
            return parsed
    return None


def _team_runtime_failed(data):
    if not isinstance(data, dict):
        return False
    if data.get('ok') is False:
        return True
    if str(data.get('status') or '').lower() in {'failed', 'error'}:
        return True
    actions = data.get('actions') if isinstance(data.get('actions'), dict) else {}
    if actions.get('needs_attention') is True:
        return True
    attention = data.get('attention') if isinstance(data.get('attention'), dict) else {}
    if attention.get('required') is True:
        return True
    return False


def _team_sync_freshness(sync_cfg, repo_path=None, now=None):
    stale_days = _team_int(sync_cfg.get('stale_days'), _DEFAULTS['team_sync']['stale_days'], minimum=0)
    now_dt = now or datetime.now().astimezone()
    manifest_status, manifest_err = _team_manifest_status(sync_cfg)
    status_path = _team_sync_optional_path(sync_cfg, 'sync_state_path')
    data, state_err = _team_read_json_file(status_path) if status_path else (None, 'missing_path')

    info = {
        'source': 'none',
        'stale_days': stale_days,
        'age_days': None,
        'is_stale': False,
        'reason': '',
        'last_checked_at': '',
        'task_status': manifest_status,
    }
    if manifest_status in {'DISABLED', 'PAUSED'}:
        info.update({
            'source': 'sync_task_manifest',
            'is_stale': True,
            'reason': f'task_{manifest_status.lower()}',
        })
        return info

    if data:
        finished = _team_runtime_finished_at(data)
        age_days = None
        if finished:
            age_days = max(0, (now_dt - finished.astimezone()).total_seconds() / 86400)
        failed = _team_runtime_failed(data)
        info.update({
            'source': 'sync_state',
            'last_checked_at': finished.isoformat(timespec='seconds') if finished else '',
            'age_days': age_days,
            'is_stale': failed or age_days is None or age_days > stale_days,
            'reason': 'last_run_failed' if failed else 'last_run_missing_time' if age_days is None else 'last_run_too_old' if age_days > stale_days else '',
        })
        return info

    if status_path and state_err:
        info.update({
            'source': 'sync_state',
            'is_stale': True,
            'reason': f'sync_state_{state_err}',
        })
        return info

    if repo_path and (Path(repo_path) / '.git').exists():
        commit_at, git_err = _team_git_last_commit(repo_path)
        if commit_at:
            age_days = max(0, (now_dt - commit_at.astimezone()).total_seconds() / 86400)
            info.update({
                'source': 'git_commit',
                'last_checked_at': commit_at.isoformat(timespec='seconds'),
                'age_days': age_days,
                'is_stale': age_days > stale_days,
                'reason': 'git_commit_too_old' if age_days > stale_days else '',
            })
        elif git_err:
            info.update({
                'source': 'git_commit',
                'is_stale': True,
                'reason': git_err,
            })
    elif manifest_err:
        info['reason'] = f'manifest_{manifest_err}'
    return info


def _team_local_config(repo_path):
    config_path = Path(repo_path) / '.kanban.config.json'
    try:
        data = json.loads(config_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _team_local_list(value, default):
    raw = value if value not in (None, '') else default
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item or '').strip()]
    return list(default)


def _team_local_should_skip(fpath, repo_path, skip_patterns):
    try:
        rel = str(Path(fpath).relative_to(repo_path))
    except ValueError:
        rel = Path(fpath).name
    name = Path(fpath).name
    for pat in skip_patterns:
        if fnmatch(name, pat) or fnmatch(rel, pat):
            return True
    return False


def _team_local_project_name(repo_path, scan_root, fpath):
    try:
        rel_repo = Path(fpath).relative_to(repo_path)
    except ValueError:
        rel_repo = Path(fpath).name
    parts = getattr(rel_repo, 'parts', ())
    if len(parts) >= 3 and parts[0] == 'project':
        return parts[1]
    try:
        rel_scan = Path(fpath).relative_to(scan_root)
    except ValueError:
        rel_scan = Path(fpath).name
    scan_parts = getattr(rel_scan, 'parts', ())
    if len(scan_parts) >= 2:
        return scan_parts[0]
    return Path(scan_root).name if Path(scan_root).name != Path(repo_path).name else ''


def load_local_team_kanban_data(config=None):
    sync_cfg = _team_sync_config(config)
    repo_path, err = _team_local_repo_path(sync_cfg)
    if err:
        return None, {'ok': False, 'skipped': True, 'reason': err}

    local_config = _team_local_config(repo_path)
    scan_dirs = _team_local_list(sync_cfg.get('local_scan_dirs'), local_config.get('scan_dirs') or ['project'])
    skip_patterns = _team_local_list(local_config.get('skip_patterns'), _DEFAULTS.get('skip_patterns') or [])
    tasks = []
    for scan_dir in scan_dirs:
        scan_root = (repo_path / str(scan_dir)).resolve()
        if scan_root != repo_path and not _path_is_relative_to(scan_root, repo_path):
            continue
        if not scan_root.exists() or not scan_root.is_dir():
            continue
        for root, dirs, files in os.walk(scan_root):
            dirs[:] = [x for x in dirs if not x.startswith('.') and x != 'vendor']
            for filename in files:
                if not filename.endswith('.md'):
                    continue
                fpath = Path(root) / filename
                if _team_local_should_skip(fpath, repo_path, skip_patterns):
                    continue
                try:
                    content = fpath.read_text(encoding='utf-8')
                except OSError:
                    continue
                if '{' in content[:200]:
                    continue
                fm, _fm_block = extract_frontmatter(content)
                if not fm:
                    continue
                rel_path = str(fpath.relative_to(repo_path))
                task = dict(fm)
                task.setdefault('path', rel_path)
                task.setdefault('filename', filename)
                task.setdefault('project', _team_local_project_name(repo_path, scan_root, fpath))
                tasks.append(task)

    return {
        'tasks': tasks,
        'source': 'team-local-repo',
        'repo_path': str(repo_path),
    }, {
        'ok': True,
        'skipped': False,
        'source': 'local_repo',
        'path': str(repo_path),
        'tasks': len(tasks),
    }


def fetch_team_kanban_data(config=None):
    sync_cfg = _team_sync_config(config)
    if not sync_cfg.get('enabled'):
        return None, {'ok': False, 'skipped': True, 'reason': 'disabled'}
    if _team_sync_source(sync_cfg) == 'local_repo':
        return load_local_team_kanban_data(config)
    team_url = sync_cfg.get('team_kanban_url') or ''
    if not team_url:
        return None, {'ok': False, 'skipped': True, 'reason': 'missing_url'}
    headers = _team_sync_auth_headers(sync_cfg)
    if not headers:
        return None, {'ok': False, 'skipped': True, 'reason': 'missing_credentials'}
    timeout = sync_cfg.get('timeout_seconds', _DEFAULTS['team_sync']['timeout_seconds'])
    try:
        timeout = max(1, float(timeout))
    except (TypeError, ValueError):
        timeout = float(_DEFAULTS['team_sync']['timeout_seconds'])
    api_url = urljoin(team_url.rstrip('/') + '/', 'api/data')
    request = urllib.request.Request(api_url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = resp.read(8 * 1024 * 1024)
        data = json.loads(payload.decode('utf-8'))
    except Exception:
        return None, {'ok': False, 'skipped': True, 'reason': 'unreachable'}
    if not isinstance(data, dict):
        return None, {'ok': False, 'skipped': True, 'reason': 'invalid_payload'}
    return data, {'ok': True, 'skipped': False, 'url': api_url}


def _team_text(value):
    if value is None:
        return ''
    if isinstance(value, dict):
        for key in ('name', 'display_name', 'username', 'user', 'id', 'title'):
            if value.get(key):
                return str(value.get(key)).strip()
        return ''
    if isinstance(value, list):
        values = [_team_text(item) for item in value]
        return ', '.join(item for item in values if item)
    return str(value).strip()


def _team_values(task, *keys):
    values = []
    for key in keys:
        raw = task.get(key)
        if isinstance(raw, list):
            values.extend(_team_text(item) for item in raw)
        else:
            values.append(_team_text(raw))
    return [item for item in values if item]


def _team_name_matches(values, target_user):
    target = str(target_user or '').strip().lower()
    if not target:
        return False
    return any(str(value or '').strip().lower() == target for value in values)


def _team_remote_id(task):
    raw = ''
    for key in ('task_id', 'id', 'code', 'path', 'filename'):
        raw = _team_text(task.get(key))
        if raw:
            break
    if not raw:
        raw = json.dumps({
            'title': _team_text(task.get('title')),
            'created': _team_text(task.get('created') or task.get('created_at')),
        }, ensure_ascii=False, sort_keys=True)
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '-', raw).strip('-._')
    if cleaned:
        return cleaned[:96]
    return 'card-' + hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]


def _team_status(task):
    status = _team_text(task.get('status') or 'todo').lower().replace('_', '-')
    return status or 'todo'


def _team_due_date(task):
    raw = _team_text(task.get('due_date') or task.get('due') or task.get('deadline'))
    if not raw:
        return ''
    raw = raw[:10]
    ok, normalized = normalize_due_date(raw)
    return normalized if ok else ''


def _team_remote_url(task, team_url, remote_id):
    raw = _team_text(task.get('remote_url') or task.get('url') or task.get('permalink') or task.get('href'))
    if raw.startswith('http://') or raw.startswith('https://'):
        return raw
    if raw:
        return urljoin(team_url.rstrip('/') + '/', raw.lstrip('/'))
    return team_url.rstrip('/') + '/#task=' + quote(str(remote_id), safe='')


def _team_card_path(task):
    raw = _team_text(task.get('team_path') or task.get('path') or task.get('rel_path') or task.get('filepath'))
    if raw:
        return raw.lstrip('/')
    remote_url = _team_text(task.get('remote_url') or task.get('url') or task.get('permalink') or task.get('href'))
    try:
        parsed = urlparse(remote_url)
    except Exception:
        return ''
    marker = '/blob/main/'
    if marker in parsed.path:
        return unquote(parsed.path.split(marker, 1)[1]).lstrip('/')
    return ''


def _team_updated_at(task, fallback):
    return _team_text(
        task.get('updated_at')
        or task.get('updated')
        or task.get('modified_at')
        or task.get('created_at')
        or task.get('created')
    ) or fallback


def normalize_team_kanban_task(task, config=None, generated_at=None):
    if not isinstance(task, dict):
        return None
    sync_cfg = _team_sync_config(config)
    remote_id = _team_remote_id(task)
    title = _team_text(task.get('title') or task.get('display_title') or task.get('issue') or task.get('filename')) or remote_id
    status = _team_status(task)
    assignees = _team_values(task, 'assignee', 'assigned_to', 'owner', 'assignees')
    creators = _team_values(task, 'created_by', 'creator', 'author', 'created_by_name', 'reporter')
    assignee = assignees[0] if assignees else ''
    now_text = generated_at or datetime.now().astimezone().isoformat(timespec='seconds')
    team_path = _team_card_path(task)
    return {
        'remote_task_id': remote_id,
        'source': TEAM_KANBAN_SOURCE_PREFIX + remote_id,
        'source_ref': _team_text(task.get('source') or task.get('promoted_from') or ''),
        'title': re.sub(r'[\r\n]+', ' ', title).strip(),
        'status': status,
        'assignee': assignee,
        'assignees': assignees,
        'created_by': creators[0] if creators else '',
        'creators': creators,
        'due_date': _team_due_date(task),
        'remote_url': _team_remote_url(task, sync_cfg.get('team_kanban_url') or '', remote_id),
        'updated_at': _team_updated_at(task, now_text),
        'project': _team_text(task.get('project') or ''),
        'path': team_path,
        'team_path': team_path,
    }


def select_team_kanban_tasks(remote_data, config=None, generated_at=None):
    sync_cfg = _team_sync_config(config)
    target_user = _team_target_user(sync_cfg)
    raw_tasks = remote_data.get('tasks') if isinstance(remote_data, dict) else []
    if not isinstance(raw_tasks, list):
        raw_tasks = []
    selected = []
    for raw in raw_tasks:
        item = normalize_team_kanban_task(raw, config=config, generated_at=generated_at)
        if not item:
            continue
        if item['status'] not in TEAM_KANBAN_ACTIVE_STATUSES:
            continue
        assigned_to_target = _team_name_matches(item.get('assignees') or [item.get('assignee')], target_user)
        created_by_target = _team_name_matches(item.get('creators') or [item.get('created_by')], target_user)
        handoff_from_target = str(item.get('source_ref') or '').startswith('personal-kanban/')
        if assigned_to_target or created_by_target or handoff_from_target:
            selected.append(item)
    selected.sort(key=lambda item: (item.get('due_date') or '9999-99-99', item.get('remote_task_id') or ''))
    return selected


def _team_json_load(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        return default
    return data if isinstance(data, dict) else default


def _team_json_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def _team_due_soon(due_date, *, now=None, days=3):
    if not due_date:
        return False
    try:
        due = datetime.strptime(str(due_date), '%Y-%m-%d').date()
    except ValueError:
        return False
    today = (now or datetime.now()).date()
    return today <= due <= today + timedelta(days=max(0, int(days)))


def _team_overdue(due_date, *, now=None):
    if not due_date:
        return False
    try:
        due = datetime.strptime(str(due_date), '%Y-%m-%d').date()
    except ValueError:
        return False
    today = (now or datetime.now()).date()
    return due < today


def build_team_kanban_digest(records, previous_snapshot=None, config=None, now=None):
    sync_cfg = _team_sync_config(config)
    now_dt = now or datetime.now().astimezone()
    generated_at = now_dt.isoformat(timespec='seconds')
    previous = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    previous_tasks = previous.get('tasks') if isinstance(previous.get('tasks'), dict) else {}
    due_soon_days = sync_cfg.get('due_soon_days', _DEFAULTS['team_sync']['due_soon_days'])
    try:
        due_soon_days = int(due_soon_days)
    except (TypeError, ValueError):
        due_soon_days = int(_DEFAULTS['team_sync']['due_soon_days'])

    entries = []

    def add_entry(kind, record, **extra):
        entry = {
            'type': kind,
            'remote_task_id': record.get('remote_task_id'),
            'title': record.get('title') or '未命名团队卡',
            'status': record.get('status') or '',
            'assignee': record.get('assignee') or '',
            'due_date': record.get('due_date') or '',
            'remote_url': record.get('remote_url') or '',
            'team_path': record.get('team_path') or record.get('path') or '',
            'source_ref': record.get('source_ref') or '',
            'timestamp': record.get('updated_at') or generated_at,
        }
        entry.update(extra)
        entries.append(entry)

    for record in records:
        remote_id = record.get('remote_task_id')
        if not remote_id:
            continue
        previous_record = previous_tasks.get(remote_id)
        if not isinstance(previous_record, dict):
            add_entry('new_card', record)
        else:
            if str(previous_record.get('status') or '') != str(record.get('status') or ''):
                add_entry('status_changed', record, from_status=previous_record.get('status') or '', to_status=record.get('status') or '')
            if str(previous_record.get('assignee') or '') != str(record.get('assignee') or ''):
                add_entry('assignee_changed', record, from_assignee=previous_record.get('assignee') or '', to_assignee=record.get('assignee') or '')
        if _team_due_soon(record.get('due_date'), now=now_dt, days=due_soon_days):
            add_entry('due_soon', record)
        if _team_overdue(record.get('due_date'), now=now_dt):
            add_entry('overdue', record)

    entries.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
    snapshot_tasks = {
        record['remote_task_id']: {
            'title': record.get('title') or '',
            'status': record.get('status') or '',
            'assignee': record.get('assignee') or '',
            'due_date': record.get('due_date') or '',
            'remote_url': record.get('remote_url') or '',
            'team_path': record.get('team_path') or record.get('path') or '',
            'source_ref': record.get('source_ref') or '',
            'updated_at': record.get('updated_at') or '',
        }
        for record in records
        if record.get('remote_task_id')
    }
    digest = {
        'ok': True,
        'source': 'team-kanban',
        'generated_at': generated_at,
        'summary': f"{len(entries)} 条团队动态 · {len(records)} 张相关活跃卡",
        'entries': entries,
        'stats': {
            'selected': len(records),
            'new_card': sum(1 for item in entries if item.get('type') == 'new_card'),
            'status_changed': sum(1 for item in entries if item.get('type') == 'status_changed'),
            'assignee_changed': sum(1 for item in entries if item.get('type') == 'assignee_changed'),
            'due_soon': sum(1 for item in entries if item.get('type') == 'due_soon'),
            'overdue': sum(1 for item in entries if item.get('type') == 'overdue'),
        },
    }
    snapshot = {
        'generated_at': generated_at,
        'source': 'team-kanban',
        'tasks': snapshot_tasks,
    }
    return digest, snapshot


def _annotate_team_digest_freshness(digest, sync_cfg, fetch_status=None, repo_path=None, now=None):
    if not isinstance(digest, dict):
        return digest
    stale_days = _team_int(sync_cfg.get('stale_days'), _DEFAULTS['team_sync']['stale_days'], minimum=0)
    digest['stale_days'] = stale_days
    status = _team_sync_freshness(sync_cfg, repo_path=repo_path, now=now)
    if fetch_status and fetch_status.get('ok') is False and not fetch_status.get('skipped'):
        status = dict(status)
        status.update({
            'is_stale': True,
            'reason': fetch_status.get('reason') or 'fetch_failed',
        })
    digest['sync_status'] = status
    digest['age_days'] = status.get('age_days')
    digest['is_stale'] = bool(status.get('is_stale'))
    if status.get('reason'):
        digest['stale_reason'] = status.get('reason')
    return digest


def _team_notify_state_path(sync_cfg):
    return _team_sync_state_path(sync_cfg, 'notify_state_path')


def _team_notification_key(event_type, entry):
    if event_type == 'sync_stale':
        return 'sync_stale:team-sync'
    remote_id = str(entry.get('remote_task_id') or '').strip() or 'unknown'
    suffix_parts = []
    for key in ('to_status', 'from_status', 'to_assignee', 'due_date'):
        value = str(entry.get(key) or '').strip()
        if value:
            suffix_parts.append(value)
    suffix = ':' + ':'.join(suffix_parts) if suffix_parts else ''
    return f"{event_type}:{remote_id}{suffix}"


def _team_event_from_digest_entry(entry, target_user):
    kind = str(entry.get('type') or '').strip()
    assignee = str(entry.get('assignee') or '').strip()
    if kind in {'new_card', 'assignee_changed'} and _team_name_matches([assignee], target_user):
        return 'team_assigned'
    if kind == 'due_soon':
        return 'team_due_soon'
    if kind == 'overdue':
        return 'team_overdue'
    if kind == 'status_changed' and str(entry.get('source_ref') or '').startswith('personal-kanban/'):
        return 'handoff_status_changed'
    return ''


def _team_event_title(event_type, entry):
    title = entry.get('title') or '未命名团队卡'
    if event_type == 'team_assigned':
        return f"团队板新指派给我：{title}"
    if event_type == 'team_due_soon':
        return f"我相关团队卡临期：{title}"
    if event_type == 'team_overdue':
        return f"我相关团队卡逾期：{title}"
    if event_type == 'handoff_status_changed':
        return f"我交接的团队卡状态变更：{title}"
    if event_type == 'sync_stale':
        return '团队双同步可能停摆'
    return title


def _team_event_fields(event_type, entry, digest=None):
    if event_type == 'sync_stale':
        status = (digest or {}).get('sync_status') or {}
        return [
            ('状态', status.get('task_status') or status.get('reason') or 'stale'),
            ('最后检查', status.get('last_checked_at') or '未知'),
            ('阈值', f"{(digest or {}).get('stale_days', 3)} 天"),
        ]
    fields = [
        ('状态', entry.get('status') or ''),
        ('负责人', entry.get('assignee') or ''),
        ('到期日', entry.get('due_date') or ''),
    ]
    if event_type == 'handoff_status_changed':
        fields.extend([
            ('原状态', entry.get('from_status') or ''),
            ('新状态', entry.get('to_status') or ''),
            ('来源', entry.get('source_ref') or ''),
        ])
    if entry.get('to_assignee'):
        fields.append(('新负责人', entry.get('to_assignee') or ''))
    return fields


def notify_team_digest_events(digest, config=None, force=False):
    source = config if isinstance(config, dict) else load_config()
    sync_cfg = _team_sync_config(source)
    target_user = _team_target_user(sync_cfg)
    feishu_notify.set_config(_normalize_feishu_config(source))
    if not feishu_notify.is_enabled():
        return {'ok': True, 'skipped': True, 'reason': 'feishu_disabled', 'sent': 0}

    state_path = _team_notify_state_path(sync_cfg)
    state = _team_json_load(state_path, {'sent': {}})
    sent_keys = state.get('sent') if isinstance(state.get('sent'), dict) else {}
    if force:
        sent_keys = {}
    sent = []
    warnings = []
    entries = digest.get('entries') if isinstance(digest, dict) else []
    if not isinstance(entries, list):
        entries = []

    if digest.get('is_stale'):
        stale_entry = {'remote_task_id': 'team-sync', 'title': '团队双同步', 'type': 'sync_stale'}
        key = _team_notification_key('sync_stale', stale_entry)
        if key not in sent_keys:
            warning = feishu_notify.notify_member_event(
                target_user,
                'sync_stale',
                _team_event_title('sync_stale', stale_entry),
                _team_event_fields('sync_stale', stale_entry, digest),
                body='团队镜像同步超过新鲜度阈值或调度任务不可用，请先恢复双同步再判断团队卡状态。',
                url='',
            )
            if warning:
                warnings.append(warning)
            else:
                sent.append(key)
                sent_keys[key] = datetime.now().astimezone().isoformat(timespec='seconds')
    else:
        sent_keys = {key: val for key, val in sent_keys.items() if not str(key).startswith('sync_stale:')}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        event_type = _team_event_from_digest_entry(entry, target_user)
        if not event_type:
            continue
        key = _team_notification_key(event_type, entry)
        if key in sent_keys:
            continue
        warning = feishu_notify.notify_member_event(
            target_user,
            event_type,
            _team_event_title(event_type, entry),
            _team_event_fields(event_type, entry, digest),
            body='',
            url=entry.get('remote_url') or '',
        )
        if warning:
            warnings.append(warning)
            continue
        sent.append(key)
        sent_keys[key] = datetime.now().astimezone().isoformat(timespec='seconds')

    state['sent'] = sent_keys
    state['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
    _team_json_write(state_path, state)
    return {'ok': True, 'skipped': False, 'sent': len(sent), 'warnings': warnings}


def build_team_feishu_smoke_digest(config=None, now=None):
    sync_cfg = _team_sync_config(config)
    target_user = _team_target_user(sync_cfg)
    now_dt = now or datetime.now().astimezone()
    stamp = now_dt.strftime('%Y%m%d%H%M%S')
    due_date = (now_dt.date() + timedelta(days=1)).isoformat()
    return {
        'ok': True,
        'source': 'team-kanban-smoke',
        'generated_at': now_dt.isoformat(timespec='seconds'),
        'summary': '飞书四类团队对接事件自测',
        'is_stale': True,
        'stale_days': _team_int(sync_cfg.get('stale_days'), _DEFAULTS['team_sync']['stale_days'], minimum=0),
        'sync_status': {
            'source': 'smoke_test',
            'reason': 'manual_smoke_test',
            'task_status': 'SMOKE',
            'last_checked_at': now_dt.isoformat(timespec='seconds'),
        },
        'entries': [
            {
                'type': 'new_card',
                'remote_task_id': f'SMOKE-ASSIGNED-{stamp}',
                'title': '飞书自测：团队板新指派给我',
                'status': 'todo',
                'assignee': target_user,
                'due_date': '',
                'remote_url': '',
                'timestamp': now_dt.isoformat(timespec='seconds'),
            },
            {
                'type': 'due_soon',
                'remote_task_id': f'SMOKE-DUE-{stamp}',
                'title': '飞书自测：我相关团队卡临期',
                'status': 'in-progress',
                'assignee': target_user,
                'due_date': due_date,
                'remote_url': '',
                'timestamp': now_dt.isoformat(timespec='seconds'),
            },
            {
                'type': 'status_changed',
                'remote_task_id': f'SMOKE-HANDOFF-{stamp}',
                'title': '飞书自测：我交接的团队卡状态变更',
                'status': 'review',
                'assignee': 'Pat',
                'due_date': '',
                'remote_url': '',
                'source_ref': 'personal-kanban/SMOKE',
                'from_status': 'todo',
                'to_status': 'review',
                'timestamp': now_dt.isoformat(timespec='seconds'),
            },
        ],
    }


def test_team_feishu_notifications(config=None):
    source = config if isinstance(config, dict) else load_config()
    digest = build_team_feishu_smoke_digest(source)
    result = notify_team_digest_events(digest, config=source, force=True)
    result.update({
        'test': 'team_feishu_notifications',
        'target_user': _team_target_user(_team_sync_config(source)),
        'expected_events': [
            'sync_stale',
            'team_assigned',
            'team_due_soon',
            'handoff_status_changed',
        ],
    })
    return result


def _team_pointer_body(record):
    due_date = record.get('due_date') or '无'
    assignee = record.get('assignee') or '未分配'
    status = record.get('status') or 'todo'
    remote_url = record.get('remote_url') or ''
    team_path = record.get('team_path') or record.get('path') or ''
    title = record.get('title') or '未命名团队卡'
    return '\n'.join([
        '## 团队看板指针',
        '',
        f"- 标题：{title}",
        f"- 远程状态：{status}",
        f"- 远程负责人：{assignee}",
        f"- 到期日：{due_date}",
        f"- 团队卡位置：{team_path}",
        f"- 远程卡：{remote_url}",
        '',
        '> 只读同步指针卡；不复制团队卡正文。',
        '',
    ])


def _format_frontmatter_scalar(value):
    return str(value if value is not None else '').replace('\r', ' ').replace('\n', ' ').strip()


def _rewrite_task_metadata_and_body(rel_path, fields, body_text):
    with MARKDOWN_WRITE_LOCK:
        fpath = REPO_ROOT / rel_path
        if not fpath.exists():
            return False, '文件不存在'
        content = fpath.read_text(encoding='utf-8')
        _fm, fm_block = extract_frontmatter(content)
        if not fm_block:
            return False, '无 frontmatter'
        lines = fm_block.split('\n')
        pending = {key: _format_frontmatter_scalar(value) for key, value in fields.items()}
        new_lines = []
        seen = set()
        for line in lines:
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
            if m and m.group(1) in pending:
                key = m.group(1)
                new_lines.append(f"{key}: {pending[key]}")
                seen.add(key)
            else:
                new_lines.append(line)
        for key, value in pending.items():
            if key in seen:
                continue
            new_lines.insert(_frontmatter_insert_index(new_lines, key), f"{key}: {value}")
        today = datetime.now().strftime('%Y-%m-%d')
        updated_found = False
        final_lines = []
        for line in new_lines:
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', line.strip())
            if m and m.group(1) == 'updated':
                final_lines.append(f"updated: {today}")
                updated_found = True
            else:
                final_lines.append(line)
        if not updated_found:
            final_lines.insert(_frontmatter_insert_index(final_lines, 'updated'), f"updated: {today}")
        _atomic_write_text(fpath, '\n'.join(final_lines) + '\n\n' + body_text.rstrip() + '\n')
    return True, 'OK'


def _find_team_pointer_cards(target_project=''):
    index = {}
    for doc in scan_all():
        source = str(doc.get('source') or '')
        if source.startswith(TEAM_KANBAN_SOURCE_PREFIX):
            index[source] = doc
    target_dir = REPO_ROOT / 'project' / str(target_project or '')
    if target_project and target_dir.exists():
        for fpath in target_dir.rglob('*.md'):
            if any(part.startswith('.') or part == 'vendor' for part in fpath.relative_to(target_dir).parts[:-1]):
                continue
            try:
                content = fpath.read_text(encoding='utf-8')
            except OSError:
                continue
            fm, _fm_block = extract_frontmatter(content)
            if not fm:
                continue
            source = str(fm.get('source') or '')
            if source.startswith(TEAM_KANBAN_SOURCE_PREFIX) and source not in index:
                doc = {'path': str(fpath.relative_to(REPO_ROOT)), 'project': target_project, **fm}
                index[source] = doc
    return index


def upsert_team_kanban_pointer_cards(records, config=None):
    sync_cfg = _team_sync_config(config)
    target_project = _team_pointer_project(sync_cfg)
    target_user = _team_target_user(sync_cfg)
    index = _find_team_pointer_cards(target_project)
    created = []
    updated = []
    for record in records:
        source = record.get('source') or ''
        if not source:
            continue
        fields = {
            'title': record.get('title') or '团队看板指针',
            'status': record.get('status') or 'todo',
            'assignee': record.get('assignee') or target_user,
            'due_date': record.get('due_date') or '',
            'kind': 'task',
            'domain': 'team',
            'source': source,
            'remote_url': record.get('remote_url') or '',
            'team_path': record.get('team_path') or record.get('path') or '',
            'next_action': '查看团队看板远程卡并处理对接',
        }
        body = _team_pointer_body(record)
        existing = index.get(source)
        if existing and existing.get('path'):
            ok, _msg = _rewrite_task_metadata_and_body(existing['path'], fields, body)
            if ok:
                updated.append(existing['path'])
            continue
        ok, rel_path, _task_id = create_document(
            target_project,
            fields['title'],
            fields['assignee'],
            'medium',
            body=body,
            workdir=f"project/{target_project}/",
            due_date=fields['due_date'] or None,
        )
        if not ok:
            continue
        _rewrite_task_metadata_and_body(rel_path, fields, body)
        created.append(rel_path)
        index[source] = {'path': rel_path, **fields}
    return {'created': created, 'updated': updated}


def load_team_kanban_digest(config=None):
    sync_cfg = _team_sync_config(config)
    if sync_cfg.get('enabled') and _team_sync_source(sync_cfg) == 'local_repo':
        remote_data, fetch_status = fetch_team_kanban_data(config)
        now_dt = datetime.now().astimezone()
        if remote_data is not None:
            records = select_team_kanban_tasks(remote_data, config=config, generated_at=now_dt.isoformat(timespec='seconds'))
            snapshot_path = _team_sync_state_path(sync_cfg, 'snapshot_path')
            previous_snapshot = _team_json_load(snapshot_path, {'tasks': {}})
            digest, _snapshot = build_team_kanban_digest(records, previous_snapshot, config=config, now=now_dt)
            digest['source'] = 'team-kanban-local'
            digest['fetch_status'] = fetch_status
            repo_path, _err = _team_local_repo_path(sync_cfg)
            _annotate_team_digest_freshness(digest, sync_cfg, fetch_status=fetch_status, repo_path=repo_path, now=now_dt)
            return digest
        digest = {
            'ok': False,
            'source': 'team-kanban-local',
            'generated_at': '',
            'entries': [],
            'error': fetch_status.get('reason') or 'local_repo_unavailable',
            'fetch_status': fetch_status,
        }
        _annotate_team_digest_freshness(digest, sync_cfg, fetch_status=fetch_status, repo_path=None)
        digest['is_stale'] = True
        return digest

    digest_path = _team_sync_state_path(sync_cfg, 'digest_path')
    digest = _team_json_load(digest_path, {
        'ok': False,
        'source': 'team-kanban',
        'generated_at': '',
        'entries': [],
        'error': 'missing',
    })
    if not isinstance(digest.get('entries'), list):
        digest['entries'] = []
    stale_days = _team_int(sync_cfg.get('stale_days'), _DEFAULTS['team_sync']['stale_days'], minimum=0)
    generated = _parse_dynamic_datetime(digest.get('generated_at'))
    now = datetime.now().astimezone()
    age_days = None
    if generated:
        age_days = max(0, (now - generated.astimezone()).total_seconds() / 86400)
    is_stale = age_days is None or age_days > stale_days
    digest['stale_days'] = stale_days
    digest['age_days'] = age_days
    digest['is_stale'] = is_stale
    return digest


def sync_team_kanban_from_data(remote_data, config=None, now=None):
    sync_cfg = _team_sync_config(config)
    now_dt = now or datetime.now().astimezone()
    records = select_team_kanban_tasks(remote_data, config=config, generated_at=now_dt.isoformat(timespec='seconds'))
    snapshot_path = _team_sync_state_path(sync_cfg, 'snapshot_path')
    digest_path = _team_sync_state_path(sync_cfg, 'digest_path')
    previous_snapshot = _team_json_load(snapshot_path, {'tasks': {}})
    upsert_result = upsert_team_kanban_pointer_cards(records, config=config)
    digest, snapshot = build_team_kanban_digest(records, previous_snapshot, config=config, now=now_dt)
    repo_path = None
    if isinstance(remote_data, dict) and remote_data.get('repo_path'):
        repo_path = Path(str(remote_data.get('repo_path')))
    _annotate_team_digest_freshness(digest, sync_cfg, repo_path=repo_path, now=now_dt)
    _team_json_write(digest_path, digest)
    _team_json_write(snapshot_path, snapshot)
    notify_result = notify_team_digest_events(digest, config=config)
    return {
        'ok': True,
        'skipped': False,
        'selected': len(records),
        'created': len(upsert_result['created']),
        'updated': len(upsert_result['updated']),
        'digest_entries': len(digest.get('entries') or []),
        'digest_path': str(digest_path.relative_to(REPO_ROOT.resolve())),
        'snapshot_path': str(snapshot_path.relative_to(REPO_ROOT.resolve())),
        'notifications': notify_result,
    }


def sync_team_handoff_pointer(team_rel_path, team_project, content, remote_url='', config=None, now=None):
    """Create the personal-side read-only pointer for a freshly handed-off team card."""
    source = config if isinstance(config, dict) else load_config()
    sync_cfg = _team_sync_config(source)
    now_dt = now or datetime.now().astimezone()
    fm, _fm_block = extract_frontmatter(content)
    if not fm:
        return {'ok': False, 'reason': 'team_card_no_frontmatter'}
    raw = dict(fm)
    raw.update({
        'path': team_rel_path,
        'filename': Path(team_rel_path).name,
        'project': team_project,
        'remote_url': remote_url,
    })
    records = select_team_kanban_tasks(
        {'tasks': [raw]},
        config=source,
        generated_at=now_dt.isoformat(timespec='seconds'),
    )
    upsert_result = upsert_team_kanban_pointer_cards(records, config=source)
    snapshot_path = _team_sync_state_path(sync_cfg, 'snapshot_path')
    previous_snapshot = _team_json_load(snapshot_path, {'tasks': {}})
    _digest, partial_snapshot = build_team_kanban_digest(records, previous_snapshot, config=source, now=now_dt)
    previous_tasks = previous_snapshot.get('tasks') if isinstance(previous_snapshot.get('tasks'), dict) else {}
    partial_tasks = partial_snapshot.get('tasks') if isinstance(partial_snapshot.get('tasks'), dict) else {}
    merged_snapshot = dict(previous_snapshot)
    merged_snapshot.update({
        'generated_at': partial_snapshot.get('generated_at') or now_dt.isoformat(timespec='seconds'),
        'source': partial_snapshot.get('source') or 'team-kanban',
        'tasks': {**previous_tasks, **partial_tasks},
    })
    _team_json_write(snapshot_path, merged_snapshot)
    try:
        snapshot_ref = str(snapshot_path.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        snapshot_ref = str(snapshot_path)
    return {
        'ok': True,
        'selected': len(records),
        'created': len(upsert_result['created']),
        'updated': len(upsert_result['updated']),
        'created_paths': upsert_result['created'],
        'updated_paths': upsert_result['updated'],
        'snapshot_path': snapshot_ref,
        'notifications': {
            'sent': 0,
            'reason': 'handoff_created_event_already_sent_by_commit',
        },
    }


def sync_team_kanban(config=None):
    remote_data, fetch_status = fetch_team_kanban_data(config)
    if remote_data is None:
        return fetch_status
    return sync_team_kanban_from_data(remote_data, config=config)


class TeamKanbanSyncManager:
    """Lightweight in-process scheduler for team pointer-card sync."""

    def __init__(self, config=None, sync_fn=None, logger=None):
        self.config = config if isinstance(config, dict) else load_config()
        self.sync_fn = sync_fn or sync_team_kanban
        self.logger = logger or (lambda *_args, **_kwargs: None)
        sync_cfg = _team_sync_config(self.config)
        self.enabled = bool(sync_cfg.get('enabled') and sync_cfg.get('auto_sync', True))
        self.interval_seconds = _team_int(sync_cfg.get('interval_seconds'), _DEFAULTS['team_sync']['interval_seconds'], minimum=30)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._status = {
            'enabled': self.enabled,
            'running': False,
            'last_run_at': '',
            'last_result': None,
            'last_error': None,
            'interval_seconds': self.interval_seconds,
        }

    def start(self):
        if not self.enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name='team-kanban-sync', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def run_once(self):
        if not self.enabled:
            return {'ok': False, 'skipped': True, 'reason': 'disabled'}
        with self._lock:
            if self._status.get('running'):
                return {'ok': False, 'skipped': True, 'reason': 'already_running'}
            self._status['running'] = True
            self._status['last_error'] = None
        try:
            result = self.sync_fn(self.config)
            with self._lock:
                self._status['last_run_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
                self._status['last_result'] = result
            return result
        except Exception as exc:
            with self._lock:
                self._status['last_run_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
                self._status['last_error'] = str(exc)
            self.logger(f"  [团队同步] 自动同步失败: {exc}")
            return {'ok': False, 'error': str(exc)}
        finally:
            with self._lock:
                self._status['running'] = False

    def _loop(self):
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval_seconds)


def _safe_task_path_value(path):
    value = str(path or '').strip()
    if not value:
        return '', '缺少 path'
    if '..' in value or value.startswith('/'):
        return '', '非法路径'
    return value, ''


def _team_project_dir(repo_path, project):
    name = str(project or '').strip()
    if not name or '/' in name or name.startswith('.') or name.startswith('_'):
        return None, '缺少有效团队项目'
    project_root = (repo_path / 'project').resolve()
    target = (project_root / name).resolve()
    if not _path_is_relative_to(target, project_root):
        return None, '非法团队项目路径'
    if not target.exists() or not target.is_dir():
        return None, f'团队项目不存在: {name}'
    return target, ''


def _team_git_status(repo_path):
    try:
        proc = subprocess.run(
            ['git', '-C', str(repo_path), 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
            capture_output=True,
            text=True,
            timeout=5,
            env=_git_subprocess_env(),
        )
    except Exception as exc:
        return None, f'git_status_error:{exc}'
    if proc.returncode != 0:
        return None, 'git_status_failed'
    rows = []
    records = (proc.stdout or '').split('\0')
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:].strip()
        if status and (status[0] in {'R', 'C'} or status[1] in {'R', 'C'}):
            index += 1
        rows.append({'status': status, 'path': path})
    return rows, ''


_GIT_PROXY_ENV_CACHE = {'loaded_at': 0, 'values': {}}


def _scutil_proxy_value(text, key):
    m = re.search(rf'^\s*{re.escape(key)}\s*:\s*(.+?)\s*$', text or '', re.MULTILINE)
    return m.group(1).strip() if m else ''


def _system_git_proxy_env():
    now = time.time()
    cached_at = float(_GIT_PROXY_ENV_CACHE.get('loaded_at') or 0)
    if now - cached_at < 30:
        return dict(_GIT_PROXY_ENV_CACHE.get('values') or {})
    values = {}
    ok, output, _error = PLATFORM_ADAPTER.system_proxy_output()
    if ok:
        https_enabled = _scutil_proxy_value(output, 'HTTPSEnable') == '1'
        https_host = _scutil_proxy_value(output, 'HTTPSProxy')
        https_port = _scutil_proxy_value(output, 'HTTPSPort')
        if https_enabled and https_host and https_port:
            values['HTTPS_PROXY'] = f'http://{https_host}:{https_port}'
        http_enabled = _scutil_proxy_value(output, 'HTTPEnable') == '1'
        http_host = _scutil_proxy_value(output, 'HTTPProxy')
        http_port = _scutil_proxy_value(output, 'HTTPPort')
        if http_enabled and http_host and http_port:
            values['HTTP_PROXY'] = f'http://{http_host}:{http_port}'
    _GIT_PROXY_ENV_CACHE['loaded_at'] = now
    _GIT_PROXY_ENV_CACHE['values'] = values
    return dict(values)


def _git_subprocess_env():
    env = os.environ.copy()
    env.setdefault('GIT_TERMINAL_PROMPT', '0')
    has_https_proxy = any(env.get(k) for k in ('HTTPS_PROXY', 'https_proxy'))
    has_http_proxy = any(env.get(k) for k in ('HTTP_PROXY', 'http_proxy'))
    proxy_env = _system_git_proxy_env() if not (has_https_proxy and has_http_proxy) else {}
    for key, value in proxy_env.items():
        env.setdefault(key, value)
    return env


def _team_git_run(repo_path, args, timeout=20):
    try:
        proc = subprocess.run(
            ['git', '-C', str(repo_path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_subprocess_env(),
        )
    except Exception as exc:
        return {'ok': False, 'returncode': -1, 'stdout': '', 'stderr': str(exc)}
    return {
        'ok': proc.returncode == 0,
        'returncode': proc.returncode,
        'stdout': (proc.stdout or '').strip(),
        'stderr': (proc.stderr or '').strip(),
    }


def _team_git_error_code(prefix, result):
    code = result.get('returncode') if isinstance(result, dict) else ''
    return f'{prefix}:{code}'


def _team_handoff_publish_enabled(sync_cfg):
    return bool(sync_cfg.get('handoff_publish_enabled') or sync_cfg.get('publish_on_commit'))


def _team_handoff_publish_remote(sync_cfg):
    value = str(sync_cfg.get('handoff_publish_remote') or sync_cfg.get('publish_remote') or 'origin').strip()
    return value or 'origin'


def _team_handoff_publish_branch(sync_cfg):
    value = str(sync_cfg.get('handoff_publish_branch') or sync_cfg.get('publish_branch') or 'main').strip()
    return value or 'main'


def _team_handoff_publish_worktree_path(sync_cfg):
    return _team_sync_state_path(sync_cfg, 'handoff_publish_worktree_path')


def _team_handoff_remote_url(repo_path, remote):
    result = _team_git_run(repo_path, ['remote', 'get-url', remote], timeout=5)
    if not result.get('ok') or not result.get('stdout'):
        return '', _team_git_error_code('git_remote_missing', result)
    return result['stdout'].strip(), ''


def _github_base_from_git_remote(remote_url):
    value = str(remote_url or '').strip()
    if value.endswith('.git'):
        value = value[:-4]
    m = re.match(r'^git@github\.com:(.+)$', value)
    if m:
        return 'https://github.com/' + m.group(1).strip('/')
    m = re.match(r'^https://(?:[^/@]+@)?github\.com/(.+)$', value)
    if m:
        return 'https://github.com/' + m.group(1).strip('/')
    return ''


def _team_handoff_github_url(sync_cfg, remote_url, branch, rel_path):
    base = str(sync_cfg.get('handoff_publish_github_base_url') or sync_cfg.get('github_base_url') or '').strip().rstrip('/')
    if not base:
        base = _github_base_from_git_remote(remote_url)
    if not base:
        return ''
    return f"{base}/blob/{quote(str(branch or 'main'), safe='')}/{quote(str(rel_path or ''), safe='/')}"


def _team_handoff_publish_preflight(sync_cfg, repo_path):
    enabled = _team_handoff_publish_enabled(sync_cfg)
    remote = _team_handoff_publish_remote(sync_cfg)
    branch = _team_handoff_publish_branch(sync_cfg)
    info = {
        'enabled': enabled,
        'mode': 'scoped_git' if enabled else 'local_write',
        'remote': remote,
        'branch': branch,
        'worktree_path': '',
    }
    if not enabled:
        return True, '', info
    if not repo_path or not (Path(repo_path) / '.git').exists():
        return False, 'publish_repo_not_git', info
    worktree_path = _team_handoff_publish_worktree_path(sync_cfg)
    try:
        info['worktree_path'] = str(worktree_path.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        info['worktree_path'] = str(worktree_path)
    _remote_url, err = _team_handoff_remote_url(repo_path, remote)
    if err:
        return False, err, info
    return True, '', info


def _team_handoff_ensure_git_identity(repo_path):
    email = _team_git_run(repo_path, ['config', 'user.email'], timeout=5)
    if not email.get('ok') or not email.get('stdout'):
        set_email = _team_git_run(repo_path, ['config', 'user.email', 'kanban-handoff@example.local'], timeout=5)
        if not set_email.get('ok'):
            return _team_git_error_code('git_config_email_failed', set_email)
    name = _team_git_run(repo_path, ['config', 'user.name'], timeout=5)
    if not name.get('ok') or not name.get('stdout'):
        set_name = _team_git_run(repo_path, ['config', 'user.name', 'Kanban Handoff Bot'], timeout=5)
        if not set_name.get('ok'):
            return _team_git_error_code('git_config_name_failed', set_name)
    return ''


def _team_handoff_publish_checkout(sync_cfg, source_repo_path):
    remote = _team_handoff_publish_remote(sync_cfg)
    branch = _team_handoff_publish_branch(sync_cfg)
    remote_url, err = _team_handoff_remote_url(source_repo_path, remote)
    if err:
        return None, remote_url, err
    work_root = _team_handoff_publish_worktree_path(sync_cfg)
    try:
        work_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, remote_url, f'publish_worktree_mkdir_failed:{exc.__class__.__name__}'
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    checkout_path = work_root / f'run-{run_id}'
    if not bool(sync_cfg.get('handoff_publish_force_clone')):
        fetch = _team_git_run(source_repo_path, ['fetch', '--prune', remote, branch], timeout=60)
        if fetch.get('ok'):
            ref = f'{remote}/{branch}'
            try:
                worktree = subprocess.run(
                    ['git', '-C', str(source_repo_path), 'worktree', 'add', '--detach', str(checkout_path), ref],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=_git_subprocess_env(),
                )
            except subprocess.TimeoutExpired:
                if checkout_path.exists():
                    shutil.rmtree(checkout_path, ignore_errors=True)
                return None, remote_url, 'git_worktree_timeout'
            except (FileNotFoundError, OSError) as exc:
                if checkout_path.exists():
                    shutil.rmtree(checkout_path, ignore_errors=True)
                return None, remote_url, f'git_worktree_failed:{exc.__class__.__name__}'
            if worktree.returncode == 0:
                identity_err = _team_handoff_ensure_git_identity(checkout_path)
                if identity_err:
                    return None, remote_url, identity_err
                return checkout_path, remote_url, ''
            if checkout_path.exists():
                shutil.rmtree(checkout_path, ignore_errors=True)
    clone_args = ['git', 'clone', '--depth', '1', '--branch', branch, '--single-branch', remote_url, str(checkout_path)]
    try:
        clone = subprocess.run(
            clone_args,
            capture_output=True,
            text=True,
            timeout=120,
            env=_git_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        if checkout_path.exists():
            shutil.rmtree(checkout_path, ignore_errors=True)
        return None, remote_url, 'git_clone_timeout'
    except (FileNotFoundError, OSError) as exc:
        if checkout_path.exists():
            shutil.rmtree(checkout_path, ignore_errors=True)
        return None, remote_url, f'git_clone_failed:{exc.__class__.__name__}'
    if clone.returncode != 0:
        if checkout_path.exists():
            shutil.rmtree(checkout_path, ignore_errors=True)
        return None, remote_url, f'git_clone_failed:{clone.returncode}'
    identity_err = _team_handoff_ensure_git_identity(checkout_path)
    if identity_err:
        return None, remote_url, identity_err
    return checkout_path, remote_url, ''


def _team_handoff_commit_message(title, team_project):
    clean_title = _single_line_scalar(title or '').strip() or '个人看板交接卡'
    if len(clean_title) > 42:
        clean_title = clean_title[:42].rstrip() + '...'
    clean_project = _single_line_scalar(team_project or '').strip() or '团队看板'
    return f'add({clean_project}): 从个人看板交接 {clean_title}'


def _team_handoff_cleanup_checkout(source_repo_path, checkout_path):
    if not checkout_path:
        return
    try:
        if source_repo_path and (Path(source_repo_path) / '.git').exists():
            _team_git_run(source_repo_path, ['worktree', 'remove', '--force', str(checkout_path)], timeout=20)
            _team_git_run(source_repo_path, ['worktree', 'prune'], timeout=10)
    finally:
        if checkout_path.exists():
            shutil.rmtree(checkout_path, ignore_errors=True)


def publish_team_handoff(sync_cfg, source_repo_path, team_project, assignee, filename, content, title=None):
    if not _team_handoff_publish_enabled(sync_cfg):
        return {'ok': False, 'skipped': True, 'reason': 'handoff_publish_disabled'}
    checkout_path, remote_url, checkout_err = _team_handoff_publish_checkout(sync_cfg, source_repo_path)
    if checkout_err:
        return {'ok': False, 'reason': checkout_err}

    cleanup_on_success = False
    try:
        rules_read = _discover_team_handoff_rules(checkout_path, team_project)
        missing_required_rules = [
            rule.get('path') for rule in rules_read
            if rule.get('required') and (not rule.get('exists') or rule.get('readable') is False)
        ]
        if missing_required_rules:
            return {
                'ok': False,
                'reason': 'publish_missing_required_rules',
                'rules_read': rules_read,
                'missing_required_rules': missing_required_rules,
            }
        target_dir, project_err = _team_project_dir(checkout_path, team_project)
        if not target_dir:
            return {'ok': False, 'reason': project_err, 'rules_read': rules_read}
        target_path = (target_dir / filename).resolve()
        validation = _validate_team_handoff_card(checkout_path, team_project, assignee, target_path, content)
        if not validation.get('ok'):
            return {
                'ok': False,
                'reason': 'publish_validation_failed',
                'validation': validation,
                'rules_read': rules_read,
            }

        _atomic_write_text(target_path, content)
        symlink_path, symlink_status, symlink_err = _ensure_team_assignee_inbox_symlink(checkout_path, assignee, target_path)
        if symlink_err:
            return {'ok': False, 'reason': f'publish_symlink_failed:{symlink_err}', 'validation': validation, 'rules_read': rules_read}

        team_rel_path = str(target_path.relative_to(checkout_path))
        allowed_paths = {team_rel_path}
        if symlink_path:
            allowed_paths.add(symlink_path)
        status_rows, status_err = _team_git_status(checkout_path)
        if status_err:
            return {'ok': False, 'reason': status_err, 'validation': validation, 'rules_read': rules_read}
        changed_paths = {row.get('path') for row in status_rows if row.get('path')}
        unexpected = sorted(path for path in changed_paths if path not in allowed_paths)
        if unexpected:
            return {
                'ok': False,
                'reason': 'publish_unexpected_git_changes',
                'unexpected_paths': unexpected,
                'validation': validation,
                'rules_read': rules_read,
            }
        if not changed_paths:
            return {'ok': False, 'reason': 'publish_no_changes', 'validation': validation, 'rules_read': rules_read}

        add = _team_git_run(checkout_path, ['add', '--', *sorted(allowed_paths)], timeout=10)
        if not add.get('ok'):
            return {'ok': False, 'reason': _team_git_error_code('git_add_failed', add), 'validation': validation, 'rules_read': rules_read}
        staged = _team_git_run(checkout_path, ['diff', '--cached', '--name-only', '-z'], timeout=10)
        staged_paths = {path for path in (staged.get('stdout') or '').split('\0') if path} if staged.get('ok') else set()
        if not staged.get('ok') or not staged_paths or staged_paths - allowed_paths:
            return {
                'ok': False,
                'reason': 'publish_staged_paths_not_allowed',
                'staged_paths': sorted(staged_paths),
                'allowed_paths': sorted(allowed_paths),
                'validation': validation,
                'rules_read': rules_read,
            }

        commit = _team_git_run(checkout_path, ['commit', '-m', _team_handoff_commit_message(title, team_project)], timeout=20)
        if not commit.get('ok'):
            return {'ok': False, 'reason': _team_git_error_code('git_commit_failed', commit), 'validation': validation, 'rules_read': rules_read}
        head = _team_git_run(checkout_path, ['rev-parse', '--short', 'HEAD'], timeout=5)
        remote = _team_handoff_publish_remote(sync_cfg)
        branch = _team_handoff_publish_branch(sync_cfg)
        push = _team_git_run(checkout_path, ['push', remote, f'HEAD:{branch}'], timeout=60)
        if not push.get('ok') and bool(sync_cfg.get('handoff_publish_retry_rebase', True)):
            rebase = _team_git_run(checkout_path, ['pull', '--rebase', remote, branch], timeout=60)
            if rebase.get('ok'):
                push = _team_git_run(checkout_path, ['push', remote, f'HEAD:{branch}'], timeout=60)
        if not push.get('ok'):
            return {
                'ok': False,
                'reason': _team_git_error_code('git_push_failed', push),
                'team_path': team_rel_path,
                'commit': head.get('stdout') or '',
                'validation': validation,
                'rules_read': rules_read,
            }
        cleanup_on_success = True
        return {
            'ok': True,
            'mode': 'pushed',
            'team_path': team_rel_path,
            'assignee_inbox_symlink': symlink_path,
            'assignee_inbox_symlink_status': symlink_status,
            'commit': head.get('stdout') or '',
            'remote': remote,
            'branch': branch,
            'url': _team_handoff_github_url(sync_cfg, remote_url, branch, team_rel_path),
            'validation': validation,
            'rules_read': rules_read,
        }
    finally:
        if cleanup_on_success and checkout_path and checkout_path.exists() and not bool(sync_cfg.get('handoff_publish_keep_worktree')):
            _team_handoff_cleanup_checkout(source_repo_path, checkout_path)


def _team_card_related_to_target(repo_path, rel_path, target_user):
    if not rel_path.startswith('project/') or not rel_path.endswith('.md'):
        return False, 'not_team_markdown_card'
    path = (repo_path / rel_path).resolve()
    if not path.exists() or not path.is_file():
        return False, 'team_card_missing'
    try:
        content = path.read_text(encoding='utf-8')
    except Exception:
        return False, 'team_card_unreadable'
    fm, _fm_block = extract_frontmatter(content)
    if not fm:
        return False, 'team_card_no_frontmatter'
    people = _team_values(fm, 'assignee', 'created_by', 'owner', 'reviewer', 'reviewers')
    if _team_name_matches(people, target_user):
        return True, ''
    source = str(fm.get('source') or fm.get('source_ref') or '').strip()
    if source.startswith('personal-kanban/'):
        return True, ''
    promoted_from = str(fm.get('promoted_from') or '').strip()
    if promoted_from.startswith('project/个人调度/'):
        return True, ''
    return False, 'team_card_not_related_to_target'


def _team_repo_write_guard(sync_cfg, repo_path, team_project):
    freshness = _team_sync_freshness(sync_cfg, repo_path=repo_path)
    if freshness.get('is_stale'):
        return False, f"team_sync_stale:{freshness.get('reason') or 'stale'}", freshness
    status_rows, err = _team_git_status(repo_path)
    if err:
        return False, err, freshness
    allowed_prefix = f'project/{team_project}/'
    conflict_statuses = {'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU'}
    for row in status_rows:
        status = row.get('status') or ''
        rel_path = row.get('path') or ''
        if status in conflict_statuses or 'U' in status:
            return False, f'git_conflict:{rel_path}', freshness
        if rel_path and not rel_path.startswith(allowed_prefix):
            freshness.setdefault('ignored_dirty_outside_target', []).append(rel_path)
            continue
        if rel_path and rel_path.startswith(allowed_prefix):
            if 'D' in status:
                return False, f'git_dirty_target_delete:{rel_path}', freshness
            ok, reason = _team_card_related_to_target(
                repo_path,
                rel_path,
                _team_target_user(sync_cfg),
            )
            if not ok:
                return False, f'{reason}:{rel_path}', freshness
    return True, '', freshness


TEAM_HANDOFF_CONTRACT_REL_PATH = 'shared/toolkit/kanban/TEAM_HANDOFF_CONTRACT.md'
TEAM_HANDOFF_REQUIRED_FIELDS = ('title', 'created', 'updated', 'assignee', 'priority', 'status', 'tags')
TEAM_HANDOFF_PRIORITIES = {'high', 'medium', 'low'}
TEAM_HANDOFF_STATUSES = {'todo', 'in-progress', 'review', 'done'}


def _team_handoff_rule_excerpt(content, max_chars=520):
    lines = []
    for raw in str(content or '').splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        if len(lines) >= 8:
            break
    excerpt = '\n'.join(lines)
    if len(excerpt) > max_chars:
        return excerpt[:max_chars].rstrip() + '...'
    return excerpt


def _team_handoff_rule_item(path, root, scope, required=False):
    path = Path(path)
    root = Path(root)
    try:
        rel_path = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel_path = str(path)
    item = {
        'scope': scope,
        'path': rel_path,
        'exists': path.exists(),
        'required': bool(required),
    }
    if not path.exists():
        return item
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as exc:
        item.update({'readable': False, 'error': str(exc)})
        return item
    item.update({
        'readable': True,
        'sha256': hashlib.sha256(content.encode('utf-8')).hexdigest()[:12],
        'line_count': len(content.splitlines()),
        'excerpt': _team_handoff_rule_excerpt(content),
    })
    return item


def _discover_team_handoff_rules(repo_path, team_project):
    rules = [
        _team_handoff_rule_item(
            REPO_ROOT / TEAM_HANDOFF_CONTRACT_REL_PATH,
            REPO_ROOT,
            'personal_contract',
            required=True,
        )
    ]
    if not repo_path:
        return rules
    for filename in ('CLAUDE.md', 'README.md'):
        rules.append(_team_handoff_rule_item(repo_path / filename, repo_path, 'team_root', required=True))
    project_dir = repo_path / 'project' / str(team_project or '').strip()
    for filename in ('AGENTS.md', 'CLAUDE.md', 'README.md', 'CARD_RULES.md'):
        rules.append(_team_handoff_rule_item(project_dir / filename, repo_path, 'team_project', required=False))
    return rules


def _team_handoff_filename_for(source_task_id, title, filename=None):
    value = _single_line_scalar(filename)
    if not value:
        return _team_handoff_filename(source_task_id, title), ''
    if '/' in value or '\\' in value or value.startswith('.') or not value.endswith('.md'):
        return '', '非法团队卡文件名'
    return value, ''


def _team_handoff_priority(task_file, priority=None):
    raw = _single_line_scalar(priority)
    if raw:
        return raw if raw in TEAM_HANDOFF_PRIORITIES else ''
    fm = (task_file or {}).get('frontmatter') or {}
    source_priority = _single_line_scalar(fm.get('priority') or '')
    if source_priority in TEAM_HANDOFF_PRIORITIES:
        return source_priority
    return 'medium'


def _team_member_inbox_symlink(repo_path, assignee, target_path):
    member = _single_line_scalar(assignee)
    if not member or '/' in member or '\\' in member or member.startswith('.') or member.startswith('_'):
        return None, '', '非法负责人路径'
    inbox_dir = (repo_path / 'members' / member / 'inbox').resolve()
    members_root = (repo_path / 'members').resolve()
    if not _path_is_relative_to(inbox_dir, members_root):
        return None, '', '非法成员 inbox 路径'
    link_path = inbox_dir / target_path.name
    rel_target = os.path.relpath(str(target_path), str(inbox_dir))
    return link_path, rel_target, ''


def _validate_team_handoff_card(repo_path, team_project, assignee, target_path, content, priority=None):
    errors = []
    warnings = []
    checks = []

    def add_check(name, ok, message):
        checks.append({'name': name, 'ok': bool(ok), 'message': message})
        if not ok:
            errors.append(message)

    project_root = (repo_path / 'project').resolve()
    target_dir = (project_root / str(team_project or '').strip()).resolve()
    target_path = Path(target_path).resolve()
    add_check('target_path', _path_is_relative_to(target_path, target_dir), '团队卡路径必须在目标项目目录下')
    add_check('markdown_file', target_path.suffix == '.md', '团队卡必须是 .md 文件')
    if target_path.exists():
        add_check('target_not_exists', False, '团队卡已存在')
    else:
        checks.append({'name': 'target_not_exists', 'ok': True, 'message': '团队卡目标文件不存在，可创建'})

    fm, fm_block = extract_frontmatter(content)
    add_check('frontmatter', bool(fm_block), '团队卡必须从 YAML frontmatter 开始')
    if fm_block:
        missing = [field for field in TEAM_HANDOFF_REQUIRED_FIELDS if field not in fm]
        add_check('required_fields', not missing, '缺少团队卡必需字段: ' + ', '.join(missing) if missing else '团队卡必需字段齐全')
        add_check('no_project_field', 'project' not in fm, '团队卡不应写 project 字段')
        add_check('no_manual_task_id', 'task_id' not in fm, '交接卡不应手写 task_id，交由团队看板自动回填')
        content_priority = _single_line_scalar(fm.get('priority') or '')
        confirmed_priority = _single_line_scalar(priority or '')
        status = _single_line_scalar(fm.get('status') or '')
        add_check('priority_value', content_priority in TEAM_HANDOFF_PRIORITIES, f'priority 必须是 {sorted(TEAM_HANDOFF_PRIORITIES)}')
        add_check('status_value', status in TEAM_HANDOFF_STATUSES, f'status 必须是 {sorted(TEAM_HANDOFF_STATUSES)}')
        add_check('assignee_value', _single_line_scalar(fm.get('assignee')) == _single_line_scalar(assignee), '负责人必须与审核确认的 assignee 一致')
        if confirmed_priority:
            add_check('priority_review_value', confirmed_priority == content_priority, '优先级必须与审核确认的 priority 一致')
        source = _single_line_scalar(fm.get('source') or '')
        promoted_from = _single_line_scalar(fm.get('promoted_from') or '')
        add_check('personal_source', source.startswith('personal-kanban/'), '团队卡必须保留 personal-kanban 来源')
        add_check('promoted_from', promoted_from.startswith('project/个人调度/'), '团队卡必须保留个人卡 promoted_from 路径')

    link_path, rel_target, link_err = _team_member_inbox_symlink(repo_path, assignee, target_path)
    inbox = {'required': True, 'path': '', 'target': ''}
    if link_err:
        add_check('assignee_inbox_symlink', False, link_err)
    else:
        inbox = {
            'required': True,
            'path': str(link_path.relative_to(repo_path)),
            'target': rel_target,
        }
        if link_path.is_symlink():
            existing = os.readlink(str(link_path))
            existing_target = (link_path.parent / existing).resolve()
            add_check('assignee_inbox_symlink', existing_target == target_path, '负责人 inbox symlink 必须指向目标团队卡')
        elif link_path.exists():
            add_check('assignee_inbox_symlink', False, '负责人 inbox 目标路径已存在但不是 symlink')
        else:
            checks.append({'name': 'assignee_inbox_symlink', 'ok': True, 'message': '负责人 inbox symlink 将在提交时创建'})

    return {
        'ok': not errors,
        'errors': errors,
        'warnings': warnings,
        'checks': checks,
        'inbox_symlink': inbox,
    }


def _ensure_team_assignee_inbox_symlink(repo_path, assignee, target_path):
    link_path, rel_target, err = _team_member_inbox_symlink(repo_path, assignee, target_path)
    if err:
        return None, '', err
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        existing = os.readlink(str(link_path))
        if (link_path.parent / existing).resolve() == target_path.resolve():
            return str(link_path.relative_to(repo_path)), 'exists', ''
        return None, '', '负责人 inbox symlink 已存在但指向其它目标'
    if link_path.exists():
        return None, '', '负责人 inbox 目标路径已存在但不是 symlink'
    os.symlink(rel_target, str(link_path))
    return str(link_path.relative_to(repo_path)), 'created', ''


def _team_handoff_filename(source_task_id, title):
    raw = source_task_id or title or 'handoff'
    slug = _title_to_slug(raw if raw else 'handoff')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return f"{stamp}-{slug}.md"


def _team_handoff_card_text(task_file, team_project, assignee, title=None, draft=False, priority=None):
    fm = task_file.get('frontmatter') or {}
    local_task_id = _single_line_scalar(fm.get('task_id') or '')
    local_title = _single_line_scalar(title or fm.get('title') or local_task_id or '个人看板交接')
    team_priority = _team_handoff_priority(task_file, priority)
    today = datetime.now().strftime('%Y-%m-%d')
    source_path = str(task_file.get('path').relative_to(REPO_ROOT)) if task_file.get('path') else ''
    source_ref = f"personal-kanban/{local_task_id}" if local_task_id else 'personal-kanban/unknown'
    frontmatter = [
        '---',
        f'title: {local_title}',
        f'created: {today}',
        f'updated: {today}',
        f'assignee: {_format_frontmatter_scalar(assignee)}',
        f'priority: {_format_frontmatter_scalar(team_priority)}',
        'status: todo',
        'tags: [handoff, personal-kanban]',
        'kind: task',
        'domain: team',
        f'source: {source_ref}',
        f'promoted_from: {_format_frontmatter_scalar(source_path)}',
        'next_action: 团队负责人确认交接输入并推进',
        '---',
    ]
    body = [
        '## 交接来源',
        '',
        f"- 个人卡：{local_task_id or '未编号'}",
        f"- 本地路径：{source_path}",
        f"- 目标团队项目：{team_project}",
        f"- 负责人：{assignee}",
        '',
        '## 要做什么',
        '',
        '请基于个人看板来源卡确认团队侧下一步、依赖和验收口径。',
        '',
        '## 完成标准',
        '',
        '- [ ] 团队侧负责人确认 scope',
        '- [ ] 团队板状态更新并保持回链可追踪',
        '',
        '## 执行结果',
        '<!-- 团队侧追加结果 -->',
        '',
    ]
    if draft:
        body.insert(0, '> 降级交接草稿：团队镜像当前不可安全写入，请人工复制到团队板。')
        body.insert(1, '')
    return '\n'.join(frontmatter) + '\n\n' + '\n'.join(body).rstrip() + '\n'


def _write_team_handoff_draft(sync_cfg, content, filename):
    draft_dir = _team_sync_state_path(sync_cfg, 'handoff_draft_dir')
    draft_dir.mkdir(parents=True, exist_ok=True)
    target = (draft_dir / filename).resolve()
    if not _path_is_relative_to(target, draft_dir.resolve()):
        return None, '非法草稿路径'
    _atomic_write_text(target, content)
    try:
        rel_path = str(target.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        rel_path = str(target)
    return rel_path, ''


def _team_handoff_options(config=None):
    source = config if isinstance(config, dict) else load_config()
    sync_cfg = _team_sync_config(source)
    repo_path, repo_err = _team_local_repo_path(sync_cfg)
    projects = []
    members = []
    if repo_path:
        project_root = repo_path / 'project'
        try:
            projects = sorted(
                path.name for path in project_root.iterdir()
                if path.is_dir() and not path.name.startswith(('.', '_'))
            )
        except OSError:
            projects = []
        team_cfg = _team_local_config(repo_path)
        if isinstance(team_cfg.get('members'), list):
            members = _normalize_string_list(team_cfg.get('members'))
    return {
        'ok': True,
        'repo_available': bool(repo_path and not repo_err),
        'repo_error': repo_err,
        'target_project': _team_handoff_default_project(sync_cfg),
        'projects': projects,
        'members': members,
        'publish_enabled': _team_handoff_publish_enabled(sync_cfg),
        'publish_remote': _team_handoff_publish_remote(sync_cfg),
        'publish_branch': _team_handoff_publish_branch(sync_cfg),
    }


def _backfill_team_handoff_source(rel_path, promoted_to=None, next_action=None, status=None, url=None):
    updates = []
    if promoted_to is not None:
        updates.append(('promoted_to', promoted_to))
    if status is not None:
        updates.append(('team_handoff_status', status))
    if url is not None:
        updates.append(('team_handoff_url', url))
    if next_action is not None:
        updates.append(('next_action', next_action))
    for field, value in updates:
        ok, msg = update_frontmatter_field(rel_path, field, value)[:2]
        if not ok:
            return False, f'回填 {field} 失败: {msg}'
    return True, ''


def _existing_team_handoff(task_file):
    fm = (task_file or {}).get('frontmatter') or {}
    status = _single_line_scalar(fm.get('team_handoff_status') or '')
    promoted_to = _single_line_scalar(fm.get('promoted_to') or '')
    url = _single_line_scalar(fm.get('team_handoff_url') or '')
    next_action = _single_line_scalar(fm.get('next_action') or '')
    is_written = status in {'pushed', 'written'}
    has_team_target = promoted_to.startswith('team-workspace/') or bool(url)
    if not (is_written and has_team_target):
        return None
    team_path = promoted_to[len('team-workspace/'):] if promoted_to.startswith('team-workspace/') else promoted_to
    return {
        'status': status,
        'promoted_to': promoted_to,
        'team_path': team_path,
        'url': url,
        'next_action': next_action,
    }


def _outbound_gate_ledger_path():
    return REPO_ROOT / 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl'


def _display_repo_path(path):
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT.resolve()))
    except Exception:
        return str(path)


def _outbound_gate_report_for_text(text, *, target, channel):
    ledger_path = _outbound_gate_ledger_path()
    normalized_channel = outbound_gate.normalize_channel(channel)
    try:
        result = outbound_gate.check_text(
            text,
            target=target,
            channel=normalized_channel,
            ledger_path=ledger_path,
            log=True,
        )
    except Exception as exc:
        return {
            'ok': False,
            'report_only': True,
            'channel': normalized_channel,
            'target': target,
            'verdict': 'error',
            'error': f'outbound_gate_failed:{exc.__class__.__name__}',
            'ledger_path': _display_repo_path(ledger_path),
        }
    return {
        'ok': True,
        'report_only': True,
        'channel': result.get('channel') or normalized_channel,
        'target': result.get('target') or target,
        'verdict': result.get('verdict') or '',
        'sha256': result.get('sha256') or '',
        'counts': result.get('counts') or {},
        'findings': result.get('findings') or [],
        'ledger_path': _display_repo_path(ledger_path),
    }


def preview_team_handoff(path, team_project, assignee, config=None, filename=None, priority=None):
    source = config if isinstance(config, dict) else load_config()
    sync_cfg = _team_sync_config(source)
    rel_path, err = _safe_task_path_value(path)
    if err:
        return {'ok': False, 'error': err}, 400
    task_file, err = _read_task_file(rel_path)
    if err:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
    assignee = _single_line_scalar(assignee)
    if not assignee:
        return {'ok': False, 'error': '缺少团队负责人'}, 400
    team_priority = _team_handoff_priority(task_file, priority)
    if not team_priority:
        return {'ok': False, 'error': f"团队优先级必须是 {sorted(TEAM_HANDOFF_PRIORITIES)}"}, 400
    existing_handoff = _existing_team_handoff(task_file)
    if existing_handoff:
        return {
            'ok': True,
            'mode': 'preview',
            'can_commit': False,
            'reason': 'already_pushed',
            'existing_handoff': existing_handoff,
            'source_path': rel_path,
            'team_project': team_project,
            'assignee': assignee,
            'priority': team_priority,
            'filename': '',
            'team_path': existing_handoff.get('team_path') or '',
            'proposed_team_card': {
                'path': existing_handoff.get('team_path') or '',
                'content': '',
            },
            'rules_read': [],
            'validation': {
                'ok': False,
                'errors': ['already_pushed'],
                'warnings': [],
                'checks': [{
                    'name': 'already_pushed',
                    'ok': False,
                    'message': '该个人卡已完成团队交接，不应重复推送',
                }],
                'inbox_symlink': {'required': True, 'path': '', 'target': ''},
            },
            'write_plan': [{
                'action': 'open_existing_team_card',
                'path': existing_handoff.get('team_path') or '',
            }],
            'sync_status': {},
            'publish_enabled': _team_handoff_publish_enabled(sync_cfg),
        }, 200
    local_task_id = _single_line_scalar((task_file.get('frontmatter') or {}).get('task_id') or '')
    filename, filename_err = _team_handoff_filename_for(
        local_task_id,
        (task_file.get('frontmatter') or {}).get('title') or '',
        filename,
    )
    if filename_err:
        return {'ok': False, 'error': filename_err}, 400

    repo_path, repo_err = _team_local_repo_path(sync_cfg)
    target_dir = None
    project_err = ''
    if repo_path:
        target_dir, project_err = _team_project_dir(repo_path, team_project)
    guard_ok = False
    guard_reason = repo_err or project_err
    freshness = {}
    if repo_path and target_dir and not guard_reason:
        guard_ok, guard_reason, freshness = _team_repo_write_guard(sync_cfg, repo_path, team_project)
        if guard_ok:
            publish_ok, publish_reason, publish_status = _team_handoff_publish_preflight(sync_cfg, repo_path)
            freshness['publish'] = publish_status
            if not publish_ok:
                guard_ok = False
                guard_reason = publish_reason

    rules_read = _discover_team_handoff_rules(repo_path, team_project)
    content = _team_handoff_card_text(task_file, team_project, assignee, draft=not guard_ok, priority=team_priority)
    team_rel_path = ''
    target_path = None
    validation = {
        'ok': False,
        'errors': [guard_reason or repo_err or project_err or 'team_repo_unavailable'],
        'warnings': [],
        'checks': [],
        'inbox_symlink': {'required': True, 'path': '', 'target': ''},
    }
    if repo_path and target_dir:
        target_path = (target_dir / filename).resolve()
        team_rel_path = str(target_path.relative_to(repo_path))
        validation = _validate_team_handoff_card(repo_path, team_project, assignee, target_path, content, priority=team_priority)
    outbound_report = _outbound_gate_report_for_text(
        content,
        target=team_rel_path or f'team-handoff:{team_project}/{filename}',
        channel='team-handoff',
    )
    missing_required_rules = [
        rule.get('path') for rule in rules_read
        if rule.get('required') and (not rule.get('exists') or rule.get('readable') is False)
    ]
    if missing_required_rules:
        validation.setdefault('errors', []).append('缺少必读规则: ' + ', '.join(missing_required_rules))
        validation.setdefault('checks', []).append({
            'name': 'required_rules',
            'ok': False,
            'message': '缺少必读规则: ' + ', '.join(missing_required_rules),
        })
        validation['ok'] = False
    else:
        validation.setdefault('checks', []).append({
            'name': 'required_rules',
            'ok': True,
            'message': '必读规则已读取',
        })

    can_commit = bool(repo_path and target_dir and guard_ok and validation.get('ok'))
    write_plan = []
    if can_commit:
        write_plan = [
            {'action': 'create_team_card', 'path': team_rel_path},
            {'action': 'create_or_verify_assignee_inbox_symlink', **(validation.get('inbox_symlink') or {})},
            {'action': 'publish_team_handoff_scoped_git', **(freshness.get('publish') or {'enabled': False})},
            {'action': 'backfill_personal_card', 'path': rel_path, 'fields': ['promoted_to', 'team_handoff_status', 'team_handoff_url', 'next_action']},
            {'action': 'sync_personal_team_pointer', 'path': _team_pointer_project(sync_cfg)},
            {'action': 'send_feishu_handoff_created', 'assignee': assignee, 'after': 'publish_success' if _team_handoff_publish_enabled(sync_cfg) else 'local_write'},
        ]
    else:
        write_plan = [
            {'action': 'write_local_handoff_draft', 'path': sync_cfg.get('handoff_draft_dir') or _DEFAULTS['team_sync']['handoff_draft_dir']},
            {'action': 'backfill_personal_card', 'path': rel_path, 'fields': ['team_handoff_status', 'next_action']},
        ]

    return {
        'ok': True,
        'mode': 'preview',
        'can_commit': can_commit,
        'reason': '' if can_commit else (guard_reason or repo_err or project_err or 'validation_failed'),
        'source_path': rel_path,
        'team_project': team_project,
        'assignee': assignee,
        'priority': team_priority,
        'filename': filename,
        'team_path': team_rel_path,
        'proposed_team_card': {
            'path': team_rel_path,
            'content': content,
        },
        'rules_read': rules_read,
        'validation': validation,
        'outbound_gate': outbound_report,
        'write_plan': write_plan,
        'sync_status': freshness,
        'publish_enabled': _team_handoff_publish_enabled(sync_cfg),
    }, 200


def commit_team_handoff(path, team_project, assignee, config=None, filename=None, confirmed=False, priority=None):
    if confirmed is not True:
        return {'ok': False, 'error': '需要人工确认后才能写入团队看板'}, 400
    source = config if isinstance(config, dict) else load_config()
    preview, status = preview_team_handoff(path, team_project, assignee, config=source, filename=filename, priority=priority)
    if status != 200 or not preview.get('ok'):
        return preview, status
    if preview.get('reason') == 'already_pushed':
        return {
            'ok': False,
            'error': '该个人卡已完成团队交接，不要重复推送',
            'existing_handoff': preview.get('existing_handoff') or {},
        }, 409
    sync_cfg = _team_sync_config(source)
    rel_path = preview.get('source_path') or ''
    filename = preview.get('filename') or ''
    team_priority = preview.get('priority') or ''
    content = (preview.get('proposed_team_card') or {}).get('content') or ''

    if not preview.get('can_commit'):
        draft_path, draft_err = _write_team_handoff_draft(sync_cfg, content, filename)
        if draft_err:
            return {'ok': False, 'error': draft_err}, 500
        _backfill_team_handoff_source(rel_path, next_action='handoff-team-draft', status='draft')
        return {
            'ok': True,
            'mode': 'draft',
            'reason': preview.get('reason') or 'team_repo_unavailable',
            'draft_path': draft_path,
            'outbound_gate': preview.get('outbound_gate') or {},
            'rules_read': preview.get('rules_read') or [],
            'validation': preview.get('validation') or {},
            'sync_status': preview.get('sync_status') or {},
        }, 200

    repo_path, repo_err = _team_local_repo_path(sync_cfg)
    if not repo_path:
        return {'ok': False, 'error': repo_err or 'team_repo_unavailable'}, 500
    target_dir, project_err = _team_project_dir(repo_path, team_project)
    if not target_dir:
        return {'ok': False, 'error': project_err}, 400
    target_path = (target_dir / filename).resolve()
    if not _path_is_relative_to(target_path, target_dir.resolve()):
        return {'ok': False, 'error': '非法团队卡路径'}, 400
    if target_path.exists():
        return {'ok': False, 'error': '团队卡已存在'}, 409
    validation = _validate_team_handoff_card(repo_path, team_project, assignee, target_path, content, priority=team_priority)
    if not validation.get('ok'):
        return {'ok': False, 'error': '团队卡校验失败', 'validation': validation}, 400

    publish_enabled = _team_handoff_publish_enabled(sync_cfg)
    publish_result = None
    if publish_enabled:
        task_file_for_title, _title_err = _read_task_file(rel_path)
        publish_title = ((task_file_for_title or {}).get('frontmatter') or {}).get('title') or ''
        publish_result = publish_team_handoff(
            sync_cfg,
            repo_path,
            team_project,
            assignee,
            filename,
            content,
            title=publish_title,
        )
        if not publish_result.get('ok'):
            draft_path, draft_err = _write_team_handoff_draft(sync_cfg, content, filename)
            if draft_err:
                return {'ok': False, 'error': draft_err, 'publish': publish_result}, 500
            _backfill_team_handoff_source(rel_path, next_action='handoff-team-publish-blocked', status='publish-blocked')
            return {
                'ok': True,
                'mode': 'publish_blocked',
                'reason': publish_result.get('reason') or 'publish_failed',
                'draft_path': draft_path,
                'publish': publish_result,
                'outbound_gate': preview.get('outbound_gate') or {},
                'rules_read': publish_result.get('rules_read') or preview.get('rules_read') or [],
                'validation': publish_result.get('validation') or validation,
                'sync_status': preview.get('sync_status') or {},
            }, 200
        team_rel_path = publish_result.get('team_path') or preview.get('team_path') or ''
        symlink_path = publish_result.get('assignee_inbox_symlink') or ''
        symlink_status = publish_result.get('assignee_inbox_symlink_status') or ''
        remote_url = publish_result.get('url') or ''
    else:
        _atomic_write_text(target_path, content)
        symlink_path, symlink_status, symlink_err = _ensure_team_assignee_inbox_symlink(repo_path, assignee, target_path)
        if symlink_err:
            try:
                target_path.unlink()
            except OSError:
                pass
            return {'ok': False, 'error': f'负责人 inbox symlink 失败: {symlink_err}'}, 500
        team_rel_path = str(target_path.relative_to(repo_path))
        remote_url = ''

    promoted_to = f"team-workspace/{team_rel_path}"
    next_action = 'handoff-team-published' if publish_enabled else 'handoff-team'
    status_value = 'pushed' if publish_enabled else 'written'
    ok, msg = _backfill_team_handoff_source(
        rel_path,
        promoted_to=promoted_to,
        next_action=next_action,
        status=status_value,
        url=remote_url,
    )
    if not ok:
        return {'ok': False, 'error': msg}, 500

    try:
        pointer_sync = sync_team_handoff_pointer(
            team_rel_path,
            team_project,
            content,
            remote_url=remote_url,
            config=source,
        )
    except Exception as exc:
        pointer_sync = {'ok': False, 'reason': f'pointer_sync_failed:{exc}'}

    task_file, _err = _read_task_file(rel_path)
    fm = (task_file or {}).get('frontmatter') or {}
    local_task_id = _single_line_scalar(fm.get('task_id') or '')
    feishu_notify.set_config(_normalize_feishu_config(source))
    feishu_warning = feishu_notify.notify_member_event(
        assignee,
        'handoff_created',
        f"个人看板交接到团队：{fm.get('title') or local_task_id}",
        fields=[
            ('团队项目', team_project),
            ('来源', f'personal-kanban/{local_task_id}' if local_task_id else 'personal-kanban/unknown'),
            ('优先级', team_priority),
            ('团队卡位置', team_rel_path),
            ('发布状态', status_value),
        ],
        url=remote_url,
    )
    response = {
        'ok': True,
        'mode': 'pushed' if publish_enabled else 'written',
        'team_path': team_rel_path,
        'priority': team_priority,
        'promoted_to': promoted_to,
        'remote_url': remote_url,
        'assignee_inbox_symlink': symlink_path,
        'assignee_inbox_symlink_status': symlink_status,
        'outbound_gate': preview.get('outbound_gate') or {},
        'rules_read': preview.get('rules_read') or [],
        'validation': validation,
        'sync_status': preview.get('sync_status') or {},
        'pointer_sync': pointer_sync,
    }
    if publish_result:
        response['publish'] = publish_result
    if feishu_warning:
        response['feishu_warning'] = feishu_warning
    return response, 200


def handoff_task_to_team(path, team_project, assignee, config=None, priority=None):
    return commit_team_handoff(path, team_project, assignee, config=config, confirmed=True, priority=priority)


def _research_panel_for_project(project_dir):
    """在项目目录内（深度 ≤2）找面板：*_Panel.html 优先，其次 PANEL.md 指针文件。

    PANEL.md 首个非空、非注释行视为指针：http(s) URL 或相对项目目录的路径。
    """
    html_candidates = sorted(project_dir.glob('*_Panel.html')) + sorted(project_dir.glob('*/*_Panel.html'))
    if html_candidates:
        return {'path': str(html_candidates[0]), 'url': ''}
    pointer_candidates = sorted(project_dir.glob('PANEL.md')) + sorted(project_dir.glob('*/PANEL.md'))
    for pointer in pointer_candidates:
        try:
            lines = pointer.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        for line in lines:
            value = line.strip()
            if not value or value.startswith('#') or value.startswith('>'):
                continue
            if value.startswith('http://') or value.startswith('https://'):
                return {'path': '', 'url': value}
            target = (pointer.parent / value).resolve()
            if target.exists():
                return {'path': str(target), 'url': ''}
            break
    return None


def discover_research_boards(config=None):
    """研究项目板列表：config research_boards 手动项优先，再自动发现。

    自动发现扫 research_boards_dir 下的项目目录（跳过 . / _ 前缀，如 _archive），
    与桥接固定入口不同：研究板是纯链接（本地 HTML 或远程 URL），不起进程。
    按项目名去重，config 内的同名项覆盖自动发现。
    """
    config = config if isinstance(config, dict) else load_config()
    boards = []
    seen = set()
    raw_entries = config.get('research_boards')
    for entry in (raw_entries if isinstance(raw_entries, list) else []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('name') or '').strip()
        url = str(entry.get('url') or '').strip()
        path = str(entry.get('path') or '').strip()
        if not name or not (url or path):
            continue
        if path:
            path = os.path.expanduser(path)
        boards.append({'name': name, 'url': url, 'path': path})
        seen.add(name)
    root_value = str(config.get('research_boards_dir') or _DEFAULTS['research_boards_dir'])
    if not root_value.strip():
        return boards
    root = Path(os.path.expanduser(root_value))
    if not root.is_absolute():
        root = REPO_ROOT / root
    if root.is_dir():
        for project_dir in sorted(root.iterdir()):
            if not project_dir.is_dir() or project_dir.name.startswith(('.', '_')):
                continue
            if project_dir.name in seen:
                continue
            panel = _research_panel_for_project(project_dir)
            if panel:
                boards.append({'name': project_dir.name, **panel})
    return boards


def run_network_doctor_action(action, *, confirmed=False):
    config = load_config()
    doctor_config = config.get('network_doctor') if isinstance(config, dict) else None
    return network_doctor_panel.run(action, confirmed=confirmed, config=doctor_config)


def _apply_verge_tun_global_preset(*, confirmed=False, requested_name='verge_tun_global'):
    """Delegate the verified Clash Verge preset to the confirmed doctor fix."""
    result, status = run_network_doctor_action('fix', confirmed=confirmed)
    if result.get('ok'):
        result['preset'] = 'verge_tun_global'
        if requested_name != 'verge_tun_global':
            result['preset_alias'] = requested_name
        result['message'] = (result.get('diagnosis') or {}).get('conclusion') or '网络医生已执行'
    return result, status


def apply_network_preset(preset, *, confirmed=False):
    if preset in {'verge_tun_global', 'tag_tun_global'}:
        return _apply_verge_tun_global_preset(confirmed=confirmed, requested_name=preset)
    return {'ok': False, 'error': 'invalid preset'}, 400


def _safe_repo_path(path_value, *, allow_exts=None):
    """Resolve a repo-relative path and ensure it stays under REPO_ROOT."""
    if not path_value:
        return None, '缺少路径'
    decoded_path = unquote(str(path_value))
    if '..' in decoded_path or decoded_path.startswith('/'):
        return None, '非法路径'
    candidate = (REPO_ROOT / decoded_path).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None, '非法路径'
    if allow_exts is not None and candidate.suffix.lower() not in allow_exts:
        return None, '仅支持图片文件'
    return candidate, None


def _get_project_name_from_path(path_value):
    task_rel = _task_rel_path_in_scan_dirs(path_value)
    if task_rel is None:
        return ''
    candidate = (REPO_ROOT / task_rel).resolve(strict=False)
    matches = []
    for project_dir in _iter_project_dirs():
        resolved = project_dir.resolve(strict=False)
        if _path_is_relative_to(candidate, resolved):
            matches.append(resolved)
    if not matches:
        return candidate.parent.name
    return max(matches, key=lambda item: len(item.parts)).name


def _content_type_for_image(path_obj):
    ctype, _ = mimetypes.guess_type(str(path_obj))
    return ctype or 'application/octet-stream'


def _aws_sign(key_bytes, msg):
    return hmac.new(key_bytes, msg.encode('utf-8'), hashlib.sha256).digest()


def _build_s3_presigned_post(path, filename, content_type):
    """
    Build a provider-agnostic S3-style presigned POST contract.
    Config source:
      .kanban.config.json -> s3
      .kanban.user.config.json -> s3
      KANBAN_S3_* env vars as fallback
    """
    s3_cfg = _normalize_s3_config({'s3': S3_CONFIG})
    bucket = str(s3_cfg.get('bucket', '')).strip()
    region = str(s3_cfg.get('region', '')).strip()
    access_key = str(s3_cfg.get('access_key_id', '')).strip()
    secret_key = str(s3_cfg.get('secret_access_key', '')).strip()
    public_base_url = str(s3_cfg.get('public_base_url', '')).strip().rstrip('/')
    upload_url = str(s3_cfg.get('upload_url', '')).strip().rstrip('/')
    if not all([bucket, region, access_key, secret_key, public_base_url]):
        missing = [
            f'{key} ({env_name})' for key, env_name, value in [
                ('bucket', _S3_ENV_MAP['bucket'], bucket),
                ('region', _S3_ENV_MAP['region'], region),
                ('access_key_id', _S3_ENV_MAP['access_key_id'], access_key),
                ('secret_access_key', _S3_ENV_MAP['secret_access_key'], secret_key),
                ('public_base_url', _S3_ENV_MAP['public_base_url'], public_base_url),
            ]
            if not value
        ]
        return None, f"缺少 S3 配置: {', '.join(missing)}"

    task_path, err = _safe_repo_path(path)
    if err:
        return None, err
    if not task_path.exists():
        return None, '文件不存在'

    project = _get_project_name_from_path(path)
    if not project:
        return None, '仅支持 scan_dirs 内的任务卡'

    if not filename:
        return None, '缺少文件名'
    clean_filename = Path(filename).name
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', Path(clean_filename).stem).strip('-') or 'image'
    ext = Path(clean_filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return None, '仅支持图片文件'
    object_key = f"kanban/{project}/markdown-images/{uuid.uuid4().hex}{ext}"

    now = datetime.now(UTC)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    credential_scope = f'{date_stamp}/{region}/s3/aws4_request'
    credential = f'{access_key}/{credential_scope}'
    expiration = (now.timestamp() + 3600)
    expiration_iso = datetime.fromtimestamp(expiration, UTC).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    policy_doc = {
        'expiration': expiration_iso,
        'conditions': [
            {'bucket': bucket},
            {'key': object_key},
            {'Content-Type': content_type},
            {'x-amz-algorithm': _AWS_ALGORITHM},
            {'x-amz-credential': credential},
            {'x-amz-date': amz_date},
            ['content-length-range', 1, 10 * 1024 * 1024],
        ],
    }
    policy_json = json.dumps(policy_doc, separators=(',', ':'))
    policy_b64 = base64.b64encode(policy_json.encode('utf-8')).decode('ascii')
    k_date = _aws_sign(('AWS4' + secret_key).encode('utf-8'), date_stamp)
    k_region = _aws_sign(k_date, region)
    k_service = _aws_sign(k_region, 's3')
    k_signing = _aws_sign(k_service, 'aws4_request')
    signature = hmac.new(k_signing, policy_b64.encode('utf-8'), hashlib.sha256).hexdigest()

    final_url = f'{public_base_url}/{object_key}'
    return {
        'upload_url': upload_url or f'https://{bucket}.s3.{region}.amazonaws.com',
        'final_url': final_url,
        'method': 'POST',
        'fields': {
            'key': object_key,
            'Content-Type': content_type,
            'Policy': policy_b64,
            'X-Amz-Algorithm': _AWS_ALGORITHM,
            'X-Amz-Credential': credential,
            'X-Amz-Date': amz_date,
            'X-Amz-Signature': signature,
        },
        'max_bytes': 10 * 1024 * 1024,
        'key': object_key,
        'project': project,
        'original_name': stem + ext,
    }, None

# ── AI 队列（全局 .ai-queue.json）────────────────────────

_queue_lock = threading.RLock()
_ORPHANED_RUNNING = 'orphaned-running'
_ORPHANED_UNKNOWN = 'orphaned-unknown'
_ACTIVE_QUEUE_STATUSES = {'queued', 'running', _ORPHANED_RUNNING}

def _queue_file():
    return REPO_ROOT / '.ai-queue.json'

def _queue_default():
    return {'concurrency': AI_MAX_CONCURRENT, 'entries': []}

def _truncate_title(text, max_len=60):
    """将 AI 输出压缩为线程标题。"""
    if not text:
        return 'AI 对话'
    for line in str(text).strip().splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^[#>*\-\s]+', '', line).strip()
        if len(line) > max_len:
            return line[:max_len].rstrip() + '...'
        return line
    return 'AI 对话'

def _migrate_entry_to_thread(entry):
    """把旧队列条目迁移为线程格式。"""
    if 'messages' not in entry or not isinstance(entry.get('messages'), list):
        entry['messages'] = []
        output = entry.get('output')
        if output:
            entry['messages'].append({
                'role': 'ai',
                'content': output,
                'timestamp': entry.get('completed_at') or entry.get('timestamp'),
                'duration_ms': entry.get('duration_ms'),
                'model': None,
                'input_tokens': None,
                'output_tokens': None,
            })
        entry['session_id'] = None
        entry['session_valid'] = False
        entry['title'] = _truncate_title(output)
        return True
    changed = False
    if entry.get('status') == 'completed' and entry.get('error'):
        entry['error'] = None
        changed = True
    if 'session_id' not in entry:
        entry['session_id'] = None
        changed = True
    if 'session_valid' not in entry:
        entry['session_valid'] = bool(entry.get('session_id'))
        changed = True
    if 'title' not in entry:
        title_source = None
        if entry.get('messages'):
            for msg in entry['messages']:
                if msg.get('role') == 'ai' and msg.get('content'):
                    title_source = msg.get('content')
                    break
        if not title_source:
            title_source = entry.get('output')
        entry['title'] = _truncate_title(title_source)
        changed = True
    return changed


def _latest_ai_message_from_entry(entry):
    for msg in reversed((entry or {}).get('messages') or []):
        if str((msg or {}).get('role') or '') == 'ai' and (msg or {}).get('content'):
            return dict(msg)
    return None


def _latest_ai_message_from_ledger(entry):
    path = str((entry or {}).get('path') or '')
    run_id = str((entry or {}).get('id') or '')
    if not path or not run_id:
        return None
    events, err = _ledger_read_events(path)
    if err or not events:
        return None
    latest = None
    latest_idx = -1
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get('event') != 'message' or event.get('run_id') != run_id:
            continue
        if event.get('role') != 'ai' or not event.get('content'):
            continue
        try:
            idx = int(event.get('idx'))
        except (TypeError, ValueError):
            idx = latest_idx + 1
        if idx >= latest_idx:
            latest_idx = idx
            latest = {
                'role': 'ai',
                'content': event.get('content') or '',
                'timestamp': event.get('ts') or event.get('timestamp'),
                'duration_ms': event.get('duration_ms'),
                'model': event.get('model'),
                'input_tokens': event.get('input_tokens'),
                'output_tokens': event.get('output_tokens'),
            }
    return latest


def _recover_running_entry_from_durable_message(entry, now):
    """If a worker wrote an AI message before status update, recover it on restart."""
    msg = _latest_ai_message_from_entry(entry)
    if not msg:
        msg = _latest_ai_message_from_ledger(entry)
        if msg:
            messages = entry.get('messages')
            if not isinstance(messages, list):
                messages = []
                entry['messages'] = messages
            messages.append(msg)
    if not msg:
        return False
    content = str(msg.get('content') or '')
    if not content:
        return False
    entry['status'] = 'completed'
    entry['output'] = content
    entry['error'] = None
    entry['pid'] = None
    entry['completed_at'] = msg.get('timestamp') or now
    entry['duration_ms'] = msg.get('duration_ms') if msg.get('duration_ms') is not None else entry.get('duration_ms')
    entry['output_length'] = len(content)
    if not entry.get('title'):
        entry['title'] = _truncate_title(content)
    if 'session_valid' not in entry:
        entry['session_valid'] = bool(entry.get('session_id'))
    return True

# ---------------- 评论分支 · 耐久台账 (KAN-111) ----------------
# 设计:队列(.ai-queue.json)/结果(task.ai-results.jsonl)是会被清理的运行态;
# ledger.jsonl 是只增事件台账(锚),入 git,给分支树与 canvas source_ref{kind:'comment'} 提供稳定 entry_id。
# entry_id = "<run_id>#<消息序号>"(messages[] 只增,故天然稳定)。
COMMENTS_LEDGER_SCHEMA = 'kanban.comments/v1'
COMMENTS_PROMPT_AUDIT_VERSION = 'ai-run-prompt-ledger/v1'
CARD_LINEAGE_SCHEMA = 'kanban.card-lineage/v1'
_LEDGER_LOCK = threading.Lock()
_LINEAGE_TRACKED_FRONTMATTER_FIELDS = {
    'status', 'assignee', 'priority', 'due_date', 'next_action',
    'workdir', 'title',
}
_LINEAGE_TERMINAL_STATUSES = {'completed', 'error', 'timeout', 'killed'}
_LINEAGE_FORBIDDEN_KEYS = {
    'content', 'output', 'prompt', 'prompt_override', 'stdout', 'stderr',
    'raw', 'body', 'messages',
}


def _comments_ledger_config(config=None):
    source = config if isinstance(config, dict) else load_config()
    raw = source.get('comments_ledger')
    merged = dict(_DEFAULTS.get('comments_ledger') or {})
    if isinstance(raw, dict):
        merged.update({k: raw[k] for k in ('enabled', 'ai_content', 'digest_chars') if k in raw})
    try:
        merged['digest_chars'] = max(200, int(merged.get('digest_chars', 2000)))
    except (TypeError, ValueError):
        merged['digest_chars'] = 2000
    if merged.get('ai_content') not in ('digest', 'full'):
        merged['ai_content'] = 'digest'
    return merged


def _task_id_from_rel_path(task_rel_path):
    stem = Path(str(task_rel_path or '')).stem
    m = re.match(r'^([A-Za-z]+-\d+)', stem)
    return m.group(1) if m else stem


def _path_in_scan_dirs(candidate):
    """Return whether a resolved repository path belongs to configured scan_dirs."""
    try:
        resolved = Path(candidate).resolve(strict=False)
        resolved.relative_to(REPO_ROOT.resolve(strict=False))
    except (OSError, ValueError):
        return False
    for raw_scan_dir in SCAN_DIRS:
        scan_root = (REPO_ROOT / str(raw_scan_dir or '')).resolve(strict=False)
        if _path_is_relative_to(resolved, scan_root):
            return True
    return False


def _task_rel_path_in_scan_dirs(task_rel_path):
    candidate, err = _safe_repo_path(task_rel_path)
    if err or candidate.suffix.lower() != '.md' or not _path_in_scan_dirs(candidate):
        return None
    try:
        return candidate.relative_to(REPO_ROOT.resolve(strict=False))
    except ValueError:
        return None


def _ledger_rel_for_task(task_rel_path):
    """台账 sidecar 路径:<scan_dir>/.comments/<task_id>/ledger.jsonl。"""
    task_path = _task_rel_path_in_scan_dirs(task_rel_path)
    if task_path is None:
        return None
    key = _CANVAS_ID_SAFE_RE.sub('-', _task_id_from_rel_path(task_rel_path)).strip('-._') or task_path.stem
    return str(task_path.parent / '.comments' / key / 'ledger.jsonl')


def _ledger_append_events(task_rel_path, events):
    """只增追加;单次 write + 锁;任何失败静默返回 False(台账绝不阻塞 AI 执行)。"""
    try:
        rel = _ledger_rel_for_task(task_rel_path)
        if not rel or not events:
            return False
        abs_path = (REPO_ROOT / rel).resolve()
        abs_path.relative_to(REPO_ROOT.resolve())  # jail:只写仓内
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        payload = ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events)
        with _LEDGER_LOCK:
            with open(abs_path, 'a', encoding='utf-8') as fh:
                fh.write(payload)
        return True
    except Exception:
        return False


def _ledger_read_events(task_rel_path):
    rel = _ledger_rel_for_task(task_rel_path)
    if not rel:
        return None, 'Ledger 只支持 scan_dirs 内的 Markdown 任务卡'
    abs_path = REPO_ROOT / rel
    if not abs_path.exists():
        return [], ''
    events = []
    try:
        with open(abs_path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 坏行跳过,只增文件不回改
    except OSError as e:
        return None, str(e)
    return events, ''


def _lineage_rel_for_task(task_rel_path):
    """卡片血缘 sidecar: <scan_dir>/.lineage/<task_id>/ledger.jsonl。"""
    task_path = _task_rel_path_in_scan_dirs(task_rel_path)
    if task_path is None:
        return None
    key = _CANVAS_ID_SAFE_RE.sub('-', _task_id_from_rel_path(task_rel_path)).strip('-._') or task_path.stem
    return str(task_path.parent / '.lineage' / key / 'ledger.jsonl')


def _lineage_event_id(event_type, *parts):
    seed = '|'.join(str(p or '') for p in (event_type,) + parts)
    return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]


def _lineage_now():
    return datetime.now().replace(microsecond=0).isoformat()


def _lineage_short_text(value, limit=500):
    text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
    return text[:limit]


def _lineage_digest_fields(prefix, text):
    value = str(text or '')
    return {
        f'{prefix}_len': len(value),
        f'{prefix}_sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()[:16],
    }


def _lineage_clean_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            k = str(key)
            if k in _LINEAGE_FORBIDDEN_KEYS:
                continue
            if k.endswith('_content') or k.endswith('_output') or k.endswith('_prompt'):
                continue
            clean[k] = _lineage_clean_value(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_lineage_clean_value(item) for item in list(value)[:20]]
    return _lineage_short_text(value)


def _lineage_clean_event(event):
    clean = {}
    for key, value in dict(event or {}).items():
        k = str(key)
        if k in _LINEAGE_FORBIDDEN_KEYS:
            continue
        if k.endswith('_content') or k.endswith('_output') or k.endswith('_prompt'):
            continue
        clean[k] = _lineage_clean_value(value)
    return clean


def _lineage_base_event(task_rel_path, event_type, actor='kanban', event_id=None):
    return {
        'v': 1,
        'schema': CARD_LINEAGE_SCHEMA,
        'event': event_type,
        'event_id': event_id or uuid.uuid4().hex[:12],
        'ts': _lineage_now(),
        'task_id': _task_id_from_rel_path(task_rel_path),
        'path': str(task_rel_path or ''),
        'actor': _lineage_short_text(actor or 'kanban', 80),
        'sensitivity': 'metadata_only',
    }


def _lineage_tool_session_fields(tool, session_id):
    tool_name = str(tool or '').strip().lower()
    sid = str(session_id or '').strip()
    if tool_name == 'codex':
        fields = {'tool_session_kind': 'codex_thread'}
        if sid:
            fields['thread_id'] = sid
        return fields
    if tool_name == 'claude':
        fields = {'tool_session_kind': 'claude_session'}
        if sid:
            fields['session_id'] = sid
        return fields
    fields = {'tool_session_kind': 'unknown'}
    if sid:
        fields['session_id'] = sid
    return fields


def _lineage_append_events(task_rel_path, events):
    """只增追加并按 event_id 去重;失败返回 None,不阻断主流程。"""
    try:
        rel = _lineage_rel_for_task(task_rel_path)
        if not rel or not events:
            return 0
        abs_path = (REPO_ROOT / rel).resolve()
        abs_path.relative_to(REPO_ROOT.resolve())
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if abs_path.exists():
            with open(abs_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    try:
                        item = json.loads(line.strip())
                    except Exception:
                        continue
                    if isinstance(item, dict) and item.get('event_id'):
                        existing.add(str(item.get('event_id')))
        to_write = []
        for event in events:
            clean = _lineage_clean_event(event)
            event_id = str(clean.get('event_id') or uuid.uuid4().hex[:12])
            if event_id in existing:
                continue
            clean['event_id'] = event_id
            clean.setdefault('v', 1)
            clean.setdefault('schema', CARD_LINEAGE_SCHEMA)
            clean.setdefault('sensitivity', 'metadata_only')
            to_write.append(clean)
            existing.add(event_id)
        if not to_write:
            return 0
        payload = ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in to_write)
        with _LEDGER_LOCK:
            with open(abs_path, 'a', encoding='utf-8') as fh:
                fh.write(payload)
        return len(to_write)
    except Exception:
        return None


def _lineage_read_events(task_rel_path):
    rel = _lineage_rel_for_task(task_rel_path)
    if not rel:
        return None, 'Lineage 只支持 scan_dirs 内的 Markdown 任务卡'
    abs_path = REPO_ROOT / rel
    if not abs_path.exists():
        return [], ''
    events = []
    try:
        with open(abs_path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        return None, str(e)
    return events, ''


def _lineage_record_event(task_rel_path, event_type, actor='kanban', event_id=None, **fields):
    event = _lineage_base_event(task_rel_path, event_type, actor=actor, event_id=event_id)
    event.update(fields)
    return _lineage_append_events(task_rel_path, [event]) is not None


def _lineage_record_frontmatter_change(task_rel_path, field, old_value, new_value, *, actor='kanban', old_path=None):
    if field not in _LINEAGE_TRACKED_FRONTMATTER_FIELDS:
        return True
    if str(old_value or '').strip() == str(new_value or '').strip():
        return True
    payload = {
        'field': field,
        'old_value': _lineage_short_text(old_value),
        'new_value': _lineage_short_text(new_value),
    }
    if old_path and old_path != task_rel_path:
        payload['old_path'] = old_path
    return _lineage_record_event(task_rel_path, 'frontmatter_changed', actor=actor, **payload)


def _lineage_record_card_created(task_rel_path, fm, *, actor='kanban'):
    fm = fm or {}
    payload = {
        'title': fm.get('title') or '',
        'assignee': fm.get('assignee') or '',
        'priority': fm.get('priority') or '',
        'status': fm.get('status') or '',
        'workdir': fm.get('workdir') or '',
    }
    if fm.get('promoted_from'):
        payload['promoted_from'] = fm.get('promoted_from')
    return _lineage_record_event(task_rel_path, 'card_created', actor=actor, **payload)


def _lineage_record_queue_entry_created(entry):
    path = str((entry or {}).get('path') or '')
    run_id = str((entry or {}).get('id') or '')
    if not path or not run_id:
        return True
    metadata = entry.get('metadata') if isinstance(entry.get('metadata'), dict) else {}
    fork_meta = metadata.get('fork') if isinstance(metadata.get('fork'), dict) else {}
    event_type = 'ai_fork_queued' if fork_meta else 'ai_run_queued'
    payload = {
        'run_id': run_id,
        'tool': entry.get('tool') or '',
        'workdir': entry.get('workdir') or '',
        'status': entry.get('status') or '',
        'origin': ((metadata.get('dialogue') or {}).get('origin') if isinstance(metadata.get('dialogue'), dict) else '') or 'card',
    }
    if fork_meta:
        payload['parent_run_id'] = fork_meta.get('parent_run_id') or ''
        payload['parent_entry_id'] = fork_meta.get('parent_entry_id') or ''
        payload['parent_index'] = fork_meta.get('parent_index')
    return _lineage_record_event(path, event_type, actor='kanban-ai', **payload)


def _lineage_record_ai_message(entry_snapshot, idx, message):
    path = str((entry_snapshot or {}).get('path') or '')
    run_id = str((entry_snapshot or {}).get('id') or '')
    if not path or not run_id:
        return True
    role = str((message or {}).get('role') or '')
    if role != 'user':
        return True
    content = str((message or {}).get('content') or '')
    payload = {
        'run_id': run_id,
        'entry_id': f'{run_id}#{idx}',
        'idx': idx,
        'role': role,
        'author': (message or {}).get('author') or '用户',
        'tool': (entry_snapshot or {}).get('tool') or '',
        **_lineage_digest_fields('message', content),
    }
    if (message or {}).get('forked_from'):
        payload['forked_from'] = (message or {}).get('forked_from')
    for key in ('skill_id', 'skill_name', 'skill_applied'):
        if (message or {}).get(key) is not None:
            payload[key] = (message or {}).get(key)
    return _lineage_record_event(path, 'ai_comment_added', actor=payload['author'], **payload)


def _lineage_record_queue_update(before, updates, after):
    path = str((after or {}).get('path') or (before or {}).get('path') or '')
    run_id = str((after or {}).get('id') or (before or {}).get('id') or '')
    if not path or not run_id:
        return True
    status = str((after or {}).get('status') or '')
    old_status = str((before or {}).get('status') or '')
    updates = updates or {}
    if status in _LINEAGE_TERMINAL_STATUSES and status != old_status:
        event_type = 'ai_run_completed' if status == 'completed' else 'ai_run_finished'
    elif 'session_id' in updates and updates.get('session_id'):
        event_type = 'ai_session_captured'
    else:
        return True
    payload = {
        'run_id': run_id,
        'tool': (after or {}).get('tool') or '',
        'status': status,
        'previous_status': old_status,
        'duration_ms': (after or {}).get('duration_ms'),
        'output_length': (after or {}).get('output_length', 0),
        'session_valid': (after or {}).get('session_valid', True),
    }
    payload.update(_lineage_tool_session_fields(payload['tool'], (after or {}).get('session_id')))
    if (after or {}).get('error'):
        payload.update(_lineage_digest_fields('error', (after or {}).get('error')))
    return _lineage_record_event(path, event_type, actor='kanban-ai', **payload)


def _lineage_record_canvas_events(task_rel_path, canvas_events, canvas_rel, actor='kanban'):
    events = []
    for item in canvas_events or []:
        if not isinstance(item, dict):
            continue
        if item.get('event') not in {'node_added', 'node_bound'}:
            continue
        source_ref = item.get('source_ref') if isinstance(item.get('source_ref'), dict) else {}
        if not source_ref and not item.get('run_id'):
            continue
        event = _lineage_base_event(task_rel_path, 'canvas_source_bound', actor=actor)
        event.update({
            'canvas_ref': canvas_rel,
            'canvas_event': item.get('event'),
            'node_id': item.get('node_id') or '',
            'node_type': item.get('node_type') or '',
            'source_ref': source_ref,
        })
        run_id = item.get('run_id') or source_ref.get('run_id')
        if run_id:
            event['run_id'] = run_id
        events.append(event)
    return _lineage_append_events(task_rel_path, events) is not None


def _lineage_record_archive(task_rel_path, archived_path, actor='kanban'):
    return _lineage_record_event(
        task_rel_path,
        'card_archived',
        actor=actor,
        archived_path=archived_path,
    )


_LINEAGE_PILOT_BACKFILL = {
    'KAN-109': {
        'summary': 'Converse/Canvas 方向卡: 看板是事实源, 画布是投影。',
        'relations': ['KAN-110', 'KAN-111'],
    },
    'KAN-110': {
        'summary': 'Canvas Studio 执行卡: 本地画布子应用、RefNode、DialogueNode 与按需投影。',
        'relations': ['KAN-109', 'KAN-111'],
    },
    'KAN-111': {
        'summary': '评论分支模型卡: parent 指针与 .comments 台账是血缘层输入之一。',
        'relations': ['KAN-110'],
    },
    'KAN-166': {
        'summary': 'Claude Fleet 处置卡: 不做常驻面板, 保留 am find 与卡片血缘元数据。',
        'relations': ['KAN-109', 'KAN-110', 'KAN-111'],
    },
}


def backfill_card_lineage(task_ids=None, dry_run=True):
    """KAN-167 试点回填:固定小范围、确定性 event_id、可复跑。"""
    targets = list(task_ids or _LINEAGE_PILOT_BACKFILL.keys())
    docs = {str(doc.get('task_id') or ''): doc for doc in scan_all()}
    rows = []
    for task_id in targets:
        spec = _LINEAGE_PILOT_BACKFILL.get(task_id, {})
        doc = docs.get(task_id)
        if not doc:
            rows.append({'task_id': task_id, 'status': 'missing'})
            continue
        rel_path = doc.get('path') or ''
        event_id = _lineage_event_id('backfill', 'KAN-167', task_id)
        existing, err = _lineage_read_events(rel_path)
        if existing is None:
            rows.append({'task_id': task_id, 'path': rel_path, 'status': 'error', 'error': err})
            continue
        already = any(str(e.get('event_id') or '') == event_id for e in existing if isinstance(e, dict))
        event = _lineage_base_event(rel_path, 'pilot_backfill', actor='kanban-167', event_id=event_id)
        event.update({
            'summary': spec.get('summary') or '',
            'source_card': 'KAN-167',
            'related_cards': spec.get('relations') or [],
            'title': doc.get('title') or '',
            'status': doc.get('status') or '',
            'assignee': doc.get('assignee') or '',
            'workdir': doc.get('workdir') or '',
        })
        if already:
            rows.append({
                'task_id': task_id,
                'path': rel_path,
                'status': 'skipped',
                'reason': 'event_id exists',
                'event': event,
            })
            continue
        if dry_run:
            rows.append({'task_id': task_id, 'path': rel_path, 'status': 'would_write', 'event': event})
            continue
        appended = _lineage_append_events(rel_path, [event])
        if appended is None:
            rows.append({'task_id': task_id, 'path': rel_path, 'status': 'error', 'error': 'append failed'})
        else:
            rows.append({'task_id': task_id, 'path': rel_path, 'status': 'written' if appended else 'skipped', 'event': event})
    return {
        'ok': True,
        'schema': CARD_LINEAGE_SCHEMA,
        'dry_run': bool(dry_run),
        'targets': rows,
    }


def _ledger_content_fields(role, content, config=None):
    """user 消息全文(Owner 的判断=最值钱的决策记录);AI 消息按 config 摘要+sha 指纹,可证伪可对账。"""
    text = str(content or '')
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    cfg = _comments_ledger_config(config)
    fields = {'content_len': len(text), 'content_sha256': sha}
    if role == 'ai' and cfg['ai_content'] == 'digest' and len(text) > cfg['digest_chars']:
        fields['content'] = text[:cfg['digest_chars']]
        fields['content_truncated'] = True
    else:
        fields['content'] = text
        fields['content_truncated'] = False
    return fields


def _ledger_prompt_audit_fields(message):
    raw_prompt = (message or {}).get('raw_prompt')
    if raw_prompt is None:
        return {}
    text = str(raw_prompt)
    return {
        'prompt_audit_version': str((message or {}).get('prompt_audit_version') or COMMENTS_PROMPT_AUDIT_VERSION),
        'prompt_source': str((message or {}).get('prompt_source') or 'prompt_override'),
        'raw_prompt': text,
        'raw_prompt_len': len(text),
        'raw_prompt_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()[:16],
    }


def _ledger_record_message(entry_snapshot, idx, message):
    """由 _queue_append_message 钩出(锁外调用)。父指针:同 run 前一条;分叉 run 的第 0 条指回父 run 的分叉点。"""
    try:
        cfg = _comments_ledger_config()
        if not cfg.get('enabled', True):
            return
        run_id = entry_snapshot.get('id')
        path = str(entry_snapshot.get('path') or '')
        if not run_id or not path:
            return
        role = str(message.get('role') or '')
        fork_meta = ((entry_snapshot.get('metadata') or {}).get('fork') or {})
        if idx > 0:
            parent = f'{run_id}#{idx - 1}'
        else:
            parent = fork_meta.get('parent_entry_id') or None
        event = {
            'v': 1,
            'schema': COMMENTS_LEDGER_SCHEMA,
            'event': 'message',
            'entry_id': f'{run_id}#{idx}',
            'run_id': run_id,
            'idx': idx,
            'parent': parent,
            'role': role,
            'author': str(message.get('author') or ('' if role == 'ai' else '用户')),
            'tool': str(entry_snapshot.get('tool') or ''),
            'path': path,
            'task_id': _task_id_from_rel_path(path),
            'ts': str(message.get('timestamp') or datetime.now().strftime('%Y-%m-%dT%H:%M:%S')),
        }
        if role == 'ai':
            for key in ('model', 'input_tokens', 'output_tokens', 'duration_ms'):
                if message.get(key) is not None:
                    event[key] = message.get(key)
        if idx == 0 and fork_meta:
            event['fork_of'] = dict(fork_meta)
        event.update(_ledger_content_fields(role, message.get('content')))
        event.update(_ledger_prompt_audit_fields(message))
        _ledger_append_events(path, [event])
    except Exception:
        pass  # 台账绝不带崩执行链


def _queue_append_message(entry_id, message, ledger_fields=None):
    """向指定 entry 追加一条消息(并钩出耐久台账事件,锁外写)。"""
    ledger_call = None
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        entry = _queue_find_entry(queue, entry_id)
        if not entry:
            if changed:
                _queue_save_unlocked(queue)
            return False
        if 'messages' not in entry or not isinstance(entry.get('messages'), list):
            entry['messages'] = []
        entry['messages'].append(message)
        _queue_save_unlocked(queue)
        snapshot = {k: entry.get(k) for k in ('id', 'path', 'tool', 'metadata')}
        ledger_message = dict(message or {})
        if isinstance(ledger_fields, dict):
            ledger_message.update(ledger_fields)
        ledger_call = (snapshot, len(entry['messages']) - 1, ledger_message)
    if ledger_call:
        _ledger_record_message(ledger_call[0], ledger_call[1], ledger_call[2])
        _lineage_record_ai_message(ledger_call[0], ledger_call[1], message)
    return True

def _normalize_claude_command(cmd, session_id=None):
    """确保 Claude 命令包含 JSON 输出，并可注入 resume session。"""
    command = list(cmd or [])
    if not command:
        command = ['claude']
    if '--output-format' in command:
        idx = command.index('--output-format')
        if idx == len(command) - 1:
            command.append('json')
        else:
            command[idx + 1] = 'json'
    else:
        command.extend(['--output-format', 'json'])
    if session_id:
        if '--resume' in command:
            idx = command.index('--resume')
            if idx == len(command) - 1:
                command.append(session_id)
            else:
                command[idx + 1] = session_id
        else:
            command.extend(['--resume', session_id])
    return command

# Codex exec 初始运行支持的带值 flags
_CODEX_FLAGS_WITH_VALUES = {
    '--model', '-m', '--profile', '-p', '--output-last-message', '-o',
    '--output-schema', '--cd', '-C', '--add-dir', '--sandbox', '-s',
    '--ask-for-approval', '-a', '-c', '--config', '--image', '-i',
}

def _normalize_codex_command(cmd):
    """将任意 Codex 配置命令重建为标准格式：[binary, 'exec', ...flags, '--json']。"""
    command = list(cmd or [])
    if not command:
        return ['codex', 'exec', '--skip-git-repo-check', '--json']
    binary = command[0]
    flags = []
    i = 1
    while i < len(command):
        token = command[i]
        if token in ('exec', 'e'):
            i += 1
            continue
        if token in _CODEX_FLAGS_WITH_VALUES and i + 1 < len(command):
            flags.append(token)
            flags.append(command[i + 1])
            i += 2
            continue
        if token.startswith('-'):
            flags.append(token)
        i += 1
    if '--json' not in flags:
        flags.append('--json')
    # 看板已用 allowed roots 校验 workdir；这里还需允许 Documents 下的非 Git 容器。
    if '--skip-git-repo-check' not in flags:
        flags.append('--skip-git-repo-check')
    return [binary, 'exec'] + flags

# codex exec resume 明确支持的 flags（来自 codex exec resume --help）
_CODEX_EXEC_RESUME_SAFE_FLAGS = {
    '--json', '--yolo', '--dangerously-bypass-approvals-and-sandbox',
    '--ephemeral', '--skip-git-repo-check', '--ignore-rules', '--ignore-user-config',
}
_CODEX_EXEC_RESUME_FLAGS_WITH_VALUES = {
    '--model', '-m', '--ask-for-approval', '-a', '--config', '-c', '--image', '-i',
}

def _normalize_codex_resume_command(cmd, session_id):
    """将 Codex 配置命令转换为 exec resume 命令。只保留 resume 安全的参数。"""
    command = list(cmd or [])
    if not command:
        return [
            'codex', 'exec', 'resume', session_id, '-',
            '--yolo', '--json', '--skip-git-repo-check',
        ]
    binary = command[0]
    flags = []
    i = 1
    while i < len(command):
        token = command[i]
        if token in ('exec', 'e'):
            i += 1
            continue
        if token in ('--yolo', '--dangerously-bypass-approvals-and-sandbox'):
            flags.append(token)
            i += 1
            continue
        if token in _CODEX_EXEC_RESUME_FLAGS_WITH_VALUES and i + 1 < len(command):
            flags.append(token)
            flags.append(command[i + 1])
            i += 2
            continue
        if token in _CODEX_EXEC_RESUME_SAFE_FLAGS:
            flags.append(token)
            i += 1
            continue
        # 跳过不安全的带值 flags
        if token in _CODEX_FLAGS_WITH_VALUES:
            i += 2
            continue
        i += 1
    if '--json' not in flags:
        flags.append('--json')
    if '--skip-git-repo-check' not in flags:
        flags.append('--skip-git-repo-check')
    return [binary, 'exec', 'resume', session_id, '-'] + flags

def _parse_claude_json_output(stdout):
    """解析 Claude JSON 输出。失败时回退为原始 stdout。"""
    content = stdout
    session_id = None
    model = None
    input_tokens = None
    output_tokens = None
    try:
        payload = json.loads(stdout)
    except Exception:
        return {
            'content': content,
            'session_id': session_id,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }
    if not isinstance(payload, dict):
        return {
            'content': content,
            'session_id': session_id,
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }
    session_id = payload.get('session_id')
    model = payload.get('model')
    model_usage = payload.get('modelUsage') if isinstance(payload.get('modelUsage'), dict) else {}
    if not model and model_usage:
        model = ', '.join(str(name) for name in model_usage.keys())
    usage = payload.get('usage') if isinstance(payload.get('usage'), dict) else {}
    input_tokens = usage.get('input_tokens', payload.get('input_tokens'))
    output_tokens = usage.get('output_tokens', payload.get('output_tokens'))
    result = payload.get('result', stdout)
    if isinstance(result, dict):
        content = result.get('content') or result.get('text') or json.dumps(result, ensure_ascii=False)
    elif isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                parts.append(item.get('text') or item.get('content') or json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        content = '\n'.join(part for part in parts if part)
    elif result is None:
        content = stdout
    else:
        content = result
    return {
        'content': content,
        'session_id': session_id,
        'model': model,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
    }

# Claude CLI OAuth token 过期 + 多实例并发刷新竞态时,API 会临时拒绝
# (典型输出: "Failed to authenticate. API Error: 403 Request not allowed")。
# 这类失败等一个刷新窗口后重试一次通常即恢复,不应直接判死。
_CLAUDE_AUTH_FAILURE_RE = re.compile(
    r'failed to authenticate|request not allowed|authentication[_ ]?failed'
    r'|oauth token .{0,20}expired|invalid bearer token',
    re.I,
)
_CLAUDE_AUTH_RETRY_DELAYS_SECONDS = ai_run_guard.CLAUDE_AUTH_RETRY_DELAYS_SECONDS

def _is_claude_auth_failure(parsed, stdout, stderr):
    """判断 claude CLI 非零退出是否属于可重试的鉴权失败。"""
    text = ' '.join(str(x) for x in (parsed.get('content'), stdout, stderr) if x)
    return bool(_CLAUDE_AUTH_FAILURE_RE.search(text))

def _parse_codex_jsonl_output(stdout):
    """解析 Codex --json JSONL 输出。提取 thread_id、AI 回复和 token 统计。

    兼容多种字段形态：
    - thread_id: thread.started.thread_id / session_id / id
    - AI 回复: item.completed.item.type='agent_message' + item.text (已验证)
               或 item.agent_message.text / item.content[].text / item.text (备选)
    """
    thread_id = None
    last_agent_text = None
    input_tokens = None
    output_tokens = None
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        etype = event.get('type', '')
        if etype == 'thread.started':
            thread_id = (event.get('thread_id')
                         or event.get('session_id')
                         or event.get('id'))
        if etype == 'item.completed':
            item = event.get('item') if isinstance(event.get('item'), dict) else {}
            item_type = item.get('type', '')
            if item_type == 'agent_message' and item.get('text'):
                last_agent_text = item.get('text')
            elif isinstance(item.get('agent_message'), dict) and item.get('agent_message', {}).get('text'):
                last_agent_text = item['agent_message']['text']
            elif isinstance(item.get('content'), list):
                texts = [p.get('text', '') for p in item['content']
                         if isinstance(p, dict) and p.get('type') in ('output_text', 'text') and p.get('text')]
                if texts:
                    last_agent_text = '\n'.join(texts)
            elif item.get('text'):
                last_agent_text = item.get('text')
        if etype == 'turn.completed':
            usage = event.get('usage', {})
            if isinstance(usage, dict):
                input_tokens = usage.get('input_tokens', input_tokens)
                output_tokens = usage.get('output_tokens', output_tokens)
    return {
        'content': last_agent_text or stdout,
        'session_id': thread_id,
        'model': None,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
    }

def _skills_root():
    """Return the project-level Claude skills directory."""
    return REPO_ROOT / '.claude' / 'skills'

def _parse_skill_md(skill_md_path):
    """解析 SKILL.md，返回元数据和完整内容。解析失败返回 None。"""
    try:
        raw_content = Path(skill_md_path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None

    skill_dir = Path(skill_md_path).parent
    meta = {
        'id': skill_dir.name,
        'name': skill_dir.name,
        'description': '',
        'argument_hint': '',
        'raw_content': raw_content,
    }

    lines = raw_content.splitlines()
    if len(lines) >= 2 and re.match(r'^---\s*$', lines[0] or ''):
        end_idx = None
        for idx in range(1, len(lines)):
            if re.match(r'^---\s*$', lines[idx] or ''):
                end_idx = idx
                break
        if end_idx is not None:
            for line in lines[1:end_idx]:
                m = re.match(r'^name:\s*(.+)$', line)
                if m:
                    meta['name'] = m.group(1).strip().strip('"\'')
                    continue
                m = re.match(r'^description:\s*(.+)$', line)
                if m:
                    meta['description'] = m.group(1).strip().strip('"\'')
                    continue
                m = re.match(r'^argument-hint:\s*(.+)$', line)
                if m:
                    meta['argument_hint'] = m.group(1).strip().strip('"\'')
    return meta

def _scan_skills():
    """扫描 REPO_ROOT/.claude/skills/ 顶层目录，返回轻量 Skill 元数据。"""
    root = _skills_root()
    if not root.exists() or not root.is_dir():
        return []
    skills = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        parsed = _parse_skill_md(child / 'SKILL.md')
        if not parsed:
            continue
        skills.append({
            'id': parsed['id'],
            'name': parsed.get('name') or parsed['id'],
            'description': parsed.get('description') or '',
            'argument_hint': parsed.get('argument_hint') or '',
        })
    return sorted(skills, key=lambda s: ((s.get('name') or '').lower(), (s.get('id') or '').lower()))

def _load_skill(skill_id):
    """根据 skill_id 安全加载完整 Skill 元数据。"""
    if not skill_id or not isinstance(skill_id, str):
        return None
    root = _skills_root().resolve()
    try:
        skill_md_path = (root / skill_id / 'SKILL.md').resolve()
        skill_md_path.relative_to(root)
    except (OSError, ValueError):
        return None
    if skill_md_path.name != 'SKILL.md' or skill_md_path.parent.parent != root:
        return None
    parsed = _parse_skill_md(skill_md_path)
    if not parsed:
        return None
    return parsed

def _load_skill_content(skill_id):
    """根据 skill_id（目录名）加载完整 SKILL.md 内容。返回文本或 None。"""
    skill = _load_skill(skill_id)
    return skill.get('raw_content') if skill else None

def _replace_skill_arguments(skill_content, skill_id, arguments):
    """替换 $ARGUMENTS、$0、$1 占位符。"""
    args = str(arguments or '').strip()
    first_arg = args.split(None, 1)[0] if args else ''
    return (skill_content or '') \
        .replace('$ARGUMENTS', args) \
        .replace('$0', skill_id or '') \
        .replace('$1', first_arg)

def _parse_skill_command(comment, requested_skill_id=None):
    """以后端为准解析评论开头的 /skill 命令，返回应用信息或 None。"""
    text = str(comment or '').strip()
    requested_skill_id = str(requested_skill_id or '').strip()
    if requested_skill_id:
        skill = _load_skill(requested_skill_id)
        if skill:
            prefix = '/' + requested_skill_id
            args = text[len(prefix):].strip() if text == prefix or text.startswith(prefix + ' ') else ''
            return {'skill': skill, 'args': args}

    m = re.match(r'^/([A-Za-z0-9_.-]+)(?:\s+(.*))?$', text, re.S)
    if not m:
        return None
    skill = _load_skill(m.group(1))
    if not skill:
        return None
    return {'skill': skill, 'args': (m.group(2) or '').strip()}

def _build_skill_augmented_prompt(skill, args, original_comment):
    """Build the prompt sent to Claude while keeping UI history clean."""
    skill_id = skill.get('id') or ''
    skill_content = _replace_skill_arguments(skill.get('raw_content') or '', skill_id, args)
    return (
        f'<skill_instructions id="{skill_id}">\n'
        f'{skill_content}\n'
        f'</skill_instructions>\n\n'
        f'<user_comment>\n'
        f'{str(original_comment or "").strip()}\n'
        f'</user_comment>'
    )

def _queue_load_unlocked():
    """在已持有 _queue_lock 时加载队列文件。"""
    queue_file = _queue_file()
    if not queue_file.exists():
        return _queue_default()
    try:
        queue = json.loads(queue_file.read_text(encoding='utf-8'))
    except Exception:
        return _queue_default()
    if not isinstance(queue, dict):
        return _queue_default()
    entries = queue.get('entries')
    if not isinstance(entries, list):
        queue['entries'] = []
    changed = False
    for entry in queue['entries']:
        if _migrate_entry_to_thread(entry):
            changed = True
    if changed:
        _queue_save_unlocked(queue)
    queue['concurrency'] = AI_MAX_CONCURRENT
    return queue

def _queue_save_unlocked(queue):
    """在已持有 _queue_lock 时原子写入队列文件。"""
    queue['concurrency'] = AI_MAX_CONCURRENT
    if not isinstance(queue.get('entries'), list):
        queue['entries'] = []
    queue_file = _queue_file()
    tmp = queue_file.with_name(f'{queue_file.name}.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(str(tmp), str(queue_file))

def _queue_load():
    """加载队列文件。缺失或损坏时返回默认结构。"""
    with _queue_lock:
        return _queue_load_unlocked()

def _queue_save(queue):
    """原子写入队列文件。"""
    with _queue_lock:
        _queue_save_unlocked(queue)

def _queue_find_entry(queue, entry_id):
    for entry in queue.get('entries', []):
        if entry.get('id') == entry_id:
            return entry
    return None

def _queue_prune_missing_entries(queue):
    """删除对应任务文件已不存在的条目。"""
    kept = []
    changed = False
    for entry in queue.get('entries', []):
        path = entry.get('path', '')
        status = entry.get('status')
        if (path and (REPO_ROOT / path).exists()) or status in {'running', _ORPHANED_RUNNING}:
            kept.append(entry)
        else:
            changed = True
    if changed:
        queue['entries'] = kept
    return changed

def _queue_snapshot():
    """读取队列快照，并顺手清理已删除任务的条目。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        if changed:
            _queue_save_unlocked(queue)
        return {
            'concurrency': queue.get('concurrency', AI_MAX_CONCURRENT),
            'entries': [_queue_public_entry(entry) for entry in queue.get('entries', [])],
        }


def _queue_public_entry(entry):
    public = dict(entry)
    public.pop('prompt_override', None)
    public.pop('post_success_frontmatter', None)
    metadata = public.get('metadata') if isinstance(public.get('metadata'), dict) else {}
    seed_meta = metadata.get('canvas_seed') if isinstance(metadata.get('canvas_seed'), dict) else None
    if seed_meta:
        run_succeeded = public.get('status') == 'completed'
        canvas_payload, canvas_status = get_canvas_for_task(public.get('path', ''))
        canvas = canvas_payload.get('canvas') if canvas_status == 200 else None
        quality = canvas_seed.minimum_seed_quality(canvas or {}, ai_run_succeeded=run_succeeded)
        canvas_ref = str((canvas_payload or {}).get('canvas_ref') or '')
        queued_at = str(seed_meta.get('queued_at') or '')
        expected_actor = str(public.get('tool') or '')
        canvas_events = _canvas_events_read(REPO_ROOT / canvas_ref) if canvas_ref else []
        canvas_changed = any(
            str(event.get('actor') or '') == expected_actor
            and (not queued_at or str(event.get('ts') or '') >= queued_at)
            and str(event.get('event') or '') not in {'canvas_save_rejected'}
            for event in canvas_events
            if isinstance(event, dict)
        )
        if run_succeeded and not canvas_changed:
            quality['passed'] = False
            quality['stage'] = canvas_seed.seed_stage(ai_run_succeeded=True, quality_passed=False)
            quality.setdefault('missing', []).append('agent_canvas_change')
        quality['canvas_changed'] = canvas_changed
        public['quality_gate'] = quality
        public['quality_passed'] = bool(quality.get('passed'))
        public['usable'] = bool(quality.get('passed'))
    return public


def _queue_add_entry(tool, path, workdir='', prompt_override=None, post_success_frontmatter=None,
                     metadata=None, dedupe_key=None, ai_profile=None):
    """添加一条排队条目，返回 entry id。"""
    created_entry = None
    with _queue_lock:
        queue = _queue_load_unlocked()
        _queue_prune_missing_entries(queue)
        clean_dedupe_key = str(dedupe_key or '').strip()
        if clean_dedupe_key:
            for existing in queue['entries']:
                if (existing.get('status') in _ACTIVE_QUEUE_STATUSES
                        and str(existing.get('dedupe_key') or '') == clean_dedupe_key):
                    return existing.get('id')
        entry_id = uuid.uuid4().hex[:8]
        max_order = max((e.get('order', 0) for e in queue['entries']), default=-1)
        entry = {
            'id': entry_id,
            'tool': tool,
            'path': path,
            'workdir': workdir,
            'status': 'queued',
            'read': False,
            'order': max_order + 1,
            'pid': None,
            'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'started_at': None,
            'completed_at': None,
            'duration_ms': None,
            'output': None,
            'error': None,
            'session_id': None,
            'session_valid': True,
            'messages': [],
            'title': None,
            'prompt_length': 0,
            'output_length': 0,
        }
        if prompt_override is not None:
            entry['prompt_override'] = str(prompt_override)
        if isinstance(post_success_frontmatter, dict):
            entry['post_success_frontmatter'] = dict(post_success_frontmatter)
        if isinstance(metadata, dict):
            entry['metadata'] = dict(metadata)
        clean_profile = str(ai_profile or '').strip()
        if clean_profile:
            entry['ai_profile'] = clean_profile
        if clean_dedupe_key:
            entry['dedupe_key'] = clean_dedupe_key
        queue['entries'].append(entry)
        _queue_save_unlocked(queue)
        created_entry = dict(entry)
    _lineage_record_queue_entry_created(created_entry)
    return entry_id


def _queue_find_active_by_dedupe_key(dedupe_key):
    """Return an active queued/running entry for an idempotent request key."""
    clean_key = str(dedupe_key or '').strip()
    if not clean_key:
        return None
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        match = next((
            dict(entry) for entry in queue['entries']
            if entry.get('status') in _ACTIVE_QUEUE_STATUSES
            and str(entry.get('dedupe_key') or '') == clean_key
        ), None)
        if changed:
            _queue_save_unlocked(queue)
        return match


def _queue_apply_success_frontmatter_update(entry):
    spec = entry.get('post_success_frontmatter') if isinstance(entry, dict) else None
    if not isinstance(spec, dict):
        return None
    path = str(spec.get('path') or entry.get('path') or '').strip()
    field = str(spec.get('field') or '').strip()
    raw_value = str(spec.get('value') or '').strip()
    if field != 'landing_updated':
        return '不支持的成功回写字段'
    if path != str(entry.get('path') or '').strip():
        return '成功回写路径与队列任务不一致'
    value = datetime.now().strftime('%Y-%m-%d') if raw_value == 'today' else raw_value
    ok, msg = update_frontmatter_field(path, field, value)[:2]
    return None if ok else f'{field} 回写失败: {msg}'

def _queue_update_entry(entry_id, updates, *, only_if_statuses=None, unless_statuses=None):
    """更新指定条目的字段。"""
    lineage_call = None
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        entry = _queue_find_entry(queue, entry_id)
        if not entry:
            if changed:
                _queue_save_unlocked(queue)
            return False
        status = entry.get('status')
        if only_if_statuses and status not in only_if_statuses:
            if changed:
                _queue_save_unlocked(queue)
            return False
        if unless_statuses and status in unless_statuses:
            if changed:
                _queue_save_unlocked(queue)
            return False
        before = dict(entry)
        entry.update(updates)
        lineage_call = (before, dict(updates or {}), dict(entry))
        _queue_save_unlocked(queue)
    if lineage_call:
        _lineage_record_queue_update(*lineage_call)
    return True

def _queue_remove_entry(entry_id):
    """从队列中移除一条条目。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        new_entries = [e for e in queue['entries'] if e.get('id') != entry_id]
        removed = len(new_entries) != len(queue['entries'])
        if removed:
            queue['entries'] = new_entries
        if removed or changed:
            _queue_save_unlocked(queue)
        return removed

def _queue_get_entry(entry_id):
    """获取一条队列记录。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        entry = _queue_find_entry(queue, entry_id)
        if changed:
            _queue_save_unlocked(queue)
        return dict(entry) if entry else None

def _queue_get_by_path(path):
    """获取某个任务路径的所有条目（用于任务详情的 AI Activity）。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        entries = [dict(e) for e in queue['entries'] if e.get('path') == path]
        if changed:
            _queue_save_unlocked(queue)
        return entries


def _review_cycle_task_context(task_path):
    """Resolve one card and its trusted workdir for the review-cycle seam."""
    task_rel = _task_rel_path_in_scan_dirs(task_path)
    if task_rel is None:
        return None, '路径不在 scan_dirs 范围内或不是 Markdown 任务卡'
    path = task_rel.as_posix()
    filepath = REPO_ROOT / task_rel
    if not filepath.is_file() or filepath.suffix.lower() != '.md':
        return None, '任务文件不存在'
    try:
        raw = filepath.read_text(encoding='utf-8')
    except OSError as exc:
        return None, f'任务读取失败: {exc}'
    fm, _ = extract_frontmatter(raw)
    workdir_value = (fm or {}).get('workdir', '')
    resolved, error = resolve_workdir(workdir_value, path)
    if error or not resolved:
        return None, error or 'workdir 无效'
    cwd, error = _coerce_workdir_to_cwd(resolved)
    if error or not cwd:
        return None, error or 'workdir 无效'
    if not Path(cwd).is_dir():
        return None, 'workdir_not_found'
    return {
        'path': path,
        'filepath': filepath,
        'raw': raw,
        'fm': fm or {},
        'workdir_value': workdir_value,
        'cwd': Path(cwd),
    }, ''


def _review_cycle_latest_producer_tool(task_path, reviewer_tool):
    entries = sorted(
        _queue_get_by_path(task_path),
        key=lambda row: str(row.get('completed_at') or row.get('timestamp') or ''),
        reverse=True,
    )
    for entry in entries:
        profile = str(entry.get('ai_profile') or '')
        metadata = entry.get('metadata') if isinstance(entry.get('metadata'), dict) else {}
        if (entry.get('status') == 'completed' and profile.startswith('execute_')
                and metadata.get('kind') != 'review_cycle'
                and entry.get('tool') in {'claude', 'codex'}):
            return entry['tool']
    return 'codex' if reviewer_tool == 'claude' else 'claude'


def _review_cycle_queue_spec(context, spec):
    tool = str(spec.get('tool') or '').strip().lower()
    requested_profile = str(spec.get('profile') or '').strip()
    profile, profile_error = resolve_ai_profile(
        tool, requested_profile, 'canvas', has_custom_prompt=True,
    )
    if profile_error or not profile:
        return None, profile_error or f'AI profile 不可用: {requested_profile or tool}'
    run_id = _queue_add_entry(
        tool,
        context['path'],
        context['workdir_value'],
        prompt_override=str(spec.get('prompt') or ''),
        metadata=spec.get('metadata') if isinstance(spec.get('metadata'), dict) else {},
        dedupe_key=str(spec.get('dedupe_key') or ''),
        ai_profile=profile,
    )
    return run_id, ''


def start_review_cycle(task_path, reviewer_tool='claude', producer_tool='', actor='user'):
    context, error = _review_cycle_task_context(task_path)
    if error:
        return {'ok': False, 'error': error}, 404 if error == '任务文件不存在' else 400
    reviewer_tool = str(reviewer_tool or 'claude').strip().lower()
    if reviewer_tool not in {'claude', 'codex'}:
        return {'ok': False, 'error': 'reviewer_tool 只支持 claude 或 codex'}, 400
    producer_tool = str(producer_tool or '').strip().lower()
    if not producer_tool:
        producer_tool = _review_cycle_latest_producer_tool(context['path'], reviewer_tool)
    if producer_tool not in {'claude', 'codex'}:
        return {'ok': False, 'error': 'producer_tool 只支持 claude 或 codex'}, 400
    reviewer_profile, profile_error = resolve_ai_profile(
        reviewer_tool, f'review_{reviewer_tool}', 'canvas', has_custom_prompt=True,
    )
    if profile_error or not reviewer_profile:
        return {'ok': False, 'error': profile_error or '独立复核 profile 未配置'}, 400
    producer_profile, profile_error = resolve_ai_profile(
        producer_tool, f'execute_{producer_tool}', 'canvas', has_custom_prompt=True,
    )
    if profile_error or not producer_profile:
        return {'ok': False, 'error': profile_error or '修订 profile 未配置'}, 400
    try:
        prepared = review_cycle.start_cycle(
            REPO_ROOT, context['path'], context['raw'], context['cwd'],
            reviewer_tool=reviewer_tool,
            reviewer_profile=reviewer_profile,
            producer_tool=producer_tool,
            producer_profile=producer_profile,
            actor=actor,
            scan_dirs=SCAN_DIRS,
        )
    except review_cycle.ReviewCycleError as exc:
        return {'ok': False, 'error': str(exc)}, 409
    run_id, error = _review_cycle_queue_spec(context, prepared['queue'])
    if error:
        review_cycle.record_enqueue_failure(
            REPO_ROOT, context['path'], prepared['cycle_id'], error, SCAN_DIRS,
        )
        return {'ok': False, 'error': error}, 400
    review_cycle.record_queued(
        REPO_ROOT, context['path'], prepared['cycle_id'], 'review', run_id, SCAN_DIRS,
    )
    _queue_consume_next()
    return {
        'ok': True, 'run_id': run_id,
        'review_cycle': review_cycle.project_state(REPO_ROOT, context['path'], SCAN_DIRS),
    }, 200


def repair_review_cycle(task_path, actor='user'):
    context, error = _review_cycle_task_context(task_path)
    if error:
        return {'ok': False, 'error': error}, 404 if error == '任务文件不存在' else 400
    if str(context['fm'].get('status') or '').strip().lower() == 'done':
        return {'ok': False, 'error': '已完成任务需先重新打开，独立复核不能直接修改 done 卡'}, 409
    try:
        prepared = review_cycle.prepare_repair(
            REPO_ROOT, context['path'], context['raw'], context['cwd'],
            scan_dirs=SCAN_DIRS,
        )
    except review_cycle.ReviewCycleError as exc:
        return {'ok': False, 'error': str(exc)}, 409
    run_id, error = _review_cycle_queue_spec(context, prepared['queue'])
    if error:
        review_cycle.record_enqueue_failure(
            REPO_ROOT, context['path'], prepared['cycle_id'], error, SCAN_DIRS,
        )
        return {'ok': False, 'error': error}, 400
    review_cycle.record_queued(
        REPO_ROOT, context['path'], prepared['cycle_id'], 'repair', run_id, SCAN_DIRS,
    )
    _queue_consume_next()
    return {
        'ok': True, 'run_id': run_id, 'actor': str(actor or 'user')[:80],
        'review_cycle': review_cycle.project_state(REPO_ROOT, context['path'], SCAN_DIRS),
    }, 200


def _handle_review_cycle_terminal(run_id):
    entry = _queue_get_entry(run_id)
    metadata = entry.get('metadata') if isinstance((entry or {}).get('metadata'), dict) else {}
    if not entry or metadata.get('kind') != 'review_cycle':
        return
    task_path = str(entry.get('path') or '')
    context, error = _review_cycle_task_context(task_path)
    cycle_id = str(metadata.get('cycle_id') or '')
    if error:
        if cycle_id:
            review_cycle.record_enqueue_failure(REPO_ROOT, task_path, cycle_id, error, SCAN_DIRS)
        return
    try:
        result = review_cycle.process_terminal(
            REPO_ROOT, task_path, entry, context['raw'],
            scan_dirs=SCAN_DIRS,
        )
        enqueue = result.get('enqueue') if isinstance(result, dict) else None
        if not isinstance(enqueue, dict):
            return
        next_run_id, queue_error = _review_cycle_queue_spec(context, enqueue)
        if queue_error:
            review_cycle.record_enqueue_failure(REPO_ROOT, task_path, cycle_id, queue_error, SCAN_DIRS)
            return
        review_cycle.record_queued(REPO_ROOT, task_path, cycle_id, 'recheck', next_run_id, SCAN_DIRS)
    except Exception as exc:
        if cycle_id:
            review_cycle.record_enqueue_failure(
                REPO_ROOT, task_path, cycle_id, f'terminal hook: {exc}', SCAN_DIRS,
            )

def _queue_kill_entries_for_path(task_path):
    """终止某个任务路径下所有排队中和运行中的 AI 进程。返回被终止的 entry id 列表。"""
    killed_ids = []
    # 1) 终止运行中的进程
    with _ai_runs_lock:
        for run_id, info in list(_ai_runs.items()):
            if info.get('path') != task_path:
                continue
            info['killed'] = True
            proc = info.get('proc')
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
    # 2) 更新队列条目为 killed
    with _queue_lock:
        queue = _queue_load_unlocked()
        _queue_prune_missing_entries(queue)
        for entry in queue['entries']:
            if entry.get('path') != task_path:
                continue
            if entry.get('status') not in ('queued', 'running'):
                continue
            entry['status'] = 'killed'
            entry['error'] = '任务已完成，自动终止'
            entry['completed_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            killed_ids.append(entry['id'])
        if killed_ids:
            _queue_save_unlocked(queue)
    return killed_ids

def _abort_ai_launch_if_killed(run_id, proc):
    """如果条目在 CLI 启动窗口中已被标记为 killed，立刻终止子进程。"""
    with _ai_runs_lock:
        info = _ai_runs.get(run_id)
        if info:
            info['killed'] = True
    if not proc:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def _queue_cancel_entry(entry_id):
    """取消一条排队中的任务。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        for idx, entry in enumerate(queue['entries']):
            if entry.get('id') != entry_id:
                continue
            if entry.get('status') != 'queued':
                if changed:
                    _queue_save_unlocked(queue)
                return False
            del queue['entries'][idx]
            _queue_save_unlocked(queue)
            return True
        if changed:
            _queue_save_unlocked(queue)
        return False

def _queue_reorder_entries(ordered_ids):
    """重排排队中的任务顺序。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        queued = [e for e in queue['entries'] if e.get('status') == 'queued']
        queued_by_id = {e.get('id'): e for e in queued}
        ordered = [queued_by_id[eid] for eid in ordered_ids if eid in queued_by_id]
        remaining = [
            e for e in sorted(queued, key=lambda item: item.get('order', 0))
            if e.get('id') not in ordered_ids
        ]
        for idx, entry in enumerate(ordered + remaining):
            if entry.get('order') != idx:
                entry['order'] = idx
                changed = True
        if changed:
            _queue_save_unlocked(queue)


def _queue_entry_workdir_key(entry):
    """Return a stable cwd key for queue-level same-workdir serialization."""
    workdir = str((entry or {}).get('workdir') or '').strip()
    task_path = str((entry or {}).get('path') or '').strip()
    try:
        resolved, err = resolve_workdir(workdir, task_path)
        if not err and resolved:
            cwd_path, cwd_err = _coerce_workdir_to_cwd(resolved)
            candidate = cwd_path if not cwd_err and cwd_path else resolved
            return str(Path(os.path.realpath(str(candidate))))
    except Exception:
        pass

    try:
        if workdir:
            expanded = os.path.expanduser(workdir)
            candidate = Path(expanded) if os.path.isabs(expanded) else REPO_ROOT / expanded
        elif task_path:
            candidate = REPO_ROOT / Path(task_path).parent
        else:
            return ''
        return str(Path(os.path.realpath(str(candidate))))
    except Exception:
        return workdir or task_path


def _queue_claim_next():
    """原子地领取下一条排队任务，防止重复消费。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        queued = sorted(
            [e for e in queue['entries'] if e.get('status') == 'queued'],
            key=lambda e: e.get('order', 0)
        )
        if not queued:
            if changed:
                _queue_save_unlocked(queue)
            return None
        running_workdirs = {
            key for key in (
                _queue_entry_workdir_key(e)
                for e in queue['entries']
                if e.get('status') in {'running', _ORPHANED_RUNNING}
            )
            if key
        }
        entry = None
        for candidate in queued:
            candidate_key = _queue_entry_workdir_key(candidate)
            if candidate_key and candidate_key in running_workdirs:
                continue
            entry = candidate
            break
        if not entry:
            if changed:
                _queue_save_unlocked(queue)
            return None
        entry.update({
            'status': 'running',
            'started_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'completed_at': None,
            'duration_ms': None,
            'output': None,
            'error': None,
            'pid': None,
            'pid_started_at': None,
        })
        _queue_save_unlocked(queue)
        return dict(entry)

def _ai_run_is_killed(run_id):
    with _ai_runs_lock:
        info = _ai_runs.get(run_id)
        return bool(info and info.get('killed'))

def _queue_consume_next():
    """核心调度：有空闲槽位时，按 order 取出下一条排队任务执行。"""
    while _ai_semaphore.acquire(blocking=False):
        entry = _queue_claim_next()
        if not entry:
            _ai_semaphore.release()
            break
        entry_id = entry['id']
        # 读取任务文件内容作为 CLI 输入
        filepath = REPO_ROOT / entry['path']
        if not filepath.exists():
            _queue_remove_entry(entry_id)
            _ai_semaphore.release()
            continue
        try:
            prompt_body = filepath.read_text(encoding='utf-8')
        except Exception as e:
            _queue_update_entry(entry_id, {
                'status': 'error',
                'error': f'读取任务失败: {e}',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, only_if_statuses={'running'})
            _ai_semaphore.release()
            continue
        raw_card = prompt_body  # 始终保留原始卡内容，用于状态判断
        if entry.get('prompt_override') is not None:
            prompt_body = str(entry.get('prompt_override') or '')
        else:
            # 把卡里「给 AI 的常驻说明」段提到 prompt 最前作为优先指令（支持 /skill）
            prompt_body = _apply_card_ai_note_to_prompt(prompt_body)
        # 防御：跳过已完成任务的队列条目（如服务器重启后遗留），始终用原始卡内容判断
        fm_check, _ = extract_frontmatter(raw_card)
        review_meta = entry.get('metadata') if isinstance(entry.get('metadata'), dict) else {}
        review_stage = review_meta.get('stage') if review_meta.get('kind') == 'review_cycle' else ''
        # 独立 reviewer/rechecker 是只读验收，可审已完成卡；repair 仍受 done 红线约束。
        if (fm_check or {}).get('status', '') == 'done' and review_stage not in {'review', 'recheck'}:
            _queue_update_entry(entry_id, {
                'status': 'killed',
                'error': '任务已完成，跳过执行',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, only_if_statuses={'running'})
            _ai_semaphore.release()
            continue
        _queue_update_entry(entry_id, {
            'prompt_length': len(prompt_body),
        }, only_if_statuses={'running'})
        t = threading.Thread(
            target=_run_cli,
            args=(entry_id, entry['path'], entry['tool'], prompt_body),
            daemon=True
        )
        with _ai_runs_lock:
            _ai_runs[entry_id] = {
                'thread': t, 'path': entry['path'],
                'tool': entry['tool'], 'started_at': time.time()
            }
        t.start()

# ── AI CLI 后台执行 ─────────────────────────────────────

def _run_cli(run_id, task_path, tool, prompt_body=''):
    """后台线程：执行 CLI 并更新队列条目。信号量已由 _queue_consume_next 获取。"""
    filepath = REPO_ROOT / task_path
    started_at = time.time()
    proc = None

    try:
        current_entry = _queue_get_entry(run_id) or {}
        cmd = _ai_command_for_entry(tool, current_entry)
        if not cmd:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': f'AI profile 不可用: {current_entry.get("ai_profile") or tool}',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            return
        if tool == 'claude':
            cmd = _normalize_claude_command(cmd)
        elif tool == 'codex':
            cmd = _normalize_codex_command(cmd)

        workdir_value = str(current_entry.get('workdir') or '').strip()
        if not workdir_value:
            try:
                raw = filepath.read_text(encoding='utf-8')
                fm, _ = extract_frontmatter(raw)
                workdir_value = fm.get('workdir', '') if fm else ''
            except Exception:
                pass

        cwd_path, cwd_err = resolve_workdir(workdir_value, task_path)
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            return
        cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            return
        if not cwd_path.exists():
            cwd_path.mkdir(parents=True, exist_ok=True)
        cwd = str(cwd_path)

        auth_retry_delays = iter(_CLAUDE_AUTH_RETRY_DELAYS_SECONDS if tool == 'claude' else ())
        while True:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=cwd,
                start_new_session=True,
                env=ai_run_guard.sanitized_cli_env(),
            )

            with _ai_runs_lock:
                _ai_runs[run_id] = {
                    'proc': proc, 'path': task_path, 'tool': tool,
                    'status': 'running', 'started_at': started_at,
                    'killed': False,
                }

            current_entry = _queue_get_entry(run_id) or {}
            if current_entry.get('status') != 'running':
                _abort_ai_launch_if_killed(run_id, proc)
                return
            proc_pid = getattr(proc, 'pid', None)
            _queue_update_entry(run_id, {
                'pid': proc_pid,
                'pid_started_at': server_instance.process_start_time(proc_pid),
            }, only_if_statuses={'running'})
            if _ai_run_is_killed(run_id):
                _abort_ai_launch_if_killed(run_id, proc)
                return

            stdout, stderr = proc.communicate(input=prompt_body, timeout=86400)
            duration_ms = int((time.time() - started_at) * 1000)
            if tool == 'claude':
                parsed = _parse_claude_json_output(stdout)
            else:
                parsed = _parse_codex_jsonl_output(stdout)

            if (proc.returncode != 0 and not _ai_run_is_killed(run_id)
                    and _is_claude_auth_failure(parsed, stdout, stderr)):
                retry_delay = next(auth_retry_delays, None)
                if retry_delay is not None:
                    time.sleep(retry_delay)
                    if _ai_run_is_killed(run_id):
                        return
                    continue
            break

        if _ai_run_is_killed(run_id):
            partial = parsed.get('content', stdout) if parsed.get('content') else None
            if partial:
                _queue_append_message(run_id, {
                    'role': 'ai',
                    'content': partial,
                    'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'duration_ms': duration_ms,
                    'model': parsed.get('model'),
                    'input_tokens': parsed.get('input_tokens'),
                    'output_tokens': parsed.get('output_tokens'),
                })
                _queue_update_entry(run_id, {
                    'output': partial,
                    'title': _truncate_title(partial),
                    'output_length': len(partial or ''),
                    'session_id': parsed.get('session_id'),
                    'session_valid': bool(parsed.get('session_id')),
                })
            return
        if proc.returncode != 0:
            error_msg = ai_run_guard.nonzero_exit_error(
                stderr, parsed.get('content'), stdout, proc.returncode
            )
            session_id = parsed.get('session_id')
            session_valid = bool(session_id) and not re.search(r'session|resume.*not found|not found', error_msg, re.I)
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': error_msg,
                'session_id': session_id,
                'session_valid': session_valid,
                'duration_ms': duration_ms,
                'output': parsed.get('content', stdout),
                'title': _truncate_title(parsed.get('content', stdout)),
                'output_length': len(parsed.get('content', stdout) or ''),
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
        else:
            ai_content = parsed.get('content', stdout)
            session_id = parsed.get('session_id')
            current_entry = _queue_get_entry(run_id) or {}
            title = current_entry.get('title') or _truncate_title(ai_content)
            _queue_append_message(run_id, {
                'role': 'ai',
                'content': ai_content,
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'duration_ms': duration_ms,
                'model': parsed.get('model'),
                'input_tokens': parsed.get('input_tokens'),
                'output_tokens': parsed.get('output_tokens'),
            })
            post_success_error = _queue_apply_success_frontmatter_update(current_entry)
            if post_success_error:
                _queue_update_entry(run_id, {
                    'status': 'error',
                    'error': post_success_error,
                    'session_id': session_id,
                    'session_valid': bool(session_id),
                    'title': title,
                    'duration_ms': duration_ms,
                    'output': ai_content,
                    'output_length': len(ai_content or ''),
                    'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                }, unless_statuses={'killed'})
                return
            governance_record_error = _record_governance_noise_review_result(
                run_id, current_entry, ai_content, parsed, duration_ms
            )
            extra_updates = {}
            if governance_record_error:
                extra_updates['governance_noise_record_error'] = governance_record_error
            _queue_update_entry(run_id, {
                'status': 'completed',
                'output': ai_content,
                'error': None,
                'session_id': session_id,
                'session_valid': bool(session_id),
                'title': title,
                'duration_ms': duration_ms,
                'output_length': len(ai_content or ''),
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                **extra_updates,
            }, unless_statuses={'killed'})

    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.kill()
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'timeout',
            'error': '执行超时',
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except FileNotFoundError:
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': _cli_not_found_error(tool),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except Exception as e:
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': str(e),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    finally:
        with _ai_runs_lock:
            _ai_runs.pop(run_id, None)
        _handle_review_cycle_terminal(run_id)
        _ai_semaphore.release()
        _queue_consume_next()

def _run_cli_resume(run_id, session_id, cwd, comment, task_path):
    """后台线程：通过 --resume 恢复会话并继续处理评论。"""
    started_at = time.time()
    proc = None

    try:
        current_entry = _queue_get_entry(run_id) or {}
        cmd = _ai_command_for_entry('claude', current_entry)
        if not cmd:
            raise ValueError(f'AI profile 不可用: {current_entry.get("ai_profile") or "claude"}')
        cmd = _normalize_claude_command(cmd, session_id=session_id)
        cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd)
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            return
        if not cwd_path.exists():
            cwd_path.mkdir(parents=True, exist_ok=True)
        cwd = str(cwd_path)
        auth_retry_delays = iter(_CLAUDE_AUTH_RETRY_DELAYS_SECONDS)
        while True:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=cwd,
                start_new_session=True,
                env=ai_run_guard.sanitized_cli_env(),
            )

            with _ai_runs_lock:
                _ai_runs[run_id] = {
                    'proc': proc, 'path': task_path, 'tool': 'claude',
                    'status': 'running', 'started_at': started_at,
                    'killed': False,
                }

            current_entry = _queue_get_entry(run_id) or {}
            if current_entry.get('status') != 'running':
                _abort_ai_launch_if_killed(run_id, proc)
                return
            proc_pid = getattr(proc, 'pid', None)
            _queue_update_entry(run_id, {
                'pid': proc_pid,
                'pid_started_at': server_instance.process_start_time(proc_pid),
            }, only_if_statuses={'running'})
            if _ai_run_is_killed(run_id):
                _abort_ai_launch_if_killed(run_id, proc)
                return

            stdout, stderr = proc.communicate(input=comment, timeout=86400)
            duration_ms = int((time.time() - started_at) * 1000)
            parsed = _parse_claude_json_output(stdout)

            if (proc.returncode != 0 and not _ai_run_is_killed(run_id)
                    and _is_claude_auth_failure(parsed, stdout, stderr)):
                retry_delay = next(auth_retry_delays, None)
                if retry_delay is not None:
                    time.sleep(retry_delay)
                    if _ai_run_is_killed(run_id):
                        return
                    continue
            break

        if _ai_run_is_killed(run_id):
            partial = parsed.get('content', stdout) if parsed.get('content') else None
            if partial:
                _queue_append_message(run_id, {
                    'role': 'ai',
                    'content': partial,
                    'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'duration_ms': duration_ms,
                    'model': parsed.get('model'),
                    'input_tokens': parsed.get('input_tokens'),
                    'output_tokens': parsed.get('output_tokens'),
                })
                _queue_update_entry(run_id, {
                    'output': partial,
                    'title': _truncate_title(partial),
                    'output_length': len(partial or ''),
                })
            return

        if proc.returncode != 0:
            error_msg = ai_run_guard.nonzero_exit_error(
                stderr, parsed.get('content'), stdout, proc.returncode
            )
            session_valid = bool(session_id) and not re.search(r'session|resume.*not found|not found', error_msg, re.I)
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': error_msg,
                'session_valid': session_valid,
                'duration_ms': duration_ms,
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
        else:
            ai_content = parsed.get('content', stdout)
            _queue_append_message(run_id, {
                'role': 'ai',
                'content': ai_content,
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'duration_ms': duration_ms,
                'model': parsed.get('model'),
                'input_tokens': parsed.get('input_tokens'),
                'output_tokens': parsed.get('output_tokens'),
            })
            current_entry = _queue_get_entry(run_id) or {}
            title = current_entry.get('title') or _truncate_title(ai_content)
            _queue_update_entry(run_id, {
                'status': 'completed',
                'output': ai_content,
                'error': None,
                'session_valid': bool(session_id),
                'title': title,
                'duration_ms': duration_ms,
                'output_length': len(ai_content or ''),
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})

    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.kill()
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'timeout',
            'error': '执行超时',
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except FileNotFoundError:
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': _cli_not_found_error('claude'),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except Exception as e:
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': str(e),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    finally:
        with _ai_runs_lock:
            _ai_runs.pop(run_id, None)
        _ai_semaphore.release()
        _queue_consume_next()

def _run_codex_resume(run_id, session_id, cwd, comment, task_path):
    """后台线程：通过 codex exec resume 恢复 Codex 会话并继续处理评论。"""
    started_at = time.time()
    proc = None

    try:
        current_entry = _queue_get_entry(run_id) or {}
        cmd = _ai_command_for_entry('codex', current_entry)
        if not cmd:
            raise ValueError(f'AI profile 不可用: {current_entry.get("ai_profile") or "codex"}')
        cmd = _normalize_codex_resume_command(cmd, session_id)
        cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd)
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            return
        if not cwd_path.exists():
            cwd_path.mkdir(parents=True, exist_ok=True)
        cwd = str(cwd_path)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=cwd,
            start_new_session=True,
            env=ai_run_guard.sanitized_cli_env(),
        )

        with _ai_runs_lock:
            _ai_runs[run_id] = {
                'proc': proc, 'path': task_path, 'tool': 'codex',
                'status': 'running', 'started_at': started_at,
                'killed': False,
            }

        current_entry = _queue_get_entry(run_id) or {}
        if current_entry.get('status') != 'running':
            _abort_ai_launch_if_killed(run_id, proc)
            return
        proc_pid = getattr(proc, 'pid', None)
        _queue_update_entry(run_id, {
            'pid': proc_pid,
            'pid_started_at': server_instance.process_start_time(proc_pid),
        }, only_if_statuses={'running'})
        if _ai_run_is_killed(run_id):
            _abort_ai_launch_if_killed(run_id, proc)
            return

        stdout, stderr = proc.communicate(input=comment, timeout=86400)
        duration_ms = int((time.time() - started_at) * 1000)
        parsed = _parse_codex_jsonl_output(stdout)

        if _ai_run_is_killed(run_id):
            return

        if proc.returncode != 0:
            error_msg = ai_run_guard.nonzero_exit_error(
                stderr, parsed.get('content'), stdout, proc.returncode
            )
            session_valid = bool(session_id) and not re.search(r'session|resume.*not found|not found', error_msg, re.I)
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': error_msg,
                'session_valid': session_valid,
                'duration_ms': duration_ms,
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
        else:
            ai_content = parsed.get('content', stdout)
            _queue_append_message(run_id, {
                'role': 'ai',
                'content': ai_content,
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'duration_ms': duration_ms,
                'model': parsed.get('model'),
                'input_tokens': parsed.get('input_tokens'),
                'output_tokens': parsed.get('output_tokens'),
            })
            current_entry = _queue_get_entry(run_id) or {}
            title = current_entry.get('title') or _truncate_title(ai_content)
            _queue_update_entry(run_id, {
                'status': 'completed',
                'output': ai_content,
                'error': None,
                'session_valid': bool(session_id),
                'title': title,
                'duration_ms': duration_ms,
                'output_length': len(ai_content or ''),
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})

    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.kill()
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'timeout',
            'error': '执行超时',
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except FileNotFoundError:
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': _cli_not_found_error('codex'),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    except Exception as e:
        if _ai_run_is_killed(run_id):
            return
        _queue_update_entry(run_id, {
            'status': 'error',
            'error': str(e),
            'duration_ms': int((time.time() - started_at) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, unless_statuses={'killed'})
    finally:
        with _ai_runs_lock:
            _ai_runs.pop(run_id, None)
        _ai_semaphore.release()
        _queue_consume_next()

def _build_fork_replay(parent_entry, fork_idx, per_msg_cap=4000, total_cap=40000):
    """从父线程 messages[0..fork_idx] 构造确定性上下文回放。
    资深 CLI(claude/codex)的 resume 是原地续写单会话,无法从历史中点分叉;
    故 fork=新会话+忠实回放,规则固定(逐条截断+超预算丢最早),不经 LLM 摘要。"""
    messages = list(parent_entry.get('messages') or [])[:fork_idx + 1]
    rendered = []
    for i, msg in enumerate(messages):
        role = 'AI' if str(msg.get('role') or '') == 'ai' else '用户'
        text = str(msg.get('content') or '')
        if len(text) > per_msg_cap:
            text = text[:per_msg_cap] + f'\n……(此条截断,原长 {len(text)} 字符)'
        rendered.append(f'[{i}] {role}: {text}')
    omitted = 0
    while rendered and sum(len(r) for r in rendered) > total_cap:
        rendered.pop(0)
        omitted += 1
    header = (
        f'以下是本任务此前一段对话的忠实回放(其中"AI"是你)。'
        f'现在从第 {fork_idx} 条之后【分叉】出一条新支线:请基于回放上下文继续,不要重复已有结论。'
    )
    if omitted:
        header += f'(最早 {omitted} 条已因长度省略)'
    return header + '\n\n--- 对话回放 ---\n' + '\n\n'.join(rendered) + '\n--- 回放结束 ---\n'


def _normalize_source_quote(value, expected_path=''):
    """Validate the task-body quote carried by a user message.

    Quotes are message metadata, never markdown mutations.  Keep the stored
    snapshot bounded and require its locator to stay on the current task.
    """
    if value in (None, ''):
        return None, ''
    if not isinstance(value, dict):
        return None, 'source_quote 必须是对象'
    quote_text = str(value.get('quote_text') or '').strip()
    if not quote_text:
        return None, 'source_quote.quote_text 不能为空'
    if len(quote_text.encode('utf-8')) > 8 * 1024:
        return None, '正文引用超过大小限制(8KB)'
    section = str(value.get('section') or '').strip()
    if len(section.encode('utf-8')) > 512:
        return None, 'source_quote.section 超过大小限制'
    raw_context = value.get('context') if isinstance(value.get('context'), dict) else {}
    raw_locator = value.get('source_locator') if isinstance(value.get('source_locator'), dict) else {}
    task_path = str(raw_locator.get('task_path') or expected_path or '').strip()
    if expected_path and task_path != str(expected_path):
        return None, '正文引用不属于当前任务卡'
    if '..' in task_path or task_path.startswith('/'):
        return None, '正文引用路径非法'

    prefix = str(raw_locator.get('prefix') or raw_context.get('prefix') or '')[-500:]
    suffix = str(raw_locator.get('suffix') or raw_context.get('suffix') or '')[:500]
    try:
        text_index = int(raw_locator.get('text_index', -1))
    except (TypeError, ValueError):
        text_index = -1
    try:
        block_index = int(raw_locator.get('block_index', -1))
    except (TypeError, ValueError):
        block_index = -1
    normalized = {
        'quote_text': quote_text,
        'section': section,
        'context': {'prefix': prefix, 'suffix': suffix},
        'source_locator': {
            'task_path': task_path,
            'body_rev': str(raw_locator.get('body_rev') or '')[:128],
            'text_index': max(-1, text_index),
            'prefix': prefix,
            'suffix': suffix,
            'block_index': max(-1, block_index),
        },
    }
    return normalized, ''


def _source_quote_prompt(prompt, source_quote):
    if not source_quote:
        return str(prompt or '')
    section = str(source_quote.get('section') or '').strip()
    heading = f'（章节：{section}）' if section else ''
    return (
        f'【任务正文引用{heading}】\n'
        f'{source_quote.get("quote_text") or ""}\n'
        f'【引用结束】\n\n{str(prompt or "")}'
    )


def _handle_ai_fork(parent_run_id, fork_idx, comment, author=None, prompt_comment=None, source_quote=None):
    """从父线程的历史消息点分叉出新线程(多 AI 工具的 Branch)。
    新线程=独立队列条目:metadata.fork 记父指针,prompt=回放+新指令,walk 正常执行/评论流。"""
    parent = _queue_get_entry(parent_run_id)
    if not parent:
        return {'ok': False, 'error': '父线程不存在'}
    if not comment or not str(comment).strip():
        return {'ok': False, 'error': '评论不能为空'}
    tool = parent.get('tool', 'claude')
    if tool not in ('claude', 'codex'):
        return {'ok': False, 'error': f'工具 {tool} 不支持分叉'}
    messages = parent.get('messages') or []
    try:
        fork_idx = int(fork_idx)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'fork_from_index 必须是整数'}
    if fork_idx < 0 or fork_idx >= len(messages):
        return {'ok': False, 'error': f'分叉点越界(可用 0..{max(len(messages) - 1, 0)})'}
    comment = str(comment).strip()
    prompt_comment = str(prompt_comment if prompt_comment is not None else comment).strip()
    prompt_comment = _source_quote_prompt(prompt_comment, source_quote)
    replay = _build_fork_replay(parent, fork_idx)
    fork_meta = {
        'parent_run_id': parent_run_id,
        'parent_index': fork_idx,
        'parent_entry_id': f'{parent_run_id}#{fork_idx}',
        'parent_title': str(parent.get('title') or ''),
    }
    fork_metadata = {'fork': fork_meta}
    # 分叉必须继承父线程的 dialogue lifecycle:未晋升的旁聊(durable_on_promotion)
    # 分叉后不得以占位节点漏进 Project Graph(投影只跳过带 lifecycle 标记的条目)
    parent_metadata = parent.get('metadata') if isinstance(parent.get('metadata'), dict) else {}
    parent_dialogue = parent_metadata.get('dialogue')
    if isinstance(parent_dialogue, dict) and parent_dialogue:
        fork_metadata['dialogue'] = dict(parent_dialogue)
    new_id = _queue_add_entry(
        tool,
        parent.get('path', ''),
        parent.get('workdir', ''),
        prompt_override=replay + '\n【新支线的第一条指令】\n' + prompt_comment,
        metadata=fork_metadata,
        ai_profile=parent.get('ai_profile'),
    )
    # 展示层只记用户的新评论(回放是发送层的事,同 comment/prompt_comment 分离惯例)
    user_message = {
        'role': 'user',
        'content': comment,
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'author': author or '用户',
        'forked_from': fork_meta['parent_entry_id'],
    }
    if source_quote:
        user_message['source_quote'] = source_quote
    _queue_append_message(new_id, user_message)
    _queue_consume_next()
    return {'ok': True, 'run_id': new_id, 'forked_from': fork_meta['parent_entry_id'], 'queued': True}


def _handle_ai_comment(run_id, comment, author=None, prompt_comment=None, skill_meta=None, source_quote=None):
    """在现有线程上追加用户评论，并恢复会话继续执行。支持 Claude 和 Codex。
    支持 killed/error 状态的重试：有有效 session 时 resume，否则 fallback 到全新执行。"""
    entry = _queue_get_entry(run_id)
    if not entry:
        return {'ok': False, 'error': '线程不存在'}
    if not comment or not str(comment).strip():
        return {'ok': False, 'error': '评论不能为空'}
    tool = entry.get('tool', 'claude')
    if tool not in ('claude', 'codex'):
        return {'ok': False, 'error': f'工具 {tool} 不支持评论功能'}
    if entry.get('status') == 'running':
        return {'ok': False, 'error': '别急，先等AI执行完，喝杯咖啡，休息下吧。'}
    if entry.get('status') not in {'completed', 'error', 'killed'}:
        return {'ok': False, 'error': f'当前状态不支持继续（{entry.get("status")}）'}
    session_id = entry.get('session_id')
    session_valid = entry.get('session_valid', True)
    use_resume = bool(session_id and session_valid)
    if not _ai_semaphore.acquire(blocking=False):
        return {'ok': False, 'error': '并发已满，请稍后重试'}

    comment = str(comment).strip()
    prompt_comment = str(prompt_comment if prompt_comment is not None else comment).strip()
    prompt_comment = _source_quote_prompt(prompt_comment, source_quote)
    user_message = {
        'role': 'user',
        'content': comment,
        'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'author': author or '用户',
    }
    if source_quote:
        user_message['source_quote'] = source_quote
    if skill_meta:
        user_message.update({
            'skill_id': skill_meta.get('skill_id') or '',
            'skill_name': skill_meta.get('skill_name') or '',
            'skill_args': skill_meta.get('skill_args') or '',
            'skill_applied': True,
        })
    _queue_append_message(run_id, user_message)
    updates = {
        'status': 'running',
        'pid': None,
        'error': None,
        'output': None,
        'started_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'completed_at': None,
        'duration_ms': None,
        'prompt_length': len(prompt_comment),
        'read': False,
    }
    if not use_resume:
        updates['session_id'] = None
        updates['session_valid'] = True
    _queue_update_entry(run_id, updates)

    if use_resume:
        workdir_value = entry.get('workdir', '')
        cwd_path, cwd_err = resolve_workdir(workdir_value, entry.get('path', ''))
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            _ai_semaphore.release()
            return {'ok': False, 'error': cwd_err or 'workdir 无效'}
        cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
        if cwd_err or not cwd_path:
            _queue_update_entry(run_id, {
                'status': 'error',
                'error': cwd_err or 'workdir 无效',
                'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            }, unless_statuses={'killed'})
            _ai_semaphore.release()
            return {'ok': False, 'error': cwd_err or 'workdir 无效'}
        if not cwd_path.exists():
            cwd_path.mkdir(parents=True, exist_ok=True)
        if tool == 'codex':
            target_fn = _run_codex_resume
        else:
            target_fn = _run_cli_resume
        t = threading.Thread(
            target=target_fn,
            args=(run_id, session_id, str(cwd_path), prompt_comment, entry['path']),
            daemon=True
        )
    else:
        task_file = REPO_ROOT / entry['path']
        task_content = task_file.read_text(encoding='utf-8') if task_file.exists() else ''
        combined_prompt = prompt_comment
        if task_content:
            combined_prompt = f"{prompt_comment}\n\n---\n\n{task_content}"
        t = threading.Thread(
            target=_run_cli,
            args=(run_id, entry['path'], tool, combined_prompt),
            daemon=True
        )
    with _ai_runs_lock:
        _ai_runs[run_id] = {
            'thread': t,
            'path': entry['path'],
            'tool': tool,
            'started_at': time.time(),
            'killed': False,
        }
    t.start()
    return {'ok': True, 'run_id': run_id, 'skill': skill_meta or None}

def _orphaned_unknown_updates(now, *, observed_after_restart=False):
    reason = (
        '服务重启后观察到孤儿进程已退出；输出管道已断，最终结果未知'
        if observed_after_restart else
        '服务重启时原运行进程已退出；输出管道已断，最终结果未知'
    )
    return {
        'status': _ORPHANED_UNKNOWN,
        'error': reason,
        'completed_at': now,
        'last_observed_at': now,
        'recovery_state': 'pid-exited-output-unknown',
    }


def _reconcile_orphaned_runs():
    """把重启后仍存活但已断流的进程在退出时诚实地终态化。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        for entry in queue.get('entries', []):
            if entry.get('status') != _ORPHANED_RUNNING:
                continue
            if server_instance.process_matches_started_at(
                entry.get('pid'),
                str(entry.get('pid_started_at') or entry.get('started_at') or ''),
            ):
                continue
            entry.update(_orphaned_unknown_updates(now, observed_after_restart=True))
            changed = True
        if changed:
            _queue_save_unlocked(queue)
    if changed:
        _queue_consume_next()
    return changed


def _recover_queue():
    """启动对账：保留队列，按 pid 把断流运行标成显式孤儿态。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        for entry in queue['entries']:
            status = entry.get('status')
            if status not in {'running', _ORPHANED_RUNNING}:
                continue
            if status == 'running' and _recover_running_entry_from_durable_message(entry, now):
                changed = True
                continue
            if server_instance.process_matches_started_at(
                entry.get('pid'),
                str(entry.get('pid_started_at') or entry.get('started_at') or ''),
            ):
                entry.update({
                    'status': _ORPHANED_RUNNING,
                    'error': '服务已重启；子进程仍存活，但输出管道已断，不能续接或读取最终输出',
                    'last_observed_at': now,
                    'recovery_state': 'pid-still-running-output-detached',
                })
            else:
                entry.update(_orphaned_unknown_updates(now))
            changed = True
        if changed:
            _queue_save_unlocked(queue)
    # 尝试恢复排队中的任务
    _queue_consume_next()

def _migrate_jsonl_to_queue():
    """一次性迁移：将现有 .ai-results.jsonl 文件合并到全局 .ai-queue.json。"""
    with _queue_lock:
        queue = _queue_load_unlocked()
        changed = _queue_prune_missing_entries(queue)
        existing_ids = {e['id'] for e in queue['entries']}
        migrated = 0
        for scan_dir in SCAN_DIRS:
            base = REPO_ROOT / scan_dir
            if not base.exists():
                continue
            for jsonl_file in list(base.rglob('*.ai-results.jsonl')):
                try:
                    lines = jsonl_file.read_text(encoding='utf-8').strip().split('\n')
                except Exception:
                    continue
                for line in lines:
                    try:
                        old = json.loads(line.strip())
                    except Exception:
                        continue
                    entry_id = old.get('run_id', uuid.uuid4().hex[:8])
                    if entry_id in existing_ids:
                        continue
                    entry = {
                        'id': entry_id,
                        'tool': old.get('tool', 'claude'),
                        'path': old.get('path', ''),
                        'workdir': old.get('workdir', ''),
                        'status': old.get('status', 'completed'),
                        'read': True,  # 旧记录视为已读
                        'order': len(queue['entries']),
                        'pid': old.get('pid'),
                        'timestamp': old.get('timestamp', ''),
                        'started_at': None,
                        'completed_at': old.get('timestamp', ''),
                        'duration_ms': old.get('duration_ms'),
                        'output': old.get('output'),
                        'error': old.get('error'),
                        'session_id': None,
                        'session_valid': False,
                        'messages': [{
                            'role': 'ai',
                            'content': old.get('output'),
                            'timestamp': old.get('timestamp', ''),
                            'duration_ms': old.get('duration_ms'),
                            'model': None,
                            'input_tokens': None,
                            'output_tokens': None,
                        }] if old.get('output') else [],
                        'title': _truncate_title(old.get('output')),
                        'prompt_length': old.get('prompt_length', 0),
                        'output_length': old.get('output_length', 0),
                    }
                    queue['entries'].append(entry)
                    existing_ids.add(entry_id)
                    migrated += 1
                    changed = True
        if changed:
            _queue_save_unlocked(queue)
        if migrated:
            print(f"  迁移: {migrated} 条 AI 记录已导入队列")

# ── HTTP 服务器 ────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {args[0]}")

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _bound_port(self):
        server = getattr(self, 'server', None)
        port = getattr(server, 'server_port', None)
        if port:
            return port
        address = getattr(server, 'server_address', None)
        if isinstance(address, tuple) and len(address) > 1:
            return address[1]
        return PORT

    def _host_name(self):
        headers = getattr(self, 'headers', None)
        if headers is None:
            # Unit-level handler probes do not construct BaseHTTPRequestHandler.
            # A real accepted HTTP request always has a headers object.
            return 'localhost' if not hasattr(self, 'server') else ''
        host = str(headers.get('Host', '') or '').strip()
        if not host:
            if not hasattr(self, 'server'):
                return 'localhost'
            return ''
        if any(char in host for char in (',', '/', '\\', '@')) or any(char.isspace() for char in host):
            return ''
        try:
            parsed = urlparse(f'//{host}')
            if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                return ''
            return (parsed.hostname or '').lower()
        except ValueError:
            return ''

    def _security_denied(self, reason):
        client = getattr(self, 'client_address', ('unknown',))[0]
        method = str(getattr(self, 'command', '') or 'UNKNOWN')[:12]
        path = str(getattr(self, 'path', '') or '/')[:240].replace('\n', ' ')
        print(f'[security] denied method={method} client={client} path={path} reason={reason}', file=sys.stderr)

    def _request_host_guard(self):
        host_name = self._host_name()
        if host_name not in ALLOWED_HOSTS:
            self._security_denied('untrusted-host')
            self._json({'ok': False, 'error': 'cross-origin blocked'}, 403)
            return False
        return True

    def _allowed_origins(self):
        port = self._bound_port()
        allowed = {f'http://localhost:{port}', f'http://127.0.0.1:{port}'}
        # Owner 2026-07-03 拍板(KAN-110):canvas-studio 空间工作台是自己人——
        # 精确放行 config canvas_studio_url 这一个源;硬约束仅限 http+本机回环,
        # 配置写了外网地址也不会被信任;守护其余逻辑一寸不动。
        try:
            studio = str(load_config().get('canvas_studio_url')
                         or _DEFAULTS.get('canvas_studio_url') or '').strip().rstrip('/')
            if studio:
                parsed_studio = urlparse(studio)
                if parsed_studio.scheme == 'http' and parsed_studio.hostname in ('localhost', '127.0.0.1'):
                    allowed.add(f'http://{parsed_studio.netloc}')
                    alt_host = '127.0.0.1' if parsed_studio.hostname == 'localhost' else 'localhost'
                    if parsed_studio.port:
                        allowed.add(f'http://{alt_host}:{parsed_studio.port}')
        except Exception:
            pass
        return allowed

    def _state_change_guard(self, path):
        if path in _STATE_CHANGE_GUARD_EXEMPT_PATHS:
            return True
        if not self._request_host_guard():
            return False
        origin = str(self.headers.get('Origin', '') or '').strip()
        if origin and origin.rstrip('/') not in self._allowed_origins():
            self._security_denied('untrusted-origin')
            self._json({'ok': False, 'error': 'cross-origin blocked'}, 403)
            return False
        return True

    # ── 认证辅助方法 ──

    def _autologin_user_from_request(self):
        """Return configured bypass user when ?autologin=1 is explicitly allowed."""
        try:
            parsed = urlparse(getattr(self, 'path', '') or '')
            wants_autologin = '1' in parse_qs(parsed.query).get('autologin', [])
        except Exception:
            wants_autologin = False
        if not wants_autologin:
            return ''
        auth_cfg = _auth_config()
        # This only helps a remote team board if that service runs this same code
        # and its own config explicitly enables auth.autologin.
        if auth_cfg.get('autologin') is not True:
            return ''
        bypass_user = _auth_bypass_user(auth_cfg)
        return bypass_user if bypass_user in ALL_MEMBERS else ''

    def _get_session(self):
        """从 Cookie 中读取并验证会话。返回 session dict 或 None。"""
        def fallback_session(user=''):
            session_user = user if user in ALL_MEMBERS else CURRENT_MEMBER
            if session_user and session_user in ALL_MEMBERS:
                return {'user': session_user, 'created_at': 0}
            if os.environ.get('CI') == 'true' and ALL_MEMBERS:
                return {'user': ALL_MEMBERS[0], 'created_at': 0}
            return None

        _cleanup_expired_sessions()
        autologin_user = self._autologin_user_from_request()
        if not hasattr(self, 'headers'):
            return fallback_session(autologin_user)
        cookie_header = self.headers.get('Cookie', '')
        if not cookie_header and isinstance(self.headers, dict):
            return fallback_session(autologin_user)
        if not cookie_header:
            return fallback_session(autologin_user)
        session = _session_from_cookie_header(cookie_header)
        return session or fallback_session(autologin_user)

    def _get_client_ip(self):
        return self.client_address[0]

    def _check_rate_limit(self):
        """检查登录速率限制。返回 (allowed, error_dict_or_None)。"""
        ip = self._get_client_ip()
        now = time.time()
        attempt = _login_attempts.get(ip)
        if attempt and attempt.get('locked_until', 0) > now:
            retry_after = int(attempt['locked_until'] - now)
            return False, {'ok': False, 'error': f'登录尝试过多，请 {retry_after} 秒后再试', 'retry_after': retry_after}
        return True, None

    def _record_failed_login(self):
        ip = self._get_client_ip()
        now = time.time()
        attempt = _login_attempts.get(ip, {'count': 0, 'locked_until': 0})
        attempt['count'] = attempt.get('count', 0) + 1
        if attempt['count'] >= 3:
            attempt['locked_until'] = now + 900
            attempt['count'] = 0
        _login_attempts[ip] = attempt

    def _clear_rate_limit(self):
        _login_attempts.pop(self._get_client_ip(), None)

    def _send_unauthorized(self):
        self._json({'ok': False, 'requireLogin': True}, 401)

    def _serve_html(self):
        """提供 HTML 页面，根据认证状态注入不同数据。"""
        wants_app = '1' in parse_qs(urlparse(self.path).query).get('app', [])
        _cleanup_expired_sessions()
        existing_cookie_session = None
        if hasattr(self, 'headers'):
            existing_cookie_session = _session_from_cookie_header(self.headers.get('Cookie', ''))
        session = self._get_session()
        autologin_user = self._autologin_user_from_request()
        session_cookie = ''
        if autologin_user and not existing_cookie_session:
            _cleanup_expired_sessions()
            token = secrets.token_hex(32)
            _sessions[token] = {'user': autologin_user, 'created_at': time.time()}
            session = _sessions[token]
            session_cookie = f'kanban_session={token}; HttpOnly; SameSite=Lax; Path=/'
        if not (session and session.get('user')) and not wants_app:
            public_html = render_public_entry_html()
            if public_html is not None:
                body = public_html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(body))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
        if session and session.get('user'):
            data = get_data()
            data['auth'] = {'authenticated': True, 'user': session['user']}
        else:
            config = load_config()
            ai_members = config.get('ai_members') or []
            data = {
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'stats': {'total_tasks': 0, 'projects': 0, 'active_projects': 0, 'members': 0},
                'tasks': [], 'members': [], 'project_names': [],
                'all_members': _combined_assignee_members(ALL_MEMBERS, ai_members),
                'ai_members': ai_members,
                'team_kanban_url': config.get('team_kanban_url') or _DEFAULTS['team_kanban_url'],
                'default_tools': {}, 'user_tool_overrides': {},
                'local_integrations': [],
                'ui_features': {},
                'auth': {'authenticated': False},
            }

        html = generate_html(data)
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        if session_cookie:
            self.send_header('Set-Cookie', session_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _serve_static_asset(self, request_path):
        raw_rel = request_path.removeprefix('/static/').strip('/')
        asset_path = (_STATIC_ROOT / raw_rel).resolve()
        if asset_path != _STATIC_ROOT_RESOLVED and _STATIC_ROOT_RESOLVED not in asset_path.parents:
            self.send_error(403)
            return
        if not asset_path.exists() or not asset_path.is_file():
            self.send_error(404)
            return
        content_type = _guess_static_content_type(asset_path)
        body = asset_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(body)

    def _serve_canvas_asset(self, request_path):
        config = load_config()
        dist_dir = studio_static.resolve_dist_dir(
            REPO_ROOT,
            config.get('studio_dist_dir'),
            _DEFAULTS['studio_dist_dir'],
        )
        response = studio_static.resolve_request(request_path, dist_dir)
        self.send_response(response.status)
        self.send_header('Content-Type', response.content_type)
        self.send_header('Content-Length', len(response.body))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(response.body)

    def _handle_login(self):
        """Return the configured local authentication challenge."""
        allowed, err = self._check_rate_limit()
        if not allowed:
            self._json(err, 429)
            return
        if AUTH_MODE == 'token':
            self._json({
                'ok': True,
                'auth_mode': 'token',
                'question': '请输入本机 .kanban.auth-token 文件中的访问 token。',
                'options': [],
            })
            return
        quiz_token = secrets.token_hex(32)
        shuffled = QUIZ_OPTIONS[:]
        random.shuffle(shuffled)
        correct_indices = [i for i, (_, is_correct) in enumerate(shuffled) if is_correct]
        option_texts = [text for text, _ in shuffled]
        _quiz_tokens[quiz_token] = {
            'options': option_texts,
            'correct_indices': correct_indices,
            'created_at': time.time(),
        }
        now = time.time()
        expired = [k for k, v in _quiz_tokens.items() if now - v['created_at'] > QUIZ_TIMEOUT]
        for key in expired:
            del _quiz_tokens[key]
        self._json({
            'ok': True,
            'auth_mode': 'quiz',
            'quiz_token': quiz_token,
            'question': QUIZ_QUESTION,
            'options': option_texts,
        })

    def _create_login_session(self, member):
        _cleanup_expired_sessions()
        session_token = secrets.token_hex(32)
        _sessions[session_token] = {'user': member, 'created_at': time.time()}
        resp = json.dumps({'ok': True, 'user': member}, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(resp))
        self.send_header('Set-Cookie', f'kanban_session={session_token}; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(resp)

    def _handle_verify_token(self):
        if AUTH_MODE != 'token':
            self._json({'ok': False, 'error': 'token 登录未启用'}, 404)
            return
        allowed, err = self._check_rate_limit()
        if not allowed:
            self._json(err, 429)
            return
        body = self._read_json_body()
        supplied = body.get('access_token', '')
        if not isinstance(supplied, str):
            self._json({'ok': False, 'error': '请求格式错误'}, 400)
            return
        matched_member = LOGIN_MEMBERS[0] if LOGIN_MEMBERS else ''
        if AUTH_ACCESS_TOKEN and matched_member and secrets.compare_digest(supplied.strip(), AUTH_ACCESS_TOKEN):
            self._clear_rate_limit()
            self._create_login_session(matched_member)
            return
        self._record_failed_login()
        self._json({'ok': False, 'error': '验证失败'}, 401)

    def _handle_verify_quiz(self):
        """验证测验答案和姓名：正确则创建会话。"""
        if AUTH_MODE != 'quiz':
            self._json({'ok': False, 'error': 'quiz 登录未启用'}, 404)
            return
        allowed, err = self._check_rate_limit()
        if not allowed:
            self._json(err, 429)
            return
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({'ok': False, 'error': '请求格式错误'}, 400)
            return
        if not isinstance(body, dict):
            self._json({'ok': False, 'error': '请求格式错误'}, 400)
            return
        quiz_token = body.get('quiz_token', '')
        selected = body.get('selected', [])
        name_raw = body.get('name', '')
        if not isinstance(quiz_token, str) or not isinstance(name_raw, str):
            self._json({'ok': False, 'error': '请求格式错误'}, 400)
            return
        name = name_raw.strip()

        entry = _quiz_tokens.get(quiz_token)
        if not entry:
            self._json({'ok': False, 'error': '测验已过期，请刷新页面'}, 401)
            return
        if time.time() - entry['created_at'] > QUIZ_TIMEOUT:
            del _quiz_tokens[quiz_token]
            self._json({'ok': False, 'error': '测验已过期，请刷新页面'}, 401)
            return

        matched_member = None
        for member in LOGIN_MEMBERS:
            member_name = member.strip()
            if not member_name:
                continue
            if member_name == name:
                matched_member = member
                break
            if member_name.isascii() and name and member_name.lower() == name.lower():
                matched_member = member
                break

        correct = set(entry['correct_indices'])
        selected_set = set()
        if isinstance(selected, list):
            selected_set = {i for i in selected if isinstance(i, int)}

        if selected_set == correct and matched_member:
            del _quiz_tokens[quiz_token]
            self._clear_rate_limit()
            self._create_login_session(matched_member)
            return

        del _quiz_tokens[quiz_token]
        self._record_failed_login()
        self._json({'ok': False, 'error': '验证失败'}, 401)

    def _handle_select_user(self):
        """处理用户选择/切换请求。"""
        session = self._get_session()
        if not session:
            self._send_unauthorized()
            return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
        user = body.get('user', '')
        if user not in LOGIN_MEMBERS:
            self._json({'ok': False, 'error': '用户不在成员列表中'}, 400)
            return
        session['user'] = user
        self._json({'ok': True, 'user': user})

    def _handle_logout(self):
        """处理退出登录请求：销毁会话。"""
        cookie_header = self.headers.get('Cookie', '')
        token = None
        for part in cookie_header.split(';'):
            part = part.strip()
            if part.startswith('kanban_session='):
                token = part.split('=', 1)[1].strip()
                break
        if token and token in _sessions:
            del _sessions[token]
        resp = json.dumps({'ok': True}, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(resp))
        self.send_header('Set-Cookie', 'kanban_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
        self.end_headers()
        self.wfile.write(resp)

    def _handle_sync_webhook(self):
        manager = GIT_SYNC_MANAGER
        if not manager:
            self._json({'ok': False, 'error': 'git sync unavailable'}, 503)
            return
        if not hasattr(manager, 'mode') or manager.mode != 'server':
            self._json({'ok': False, 'error': 'webhook only enabled in server mode'}, 404)
            return
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length)
        signature = self.headers.get('X-Hub-Signature-256') or ''
        if not manager.verify_webhook_signature(raw_body, signature):
            self._json({'ok': False, 'error': 'invalid signature'}, 401)
            return
        event_name = self.headers.get('X-GitHub-Event', '')
        should_handle, reason = manager.should_handle_github_push(event_name, raw_body)
        if not should_handle:
            self._json({'ok': True, 'ignored': True, 'reason': reason}, 202)
            return
        manager.request_reconcile('webhook')
        self._json({'ok': True, 'status': manager.get_status_snapshot()})

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode('utf-8')
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            raise JsonBodyError('invalid JSON body') from e
        if not isinstance(body, dict):
            raise JsonBodyError('JSON body must be an object')
        return body

    def _handle_request_exception(self, exc):
        if isinstance(exc, JsonBodyError):
            self._json({'ok': False, 'error': str(exc)}, 400)
            return
        traceback.print_exc()
        self._json({'ok': False, 'error': 'internal error'}, 500)

    def _sync_manager(self):
        return _active_sync_manager()

    def _handle_sync_events(self):
        managers = []
        if GIT_SYNC_MANAGER:
            managers.append(GIT_SYNC_MANAGER)
        if not managers:
            self._json({'ok': False, 'error': 'git sync unavailable'}, 503)
            return
        subscriber_pairs = [(manager, manager.subscribe()) for manager in managers]
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        try:
            last_keepalive = time.time()
            while True:
                wrote_event = False
                for _manager, subscriber in subscriber_pairs:
                    try:
                        event = subscriber.get_nowait()
                    except queue.Empty:
                        continue
                    payload = json.dumps(event, ensure_ascii=False)
                    chunk = f"event: {event.get('type', 'status')}\ndata: {payload}\n\n".encode('utf-8')
                    self.wfile.write(chunk)
                    wrote_event = True
                if not wrote_event:
                    time.sleep(0.25)
                    if time.time() - last_keepalive >= 30:
                        chunk = b": keepalive\n\n"
                        self.wfile.write(chunk)
                        last_keepalive = time.time()
                self.wfile.flush()
        except Exception:
            pass
        finally:
            for manager, subscriber in subscriber_pairs:
                manager.unsubscribe(subscriber)

    def _resolve_registered_route(self, method, request_path):
        route_key = (method, request_path)
        handler_name = _ROUTE_REGISTRY.get(route_key)
        if handler_name:
            return route_key, handler_name
        for candidate, candidate_handler in _ROUTE_REGISTRY.items():
            candidate_method, candidate_path = candidate
            if (candidate_method == method and candidate_path.endswith('*')
                    and request_path.startswith(candidate_path[:-1])):
                return candidate, candidate_handler
        return route_key, None

    def _dispatch_registered_route(self, method, parsed):
        """Resolve one route, enforce shared guards, then call its thin handler."""
        method = str(method or '').upper()
        route_key, handler_name = self._resolve_registered_route(method, parsed.path)

        # Every mutating request crosses the same Host/Origin guard.  The sole
        # existing webhook exemption remains explicit and is still HMAC-checked
        # inside its route handler.  Two legacy guarded GETs keep that boundary.
        if method in _STATE_CHANGE_METHODS or route_key in _EXTRA_GUARDED_ROUTE_KEYS:
            if not self._state_change_guard(parsed.path):
                return

        session = None
        if route_key not in _PUBLIC_ROUTE_KEYS:
            session = self._get_session()
            if not session:
                self._send_unauthorized()
                return

        if handler_name is None:
            self._json({'ok': False, 'error': 'Not Found'}, 404)
            return
        handler = getattr(self, handler_name)
        handler(parsed, parse_qs(parsed.query), session)

    def _route_get_canvas_view(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        html, status = build_canvas_view_html(path_param)
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _route_get_api_data(self, parsed, query, session):
        self._json(get_data())

    def _route_get_api_dynamic_boards(self, parsed, query, session):
        self._json(get_dynamic_boards())

    def _route_get_api_project_maps(self, parsed, query, session):
        result, status = list_project_map_canvases()
        self._json(result, status)

    def _route_get_api_task_canvases(self, parsed, query, session):
        result, status = list_task_canvases()
        self._json(result, status)

    def _route_get_api_conversation_maps(self, parsed, query, session):
        result, status = list_conversation_map_manifests()
        self._json(result, status)

    def _route_get_api_conversation_map(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        result, status = get_conversation_map_manifest(path_param)
        self._json(result, status)

    def _route_get_api_conversation_project_graph(self, parsed, query, session):
        result, status = conversation_project_graph.build_project_graph(
            _conversation_project_graph_deps()
        )
        self._json(result, status)

    def _route_get_api_real_projects(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        include_archived = qs.get('include_archived', ['0'])[0] == '1'
        result, status = get_real_projects(include_archived=include_archived)
        self._json(result, status)

    def _route_get_api_project_materials(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        result, status = get_project_materials(qs.get('project_ref', [''])[0])
        self._json(result, status)

    def _route_get_api_project_posture(self, parsed, query, session):
        result, status = get_project_posture()
        self._json(result, status)

    def _route_get_api_owner_world(self, parsed, query, session):
        result, status = get_owner_world()
        self._json(result, status)

    def _route_get_api_relationship_cards(self, parsed, query, session):
        config = load_config()
        people_dir = _enabled_existing_path(config, 'relationships', 'people_dir', directory=True)
        projection_dir = _enabled_existing_path(config, 'relationships', 'team_projection_dir', directory=True)
        if relationship_cards is None or mario_levels is None or people_dir is None:
            self._json({'ok': True, 'enabled': False, 'cards': [], 'count': 0})
            return
        mario_registry, _ = mario_levels.list_levels()
        result, status = relationship_cards.build_catalog(
            people_dir,
            projection_dir or people_dir / '.disabled-team-projection',
            mario_registrations=mario_registry.get('levels', []),
        )
        self._json(result, status)

    def _route_get_api_session_evidence_search(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        result, status = session_evidence_adapter.search(
            _session_evidence_deps(),
            qs.get('q', [''])[0],
            days=qs.get('days', [90])[0],
            limit=qs.get('limit', [20])[0],
        )
        self._json(result, status)

    def _route_get_api_governance_probe(self, parsed, query, session):
        self._json(load_governance_probe())

    def _route_get_api_governance_healthcheck_status(self, parsed, query, session):
        self._json(get_governance_healthcheck_status())

    def _route_get_api_governance_noise_review_status(self, parsed, query, session):
        self._json(get_governance_noise_review_status())

    def _route_get_api_task(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [None])[0]
        code_param = qs.get('code', [None])[0]
        result, status = get_task_detail(path=path_param, code=code_param)
        self._json(result, status)

    def _route_get_api_review_cycle(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        task_path = qs.get('path', [''])[0]
        try:
            state = review_cycle.project_state(REPO_ROOT, task_path, SCAN_DIRS)
            self._json({'ok': True, 'review_cycle': state})
        except review_cycle.ReviewCycleError as exc:
            self._json({'ok': False, 'error': str(exc)}, 400)

    def _route_get_api_task_documents(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        result, status = task_document_links.list_linked_documents(
            _task_document_link_deps(),
            qs.get('path', [''])[0],
        )
        self._json(result, status)

    def _route_get_api_task_comments(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        result, status = comment_import.get_task_comments(_comment_import_deps(), path_param)
        self._json(result, status)

    def _route_get_api_ledger_wildcard(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        qs = parse_qs(parsed.query)
        task_id = unquote(parsed.path[len('/api/ledger/'):]).strip('/')
        result, status = ledger_query.query_task_ledger(
            _ledger_query_deps(),
            task_id,
            since=qs.get('since', [''])[0],
            kind=qs.get('kind', [''])[0],
        )
        self._json(result, status)

    def _route_get_api_canvas_node_history(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        qs = parse_qs(parsed.query)
        result, status = ledger_query.get_node_history(
            _ledger_query_deps(),
            qs.get('task_id', [''])[0] or qs.get('path', [''])[0],
            qs.get('node_id', [''])[0],
            since=qs.get('since', [''])[0],
        )
        self._json(result, status)

    def _route_get_api_canvas(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        map_param = qs.get('map', [''])[0]
        if map_param:
            result, status = get_project_map_canvas(map_param)
            self._json(result, status)
            return
        convmap_param = qs.get('convmap', [''])[0]
        if convmap_param:
            result, status = get_conversation_map_canvas(convmap_param)
            self._json(result, status)
            return
        path_param = qs.get('path', [''])[0]
        result, status = get_canvas_for_task(path_param)
        self._json(result, status)

    def _route_get_api_attention_queue(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        qs = parse_qs(parsed.query)
        self._json(attention_queue.build_attention_queue(
            scan_all(), requires_owner_action,
            project=qs.get('project', [''])[0],
            record_classifier=attention_gate.is_backstage_record,
        ))

    def _route_get_api_system_alerts(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        if system_alerts is None:
            self._json({"ok": True, "has_anomaly": False, "count": 0, "summary": "", "items": []})
            return
        self._json(system_alerts.build_system_alerts(
            scan_all(),
            configured_chains(),
            get_governance_healthcheck_status(),
            get_governance_noise_review_status(),
        ))

    def _route_get_api_canvas_events(self, parsed, query, session):
        # 构图事件账(Owner:「我放的动作也要可追踪的链」):只增流,回放这张图怎么长成现在的样子
        qs = parse_qs(parsed.query)
        map_param = qs.get('map', [''])[0]
        if map_param:
            result, status = get_project_map_canvas_events(map_param)
            self._json(result, status)
            return
        convmap_param = qs.get('convmap', [''])[0]
        if convmap_param:
            result, status = get_conversation_map_canvas_events(convmap_param)
            self._json(result, status)
            return
        path_param = qs.get('path', [''])[0]
        _t, rel_path, err, status = _resolve_active_task_card_path(path_param)
        if err:
            self._json({'ok': False, 'error': err}, status)
        else:
            task_file, read_err = _read_task_file(rel_path)
            if not task_file:
                self._json({'ok': False, 'error': read_err}, 404)
            else:
                canvas_path, _rel, ref_err, ref_status = _resolve_canvas_ref(rel_path, task_file['frontmatter'] or {})
                if ref_err:
                    self._json({'ok': False, 'error': ref_err}, ref_status)
                else:
                    report = _canvas_events_read_report(canvas_path)
                    events = report['events']
                    self._json({
                        'ok': True,
                        'schema': CANVAS_EVENTS_SCHEMA,
                        'count': len(events),
                        'malformed_lines': report['malformed_lines'],
                        'events': events,
                    })

    def _route_get_api_canvas_versions(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        qs = parse_qs(parsed.query)
        map_param = qs.get('map', [''])[0]
        path_param = qs.get('path', [''])[0]
        if map_param.startswith('card:') or path_param:
            result, status = get_task_canvas_versions(
                path_param or map_param.removeprefix('card:'),
                version_id=qs.get('version', [''])[0],
            )
            self._json(result, status)
            return
        result, status = get_project_map_canvas_versions(
            map_param,
            version_id=qs.get('version', [''])[0],
        )
        self._json(result, status)

    def _route_get_api_canvas_seed_intent(self, parsed, query, session):
        if not self._state_change_guard(parsed.path):
            return
        qs = parse_qs(parsed.query)
        result, status = infer_canvas_seed_intent(qs.get('path', [''])[0])
        self._json(result, status)

    def _route_get_api_task_ledger(self, parsed, query, session):
        # 评论分支耐久台账(KAN-111):返回只增事件流,树由 parent 指针在客户端重建
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        _task_path, rel_path, err, status = _resolve_active_task_card_path(path_param)
        if err:
            self._json({'ok': False, 'error': err}, status)
        else:
            events, ledger_err = _ledger_read_events(rel_path)
            if events is None:
                self._json({'ok': False, 'error': ledger_err}, 400)
            else:
                self._json({
                    'ok': True,
                    'schema': COMMENTS_LEDGER_SCHEMA,
                    'ledger_ref': _ledger_rel_for_task(rel_path),
                    'count': len(events),
                    'entries': events,
                })

    def _route_get_api_card_lineage(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        _task_path, rel_path, err, status = _resolve_active_task_card_path(path_param)
        if err:
            self._json({'ok': False, 'error': err}, status)
        else:
            events, lineage_err = _lineage_read_events(rel_path)
            if events is None:
                self._json({'ok': False, 'error': lineage_err}, 400)
            else:
                self._json({
                    'ok': True,
                    'schema': CARD_LINEAGE_SCHEMA,
                    'lineage_ref': _lineage_rel_for_task(rel_path),
                    'count': len(events),
                    'entries': events,
                })

    def _route_get_api_sync_status(self, parsed, query, session):
        if not GIT_SYNC_MANAGER:
            self._json({'ok': False, 'error': 'git sync unavailable'}, 503)
        else:
            self._json({'ok': True, 'status': _sync_status_payload()})

    def _route_get_api_sync_events(self, parsed, query, session):
        self._handle_sync_events()

    def _route_get_api_network_status(self, parsed, query, session):
        self._json(get_network_status())

    def _route_get_api_bridges_status(self, parsed, query, session):
        self._json(get_bridge_status())

    def _route_get_api_governance_matrix(self, parsed, query, session):
        self._json(load_governance_matrix())

    def _route_get_api_governance_maintenance(self, parsed, query, session):
        self._json(load_agent_mail_maintenance())

    def _route_get_api_chains_km(self, parsed, query, session):
        self._json(load_km_chain_data())

    def _route_get_api_chains_wildcard(self, parsed, query, session):
        chain_id = unquote(parsed.path.removeprefix('/api/chains/')).strip('/')
        self._json(load_chain_data(chain_id))

    def _route_get_api_queue(self, parsed, query, session):
        queue = _queue_snapshot()
        # 为运行中的条目补充实时已用时间
        with _ai_runs_lock:
            for entry in queue['entries']:
                if entry['status'] == 'running' and entry['id'] in _ai_runs:
                    elapsed = int((time.time() - _ai_runs[entry['id']].get('started_at', time.time())) * 1000)
                    entry['elapsed_ms'] = elapsed
                elif entry['status'] == _ORPHANED_RUNNING and entry.get('started_at'):
                    try:
                        started = datetime.strptime(entry['started_at'], '%Y-%m-%dT%H:%M:%S').timestamp()
                        entry['elapsed_ms'] = max(0, int((time.time() - started) * 1000))
                    except (TypeError, ValueError):
                        pass
        self._json({'ok': True, 'queue': queue})

    def _route_get_api_skills(self, parsed, query, session):
        self._json({'ok': True, 'skills': _scan_skills()})

    def _route_get_api_file(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        image_path, err = _safe_repo_path(path_param, allow_exts=ALLOWED_IMAGE_EXTS)
        if err:
            self._json({'ok': False, 'error': err}, 400)
            return
        if not _path_in_scan_dirs(image_path):
            self._json({'ok': False, 'error': '仅支持 scan_dirs 目录下的图片'}, 400)
            return
        if not image_path.exists() or not image_path.is_file():
            self._json({'ok': False, 'error': '文件不存在'}, 404)
            return
        body = image_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', _content_type_for_image(image_path))
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(body)

    def _route_get_api_ai_results(self, parsed, query, session):
        # 向后兼容：从队列中按路径过滤
        qs = parse_qs(parsed.query)
        path = qs.get('path', [''])[0]
        run_id = qs.get('run_id', [None])[0]
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        if run_id and not path:
            entry = _queue_get_entry(run_id)
            entries = [entry] if entry else []
        else:
            entries = _queue_get_by_path(path)
        results = []
        for e in entries:
            if not e:
                continue
            result = {
                'run_id': e['id'], 'tool': e['tool'], 'path': e['path'],
                'workdir': e.get('workdir', ''),
                'status': e['status'], 'pid': e.get('pid'),
                'timestamp': e.get('timestamp', ''),
                'duration_ms': e.get('duration_ms'),
                'output': e.get('output'), 'error': e.get('error'),
                'session_id': e.get('session_id'),
                'session_valid': e.get('session_valid', True),
                'messages': e.get('messages', []),
                'title': e.get('title', ''),
                'prompt_length': e.get('prompt_length', 0),
                'output_length': e.get('output_length', 0),
                # KAN-834: 透出 metadata（含 fork 父指针），否则前端树逻辑拿不到 metadata.fork，
                # 分叉线程会退化成底部平铺卡片而非嵌套到分叉点。
                'metadata': e.get('metadata', {}),
            }
            result.update(_lineage_tool_session_fields(e.get('tool'), e.get('session_id')))
            results.append(result)
        results.sort(key=lambda r: r.get('timestamp', ''), reverse=True)
        running = []
        with _ai_runs_lock:
            for rid, info in _ai_runs.items():
                if info.get('path') == path:
                    running.append({
                        'run_id': rid, 'tool': info.get('tool', ''),
                        'status': info.get('status', 'running'),
                        'pid': info['proc'].pid if info.get('proc') else None,
                    })
        if run_id:
            with _ai_runs_lock:
                if run_id in _ai_runs:
                    for r in results:
                        if r.get('run_id') == run_id and r.get('status') not in ('completed', 'error', 'timeout', 'killed'):
                            r['status'] = 'running'
        self._json({'ok': True, 'results': results, 'running': running})

    def _route_get_api_search_files(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        query = qs.get('q', [''])[0].strip()
        project = qs.get('project', [''])[0].strip()
        try:
            offset = int(qs.get('offset', ['0'])[0])
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(qs.get('limit', ['50'])[0])
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        category = qs.get('type', [''])[0].strip()
        results, total, all_total, category_counts = search_all_files(query, project, offset, limit, category)
        self._json({
            'ok': True,
            'results': results,
            'total': total,
            'all_total': all_total,
            'category_counts': category_counts,
            'has_more': offset + len(results) < total,
        })

    def _route_get_api_file_exists(self, parsed, query, session):
        qs = parse_qs(parsed.query)
        path_param = qs.get('path', [''])[0]
        safe, err = _safe_repo_path(path_param)
        self._json({'ok': True, 'exists': bool(safe and safe.exists() and not err)})

    def _route_put_api_update(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        field = body.get('field', '')
        value = body.get('value', '')
        # 安全检查：防止路径遍历
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        # 飞书通知：指派变更前读取旧 frontmatter
        old_fm = None
        if field == 'assignee' and value:
            fpath = REPO_ROOT / path
            if fpath.exists():
                content = fpath.read_text(encoding='utf-8')
                old_fm, _ = extract_frontmatter(content)
        old_assignee = old_fm.get('assignee', '') if old_fm else ''
        result = update_frontmatter_field(path, field, value)
        # 处理返回值：可能为 (ok, msg) 或 (ok, msg, new_path)
        ok, msg = result[0], result[1]
        new_path = result[2] if len(result) > 2 else None
        killed_entries = []
        if ok and field == 'status' and value == 'done':
            killed_entries = _queue_kill_entries_for_path(path)
            # Owner 经 UI 点「验收」→ status:done：打验收人标记 accepted_by:owner。
            # 这是 Owner 手动验收的唯一写路径（CLI/人闸代收走各自的落点，
            # 不经 /api/update），故在此打 owner 不会误标机器代收的卡。
            try:
                _stamp_acceptance(new_path or path, 'owner')
            except Exception:
                pass
        response = {'ok': ok, 'message': msg}
        if new_path:
            response['new_path'] = new_path
        if killed_entries:
            response['killed_entries'] = killed_entries
        # 飞书通知：指派变更后通知新旧负责人
        if ok and field == 'assignee' and value and old_assignee != value:
            task_id = old_fm.get('task_id', '') if old_fm else ''
            title = old_fm.get('title', '') if old_fm else ''
            priority = old_fm.get('priority', 'medium') if old_fm else 'medium'
            due_date = old_fm.get('due_date', '') if old_fm else ''
            parts = Path(path).parts
            project = parts[1] if len(parts) > 1 else ''
            feishu_warning = feishu_notify.notify_assignee(
                value, task_id, title, priority, due_date,
                project, '', 'reassigned', old_assignee,
            )
            if feishu_warning:
                response['feishu_warning'] = feishu_warning
            feishu_notify.notify_old_assignee(old_assignee, task_id, title, value, project)
        self._json(response)

    def _route_put_api_canvas_node(self, parsed, query, session):
        body = self._read_json_body()
        body['actor'] = str(body.get('actor') or _session_actor(session) or 'unspecified')[:40]
        result, status = ledger_query.put_canvas_node(_ledger_query_deps(), body)
        self._json(result, status)

    def _route_put_api_canvas(self, parsed, query, session):
        body = self._read_json_body()
        actor = str(body.get('actor') or _session_actor(session) or 'unspecified')[:40]
        if body.get('map'):
            result, status = put_project_map_canvas(
                body.get('map', ''), body.get('canvas'),
                actor=actor,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        elif body.get('convmap'):
            result, status = put_conversation_map_canvas(
                body.get('convmap', ''), body.get('canvas'),
                actor=actor,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        else:
            result, status = put_canvas_for_task(
                body.get('path', ''), body.get('canvas'),
                actor=actor,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        self._json(result, status)

    def _route_put_api_update_body(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        new_body = body.get('body', '')
        base_rev = body.get('base_rev')
        base_body = body.get('base_body')
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        result, status = update_task_body_with_merge(path, new_body, base_rev=base_rev, base_body=base_body)
        self._json(result, status)

    def _route_put_api_toggle_check(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        result, status = update_acceptance_checkbox(
            path,
            body.get('index'),
            body.get('expected_text', ''),
            body.get('checked'),
        )
        self._json(result, status)

    def _route_put_api_update_section(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        section = str(body.get('section') or '完成标准').strip()
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        if section != '完成标准':
            self._json({'ok': False, 'message': '只支持更新完成标准段'}, 400)
            return
        result, status = update_acceptance_section(
            path,
            body.get('body', ''),
            user=session.get('user', ''),
        )
        self._json(result, status)

    def _route_put_api_task_note(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        result, status = update_card_note_section(path, body.get('note', ''))
        self._json(result, status)

    def _route_post_api_dynamic_boards_run(self, parsed, query, session):
        body = self._read_json_body()
        provider_id = str(body.get('id') or '').strip()
        result, status = run_dynamic_board(provider_id, auto=body.get('auto') is True)
        self._json(result, status)

    def _route_post_api_comments_import(self, parsed, query, session):
        body = self._read_json_body()
        result, status = comment_import.import_comments(_comment_import_deps(), body)
        self._json(result, status)

    def _route_post_api_comments_edit(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = comment_import.edit_comment(
            _comment_import_deps(), body, actor=session.get('user') or '用户',
        )
        self._json(result, status)

    def _route_post_api_governance_noise_review(self, parsed, query, session):
        result, status = enqueue_governance_noise_review()
        self._json(result, status)

    def _route_post_api_governance_result_card(self, parsed, query, session):
        body = self._read_json_body()
        try:
            result, status = governance_result_card.upsert_weekly_card(
                _governance_result_card_deps(), body,
            )
        except governance_result_card.ProjectionError as exc:
            result, status = {'ok': False, 'error': str(exc)}, 400
        self._json(result, status)

    def _route_post_api_bridges_launch(self, parsed, query, session):
        body = self._read_json_body()
        target = str(body.get('target') or '').strip()
        result, status = launch_bridge_target(target)
        self._json(result, status)

    def _route_post_api_skill_invocation(self, parsed, query, session):
        body = self._read_json_body()
        invocation = body.get('invocation')
        try:
            result, status = skill_invocation.execute(invocation, load_config(), body.get('state'))
        except skill_invocation.InvocationError as exc:
            result, status = {'ok': False, 'outcome': 'failed', 'error': str(exc)}, 400
        persist_skill_invocation_result(invocation, result)
        self._json(result, status)

    def _route_post_api_network_preset(self, parsed, query, session):
        body = self._read_json_body()
        preset = str(body.get('preset') or '').strip()
        result, status = apply_network_preset(preset, confirmed=body.get('confirmed') is True)
        self._json(result, status)

    def _route_post_api_network_doctor(self, parsed, query, session):
        body = self._read_json_body()
        action = str(body.get('action') or '').strip()
        result, status = run_network_doctor_action(
            action,
            confirmed=body.get('confirmed') is True,
        )
        self._json(result, status)

    def _route_post_api_open(self, parsed, query, session):
        body = self._read_json_body()
        target, err, status = resolve_open_target(body.get('path', ''))
        if err:
            if status == 403:
                self._security_denied('path-outside-trusted-roots')
            self._json({'ok': False, 'error': err}, status)
            return
        opened, open_error = _open_path_in_desktop(target)
        self._json({'ok': opened, **({'error': open_error} if open_error else {})}, 200 if opened else 503)

    def _route_post_api_real_projects_refresh(self, parsed, query, session):
        body = self._read_json_body()
        result, status = refresh_real_project(body.get('project_ref', ''))
        self._json(result, status)

    def _route_post_api_real_projects_feedback(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = append_real_project_feedback(
            body, actor=session.get('user') or 'unspecified',
        )
        self._json(result, status)

    def _route_post_api_real_projects_register(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = register_real_project(
            body,
            actor=body.get('actor') or _session_actor(session) or session.get('user') or 'unspecified',
        )
        self._json(result, status)

    def _route_post_api_real_projects_link_conversation(self, parsed, query, session):
        body = self._read_json_body()
        result, status = link_project_conversation(body)
        self._json(result, status)

    def _route_post_api_real_projects_unlink_conversation(self, parsed, query, session):
        body = self._read_json_body()
        result, status = unlink_project_conversation(body)
        self._json(result, status)

    def _route_post_api_project_materials_open(self, parsed, query, session):
        body = self._read_json_body()
        target, err, status = project_conversations.resolve_registered_material(
            _project_conversation_deps(), body.get('project_ref', ''), body.get('path', '')
        )
        if err:
            self._json({'ok': False, 'error': err}, status)
            return
        opened, open_error = _open_path_in_desktop(target)
        self._json({'ok': opened, **({'error': open_error} if open_error else {})}, 200 if opened else 503)

    def _route_post_api_real_projects_update(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = update_real_project(
            body, actor=session.get('user') or 'unspecified',
        )
        self._json(result, status)

    def _route_post_api_real_projects_assign_task(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = assign_task_to_real_project(
            body, actor=session.get('user') or 'unspecified',
        )
        self._json(result, status)

    def _route_post_api_landing_refresh(self, parsed, query, session):
        body = self._read_json_body()
        prepared, status = _prepare_landing_refresh(body.get('path', ''))
        if not prepared.get('ok'):
            self._json(prepared, status)
            return
        entry_id = _queue_add_entry(
            'codex',
            prepared['path'],
            prepared.get('workdir', ''),
            prompt_override=prepared['prompt'],
            post_success_frontmatter={
                'path': prepared['path'],
                'field': 'landing_updated',
                'value': 'today',
            },
        )
        _queue_consume_next()
        self._json({
            'ok': True,
            'run_id': entry_id,
            'landing_page': prepared.get('landing_page', ''),
        })

    def _route_post_api_landing_review(self, parsed, query, session):
        body = self._read_json_body()
        prepared, status = _prepare_landing_review(body.get('path', ''))
        if not prepared.get('ok'):
            self._json(prepared, status)
            return
        entry_id = _queue_add_entry(
            'codex',
            prepared['path'],
            prepared.get('workdir', ''),
            prompt_override=prepared['prompt'],
        )
        _queue_consume_next()
        self._json({
            'ok': True,
            'run_id': entry_id,
            'landing_page': prepared.get('landing_page', ''),
        })

    def _route_post_api_canvas_resolve_ref(self, parsed, query, session):
        body = self._read_json_body()
        result, status = resolve_canvas_ref_for_task(
            body.get('path', ''), body.get('source_path', ''), body.get('kind', 'file')
        )
        self._json(result, status)

    def _route_post_api_canvas_generate(self, parsed, query, session):
        body = self._read_json_body()
        if body.get('map'):
            result, status = generate_project_map_canvas(
                body.get('map', ''),
                force=body.get('force') is True,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        elif body.get('convmap'):
            result, status = generate_conversation_map_canvas(
                body.get('convmap', ''),
                force=body.get('force') is True,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        else:
            unavailable = _canvas_ai_unavailable(
                body.get('path', ''),
                action='generate',
                include_canvas=True,
            )
            if unavailable is not None:
                result, status = unavailable
                self._json(result, status)
                return
            existing_intent, seed_check, seed_status = canvas_existing_seed_intent(body.get('path', ''))
            if not seed_check.get('ok'):
                self._json(seed_check, seed_status)
                return
            if existing_intent:
                result, status = enqueue_canvas_seed(
                    body.get('path', ''),
                    existing_intent,
                    tool=body.get('tool') or 'codex',
                )
                if isinstance(result, dict):
                    result['routed_from'] = '/api/canvas/generate'
                self._json(result, status)
                return
            result, status = generate_canvas_for_task(
                body.get('path', ''),
                force=body.get('force') is True,
                base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
            )
        self._json(result, status)

    def _route_post_api_canvas_refresh(self, parsed, query, session):
        body = self._read_json_body()
        if not body.get('map'):
            self._json({'ok': False, 'error': 'canvas refresh requires map'}, 400)
            return
        result, status = generate_project_map_canvas(
            body.get('map', ''),
            force=body.get('force') is True,
            base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
        )
        self._json(result, status)

    def _route_post_api_canvas_restore(self, parsed, query, session):
        body = self._read_json_body()
        if not body.get('map') or not body.get('version'):
            self._json({'ok': False, 'error': 'canvas restore requires map and version'}, 400)
            return
        result, status = restore_project_map_canvas_version(
            body.get('map', ''),
            body.get('version', ''),
            actor=str(body.get('actor') or 'unspecified')[:40],
            base_rev=body.get('base_rev') or body.get('base_canvas_rev'),
        )
        self._json(result, status)

    def _route_post_api_canvas_seed_intent(self, parsed, query, session):
        body = self._read_json_body()
        result, status = infer_canvas_seed_intent(body.get('path', ''))
        self._json(result, status)

    def _route_post_api_canvas_seed_run(self, parsed, query, session):
        body = self._read_json_body()
        result, status = enqueue_canvas_seed(
            body.get('path', ''),
            body.get('intent') or body.get('seed_intent') or '',
            tool=body.get('tool') or 'codex',
        )
        self._json(result, status)

    def _route_post_api_canvas_reorganize(self, parsed, query, session):
        body = self._read_json_body()
        result, status = enqueue_project_canvas_reorganize(body.get('project_ref', ''))
        self._json(result, status)

    def _route_post_api_save_user_config(self, parsed, query, session):
        body = self._read_json_body()
        user_cfg_path = REPO_ROOT / '.kanban.user.config.json'
        try:
            existing_cfg = load_user_config()
            merged_cfg, cfg_err = build_safe_user_config_update(body, existing_cfg)
            if cfg_err:
                self._json({'ok': False, 'error': cfg_err}, 400)
                return
            if merged_cfg is None:
                self._json({'ok': True})
                return
            user_cfg_path.write_text(
                json.dumps(merged_cfg, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8'
            )
            # 只热加载 UI 允许修改的工具命令，不刷新敏感配置域。
            global CLI_COMMANDS, AI_PROFILES
            config = load_config()
            CLI_COMMANDS.update({
                name: parse_command_string(cfg['command'])
                for name, cfg in config.get('tools', {}).items()
            })
            AI_PROFILES = normalize_ai_profiles(config)
            self._json({'ok': True})
        except (OSError, TypeError) as e:
            self._json({'ok': False, 'error': str(e)}, 500)

    def _route_post_api_create(self, parsed, query, session):
        body = self._read_json_body()
        project = body.get('project', '')
        project_ref = str(body.get('project_ref') or '').strip()
        if project_ref:
            validated, validated_status = validate_real_project_ref(project_ref)
            if validated_status != 200:
                self._json({
                    'ok': False,
                    'message': validated.get('error') or '未知 project_ref',
                }, validated_status)
                return
        title = body.get('title', '')
        assignee = body.get('assignee', '')
        priority = body.get('priority', 'medium')
        task_body = body.get('body', '')
        due_date = body.get('due_date', '')
        ok, msg, task_id = create_document(
            project, title, assignee, priority, task_body,
            body.get('workdir'), due_date, body.get('promoted_from'),
            body.get('task_family'), body.get('execution_profile'), body.get('legacy_id'),
            project_ref, body.get('project_role'),
        )
        feishu_warning = None
        if ok and assignee and task_id:
            body_preview = task_body[:200] if task_body else ''
            feishu_warning = feishu_notify.notify_assignee(
                assignee, task_id, title or task_id, priority,
                due_date or '', project, body_preview, 'created',
            )
        response = {'ok': ok, 'message': msg, 'task_id': task_id}
        if feishu_warning:
            response['feishu_warning'] = feishu_warning
        self._json(response)

    def _route_post_api_prepare_upload(self, parsed, query, session):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8'))
        path = body.get('path', '')
        filename = body.get('filename', '')
        content_type = body.get('content_type', '')
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        if not content_type.startswith('image/'):
            self._json({'ok': False, 'error': '仅支持图片文件'}, 400)
            return
        contract, err = _build_s3_presigned_post(path, filename, content_type)
        if err:
            code = 400 if err in {'非法路径', '仅支持图片文件', '缺少路径', '缺少文件名', '仅支持 scan_dirs 内的任务卡'} else 500
            if err == '文件不存在':
                code = 404
            self._json({'ok': False, 'error': err}, code)
            return
        self._json({'ok': True, **contract})

    def _route_post_api_queue_reorder(self, parsed, query, session):
        body = self._read_json_body()
        ordered_ids = body.get('order', [])
        _queue_reorder_entries(ordered_ids)
        self._json({'ok': True})

    def _route_post_api_queue_cancel(self, parsed, query, session):
        body = self._read_json_body()
        entry_id = body.get('id', '')
        if not _queue_cancel_entry(entry_id):
            self._json({'ok': False, 'error': '未找到排队中的任务'})
            return
        self._json({'ok': True})

    def _route_post_api_queue_mark_read(self, parsed, query, session):
        body = self._read_json_body()
        entry_id = body.get('id', '')
        _queue_update_entry(entry_id, {'read': True})
        self._json({'ok': True})

    def _route_post_api_review_cycle_start(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = start_review_cycle(
            body.get('path', ''),
            reviewer_tool=body.get('reviewer_tool') or 'claude',
            producer_tool=body.get('producer_tool') or '',
            actor=session.get('user') or 'user',
        )
        self._json(result, status)

    def _route_post_api_review_cycle_repair(self, parsed, query, session):
        body = self._read_json_body()
        session = self._get_session() or {}
        result, status = repair_review_cycle(
            body.get('path', ''), actor=session.get('user') or 'user',
        )
        self._json(result, status)

    def _route_post_api_ai_run(self, parsed, query, session):
        body = self._read_json_body()
        path = body.get('path', '')
        tool = body.get('tool', '')
        if '..' in path or path.startswith('/'):
            self._security_denied('task-path-traversal')
            self._json({'ok': False, 'error': '非法路径'}, 403)
            return
        if tool not in CLI_COMMANDS:
            self._json({'ok': False, 'error': '无效工具'}, 400)
            return
        filepath = REPO_ROOT / path
        if not filepath.exists():
            self._json({'ok': False, 'error': '文件不存在'}, 404)
            return
        raw = filepath.read_text(encoding='utf-8')
        fm, _ = extract_frontmatter(raw)
        if (fm or {}).get('status', '') == 'done':
            self._json({'ok': False, 'error': '任务已完成，无法启动 AI'}, 400)
            return
        workdir_value = fm.get('workdir', '') if fm else ''
        cwd_path, cwd_err = resolve_workdir(workdir_value, path)
        if cwd_err:
            self._security_denied('workdir-outside-trusted-roots')
            self._json({'ok': False, 'error': cwd_err}, 403)
            return
        cwd_path, cwd_err = _coerce_workdir_to_cwd(cwd_path)
        if cwd_err:
            self._security_denied('workdir-outside-trusted-roots')
            self._json({'ok': False, 'error': cwd_err}, 403)
            return
        if not cwd_path.exists():
            if body.get('create_workdir', False):
                cwd_path.mkdir(parents=True, exist_ok=True)
            else:
                self._json({'ok': False, 'error': 'workdir_not_found', 'workdir': str(cwd_path)}, 400)
                return
        # 画布对话节点(KAN-110 阶段2):可选 prompt=任意指令(默认仍是整卡内容);
        # 用户 prompt 记为 messages[0](随 _queue_append_message 钩子自动进耐久台账)。
        custom_prompt = str(body.get('prompt') or '').strip()
        if len(custom_prompt.encode('utf-8')) > 32 * 1024:
            self._json({'ok': False, 'error': 'prompt 超过大小限制(32KB)'}, 400)
            return
        if custom_prompt:
            display_message = str(body.get('display_message') or custom_prompt).strip()
            if len(display_message.encode('utf-8')) > 32 * 1024:
                self._json({'ok': False, 'error': 'display_message 超过大小限制(32KB)'}, 400)
                return
            dialogue_origin = str(body.get('origin') or 'canvas').strip().lower()
            if dialogue_origin not in {
                'canvas', 'card_chat', 'selection_quick_explain', 'selection_side_chat'
            }:
                dialogue_origin = 'canvas'
            ai_profile, profile_error = resolve_ai_profile(
                tool,
                body.get('profile'),
                dialogue_origin,
                has_custom_prompt=True,
            )
            if profile_error:
                self._json({'ok': False, 'error': profile_error}, 400)
                return
            source_quote, quote_error = _normalize_source_quote(body.get('source_quote'), path)
            if quote_error:
                self._json({'ok': False, 'error': quote_error}, 400)
                return
            canvas_context = _verified_canvas_context_entries(body.get('canvas_context'), path, fm or {})
            canvas_prompt, unresolved_count = ai_run_guard.format_canvas_prompt(custom_prompt, canvas_context)
            if unresolved_count and body.get('allow_unresolved_context') is not True:
                self._json({
                    'ok': False,
                    'error': f'有 {unresolved_count} 个上游引用未解析；默认不发送，请显式确认后重试',
                    'unresolved_count': unresolved_count,
                }, 409)
                return
            prompt_for_ai = _source_quote_prompt(canvas_prompt, source_quote)
            prompt_override = (
                f'{prompt_for_ai}\n\n'
                f'---\n(本对话挂在任务卡 {path};如需卡片全文请自行读取。)'
            )
            lifecycle = 'transient' if dialogue_origin == 'selection_quick_explain' else 'durable_on_promotion'
            entry_id = _queue_add_entry(
                tool, path, workdir_value,
                prompt_override=prompt_override,
                metadata={'dialogue': {
                    'origin': dialogue_origin,
                    'lifecycle': lifecycle,
                }},
                ai_profile=ai_profile,
            )
            user_message = {
                'role': 'user',
                'content': display_message,
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'author': body.get('author') or '用户',
            }
            if source_quote:
                user_message['source_quote'] = source_quote
            _queue_append_message(entry_id, user_message, ledger_fields={
                'prompt_audit_version': COMMENTS_PROMPT_AUDIT_VERSION,
                'prompt_source': 'prompt_override',
                'raw_prompt': prompt_override,
            })
        else:
            ai_profile, profile_error = resolve_ai_profile(
                tool,
                body.get('profile'),
                has_custom_prompt=False,
            )
            if profile_error:
                self._json({'ok': False, 'error': profile_error}, 400)
                return
            entry_id = _queue_add_entry(
                tool,
                path,
                workdir_value,
                ai_profile=ai_profile,
            )
        _queue_consume_next()
        self._json({'ok': True, 'run_id': entry_id})

    def _route_post_api_task_documents_append(self, parsed, query, session):
        body = self._read_json_body()
        task_path = str(body.get('path') or '').strip()
        source_quote, quote_error = _normalize_source_quote(body.get('source_quote'), task_path)
        if quote_error:
            self._json({'ok': False, 'error': quote_error}, 400)
            return
        request_payload = dict(body)
        request_payload['source_quote'] = source_quote
        current_session = self._get_session() or {}
        request_payload['actor'] = current_session.get('user', '') or 'human_action'
        result, status = task_document_links.append_selection(
            _task_document_link_deps(), request_payload
        )
        self._json(result, status)

    def _route_post_api_conversation_relations(self, parsed, query, session):
        body = self._read_json_body()
        current_session = self._get_session() or {}
        result, status = conversation_project_graph.append_relation(
            _conversation_project_graph_deps(),
            body,
            actor=current_session.get('user', '') or 'ai',
        )
        self._json(result, status)

    def _route_post_api_conversation_relations_audit(self, parsed, query, session):
        body = self._read_json_body()
        result, status = conversation_project_graph.audit_relations(
            _conversation_project_graph_deps(),
            body,
            actor='ai_auditor',
        )
        self._json(result, status)

    def _route_post_api_ai_comment(self, parsed, query, session):
        body = self._read_json_body()
        run_id = body.get('run_id', '')
        comment = body.get('comment', '')
        author = body.get('author', '')
        skill_id = body.get('skill_id', '')
        fork_from_index = body.get('fork_from_index', None)

        # 分叉模式(KAN-111):fork_from_index 指定父线程消息序号 → 新支线;skill 不参与分叉
        if fork_from_index is not None:
            comment_text = str(comment or '').strip()
            if skill_id or comment_text.startswith('/'):
                self._json({'ok': False, 'error': '分叉暂不支持 skill 命令，请使用纯文本'}, 400)
                return
            parent_entry = _queue_get_entry(run_id)
            source_quote, quote_error = _normalize_source_quote(
                body.get('source_quote'), (parent_entry or {}).get('path', '')
            )
            if quote_error:
                self._json({'ok': False, 'error': quote_error}, 400)
                return
            result = _handle_ai_fork(
                run_id, fork_from_index, comment_text, author,
                source_quote=source_quote,
            )
            self._json(result, 200 if result.get('ok') else 400)
            return

        # Codex 不支持 skill：提前检查，避免浪费资源解析 skill prompt
        cm_entry = _queue_get_entry(run_id)
        source_quote, quote_error = _normalize_source_quote(
            body.get('source_quote'), (cm_entry or {}).get('path', '')
        )
        if quote_error:
            self._json({'ok': False, 'error': quote_error}, 400)
            return
        cm_tool = cm_entry.get('tool', 'claude') if cm_entry else 'claude'
        if cm_tool == 'codex':
            comment_text = str(comment or '').strip()
            if skill_id or comment_text.startswith('/'):
                self._json({'ok': False, 'error': 'Codex 暂不支持 skill 命令，请使用纯文本评论'}, 400)
                return
            result = _handle_ai_comment(
                run_id, comment_text, author,
                prompt_comment=comment_text, skill_meta=None,
                source_quote=source_quote,
            )
        else:
            parsed_skill = _parse_skill_command(comment, skill_id)
            prompt_comment = comment
            skill_meta = None
            if parsed_skill:
                skill = parsed_skill['skill']
                args = parsed_skill['args']
                prompt_comment = _build_skill_augmented_prompt(skill, args, comment)
                skill_meta = {
                    'skill_id': skill.get('id') or '',
                    'skill_name': skill.get('name') or skill.get('id') or '',
                    'skill_args': args,
                    'skill_applied': True,
                }
            result = _handle_ai_comment(
                run_id, comment, author,
                prompt_comment=prompt_comment, skill_meta=skill_meta,
                source_quote=source_quote,
            )
        self._json(result, 200 if result.get('ok') else 400)

    def _route_post_api_ai_kill(self, parsed, query, session):
        body = self._read_json_body()
        run_id = body.get('run_id', '')
        with _ai_runs_lock:
            info = _ai_runs.get(run_id)
            if info:
                info['killed'] = True
        if not info or not info.get('proc'):
            self._json({'ok': False, 'error': '未找到运行中的任务'})
            return
        try:
            os.killpg(os.getpgid(info['proc'].pid), signal.SIGTERM)
        except Exception as e:
            info['proc'].kill()
        _queue_update_entry(run_id, {
            'status': 'killed', 'error': '用户终止',
            'pid': None,
            'duration_ms': int((time.time() - info.get('started_at', time.time())) * 1000),
            'completed_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, only_if_statuses={'running'})
        self._json({'ok': True})

    def _route_post_api_ai_apply(self, parsed, query, session):
        body = self._read_json_body()
        run_id = body.get('run_id', '')
        path = body.get('path', '')
        if '..' in path or path.startswith('/'):
            self._json({'ok': False, 'error': '非法路径'}, 400)
            return
        # 从队列中查找条目
        entry = _queue_get_entry(run_id)
        if not entry or not entry.get('output'):
            self._json({'ok': False, 'error': '未找到结果'})
            return
        filepath = REPO_ROOT / path
        if not filepath.exists():
            self._json({'ok': False, 'error': '文件不存在'}, 404)
            return
        tool = entry.get('tool', 'ai')
        ok, msg = append_ai_result_to_task_file(
            path,
            entry['output'],
            tool=tool,
            timestamp=entry.get('timestamp', ''),
        )
        if not ok:
            self._json({'ok': False, 'error': msg}, 500)
            return
        self._json({'ok': True})

    def _route_post_api_generate_title(self, parsed, query, session):
        body = self._read_json_body()
        ok, result = generate_title_with_ai(body.get('body', ''))
        if ok:
            self._json({'ok': True, 'title': result})
        else:
            self._json({'ok': False, 'message': result}, 500)

    def _route_post_api_sync_toggle(self, parsed, query, session):
        body = self._read_json_body()
        enabled = bool(body.get('enabled', False))
        target = str(body.get('target') or 'git').strip().lower()
        if target != 'git':
            self._json({'ok': False, 'error': 'unknown sync target'}, 400)
            return
        mgr = GIT_SYNC_MANAGER
        if mgr:
            ok = mgr.set_enabled(enabled)
            if ok is False:
                self._json({'ok': False, 'error': 'failed to persist sync config'}, 500)
                return
            self._json({'ok': True, 'target': target, 'status': _sync_status_payload()})
        else:
            self._json({'ok': False, 'error': f'{target} sync unavailable'}, 503)

    def _route_delete_api_ai_result(self, parsed, query, session):
        body = self._read_json_body()
        run_id = body.get('run_id', '')
        info = None
        with _ai_runs_lock:
            info = _ai_runs.get(run_id)
            if info:
                info['killed'] = True
        if info and info.get('proc'):
            try:
                os.killpg(os.getpgid(info['proc'].pid), signal.SIGTERM)
            except Exception:
                info['proc'].kill()
        _queue_remove_entry(run_id)
        self._json({'ok': True})

    def _route_delete_api_task(self, parsed, query, session):
        body = self._read_json_body()
        result, status = archive_task_card(body.get('path', ''))
        self._json(result, status)

    def _route_get_api_attention_gate_summary(self, parsed, query, session):
        self._json(get_attention_gate_summary())

    def _route_get_api_attention_gate_duty(self, parsed, query, session):
        self._json(get_attention_gate_duty_panel())

    def _route_get_api_attention_gate_context_v1(self, parsed, query, session):
        self._json(get_attention_gate_context())

    def _route_post_api_login(self, parsed, query, session):
        self._handle_login()

    def _route_post_api_verify_quiz(self, parsed, query, session):
        self._handle_verify_quiz()

    def _route_post_api_verify_token(self, parsed, query, session):
        self._handle_verify_token()

    def _route_post_api_logout(self, parsed, query, session):
        self._handle_logout()

    def _route_post_api_select_user(self, parsed, query, session):
        self._handle_select_user()

    def _route_post_api_sync_webhook(self, parsed, query, session):
        self._handle_sync_webhook()

    def _route_get_api_health(self, parsed, query, session):
        self._json({
            'ok': True,
            'product': 'project-canvas',
            'fingerprint': _HEALTH_FINGERPRINT,
        })

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as e:
            self._handle_request_exception(e)

    def _do_GET(self):
        parsed = urlparse(self.path)
        if not self._request_host_guard():
            return

        # HTML shells, static assets, and Canvas Studio have prefix/fallback
        # semantics, so they intentionally remain outside the exact API table.
        if parsed.path in ('/', '/index.html'):
            self._serve_html()
            return
        if parsed.path.startswith('/static/kanban/'):
            self._serve_static_asset(parsed.path)
            return
        if parsed.path == '/canvas' or parsed.path.startswith('/canvas/'):
            self._serve_canvas_asset(parsed.path)
            return
        if parsed.path == '/studio' or parsed.path.startswith('/studio/'):
            suffix = parsed.path.removeprefix('/studio')
            query = ('?' + parsed.query) if parsed.query else ''
            self.send_response(308)
            self.send_header('Location', '/canvas' + suffix + query)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        self._dispatch_registered_route('GET', parsed)

    def do_PUT(self):
        try:
            self._do_PUT()
        except Exception as e:
            self._handle_request_exception(e)

    def _do_PUT(self):
        self._dispatch_registered_route('PUT', urlparse(self.path))

    def do_POST(self):
        try:
            self._do_POST()
        except Exception as e:
            self._handle_request_exception(e)

    def _do_POST(self):
        self._dispatch_registered_route('POST', urlparse(self.path))

    def do_DELETE(self):
        try:
            self._do_DELETE()
        except Exception as e:
            self._handle_request_exception(e)

    def _do_DELETE(self):
        self._dispatch_registered_route('DELETE', urlparse(self.path))

# Exact and prefix HTTP routes. Prefix entries end in `*`; static files and
# HTML/Canvas Studio fallbacks remain explicit in Handler._do_GET.
_ROUTE_REGISTRY = {
    ('DELETE', '/api/ai-result'): '_route_delete_api_ai_result',
    ('DELETE', '/api/task'): '_route_delete_api_task',
    ('GET', '/api/ai-results'): '_route_get_api_ai_results',
    ('GET', '/api/attention-queue'): '_route_get_api_attention_queue',
    ('GET', '/api/system-alerts'): '_route_get_api_system_alerts',
    ('GET', '/api/bridges/status'): '_route_get_api_bridges_status',
    ('GET', '/api/canvas'): '_route_get_api_canvas',
    ('GET', '/api/canvas/events'): '_route_get_api_canvas_events',
    ('GET', '/api/canvas/node-history'): '_route_get_api_canvas_node_history',
    ('GET', '/api/canvas/versions'): '_route_get_api_canvas_versions',
    ('GET', '/api/canvas/seed-intent'): '_route_get_api_canvas_seed_intent',
    ('GET', '/api/card-lineage'): '_route_get_api_card_lineage',
    ('GET', '/api/chains/*'): '_route_get_api_chains_wildcard',
    ('GET', '/api/chains/km'): '_route_get_api_chains_km',
    ('GET', '/api/conversation-map'): '_route_get_api_conversation_map',
    ('GET', '/api/conversation-maps'): '_route_get_api_conversation_maps',
    ('GET', '/api/conversation-project-graph'): '_route_get_api_conversation_project_graph',
    ('GET', '/api/data'): '_route_get_api_data',
    ('GET', '/api/dynamic-boards'): '_route_get_api_dynamic_boards',
    ('GET', '/api/file'): '_route_get_api_file',
    ('GET', '/api/file-exists'): '_route_get_api_file_exists',
    ('GET', '/api/governance/healthcheck/status'): '_route_get_api_governance_healthcheck_status',
    ('GET', '/api/health'): '_route_get_api_health',
    ('GET', '/api/governance/maintenance'): '_route_get_api_governance_maintenance',
    ('GET', '/api/governance/matrix'): '_route_get_api_governance_matrix',
    ('GET', '/api/governance/noise-review/status'): '_route_get_api_governance_noise_review_status',
    ('GET', '/api/governance/probe'): '_route_get_api_governance_probe',
    ('GET', '/api/owner-world'): '_route_get_api_owner_world',
    ('GET', '/api/ledger/*'): '_route_get_api_ledger_wildcard',
    ('GET', '/api/network/status'): '_route_get_api_network_status',
    ('GET', '/api/project-maps'): '_route_get_api_project_maps',
    ('GET', '/api/project-materials'): '_route_get_api_project_materials',
    ('GET', '/api/project-posture'): '_route_get_api_project_posture',
    ('GET', '/api/attention_gate/context/v1'): '_route_get_api_attention_gate_context_v1',
    ('GET', '/api/attention_gate/duty'): '_route_get_api_attention_gate_duty',
    ('GET', '/api/attention_gate/summary'): '_route_get_api_attention_gate_summary',
    ('GET', '/api/queue'): '_route_get_api_queue',
    ('GET', '/api/real-projects'): '_route_get_api_real_projects',
    ('GET', '/api/relationship-cards'): '_route_get_api_relationship_cards',
    ('GET', '/api/review-cycle'): '_route_get_api_review_cycle',
    ('GET', '/api/search-files'): '_route_get_api_search_files',
    ('GET', '/api/session-evidence/search'): '_route_get_api_session_evidence_search',
    ('GET', '/api/skills'): '_route_get_api_skills',
    ('GET', '/api/sync/events'): '_route_get_api_sync_events',
    ('GET', '/api/sync/status'): '_route_get_api_sync_status',
    ('GET', '/api/task'): '_route_get_api_task',
    ('GET', '/api/task-canvases'): '_route_get_api_task_canvases',
    ('GET', '/api/task-comments'): '_route_get_api_task_comments',
    ('GET', '/api/task-documents'): '_route_get_api_task_documents',
    ('GET', '/api/task-ledger'): '_route_get_api_task_ledger',
    ('GET', '/canvas-view'): '_route_get_canvas_view',
    ('POST', '/api/ai-apply'): '_route_post_api_ai_apply',
    ('POST', '/api/ai-comment'): '_route_post_api_ai_comment',
    ('POST', '/api/ai-kill'): '_route_post_api_ai_kill',
    ('POST', '/api/ai-run'): '_route_post_api_ai_run',
    ('POST', '/api/bridges/launch'): '_route_post_api_bridges_launch',
    ('POST', '/api/canvas/generate'): '_route_post_api_canvas_generate',
    ('POST', '/api/canvas/refresh'): '_route_post_api_canvas_refresh',
    ('POST', '/api/canvas/reorganize'): '_route_post_api_canvas_reorganize',
    ('POST', '/api/canvas/resolve-ref'): '_route_post_api_canvas_resolve_ref',
    ('POST', '/api/canvas/restore'): '_route_post_api_canvas_restore',
    ('POST', '/api/canvas/seed-intent'): '_route_post_api_canvas_seed_intent',
    ('POST', '/api/canvas/seed-run'): '_route_post_api_canvas_seed_run',
    ('POST', '/api/comments/edit'): '_route_post_api_comments_edit',
    ('POST', '/api/comments/import'): '_route_post_api_comments_import',
    ('POST', '/api/conversation-relations'): '_route_post_api_conversation_relations',
    ('POST', '/api/conversation-relations/audit'): '_route_post_api_conversation_relations_audit',
    ('POST', '/api/create'): '_route_post_api_create',
    ('POST', '/api/dynamic-boards/run'): '_route_post_api_dynamic_boards_run',
    ('POST', '/api/generate-title'): '_route_post_api_generate_title',
    ('POST', '/api/governance/noise-review'): '_route_post_api_governance_noise_review',
    ('POST', '/api/governance/result-card'): '_route_post_api_governance_result_card',
    ('POST', '/api/landing/refresh'): '_route_post_api_landing_refresh',
    ('POST', '/api/landing/review'): '_route_post_api_landing_review',
    ('POST', '/api/login'): '_route_post_api_login',
    ('POST', '/api/logout'): '_route_post_api_logout',
    ('POST', '/api/network/doctor'): '_route_post_api_network_doctor',
    ('POST', '/api/network/preset'): '_route_post_api_network_preset',
    ('POST', '/api/open'): '_route_post_api_open',
    ('POST', '/api/prepare-upload'): '_route_post_api_prepare_upload',
    ('POST', '/api/project-materials/open'): '_route_post_api_project_materials_open',
    ('POST', '/api/queue/cancel'): '_route_post_api_queue_cancel',
    ('POST', '/api/queue/mark-read'): '_route_post_api_queue_mark_read',
    ('POST', '/api/queue/reorder'): '_route_post_api_queue_reorder',
    ('POST', '/api/real-projects/assign-task'): '_route_post_api_real_projects_assign_task',
    ('POST', '/api/real-projects/feedback'): '_route_post_api_real_projects_feedback',
    ('POST', '/api/real-projects/link-conversation'): '_route_post_api_real_projects_link_conversation',
    ('POST', '/api/real-projects/refresh'): '_route_post_api_real_projects_refresh',
    ('POST', '/api/real-projects/register'): '_route_post_api_real_projects_register',
    ('POST', '/api/real-projects/unlink-conversation'): '_route_post_api_real_projects_unlink_conversation',
    ('POST', '/api/real-projects/update'): '_route_post_api_real_projects_update',
    ('POST', '/api/review-cycle/repair'): '_route_post_api_review_cycle_repair',
    ('POST', '/api/review-cycle/start'): '_route_post_api_review_cycle_start',
    ('POST', '/api/save-user-config'): '_route_post_api_save_user_config',
    ('POST', '/api/select-user'): '_route_post_api_select_user',
    ('POST', '/api/skill-invocation'): '_route_post_api_skill_invocation',
    ('POST', '/api/sync/toggle'): '_route_post_api_sync_toggle',
    ('POST', '/api/sync/webhook'): '_route_post_api_sync_webhook',
    ('POST', '/api/task-documents/append'): '_route_post_api_task_documents_append',
    ('POST', '/api/verify-quiz'): '_route_post_api_verify_quiz',
    ('POST', '/api/verify-token'): '_route_post_api_verify_token',
    ('PUT', '/api/canvas'): '_route_put_api_canvas',
    ('PUT', '/api/canvas/node'): '_route_put_api_canvas_node',
    ('PUT', '/api/task-note'): '_route_put_api_task_note',
    ('PUT', '/api/toggle-check'): '_route_put_api_toggle_check',
    ('PUT', '/api/update'): '_route_put_api_update',
    ('PUT', '/api/update-body'): '_route_put_api_update_body',
    ('PUT', '/api/update-section'): '_route_put_api_update_section',
}

_PUBLIC_ROUTE_KEYS = frozenset({
    ('GET', '/api/attention_gate/summary'),
    ('GET', '/api/health'),
    ('POST', '/api/login'),
    ('POST', '/api/verify-quiz'),
    ('POST', '/api/verify-token'),
    ('POST', '/api/logout'),
    ('POST', '/api/sync/webhook'),
})

_EXTRA_GUARDED_ROUTE_KEYS = frozenset({
    ('GET', '/api/attention_gate/duty'),
    ('GET', '/api/attention_gate/context/v1'),
})

# ── 启动服务器 ──────────────────────────────────────────

def _argv_flag(name):
    return name in sys.argv


def _argv_value(name):
    if name not in sys.argv:
        return None
    idx = sys.argv.index(name)
    if len(sys.argv) <= idx + 1:
        return None
    return sys.argv[idx + 1]


def _active_live_running_queue_entries():
    with _queue_lock:
        queue = _queue_load_unlocked()
        entries = [
            entry for entry in (queue.get('entries') or [])
            if isinstance(entry, dict) and entry.get('status') in {'running', _ORPHANED_RUNNING}
        ]
    live = []
    for entry in entries:
        if server_instance.process_matches_started_at(
            entry.get('pid'),
            str(entry.get('pid_started_at') or entry.get('started_at') or ''),
        ):
            live.append(entry)
    return live


def _apply_port_override(config):
    raw = _argv_value('--port')
    if raw is None:
        return config
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"--port 必须是整数: {raw}")
    if port <= 0 or port > 65535:
        raise SystemExit(f"--port 超出范围: {port}")
    next_config = dict(config)
    next_config['port'] = port
    return next_config


def _apply_bind_override(config):
    raw = _argv_value('--bind')
    if raw is None:
        return config
    host = str(raw or '').strip()
    if not host or any(char.isspace() for char in host):
        raise SystemExit(f'--bind 无效: {raw}')
    next_config = dict(config)
    next_config['bind_host'] = host
    return next_config


def _configured_allowed_hosts(config):
    hosts = set(_LOCAL_HOSTS)
    raw_hosts = config.get('allowed_hosts') if isinstance(config, dict) else []
    if isinstance(raw_hosts, list):
        for raw in raw_hosts:
            host = str(raw or '').strip().lower().rstrip('.')
            if host and ',' not in host and not any(char.isspace() for char in host):
                hosts.add(host)
    bind_host = str((config or {}).get('bind_host') or _DEFAULTS['bind_host']).strip().lower()
    if bind_host not in {'0.0.0.0', '::', ''}:
        hosts.add(bind_host.rstrip('.'))
    return hosts


def _prepare_single_instance_or_exit(force_restart):
    existing = server_instance.detect_existing_instance(REPO_ROOT, PORT)
    if not existing:
        return True
    if not force_restart:
        if existing.source == 'process':
            print(
                f"[kanban] found existing scan-docs.py --serve process "
                f"(pid={existing.pid or 'unknown'}) without a live port {PORT}; "
                "refusing to start a second instance. Use --force-restart after checking the queue.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if existing.source in {'port', 'socket'} and not server_instance.probe_product_instance(PORT):
            print(
                f"[kanban] port {PORT} is occupied by a listener without the "
                f"{_HEALTH_FINGERPRINT} fingerprint; refusing to reuse it.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(
            f"[kanban] server already running on http://localhost:{PORT} "
            f"(pid={existing.pid or 'unknown'}, source={existing.source}); reusing it."
        )
        return False
    live_entries = _active_live_running_queue_entries()
    if live_entries:
        run_ids = ', '.join(str(e.get('id') or '?') for e in live_entries)
        print(
            f"[kanban] refusing --force-restart: {len(live_entries)} AI run(s) "
            f"still have live pid(s): {run_ids}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not server_instance.stop_existing_instance(existing, logger=print):
        print(
            f"[kanban] failed to stop existing server on port {PORT}; aborting.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return True


def main_serve(force_restart=False):
    global SCAN_DIRS, PORT, BIND_HOST, ALLOWED_HOSTS, ALL_MEMBERS, LOGIN_MEMBERS, AI_MAX_CONCURRENT, ZHIPU_API_KEY
    global CLI_COMMANDS, AI_PROFILES, S3_CONFIG, FEISHU_CONFIG, _ai_semaphore, GIT_SYNC_MANAGER
    global TEAM_SYNC_MANAGER, ROLE_CONFIG
    global CURRENT_MEMBER, AUTH_MODE, AUTH_ACCESS_TOKEN, AUTH_TOKEN_PATH

    _augment_path_for_clis()

    # 加载配置：默认值 ← .kanban.config.json ← .kanban.user.config.json
    config = _apply_bind_override(_apply_port_override(load_config()))
    _configure_optional_integration_paths(config)
    SCAN_DIRS = _configured_scan_dirs_or_exit(config)
    PORT = config.get('port', _DEFAULTS['port'])
    BIND_HOST = str(config.get('bind_host') or _DEFAULTS['bind_host']).strip()
    ALLOWED_HOSTS = _configured_allowed_hosts(config)
    ALL_MEMBERS = config.get('members', _DEFAULTS['members'])
    ROLE_CONFIG = role_policy.normalize_roles(config.get('roles'))
    owner_member = role_policy.member_for_role(ROLE_CONFIG, 'owner')
    LOGIN_MEMBERS = [owner_member] if owner_member in ALL_MEMBERS else (ALL_MEMBERS[:1] if ALL_MEMBERS else [])
    AI_MAX_CONCURRENT = config.get('ai_max_concurrent', _DEFAULTS['ai_max_concurrent'])
    ZHIPU_API_KEY = config.get('zhipu_api_key', _DEFAULTS['zhipu_api_key'])
    S3_CONFIG = dict(config.get('s3', _DEFAULTS['s3']))
    FEISHU_CONFIG = dict(config.get('feishu', _DEFAULTS['feishu']))
    feishu_notify.set_config(FEISHU_CONFIG)
    feishu_notify.reset_token_cache()
    CLI_COMMANDS = {
        name: parse_command_string(cfg['command'])
        for name, cfg in config.get('tools', _DEFAULTS['tools']).items()
    }
    AI_PROFILES = normalize_ai_profiles(config)
    _ai_semaphore = threading.Semaphore(AI_MAX_CONCURRENT)

    if not _prepare_single_instance_or_exit(force_restart):
        return

    # local_bypass/autologin are retained for explicit local demo profiles only.
    # The public default creates an owner-readable random token on first start.
    auth_cfg = _auth_config(config)
    AUTH_MODE = _auth_mode(config)
    AUTH_ACCESS_TOKEN = ''
    AUTH_TOKEN_PATH = None
    CURRENT_MEMBER = ''
    bypass_active = False
    if auth_cfg.get('local_bypass'):
        bypass_user = _auth_bypass_user(auth_cfg, allow_legacy_user=True, default_first_member=True)
        if bypass_user in ALL_MEMBERS:
            CURRENT_MEMBER = bypass_user
            bypass_active = True
            print(f"  认证: 本地免登录已启用 (当前用户: {CURRENT_MEMBER})")
        else:
            print(f"  认证: local_bypass 已开启,但 user='{bypass_user}' 不在成员列表,回退到安全登录")
    if not bypass_active:
        if AUTH_MODE == 'token':
            try:
                AUTH_ACCESS_TOKEN, AUTH_TOKEN_PATH = _ensure_local_auth_token(config)
            except ValueError as exc:
                raise SystemExit(f'[kanban] token 初始化失败: {exc}') from exc
            print(f"  认证: 本机随机 token (文件: {AUTH_TOKEN_PATH}, 权限: 0600)")
        else:
            print("  警告: auth.mode=quiz 是可枚举的旧兼容模式,不得用于开源默认或对外监听")
            print("  认证: 旧测验模式 (显式 opt-in)")

    if BIND_HOST not in _LOCAL_HOSTS:
        print(
            f"  严重警告: 服务将监听 {BIND_HOST};这会扩大攻击面。"
            "仅在显式配置 allowed_hosts、反向代理/TLS 和真实远程认证后使用。",
            file=sys.stderr,
        )

    # 启动前：加载/重建状态 + 回填 + 冲突检测
    state = load_state()
    if not state.get('counters'):
        # 状态文件为空或不存在，从现有任务重建
        state = rebuild_state_from_tasks(scan_all())
    all_docs = scan_all()
    synced, phantoms = ensure_counters_in_sync(all_docs, state)
    conflicts = resolve_conflicts(all_docs, state)
    backfilled = backfill_task_ids(all_docs, state)
    backfilled_workdirs = backfill_workdirs(all_docs)
    save_state(state)
    if synced or phantoms:
        print(f"  计数器同步: {synced} 个前缀已修正, {phantoms} 个幽灵计数器已移除")
    if backfilled or conflicts or backfilled_workdirs:
        print(f"  task_id: 回填 {backfilled} 个，解决冲突 {conflicts} 个")
        if backfilled_workdirs:
            print(f"  workdir: 回填 {backfilled_workdirs} 个")

    _migrate_jsonl_to_queue()
    _recover_queue()
    git_sync_mod = get_git_sync_module()
    GIT_SYNC_MANAGER = git_sync_mod.GitSyncManager(
        REPO_ROOT,
        config=config.get('git_sync', _DEFAULTS['git_sync']),
        logger=print,
    )
    GIT_SYNC_MANAGER.start()
    TEAM_SYNC_MANAGER = TeamKanbanSyncManager(config=config, logger=print)
    TEAM_SYNC_MANAGER.start()
    server = ThreadedHTTPServer((BIND_HOST, PORT), Handler)
    server.kanban_repo_root = REPO_ROOT
    server.kanban_port = PORT
    server_instance.ensure_pidfile_owner(REPO_ROOT, PORT)
    server_version = get_server_version_info()
    print(
        f"[kanban] code sha={server_version['git_sha']} "
        f"mtime={server_version['code_mtime']} "
        f"started={server_version['started_at']} port={PORT}"
    )
    print(f"\n  Project Canvas")
    print(f"  ─────────────────────────────────")
    print(f"  监听: {BIND_HOST}:{PORT}")
    print(f"  地址: http://localhost:{PORT}")
    print(f"  目录: {REPO_ROOT}")
    print(f"  按 Ctrl+C 停止\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
        if GIT_SYNC_MANAGER:
            GIT_SYNC_MANAGER.stop()
        if TEAM_SYNC_MANAGER:
            TEAM_SYNC_MANAGER.stop()
        server_instance.remove_pidfile_if_owner(REPO_ROOT)

# ── 公众态入口（cockpit 公众脸 + default-deny 脱敏活预览，KAN-7）──────────

_PUBLIC_CODENAME_SHAPES = [
    re.compile(r'\bcli_[a-z0-9]{6,}\b', re.IGNORECASE),
    re.compile(r'\b[A-Za-z]{2}\d{2,}\b'),
]

def _redact_public_text(text):
    """公众可见文本兜底脱敏：去本机路径 + 抹掉代号形态 token。
    这是 default-deny 之外的第二道防线；主闸是「没标 public_safe 就不出卡」。"""
    redacted = _redact_prompt_local_paths(str(text or ''))
    for pat in _PUBLIC_CODENAME_SHAPES:
        redacted = pat.sub('[已隐去]', redacted)
    return redacted

def build_public_preview():
    """未登录公众态预览：default-deny。
    没有任何卡显式标 public_safe 时，只出形态计数，绝不出真实标题/指派/路径/会议代号。
    只有显式 public_safe==True 的非 done 卡才出，且标题仍过 _redact_public_text。"""
    try:
        docs = scan_all()
    except Exception:
        docs = []
    active = [d for d in docs if d.get('status', 'todo') != 'done']
    def _n(pred):
        return sum(1 for d in docs if pred(d))
    lanes = [
        {'label': '今日活跃', 'count': len(active)},
        {'label': '进行中', 'count': _n(lambda d: d.get('status') == 'in-progress')},
        {'label': '待我拍板', 'count': _n(lambda d: d.get('status') == 'review')},
        {'label': '待分流', 'count': _n(lambda d: d.get('status', 'todo') == 'todo' and d.get('source') and not d.get('assignee'))},
    ]
    cards = []
    for d in docs:
        if d.get('public_safe') is True and d.get('status', 'todo') != 'done':
            cards.append({'title': _redact_public_text(d.get('title', '')), 'status': d.get('status', '')})
    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'totals': {
            'active': len(active),
            'projects': len({d.get('project') for d in docs if d.get('project')}),
        },
        'lanes': lanes,
        'cards': cards,
    }

_COCKPIT_LANDING_PATH = REPO_ROOT / 'landing' / 'cockpit-landing.html'

def _public_html_escape(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))

def render_public_entry_html():
    """未登录 root 的对外脸 = cockpit-landing.html（唯一来源）+ 服务端渲入的脱敏计数 + 进入驾驶舱 CTA。
    计数直接渲进 HTML，不向未登录客户端下发任何任务数据。失败返回 None → 回退原壳。"""
    try:
        html_text = _COCKPIT_LANDING_PATH.read_text(encoding='utf-8')
    except Exception:
        return None
    preview = build_public_preview()
    stats_html = ''.join(
        '<div style="display:flex;flex-direction:column;gap:2px">'
        f'<span class="n" style="font-variant-numeric:tabular-nums">{int(l["count"])}</span>'
        f'<span class="x">{_public_html_escape(l["label"])}</span></div>'
        for l in preview['lanes']
    )
    cards_html = ''
    if preview['cards']:
        items = ''.join(
            f'<li>{_public_html_escape(c["title"])} <em style="opacity:.6">· {_public_html_escape(c["status"])}</em></li>'
            for c in preview['cards']
        )
        cards_html = ('<ul class="public-cards" style="margin:6px 0 0;padding-left:1.1em;'
                      f'line-height:1.8">{items}</ul>')
    block = (
        '<div class="rule"></div>'
        '<p class="sec">此刻在跑</p>'
        '<div class="cols" style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-end">'
        f'{stats_html}</div>'
        f'{cards_html}'
        '<p class="sub" style="margin-top:14px">登录后是完整的实时驾驶舱；这里只露形态，不露内容。</p>'
        '<div style="margin-top:22px"><a href="/?app=1" style="display:inline-block;'
        'border:1px solid currentColor;border-radius:8px;padding:9px 18px;text-decoration:none;'
        'color:inherit;font-size:15px">进入驾驶舱 →</a></div>'
    )
    if '</main>' in html_text:
        return html_text.replace('</main>', block + '\n</main>', 1)
    return html_text + block

# ── HTML ──────────────────────────────────────────────

_HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / 'kanban.html'
_html_cache = None

def generate_html(data):
    global _html_cache
    if _html_cache is None:
        _html_cache = _HTML_TEMPLATE_PATH.read_text(encoding='utf-8')
    bootstrap = dict(data or {})
    bootstrap['server_version'] = get_server_version_info()
    data_json = json.dumps(bootstrap, ensure_ascii=False).replace('</', '<\\/')
    html = _html_cache.replace('__KANBAN_BOOTSTRAP_JSON__', data_json)
    html = html.replace('__KANBAN_HAS_API_VALUE__', 'true')
    return html

if __name__ == '__main__':
    if '--lint-naming' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        report = build_naming_lint_report()
        if '--json' in sys.argv:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_naming_lint_report(report))
            print("JSON:")
            print(json.dumps(report, ensure_ascii=False, indent=2))
    elif '--lint-grill' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        report = build_grill_lint_report()
        if '--json' in sys.argv:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_grill_lint_report(report))
            print("JSON:")
            print(json.dumps(report, ensure_ascii=False, indent=2))
    elif '--lint-ownership' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        report = build_ownership_lint_report()
        if '--json' in sys.argv:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(format_ownership_lint_report(report))
            print("JSON:")
            print(json.dumps(report, ensure_ascii=False, indent=2))
    elif '--backfill-task-family' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        result = backfill_active_task_families()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif '--backfill-lineage' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        result = backfill_card_lineage(dry_run='--write' not in sys.argv)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif '--sync-counters' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        state = load_state()
        all_docs = scan_all()
        synced, phantoms = ensure_counters_in_sync(all_docs, state)
        save_state(state)
        print(f"计数器同步完成: {synced} 个前缀已修正, {phantoms} 个幽灵计数器已移除")
        print(f"当前计数器: {json.dumps(state['counters'], ensure_ascii=False)}")
    elif '--backfill-task-ids' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        state = load_state()
        all_docs = scan_all()
        synced, phantoms = ensure_counters_in_sync(all_docs, state)
        backfilled = backfill_task_ids(all_docs, state)
        save_state(state)
        print(
            f"任务编号回填完成: {backfilled} 张卡已补 task_id, "
            f"{synced} 个前缀已修正, {phantoms} 个幽灵计数器已移除"
        )
        print(f"当前计数器: {json.dumps(state['counters'], ensure_ascii=False)}")
    elif '--sync-team-kanban' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        result = sync_team_kanban(config)
        if result.get('ok'):
            print(
                "团队看板同步完成: "
                f"{result.get('selected', 0)} 张相关卡, "
                f"新建 {result.get('created', 0)} 张, "
                f"更新 {result.get('updated', 0)} 张, "
                f"digest {result.get('digest_entries', 0)} 条"
            )
        else:
            print("团队看板同步跳过")
    elif '--test-team-feishu' in sys.argv:
        config = load_config()
        result = test_team_feishu_notifications(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif '--archive-done' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        idx = sys.argv.index('--archive-done')
        arg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ''
        days = int(arg) if arg.isdigit() else 7
        moved = archive_done_tasks(days)
        for old_path, new_path in moved:
            print(f"已归档: {old_path} -> {new_path}")
        print(f"归档完成: {len(moved)} 张 done 超过 {days} 天的卡片移入 .archive/")
    elif '--sweep-auto-accept' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        dry = '--dry-run' in sys.argv
        swept = sweep_auto_accept_reviews(dry_run=dry)
        for p in swept:
            print(("将自动通过(dry-run): " if dry else "已自动通过: ") + p)
        tail = "可自动通过（dry-run，未改动）" if dry else "已自动通过并落账"
        print(f"回扫完成: {len(swept)} 张存量 review 卡{tail}（ai-owned+reversible，非执行前 gate）")
    elif '--sweep-attention_gate-accept' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        dry = '--dry-run' in sys.argv
        rows = sweep_attention_gate_accept(dry_run=dry, config=config, logger=print)
        for r in rows:
            print(f"  [{r['action']}] {r['task_id']} ({r['age_hours']:.1f}h) — {r['reason']}")
        acc = [r for r in rows if r['action'] == 'accepted']
        rej = [r for r in rows if r['action'] == 'rejected']
        fail = [r for r in rows if r['action'] == 'review-failed']
        would = [r for r in rows if r['action'] == 'would-review']
        if dry:
            print(f"\n人闸验收超时代收(dry-run，未跑 review/未改动): "
                  f"{len(would)} 张超时 review 卡将进入真 review（假如现在执行会代收/打回这些）")
        else:
            print(f"\n人闸验收超时代收完成: 代收 {len(acc)} · 打回 {len(rej)} · "
                  f"review 未跑成留 Owner {len(fail)}（阈值 {_acceptance_timeout_hours(config):.0f}h）")
    elif '--backfill-review-since' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        dry = '--dry-run' in sys.argv
        rows = backfill_review_since(dry_run=dry)
        for path, value, source in rows:
            print(f"  {'(dry-run) ' if dry else ''}review_since={value} ({source}) ← {path}")
        print(f"review_since 回填{'（dry-run，未写）' if dry else ''}完成: {len(rows)} 张存量 review 卡")
    elif '--infer-responsibility' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        dry = '--dry-run' in sys.argv
        rows = infer_responsibility_labels(dry_run=dry)
        ai = [r for r in rows if r[1] == 'ai-owned']
        pi = [r for r in rows if r[1] == 'pi-gated']
        blank = [r for r in rows if not r[1]]
        for path, resp, safety, conf, reason, wrote in rows:
            mark = '✓写入' if wrote else ('·预览' if dry else '·跳过(低置信/留空)')
            print(f"  [{mark}] {resp or '（留空）'}/{safety or '-'} «{conf}» {path} — {reason}")
        print(
            f"\n推断完成: ai-owned {len(ai)} · pi-gated {len(pi)} · 留给 Owner {len(blank)}"
            + ("（dry-run，未写入）" if dry else "（高/中置信已写入 frontmatter）")
        )
    elif '--spawn-prior-art' in sys.argv:
        config = load_config()
        SCAN_DIRS = _configured_scan_dirs_or_exit(config)
        dry = '--dry-run' in sys.argv
        spawned = spawn_prior_art_cards(dry_run=dry)
        for src_id, newpath in spawned:
            print(("将产对标卡(dry-run): " if dry else "已产对标卡: ") + f"{src_id} → {newpath}")
        tail = "可产（dry-run，未建）" if dry else "已产并进收件箱待分流"
        print(f"前沿对标 feeder 完成: {len(spawned)} 张{tail}（触发=novel_build，幂等键 prior-art-scan/<task_id>）")
    elif '--detect-compression' in sys.argv:
        dry = '--dry-run' in sys.argv
        cands = detect_compression_candidates(dry_run=dry)
        for cls, n in cands:
            print(f"  «{cls}» × {n} → 压缩候选(核对是否同向→可委托)")
        tail = "（dry-run，未写草稿）" if dry else "（新候选已写进 DECISION_LOG 待追认区）"
        print(f"压缩触发检测完成: {len(cands)} 个候选(≥3 同类，已排除机器决策/已压缩类){tail}")
    else:
        main_serve(force_restart=_argv_flag('--force-restart'))

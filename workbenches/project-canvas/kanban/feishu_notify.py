import json
import subprocess
import time
import urllib.request
import urllib.error
import uuid


DEFAULTS = {
    'app_id': '',
    'app_secret': '',
    'kanban_base_url': '',
    'member_open_ids': {},
    'transport': 'api',
    'lark_cli_path': 'lark-cli',
    'lark_cli_profile': '',
    'lark_cli_as': 'bot',
}

ENV_MAP = {
    'app_id': 'FEISHU_APP_ID',
    'app_secret': 'FEISHU_APP_SECRET',
    'kanban_base_url': 'KANBAN_BASE_URL',
    'transport': 'KANBAN_FEISHU_TRANSPORT',
    'lark_cli_path': 'KANBAN_LARK_CLI_PATH',
    'lark_cli_profile': 'KANBAN_LARK_CLI_PROFILE',
    'lark_cli_as': 'KANBAN_LARK_CLI_AS',
}

PRIORITY_MAP = {
    'critical': {'label': '🔴 紧急', 'color': 'red'},
    'high':     {'label': '🟠 高',   'color': 'orange'},
    'medium':   {'label': '🟡 中',   'color': 'yellow'},
    'low':      {'label': '🟢 低',   'color': 'green'},
}

CONFIG = dict(DEFAULTS)
TOKEN_CACHE = {'token': '', 'expires_at': 0}


def normalize_member_open_ids(raw_member_open_ids):
    """规范化成员 open_id 映射，忽略无效配置项。"""
    if not isinstance(raw_member_open_ids, dict):
        return {}
    normalized = {}
    for key, value in raw_member_open_ids.items():
        member = str(key).strip()
        open_id = str(value).strip()
        if member:
            normalized[member] = open_id
    return normalized


def normalize_config(config, environ):
    """从配置文件读取飞书配置，并对缺失字段回退到环境变量。"""
    raw = config.get('feishu', {}) if isinstance(config, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    normalized = {}
    for key, env_name in ENV_MAP.items():
        value = raw.get(key) or environ.get(env_name, '')
        normalized[key] = str(value).strip().rstrip('/')
    normalized['transport'] = (normalized.get('transport') or 'api').lower().replace('-', '_')
    if normalized.get('lark_cli_as') not in ('bot', 'user'):
        normalized['lark_cli_as'] = 'bot'
    normalized['member_open_ids'] = normalize_member_open_ids(raw.get('member_open_ids', {}))
    return normalized


def set_config(config):
    global CONFIG
    CONFIG = dict(DEFAULTS)
    if isinstance(config, dict):
        CONFIG.update(config)


def reset_token_cache():
    TOKEN_CACHE['token'] = ''
    TOKEN_CACHE['expires_at'] = 0


def is_enabled():
    transport = str(CONFIG.get('transport') or 'api').lower()
    if transport == 'lark_cli':
        return True
    return bool(CONFIG.get('app_id', '') and CONFIG.get('app_secret', ''))


def _truncate_warning(text, limit=240):
    clean = str(text or '').replace('\n', ' ').strip()
    return clean[:limit]


def get_tenant_token():
    """获取飞书 tenant_access_token，带简单缓存（有效期 2 小时，提前 5 分钟刷新）。"""
    now = time.time()
    if TOKEN_CACHE['token'] and now < TOKEN_CACHE['expires_at'] - 300:
        return TOKEN_CACHE['token']

    if not is_enabled():
        return ''

    payload = json.dumps({
        'app_id': CONFIG.get('app_id', ''),
        'app_secret': CONFIG.get('app_secret', ''),
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        import ssl
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('code') != 0:
            print(f"  [飞书] 获取 token 失败: {data.get('msg', 'unknown')}")
            return ''
        token = data.get('tenant_access_token', '')
        expire = data.get('expire', 7200)
        TOKEN_CACHE['token'] = token
        TOKEN_CACHE['expires_at'] = now + expire
        return token
    except Exception as e:
        print(f"  [飞书] 获取 token 异常: {e}")
        return ''


def build_card(task_id, title, assignee, priority, due_date, project, body_preview, event_type):
    """构建飞书卡片消息 JSON。"""
    prio_info = PRIORITY_MAP.get(priority, PRIORITY_MAP['medium'])
    header_title = f'📋 新任务: {task_id}' if event_type == 'created' else f'🔄 任务转派: {task_id}'

    elements = [{
        'tag': 'div',
        'text': {'tag': 'lark_md', 'content': f'**{title}**'},
    }]

    fields = [
        {'is_short': True, 'text': {'tag': 'lark_md', 'content': f'**负责人:** {assignee}'}},
        {'is_short': True, 'text': {'tag': 'lark_md', 'content': f'**优先级:** {prio_info["label"]}'}},
    ]
    if due_date:
        fields.append({'is_short': True, 'text': {'tag': 'lark_md', 'content': f'**截止日期:** {due_date}'}})
    fields.append({'is_short': True, 'text': {'tag': 'lark_md', 'content': f'**项目:** {project}'}})
    elements.append({'tag': 'div', 'fields': fields})

    if body_preview:
        truncated = body_preview[:150].replace('\n', ' ').strip()
        if len(body_preview) > 150:
            truncated += '...'
        elements.append({
            'tag': 'div',
            'text': {'tag': 'lark_md', 'content': f'---\n{truncated}'},
        })

    base_url = CONFIG.get('kanban_base_url', '')
    if base_url:
        elements.append({
            'tag': 'action',
            'actions': [{
                'tag': 'button',
                'text': {'tag': 'plain_text', 'content': '查看详情'},
                'type': 'primary',
                'url': f'{base_url}/#{task_id}',
            }],
        })

    return {
        'config': {'wide_screen_mode': True},
        'header': {
            'title': {'tag': 'plain_text', 'content': header_title},
            'template': prio_info['color'],
        },
        'elements': elements,
    }


def send_card(open_id, card):
    """发送飞书卡片消息，返回 None 表示成功，字符串表示警告。"""
    if str(CONFIG.get('transport') or 'api').lower() == 'lark_cli':
        return send_card_via_lark_cli(open_id, card)

    token = get_tenant_token()
    if not token:
        return '飞书 tenant_access_token 获取失败'

    payload = json.dumps({
        'receive_id': open_id,
        'msg_type': 'interactive',
        'content': json.dumps(card, ensure_ascii=False),
        'uuid': str(uuid.uuid4()),
    }, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
        method='POST',
    )
    try:
        import ssl
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('code') != 0:
            print(f"  [飞书] 发送失败: {data.get('msg', 'unknown')}")
            return f"飞书发送失败: {data.get('msg', '')}"
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"  [飞书] 发送异常 HTTP {e.code}: {body}")
        return f"飞书通知异常 HTTP {e.code}: {body[:200]}"
    except Exception as e:
        print(f"  [飞书] 发送异常: {e}")
        return f"飞书通知异常: {e}"


def send_card_via_lark_cli(open_id, card):
    """Use lark-cli's configured encrypted credentials instead of copying app secrets."""
    cli_path = str(CONFIG.get('lark_cli_path') or 'lark-cli').strip() or 'lark-cli'
    identity = str(CONFIG.get('lark_cli_as') or 'bot').strip()
    if identity not in ('bot', 'user'):
        identity = 'bot'
    profile = str(CONFIG.get('lark_cli_profile') or '').strip()
    content = json.dumps(card, ensure_ascii=False, separators=(',', ':'))
    argv = [
        cli_path,
        'im',
        '+messages-send',
        '--as',
        identity,
        '--user-id',
        open_id,
        '--msg-type',
        'interactive',
        '--content',
        content,
        '--idempotency-key',
        f"kanban-{uuid.uuid4()}",
    ]
    if profile:
        argv.extend(['--profile', profile])
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return 'lark-cli 未找到'
    except subprocess.TimeoutExpired:
        return 'lark-cli 发送超时'
    except Exception as e:
        return f"lark-cli 发送异常: {type(e).__name__}"
    if proc.returncode != 0:
        detail = _truncate_warning(proc.stderr or proc.stdout)
        return f"lark-cli 发送失败: {detail}"
    return None


def send_text(open_id, message, idempotency_key=''):
    """发送纯文本私信，返回 None 表示成功，字符串表示警告。"""
    if str(CONFIG.get('transport') or 'api').lower() == 'lark_cli':
        return send_text_via_lark_cli(open_id, message, idempotency_key=idempotency_key)

    token = get_tenant_token()
    if not token:
        return '飞书 tenant_access_token 获取失败'
    payload = {
        'receive_id': open_id,
        'msg_type': 'text',
        'content': json.dumps({'text': str(message)}, ensure_ascii=False),
        'uuid': str(idempotency_key or uuid.uuid4()),
    }
    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
        method='POST',
    )
    try:
        import ssl
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('code') != 0:
            return f"飞书发送失败: {data.get('msg', '')}"
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return f"飞书通知异常 HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return f"飞书通知异常: {type(e).__name__}"


def send_text_via_lark_cli(open_id, message, idempotency_key=''):
    """通过 lark-cli 已加密的本机凭据发送纯文本私信。"""
    cli_path = str(CONFIG.get('lark_cli_path') or 'lark-cli').strip() or 'lark-cli'
    identity = str(CONFIG.get('lark_cli_as') or 'bot').strip()
    if identity not in ('bot', 'user'):
        identity = 'bot'
    profile = str(CONFIG.get('lark_cli_profile') or '').strip()
    argv = [
        cli_path,
        'im',
        '+messages-send',
        '--as',
        identity,
        '--user-id',
        open_id,
        '--text',
        str(message),
        '--idempotency-key',
        str(idempotency_key or f'kanban-{uuid.uuid4()}'),
    ]
    if profile:
        argv.extend(['--profile', profile])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return 'lark-cli 未找到'
    except subprocess.TimeoutExpired:
        return 'lark-cli 发送超时'
    except Exception as e:
        return f"lark-cli 发送异常: {type(e).__name__}"
    if proc.returncode != 0:
        detail = _truncate_warning(proc.stderr or proc.stdout)
        return f"lark-cli 发送失败: {detail}"
    return None


def notify_member_text(member, message, idempotency_key=''):
    """向已配置成员发送纯文本私信。"""
    if not member:
        return '未指定飞书成员'
    if not is_enabled():
        return '飞书通知未启用'
    member_open_ids = CONFIG.get('member_open_ids', {})
    if not isinstance(member_open_ids, dict):
        member_open_ids = {}
    open_id = member_open_ids.get(member, '')
    if not open_id:
        return f"成员 '{member}' 未配置飞书 open_id"
    return send_text(open_id, message, idempotency_key=idempotency_key)


def _event_template(event_type):
    if event_type in ('team_due_soon', 'team_overdue', 'sync_stale'):
        return 'orange'
    if event_type in ('handoff_status_changed', 'handoff_created'):
        return 'blue'
    return 'green'


def build_event_card(event_type, title, fields=None, body='', url=''):
    """Build a generic Feishu card for team coordination events."""
    lines = [f'**{title}**']
    for item in fields or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        label, value = str(item[0] or '').strip(), str(item[1] or '').strip()
        if not label or not value:
            continue
        lines.append(f'**{label}:** {value}')
    if body:
        truncated = str(body)[:260].replace('\n', ' ').strip()
        if len(str(body)) > 260:
            truncated += '...'
        lines.extend(['', '---', truncated])
    if url:
        lines.extend(['', f'[查看详情]({url})'])
    return {
        'schema': '2.0',
        'config': {'wide_screen_mode': True},
        'header': {
            'title': {'tag': 'plain_text', 'content': title[:60]},
            'template': _event_template(event_type),
        },
        'body': {
            'elements': [{
                'tag': 'markdown',
                'content': '\n'.join(lines),
            }],
        },
    }


def notify_member_event(member, event_type, title, fields=None, body='', url=''):
    """Send a generic event card to a configured member."""
    if not member:
        return None
    if not is_enabled():
        return None
    member_open_ids = CONFIG.get('member_open_ids', {})
    if not isinstance(member_open_ids, dict):
        member_open_ids = {}
    open_id = member_open_ids.get(member, '')
    if not open_id:
        print(f"  [飞书] 跳过: 未找到成员 '{member}' 的 open_id")
        return f"成员 '{member}' 未配置飞书 open_id"
    result = send_card(open_id, build_event_card(event_type, title, fields, body, url))
    if result is None:
        print(f"  [飞书] 已通知 {member} 关于 {event_type}")
    return result


def notify_assignee(assignee, task_id, title, priority, due_date, project, body_preview, event_type='created', old_assignee=''):
    """向任务负责人发送飞书卡片通知。返回 None 成功，字符串为警告。"""
    if not assignee:
        return None
    if not is_enabled():
        return None

    member_open_ids = CONFIG.get('member_open_ids', {})
    if not isinstance(member_open_ids, dict):
        member_open_ids = {}
    open_id = member_open_ids.get(assignee, '')
    if not open_id:
        print(f"  [飞书] 跳过: 未找到成员 '{assignee}' 的 open_id")
        return f"成员 '{assignee}' 未配置飞书 open_id"

    card = build_card(task_id, title, assignee, priority, due_date, project, body_preview, event_type)
    result = send_card(open_id, card)
    if result is None:
        print(f"  [飞书] 已通知 {assignee} 关于 {task_id}")
    return result


def notify_old_assignee(old_assignee, task_id, title, new_assignee, project):
    """向旧负责人发送简短的转出通知（fire-and-forget）。"""
    if not old_assignee:
        return
    if not is_enabled():
        return

    member_open_ids = CONFIG.get('member_open_ids', {})
    if not isinstance(member_open_ids, dict):
        member_open_ids = {}
    open_id = member_open_ids.get(old_assignee, '')
    if not open_id:
        return

    card = {
        'schema': '2.0',
        'header': {
            'title': {'tag': 'plain_text', 'content': f'🔄 任务转出: {task_id}'},
            'template': 'blue',
        },
        'elements': [{
            'tag': 'div',
            'text': {
                'tag': 'lark_md',
                'content': f'**{title}**\n已从你转派给 **{new_assignee}**\n项目: {project}',
            },
        }],
    }
    send_card(open_id, card)

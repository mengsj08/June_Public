"""Agent-mail 基建维护台账读取（仅供显式配置的可选集成使用）。

只读调用方传入目录下的维护证据，供看板治理页「基建维护台账」面板消费：
- `maintenance.jsonl`：死信归档 / 日志压缩等治理维护事件（只增台账，每行一个 JSON 对象）。
- `inbox/<sid>/*.json`：收件箱消息；sid 目录名不在 `registry.json` 键里的即「孤儿」，
  其内 `*.json` 计数 = 当前死信数（inbox 孤儿实测）。
- `archive-map-watcher/runs/`：watcher 运行日志体量（文件计数）。

单体冻结/切口纪律：本模块是无常驻状态的进程内库，scan-docs.py 只加一个薄转发
GET `/api/governance/maintenance`（解析→调本模块→翻译响应，走既有同源守护、不自带鉴权）。
缺文件 / 空台账时优雅降级：返回 ok=True + 空事件 + 计数为 0，不抛错。
"""

import glob
import json
import os
from datetime import datetime, timezone


# 维护事件展示只保留这些字段（避免把可能含敏感正文的字段泄进前端）。
_EVENT_FIELDS = ('ts', 'actor', 'action', 'sid', 'msgs', 'from', 'reason', 'moved_to')


def _resolve_home(home=None):
    raw = str(home or '').strip()
    if not raw:
        return None
    return os.path.abspath(os.path.expanduser(raw))


def _sanitize_event(obj):
    """只挑白名单字段，reason 截断，避免超长/敏感正文进前端。"""
    if not isinstance(obj, dict):
        return None
    event = {}
    for key in _EVENT_FIELDS:
        if key not in obj:
            continue
        value = obj[key]
        if key == 'reason' and isinstance(value, str) and len(value) > 400:
            value = value[:400] + '…'
        event[key] = value
    return event or None


def read_maintenance_events(home=None, limit=12):
    """读取 maintenance.jsonl，返回 (最近 limit 条倒序, 有效事件总数)。缺文件返回 ([], 0)。"""
    resolved = _resolve_home(home)
    if not resolved:
        return [], 0
    path = os.path.join(resolved, 'maintenance.jsonl')
    events = []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                event = _sanitize_event(obj)
                if event is not None:
                    events.append(event)
    except FileNotFoundError:
        return [], 0
    except OSError:
        return [], 0
    total = len(events)
    recent = list(reversed(events))
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 12
    if cap > 0:
        recent = recent[:cap]
    return recent, total


def _registry_keys(home):
    resolved = _resolve_home(home)
    if not resolved:
        return set(), False
    path = os.path.join(resolved, 'registry.json')
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, ValueError):
        return set(), False
    if isinstance(data, dict):
        return set(str(key) for key in data.keys()), True
    if isinstance(data, list):
        # 兼容列表形态：取每项的 sid/session_id 字段。
        keys = set()
        for item in data:
            if isinstance(item, dict):
                sid = item.get('sid') or item.get('session_id') or item.get('id')
                if sid:
                    keys.add(str(sid))
        return keys, True
    return set(), True


def count_dead_letters(home=None):
    """死信数 = inbox 下 sid 目录名不在 registry 键里（孤儿）的目录内 *.json 计数。

    返回 {dead_letters, orphan_dirs, registry_ok}。缺 inbox 返回全 0。
    """
    resolved = _resolve_home(home)
    if not resolved:
        return {'dead_letters': 0, 'orphan_dirs': 0, 'registry_ok': False}
    inbox = os.path.join(resolved, 'inbox')
    registry, registry_ok = _registry_keys(resolved)
    dead_letters = 0
    orphan_dirs = 0
    try:
        entries = os.listdir(inbox)
    except (FileNotFoundError, OSError):
        return {'dead_letters': 0, 'orphan_dirs': 0, 'registry_ok': registry_ok}
    for name in entries:
        sid_dir = os.path.join(inbox, name)
        if not os.path.isdir(sid_dir):
            continue
        if name in registry:
            continue
        orphan_dirs += 1
        try:
            dead_letters += len(glob.glob(os.path.join(sid_dir, '*.json')))
        except OSError:
            continue
    return {'dead_letters': dead_letters, 'orphan_dirs': orphan_dirs, 'registry_ok': registry_ok}


def count_watcher_runs(home=None):
    """archive-map-watcher/runs/ 运行日志体量（非隐藏文件计数）。缺目录返回 0。"""
    resolved = _resolve_home(home)
    if not resolved:
        return 0
    runs = os.path.join(resolved, 'archive-map-watcher', 'runs')
    try:
        entries = os.listdir(runs)
    except (FileNotFoundError, OSError):
        return 0
    return sum(1 for name in entries if not name.startswith('.'))


def load_maintenance_overview(home=None, limit=12):
    """治理页「基建维护台账」面板的数据源。永远 ok=True，缺文件优雅降级。"""
    resolved = _resolve_home(home)
    home_exists = bool(resolved and os.path.isdir(resolved))
    events, event_total = read_maintenance_events(resolved, limit=limit)
    dead = count_dead_letters(resolved)
    watcher_runs = count_watcher_runs(resolved)
    return {
        'ok': True,
        'enabled': bool(resolved),
        'home_exists': home_exists,
        'events': events,
        'event_total': event_total,
        'dead_letters': dead['dead_letters'],
        'orphan_dirs': dead['orphan_dirs'],
        'registry_ok': dead['registry_ok'],
        'watcher_runs': watcher_runs,
        'generated_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
    }

#!/usr/bin/env python3
"""Resolve Canvas Studio dist requests for the thin scan-docs HTTP adapter."""

from dataclasses import dataclass
from html import escape
import mimetypes
from pathlib import Path
from urllib.parse import unquote


MIME_OVERRIDES = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.map': 'application/json; charset=utf-8',
}


@dataclass(frozen=True)
class StaticResponse:
    status: int
    content_type: str
    body: bytes


def resolve_dist_dir(repo_root, configured_path, default_path='canvas-studio/dist'):
    raw_path = str(configured_path or default_path).strip() or default_path
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        expanded = Path(repo_root) / expanded
    return expanded.resolve()


def _content_type(path):
    override = MIME_OVERRIDES.get(path.suffix.lower())
    if override:
        return override
    guessed, _ = mimetypes.guess_type(str(path))
    if not guessed:
        return 'application/octet-stream'
    if guessed.startswith('text/') or guessed in ('application/javascript', 'application/json'):
        return guessed + '; charset=utf-8'
    return guessed


def _missing_dist_page(dist_dir):
    dist_label = escape(str(dist_dir), quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>画布工作台未构建</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f3f1;color:#151515}}
.shell{{min-height:100vh;display:grid;place-items:center;padding:24px}}
.panel{{width:min(680px,100%);padding:28px 0;border-top:1px solid #151515;border-bottom:1px solid #d8d8d5}}
h1{{margin:0 0 10px;font-size:22px;line-height:1.2}}p{{margin:0 0 12px;color:#555;font-size:14px;line-height:1.65}}
code{{display:block;padding:10px 0;color:#151515;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}
</style>
<div class="shell">
  <section class="panel">
    <h1>画布工作台还没有构建产物</h1>
    <p>进入 canvas-studio 运行 npm run build；构建失败不影响看板服务。</p>
    <code>{dist_label}</code>
  </section>
</div>
</html>""".encode('utf-8')


def resolve_request(request_path, dist_dir, mount_path='/canvas'):
    """Return a static response, with SPA fallback and traversal protection."""
    dist_root = Path(dist_dir).resolve()
    index_path = dist_root / 'index.html'
    if not dist_root.is_dir() or not index_path.is_file():
        return StaticResponse(200, 'text/html; charset=utf-8', _missing_dist_page(dist_root))

    if request_path == mount_path:
        rel_value = ''
    else:
        rel_value = unquote(request_path.removeprefix(mount_path + '/'))
    asset_path = (dist_root / rel_value).resolve()
    if asset_path != dist_root and dist_root not in asset_path.parents:
        return StaticResponse(403, 'text/plain; charset=utf-8', b'Forbidden')
    if not asset_path.is_file():
        asset_path = index_path

    return StaticResponse(200, _content_type(asset_path), asset_path.read_bytes())

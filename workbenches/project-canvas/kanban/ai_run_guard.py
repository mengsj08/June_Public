"""Small safety helpers for canvas-backed AI runs.

Kept outside scan-docs.py so prompt truthfulness, error surfacing, and retry
policy can be tested without growing the HTTP monolith.
"""

from __future__ import annotations

import os
from typing import Any, Iterable


RESOLVED_SOURCE_STATUSES = frozenset({"resolved", "corrected"})
CLAUDE_AUTH_RETRY_DELAYS_SECONDS = (30, 60)
MAX_ERROR_CHARS = 2000
# 宿主 agent 会话(Claude Code/SDK)泄漏进服务进程的变量前缀。
# 看板服务常被 agent 会话间接拉起(nohup 继承整套环境),子进程 claude CLI
# 看到 ANTHROPIC_BASE_URL / CLAUDE_CODE_* 会走宿主会话网关,鉴权必 401
# (2026-07-10 KMO-47 run f81fe08d 实锤,KAN-851 附修)。
HOST_SESSION_ENV_PREFIXES = ("CLAUDE", "ANTHROPIC")


def sanitized_cli_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """给 AI CLI 子进程用的环境:剥掉宿主 agent 会话泄漏的变量。"""
    source = os.environ if environ is None else environ
    return {
        key: value
        for key, value in source.items()
        if not key.startswith(HOST_SESSION_ENV_PREFIXES)
    }


def _compact(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_canvas_prompt(user_prompt: str, entries: Iterable[dict[str, Any]]) -> tuple[str, int]:
    """Build an auditable prompt; unresolved refs never masquerade as content."""
    lines: list[str] = []
    unresolved_count = 0
    for raw in list(entries or [])[:50]:
        if not isinstance(raw, dict):
            continue
        kind = _compact(raw.get("kind") or "node", 40)
        title = _compact(raw.get("title") or raw.get("id") or "未命名节点", 120)
        status = _compact(raw.get("status") or "resolved", 40)
        path = _compact(raw.get("resolved_path") or raw.get("path"), 300)
        lines.append(f"- [{kind}] {title}")
        if status not in RESOLVED_SOURCE_STATUSES:
            unresolved_count += 1
            detail = f"；引用={path}" if path else ""
            lines.append(f"  状态: 未解析，内容不可用（{status or 'missing'}{detail}）")
            continue
        summary = _compact(raw.get("summary"), 700)
        relation = _compact(raw.get("relation"), 360)
        if summary:
            lines.append(f"  摘要: {summary}")
        if relation:
            lines.append(f"  关联理由: {relation}")
        if path:
            lines.append(f"  来源: {path}")

    prompt = str(user_prompt or "").strip()
    if not lines:
        return prompt, unresolved_count
    return "\n".join([
        "<canvas_upstream_context>",
        "以下条目来自直接连到本对话节点的上游。resolved/corrected 条目的「来源」是本机绝对路径——请先直接读取该路径的文件全文,再基于全文回答,不要只凭文件名或摘要作答；标为‘未解析，内容不可用’的条目不得据此声称已读取原文件。",
        *lines,
        "</canvas_upstream_context>",
        "",
        "<user_request>",
        prompt,
        "</user_request>",
    ]), unresolved_count


def nonzero_exit_error(stderr: Any, parsed_content: Any, stdout: Any, returncode: int,
                       limit: int = MAX_ERROR_CHARS) -> str:
    """Prefer stderr, then parsed/stdout truth, and only then a bare exit code."""
    for value in (stderr, parsed_content, stdout):
        text = str(value or "").strip()
        if not text:
            continue
        if len(text) > limit:
            text = "…" + text[-(limit - 1):]
        return text
    return f"Exit code {returncode}"

#!/usr/bin/env python3
"""TeamSpace GitHub + Feishu daily sync reporter.

This script is intentionally self-contained and uses only the Python standard
library. It never prints secret values; it only reports whether required local
configuration is present.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


DEFAULT_CONFIG = {
    "teamspace_root": "~/Documents/TeamSpace",
    "timezone": "Asia/Shanghai",
    "env_files": ["~/.config/team-sync-reporter/secrets.env"],
    "report_window": {"mode": "yesterday"},
    "report": {
        "message_prompt_path": "$TEAMSPACE_CONFIG_DIR/feishu-message-prompt.md",
    },
    "github": {
        "repos": [
            {
                "name": "REQUIRED_REPO_NAME",
                "url": "REQUIRED_GITHUB_REPO_URL",
                "branch": "main",
            }
        ]
    },
    "feishu": {
        "sync_commands": [],
        "state_files": [
            {
                "label": "team wiki",
                "path": "$INFO_LIBRARY_ROOT/raw/feishu/team-sync/.sync_state.json",
            }
        ],
    },
    "send": {
        "mode": "webhook",
        "webhook_env": "FEISHU_BOT_WEBHOOK",
        "secret_env": "FEISHU_BOT_SECRET",
        "test_webhook_env": "FEISHU_TEST_BOT_WEBHOOK",
        "test_secret_env": "FEISHU_TEST_BOT_SECRET",
    },
}


SECRET_WORDS = ("token", "secret", "webhook", "password", "cookie", "chat_id", "authorization")


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def tail(text: str, limit: int = 1200) -> str:
    text = text or ""
    return text[-limit:]


def has_secret_name(key: str) -> bool:
    lower = key.lower()
    return any(word in lower for word in SECRET_WORDS)


def safe_env_presence(env_name: str) -> dict[str, Any]:
    value = os.environ.get(env_name, "")
    return {"name": env_name, "present": bool(value), "length": len(value) if value else 0}


def tzinfo(name: str) -> dt.tzinfo:
    if ZoneInfo:
        return ZoneInfo(name)
    if name == "Asia/Shanghai":
        return dt.timezone(dt.timedelta(hours=8))
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_env_file(path: Path) -> dict[str, bool]:
    loaded: dict[str, bool] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            continue
        if key not in os.environ:
            os.environ[key] = value
        loaded[key] = bool(value)
    return loaded


def load_config_env_files(config: dict[str, Any]) -> list[dict[str, Any]]:
    loaded = []
    for item in config.get("env_files", []):
        path = Path(os.path.expanduser(str(item)))
        key_presence = load_env_file(path)
        loaded.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "keys": {key: present for key, present in key_presence.items()},
            }
        )
    return loaded


def expand(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = os.path.expanduser(value)
        for key, replacement in env.items():
            out = out.replace(f"${key}", replacement)
        return out
    if isinstance(value, list):
        return [expand(item, env) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, env) for key, item in value.items()}
    return value


def context(config: dict[str, Any]) -> dict[str, str]:
    root = Path(os.path.expanduser(config.get("teamspace_root", "~/Documents/TeamSpace"))).resolve()
    return {
        "TEAMSPACE_ROOT": str(root),
        "ACP_HOME": str(root / "automation-control-plane"),
        "WORKFLOWS_ROOT": str(root / "workflows"),
        "INFO_LIBRARY_ROOT": str(root / "team-info-library"),
        "TEAMSPACE_CONFIG_DIR": str(root / "config"),
        "REVIEW_QUEUE_DIR": str(root / "team-info-library" / "review-queue"),
    }


def load_config(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    config = load_json(path)
    env = context(config)
    expanded = expand(config, env)
    load_config_env_files(expanded)
    return expanded, env


def repo_config_problem(repo: dict[str, Any]) -> str | None:
    name = str(repo.get("name", "")).strip()
    url = str(repo.get("url", "")).strip()
    if not name or name == "REQUIRED_REPO_NAME":
        return "repo name not configured"
    if not url or url == "REQUIRED_GITHUB_REPO_URL" or "ORG/REPO" in url:
        return "repo url not configured"
    if any(part in name for part in ["/", ":", "\\"]) or name.startswith("."):
        return "repo name must be a local directory-safe name, not a URL or path"
    return None


def run_cmd(
    argv: list[str],
    cwd: str | Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env.setdefault(
        "PATH",
        "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    )
    if env:
        command_env.update(env)
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=command_env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def ensure_layout(env: dict[str, str]) -> None:
    for key in [
        "ACP_HOME",
        "WORKFLOWS_ROOT",
        "TEAMSPACE_CONFIG_DIR",
        "REVIEW_QUEUE_DIR",
    ]:
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    for sub in ["raw/github", "raw/feishu", "normalized", "derived"]:
        (Path(env["INFO_LIBRARY_ROOT"]) / sub).mkdir(parents=True, exist_ok=True)


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def write_if_missing(path: Path, text: str, mode: int | None = None) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return True


def command_init(args: argparse.Namespace) -> int:
    root = Path(os.path.expanduser(args.root)).resolve()
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["teamspace_root"] = str(root)
    env = context(config)
    ensure_layout(env)

    acp_home = Path(env["ACP_HOME"])
    installed_script = acp_home / "team_sync_reporter.py"
    shutil.copy2(Path(__file__).resolve(), installed_script)
    installed_script.chmod(0o755)

    config_path = Path(env["TEAMSPACE_CONFIG_DIR"]) / "team-sync-reporter.config.json"
    if not config_path.exists():
        asset_config = skill_root() / "assets" / "config.example.json"
        if asset_config.exists():
            cfg = json.loads(asset_config.read_text(encoding="utf-8"))
            cfg["teamspace_root"] = str(root)
            if args.repo_name:
                cfg["github"]["repos"][0]["name"] = args.repo_name
            if args.repo_url:
                cfg["github"]["repos"][0]["url"] = args.repo_url
            config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            if args.repo_name:
                config["github"]["repos"][0]["name"] = args.repo_name
            if args.repo_url:
                config["github"]["repos"][0]["url"] = args.repo_url
            dump_json(config_path, config)

    secrets_dir = Path.home() / ".config" / "team-sync-reporter"
    secrets_template = secrets_dir / "secrets.example.env"
    asset_secrets = skill_root() / "assets" / "secrets.example.env"
    if asset_secrets.exists() and not secrets_template.exists():
        secrets_dir.mkdir(parents=True, exist_ok=True)
        secrets_template.write_text(asset_secrets.read_text(encoding="utf-8"), encoding="utf-8")
        secrets_template.chmod(0o600)

    run_script = acp_home / "run_team_sync_reporter_daily.sh"
    run_text = f"""#!/bin/zsh
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
python3 "{installed_script}" run --config "{config_path}"
"""
    write_if_missing(run_script, run_text, 0o755)

    prompt_src = skill_root() / "assets" / "workbuddy-daily-prompt.md"
    prompt_dst = acp_home / "workbuddy-daily-prompt.md"
    if prompt_src.exists() and not prompt_dst.exists():
        prompt_dst.write_text(prompt_src.read_text(encoding="utf-8"), encoding="utf-8")

    message_prompt_src = skill_root() / "assets" / "feishu-message-prompt.md"
    message_prompt_dst = Path(env["TEAMSPACE_CONFIG_DIR"]) / "feishu-message-prompt.md"
    if message_prompt_src.exists() and not message_prompt_dst.exists():
        message_prompt_dst.write_text(message_prompt_src.read_text(encoding="utf-8"), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "teamspace_root": str(root),
                "config": str(config_path),
                "script": str(installed_script),
                "daily_runner": str(run_script),
                "workbuddy_prompt": str(prompt_dst),
                "message_prompt": str(message_prompt_dst),
                "secrets_template": str(secrets_template),
                "next": "Edit config, then run doctor.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def check_command(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"name": name, "path": path, "ok": bool(path)}


def command_doctor(args: argparse.Namespace) -> int:
    config, env = load_config(Path(args.config).expanduser())
    ensure_layout(env)
    checks: dict[str, Any] = {
        "tools": [check_command(name) for name in ["python3", "git", "gh"]],
        "env_files": load_config_env_files(config),
        "github": [],
        "feishu": {"sync_commands": [], "state_files": []},
        "send": {},
    }

    gh = run_cmd(["gh", "auth", "status"], timeout=20)
    checks["gh_auth_status"] = {"ok": gh.returncode == 0, "stderr_tail": tail(gh.stderr, 500)}

    for repo in config.get("github", {}).get("repos", []):
        url = repo.get("url", "")
        problem = repo_config_problem(repo)
        if problem:
            checks["github"].append({"name": repo.get("name"), "ok": False, "reason": problem})
            continue
        result = run_cmd(["git", "ls-remote", url, "HEAD"], timeout=45)
        checks["github"].append(
            {
                "name": repo.get("name"),
                "url_configured": True,
                "ok": result.returncode == 0,
                "stderr_tail": tail(result.stderr, 500),
            }
        )

    for item in config.get("feishu", {}).get("sync_commands", []):
        argv = item.get("argv") or []
        executable = argv[0] if argv else ""
        checks["feishu"]["sync_commands"].append(
            {
                "label": item.get("label"),
                "configured": bool(argv),
                "executable_found": bool(shutil.which(executable)) if executable else False,
                "cwd_exists": Path(item.get("cwd", ".")).expanduser().exists(),
            }
        )

    for item in config.get("feishu", {}).get("state_files", []):
        path = Path(item.get("path", "")).expanduser()
        checks["feishu"]["state_files"].append(
            {"label": item.get("label"), "path": str(path), "exists": path.exists()}
        )

    send = config.get("send", {})
    mode = send.get("mode", "webhook")
    checks["send"]["mode"] = mode
    if mode == "webhook":
        checks["send"]["webhook"] = safe_env_presence(send.get("webhook_env", "FEISHU_BOT_WEBHOOK"))
        secret_env = send.get("secret_env")
        if secret_env:
            checks["send"]["secret"] = safe_env_presence(secret_env)
        checks["send"]["test_webhook"] = safe_env_presence(
            send.get("test_webhook_env", "FEISHU_TEST_BOT_WEBHOOK")
        )
        test_secret_env = send.get("test_secret_env")
        if test_secret_env:
            checks["send"]["test_secret"] = safe_env_presence(test_secret_env)
    elif mode == "command":
        argv = send.get("command", [])
        checks["send"]["command_configured"] = bool(argv)
        checks["send"]["executable_found"] = bool(shutil.which(argv[0])) if argv else False
    else:
        checks["send"]["ok"] = False
        checks["send"]["reason"] = f"unsupported send mode: {mode}"

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    any_failed = False
    for tool in checks["tools"]:
        any_failed = any_failed or not tool["ok"]
    any_failed = any_failed or not checks["gh_auth_status"]["ok"]
    any_failed = any_failed or any(not item["ok"] for item in checks["github"])
    return 1 if any_failed else 0


def repo_path(env: dict[str, str], repo: dict[str, Any]) -> Path:
    return Path(env["INFO_LIBRARY_ROOT"]) / "raw" / "github" / repo["name"]


def git_dirty(path: Path) -> bool:
    result = run_cmd(["git", "status", "--porcelain"], cwd=path)
    return bool(result.stdout.strip())


def sync_github(config: dict[str, Any], env: dict[str, str]) -> list[dict[str, Any]]:
    outputs = []
    for repo in config.get("github", {}).get("repos", []):
        name = repo.get("name")
        url = repo.get("url")
        branch = repo.get("branch", "main")
        problem = repo_config_problem(repo)
        if problem:
            outputs.append({"name": name, "ok": False, "reason": problem})
            continue
        dest = repo_path(env, repo)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not (dest / ".git").exists():
            result = run_cmd(["git", "clone", "--branch", branch, url, str(dest)], timeout=1800)
            outputs.append(
                {
                    "name": name,
                    "action": "clone",
                    "ok": result.returncode == 0,
                    "stderr_tail": tail(result.stderr),
                }
            )
            continue
        fetch = run_cmd(["git", "fetch", "origin", "--prune"], cwd=dest, timeout=600)
        entry = {"name": name, "action": "fetch", "ok": fetch.returncode == 0, "stderr_tail": tail(fetch.stderr)}
        if fetch.returncode == 0 and not git_dirty(dest):
            merge = run_cmd(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=dest, timeout=600)
            entry.update({"merge_ok": merge.returncode == 0, "merge_stderr_tail": tail(merge.stderr)})
        elif fetch.returncode == 0:
            entry.update({"merge_ok": False, "merge_skipped": "local repo dirty"})
        outputs.append(entry)
    return outputs


def sync_feishu(config: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = []
    for item in config.get("feishu", {}).get("sync_commands", []):
        label = item.get("label", "feishu-sync")
        argv = item.get("argv") or []
        cwd = item.get("cwd")
        timeout = int(item.get("timeout_seconds", 1800))
        if not argv:
            outputs.append({"label": label, "ok": False, "reason": "empty argv"})
            continue
        result = run_cmd(argv, cwd=cwd, timeout=timeout)
        outputs.append(
            {
                "label": label,
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "stdout_tail": tail(result.stdout),
                "stderr_tail": tail(result.stderr),
            }
        )
    return outputs


def command_sync(args: argparse.Namespace) -> int:
    config, env = load_config(Path(args.config).expanduser())
    ensure_layout(env)
    result = {
        "ok": True,
        "github": sync_github(config, env),
        "feishu": sync_feishu(config),
    }
    result["ok"] = all(item.get("ok") for item in result["github"]) and all(
        item.get("ok") for item in result["feishu"]
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def report_window(config: dict[str, Any], start: str | None, end: str | None) -> tuple[dt.datetime, dt.datetime]:
    tz = tzinfo(config.get("timezone", "Asia/Shanghai"))
    if start and end:
        s_date = dt.date.fromisoformat(start)
        e_date = dt.date.fromisoformat(end)
    else:
        today = dt.datetime.now(tz).date()
        mode = config.get("report_window", {}).get("mode", "yesterday")
        if mode == "today":
            s_date = e_date = today
        else:
            s_date = e_date = today - dt.timedelta(days=1)
    return (
        dt.datetime.combine(s_date, dt.time.min, tzinfo=tz),
        dt.datetime.combine(e_date, dt.time.max.replace(microsecond=0), tzinfo=tz),
    )


def git_hashes(repo: Path, start: dt.datetime, end: dt.datetime) -> list[str]:
    result = run_cmd(
        [
            "git",
            "log",
            f"--since={start.isoformat()}",
            f"--until={end.isoformat()}",
            "--format=%H",
            "--reverse",
        ],
        cwd=repo,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def show_commit(repo: Path, commit_hash: str, tz: dt.tzinfo) -> dict[str, Any]:
    meta = run_cmd(
        ["git", "show", "-s", "--format=%H%x1f%ct%x1f%an%x1f%s", commit_hash],
        cwd=repo,
    ).stdout.strip().split("\x1f")
    paths = run_cmd(
        ["git", "-c", "core.quotePath=false", "show", "--name-status", "--format=", commit_hash],
        cwd=repo,
    ).stdout.splitlines()
    files = []
    for line in paths:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[-1]})
    timestamp = int(meta[1]) if len(meta) > 1 else 0
    return {
        "hash": meta[0],
        "time": dt.datetime.fromtimestamp(timestamp, tz).isoformat(),
        "author": meta[2] if len(meta) > 2 else "",
        "subject": meta[3] if len(meta) > 3 else "",
        "files": files,
    }


TASK_ID_RE = re.compile(r"\b[A-Z]{2,10}-\d+\b")


def parse_frontmatter_or_fields(path: Path) -> dict[str, str]:
    info = {"title": "", "assignee": "", "status": "", "priority": "", "updated": ""}
    if not path.exists():
        return info
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:120]:
            stripped = line.strip()
            if stripped == "---":
                break
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip().lower()
                if key in info:
                    info[key] = value.strip().strip("'\"")
    for line in lines[:150]:
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.startswith("# ") and not info["title"]:
            info["title"] = stripped[2:].strip()
        for key in ["assignee", "status", "priority", "updated"]:
            if lower.startswith(key + ":") and not info[key]:
                info[key] = stripped.split(":", 1)[1].strip().strip("'\"")
    if not info["title"]:
        for line in lines[:60]:
            stripped = line.strip()
            if stripped and stripped != "---" and not re.match(r"^[A-Za-z_ -]+:", stripped):
                info["title"] = stripped.lstrip("#").strip()
                break
    return info


def find_task_card(repo: Path, task_id: str) -> Path | None:
    candidates = []
    for path in repo.glob(f"**/{task_id}_*.md"):
        candidates.append(path)
    for path in repo.glob(f"**/spec-{task_id.lower()}*.md"):
        candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: ("spec-" in p.name, len(str(p))))
    return candidates[0]


def analyze_github(config: dict[str, Any], env: dict[str, str], start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    repos_out = []
    total_commits = 0
    tasks: dict[str, dict[str, Any]] = {}
    for repo_cfg in config.get("github", {}).get("repos", []):
        path = repo_path(env, repo_cfg)
        if not (path / ".git").exists():
            repos_out.append({"name": repo_cfg.get("name"), "exists": False, "commits": []})
            continue
        hashes = git_hashes(path, start, end)
        commits = [show_commit(path, h, start.tzinfo or dt.timezone.utc) for h in hashes]
        total_commits += len(commits)
        for commit in commits:
            ids = set(TASK_ID_RE.findall(commit["subject"]))
            for file in commit["files"]:
                ids.update(TASK_ID_RE.findall(file["path"]))
            for task_id in ids:
                task = tasks.setdefault(
                    task_id,
                    {
                        "task_id": task_id,
                        "commit_count": 0,
                        "subjects": [],
                        "commit_authors": set(),
                        "files": set(),
                    },
                )
                task["commit_count"] += 1
                task["subjects"].append(commit["subject"])
                task["commit_authors"].add(commit["author"])
                for file in commit["files"]:
                    task["files"].add(file["path"])
        repos_out.append({"name": repo_cfg.get("name"), "path": str(path), "exists": True, "commits": commits})

        for task_id, task in tasks.items():
            if "card_loaded" in task:
                continue
            card = find_task_card(path, task_id)
            info = parse_frontmatter_or_fields(card) if card else {}
            task.update(
                {
                    "card_loaded": True,
                    "path": str(card.relative_to(path)) if card else "",
                    "title": info.get("title", ""),
                    "assignee": info.get("assignee", ""),
                    "status": info.get("status", ""),
                    "priority": info.get("priority", ""),
                    "updated": info.get("updated", ""),
                }
            )

    normalized_tasks = []
    for task in tasks.values():
        task["commit_authors"] = sorted(task["commit_authors"])
        task["files"] = sorted(task["files"])
        task["subjects"] = task["subjects"][:8]
        normalized_tasks.append(task)
    normalized_tasks.sort(key=lambda x: x["task_id"])
    return {"total_commits": total_commits, "repos": repos_out, "tasks": normalized_tasks}


def feishu_doc_items(state: dict[str, Any], label: str, start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    out = []
    for wiki_id, docs in state.get("wikis", {}).items():
        if not isinstance(docs, dict):
            continue
        for _, doc in docs.items():
            if not isinstance(doc, dict):
                continue
            raw_ts = doc.get("latest_modify_time") or doc.get("obj_edit_time")
            if not raw_ts:
                continue
            try:
                timestamp = int(raw_ts)
            except Exception:
                continue
            changed_at = dt.datetime.fromtimestamp(timestamp, start.tzinfo or dt.timezone.utc)
            if start <= changed_at <= end:
                out.append(
                    {
                        "source": label,
                        "wiki_id": wiki_id,
                        "title": doc.get("title", ""),
                        "time": changed_at.isoformat(),
                        "user": doc.get("latest_modify_user") or "",
                        "path": doc.get("path") or "",
                    }
                )
    return out


def analyze_feishu(config: dict[str, Any], start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    items = []
    state_files = []
    for item in config.get("feishu", {}).get("state_files", []):
        label = item.get("label", "feishu")
        path = Path(item.get("path", "")).expanduser()
        entry = {"label": label, "path": str(path), "exists": path.exists(), "items": 0}
        if path.exists():
            try:
                state = load_json(path)
                found = feishu_doc_items(state, label, start, end)
                items.extend(found)
                entry["items"] = len(found)
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
        state_files.append(entry)
    items.sort(key=lambda x: x["time"])
    return {"total_changes": len(items), "state_files": state_files, "items": items}


def task_sort_key(task: dict[str, Any]) -> tuple[int, str]:
    status_order = {"done": 0, "review": 1, "in-progress": 2, "todo": 3}
    return (status_order.get(task.get("status", ""), 9), task["task_id"])


def build_report(config: dict[str, Any], env: dict[str, str], start: dt.datetime, end: dt.datetime) -> tuple[str, dict[str, Any]]:
    github = analyze_github(config, env, start, end)
    feishu = analyze_feishu(config, start, end)
    tasks_by_person: dict[str, list[dict[str, Any]]] = {}
    for task in github["tasks"]:
        person = task.get("assignee") or "未标明负责人"
        tasks_by_person.setdefault(person, []).append(task)

    lines = [
        f"团队工作更新摘要（{start.date().isoformat()} 至 {end.date().isoformat()}）",
        "",
        "一、总体情况",
        f"- GitHub 仓库提交数：{github['total_commits']}",
        f"- Feishu/Wiki 源文档变更数：{feishu['total_changes']}",
        "- 统计口径：GitHub 按 commit 时间过滤；Feishu/Wiki 按 latest_modify_time 优先、obj_edit_time 兜底过滤。",
        "",
        "二、按人汇总：谁做了什么",
    ]

    if not tasks_by_person:
        lines.append("- 本时间窗口内未检测到带任务编号的 GitHub 变更。")
    for person in sorted(tasks_by_person):
        lines.append("")
        lines.append(f"{person}")
        for task in sorted(tasks_by_person[person], key=task_sort_key):
            title = task.get("title") or task["task_id"]
            status = task.get("status") or "未标明状态"
            priority = task.get("priority") or "未标明优先级"
            action = "; ".join(dict.fromkeys(task.get("subjects", [])[:3]))
            lines.append(f"- {task['task_id']}：{title}，状态 {status}，优先级 {priority}。{action}")

    lines.extend(["", "三、GitHub / 本地仓库变更"])
    for repo in github["repos"]:
        if not repo.get("exists"):
            lines.append(f"- {repo.get('name')}：本地镜像不存在。")
            continue
        lines.append(f"- {repo.get('name')}：{len(repo.get('commits', []))} 个提交。")

    review_or_active = [
        task
        for task in github["tasks"]
        if task.get("status") in {"review", "in-progress", "todo"} or task.get("priority") == "high"
    ][:10]
    if review_or_active:
        lines.append("")
        lines.append("需要继续关注：")
        for task in review_or_active:
            lines.append(
                f"- {task['task_id']}：{task.get('title') or task['task_id']}，"
                f"状态 {task.get('status') or '未标明'}，负责人 {task.get('assignee') or '未标明'}。"
            )

    lines.extend(["", "四、Feishu/Wiki 变更"])
    if not feishu["items"]:
        lines.append("本时间窗口内未检测到 Feishu/Wiki 源文档新增或修改。")
    else:
        by_source: dict[str, list[dict[str, Any]]] = {}
        for item in feishu["items"]:
            by_source.setdefault(item["source"], []).append(item)
        for source, items in sorted(by_source.items()):
            lines.append(f"{source}：{len(items)} 篇")
            for item in items[:20]:
                who = f"，修改人 {item['user']}" if item.get("user") else ""
                lines.append(f"- {item['time'][:16]}：{item['title']}{who}")
            if len(items) > 20:
                lines.append(f"- 另有 {len(items) - 20} 篇未展开。")

    lines.extend(["", "五、下一步建议"])
    next_items = review_or_active[:5]
    if next_items:
        for task in next_items:
            lines.append(f"- 确认 {task['task_id']}（{task.get('title') or task['task_id']}）的下一步处理。")
    else:
        lines.append("- 暂无需要从任务状态中自动识别出的重点跟进项。")

    data = {
        "generated_at": dt.datetime.now(start.tzinfo).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "github": github,
        "feishu": feishu,
    }
    return "\n".join(lines).strip() + "\n", data


def command_report(args: argparse.Namespace) -> int:
    config, env = load_config(Path(args.config).expanduser())
    ensure_layout(env)
    start, end = report_window(config, args.start, args.end)
    text, data = build_report(config, env, start, end)
    output = Path(args.output).expanduser() if args.output else Path(env["REVIEW_QUEUE_DIR"]) / (
        f"{start.date().isoformat()}_{end.date().isoformat()}-team-update-summary.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    json_path = output.with_suffix(".json")
    dump_json(json_path, data)
    print(json.dumps({"ok": True, "report": str(output), "data": str(json_path)}, ensure_ascii=False, indent=2))
    return 0


def feishu_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_webhook(send_cfg: dict[str, Any], message: str, target: str = "prod") -> dict[str, Any]:
    if target == "test":
        webhook_env = send_cfg.get("test_webhook_env") or send_cfg.get("webhook_env", "FEISHU_BOT_WEBHOOK")
        secret_env = send_cfg.get("test_secret_env") or send_cfg.get("secret_env")
    else:
        webhook_env = send_cfg.get("webhook_env", "FEISHU_BOT_WEBHOOK")
        secret_env = send_cfg.get("secret_env")
    webhook = os.environ.get(webhook_env)
    if not webhook:
        return {"ok": False, "reason": f"{webhook_env} not set"}
    body: dict[str, Any] = {"msg_type": "text", "content": {"text": message}}
    if secret_env and os.environ.get(secret_env):
        timestamp = str(int(time.time()))
        body["timestamp"] = timestamp
        body["sign"] = feishu_sign(os.environ[secret_env], timestamp)
    request = urllib.request.Request(
        webhook,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    try:
        data = json.loads(payload)
    except Exception:
        data = {"raw": payload[:500]}
    return {"ok": data.get("code", 0) == 0 or data.get("StatusCode") == 0, "target": target, "response": data}


def send_command(send_cfg: dict[str, Any], message: str, target: str = "prod") -> dict[str, Any]:
    argv = send_cfg.get("test_command" if target == "test" else "command") or send_cfg.get("command") or []
    if not argv:
        return {"ok": False, "reason": "send.command is empty"}
    expanded = [arg.replace("{message}", message) for arg in argv]
    if "{message}" not in " ".join(argv):
        expanded.append(message)
    result = run_cmd(expanded, timeout=int(send_cfg.get("timeout_seconds", 60)))
    return {
        "ok": result.returncode == 0,
        "target": target,
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout, 500),
        "stderr_tail": tail(result.stderr, 500),
    }


def send_message(config: dict[str, Any], message: str, target: str = "prod") -> dict[str, Any]:
    send_cfg = config.get("send", {})
    mode = send_cfg.get("mode", "webhook")
    if mode == "webhook":
        return send_webhook(send_cfg, message, target=target)
    if mode == "command":
        return send_command(send_cfg, message, target=target)
    return {"ok": False, "reason": f"unsupported send mode: {mode}"}


def command_send(args: argparse.Namespace) -> int:
    config, _ = load_config(Path(args.config).expanduser())
    message = Path(args.message_file).expanduser().read_text(encoding="utf-8")
    result = send_message(config, message, target=args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def command_run(args: argparse.Namespace) -> int:
    config, env = load_config(Path(args.config).expanduser())
    ensure_layout(env)
    sync_result = {"github": sync_github(config, env), "feishu": sync_feishu(config)}
    sync_ok = all(item.get("ok") for item in sync_result["github"]) and all(
        item.get("ok") for item in sync_result["feishu"]
    )
    start, end = report_window(config, args.start, args.end)
    report_text, data = build_report(config, env, start, end)
    draft = Path(env["REVIEW_QUEUE_DIR"]) / f"{start.date().isoformat()}_{end.date().isoformat()}-team-update-summary.md"
    draft.write_text(report_text, encoding="utf-8")
    dump_json(draft.with_suffix(".json"), {"sync": sync_result, "report": data})
    result: dict[str, Any] = {
        "ok": sync_ok,
        "sync": sync_result,
        "draft": str(draft),
        "sent": False,
    }
    if sync_ok and args.send:
        send_result = send_message(config, report_text, target=args.target)
        result["send_result"] = send_result
        result["sent"] = bool(send_result.get("ok"))
        result["ok"] = bool(send_result.get("ok"))
    state_dir = Path(env["ACP_HOME"]) / "state" / "tasks" / "team_update_report"
    dump_json(
        state_dir / f"{start.date().isoformat()}_{end.date().isoformat()}-last_run.json",
        result,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def command_workbuddy_prompt(args: argparse.Namespace) -> int:
    config, env = load_config(Path(args.config).expanduser())
    ensure_layout(env)
    script = Path(env["ACP_HOME"]) / "team_sync_reporter.py"
    config_path = Path(args.config).expanduser()
    message_prompt = config.get("report", {}).get(
        "message_prompt_path", str(Path(env["TEAMSPACE_CONFIG_DIR"]) / "feishu-message-prompt.md")
    )
    text = f"""你是这台电脑上的团队日报自动化执行员。每天运行一次团队同步日报。

边界：
- 只在 {env['TEAMSPACE_ROOT']} 下操作。
- 不打印 token、secret、webhook、cookie、password、chat id、.env 内容。
- 不执行 git push，不删除源数据。
- GitHub 变更和 Feishu/Wiki 源系统变更必须分开统计。
- “谁做了什么”优先使用任务卡 assignee 字段，commit author 只作为同步来源参考。
- 仓库名称和仓库地址只读取 {config_path}，不要猜默认仓库。

执行：
1. 运行同步和原始报告生成，不直接发送：
   python3 "{script}" run --config "{config_path}"
2. 从命令输出中找到 draft 路径；读取该原始草稿和消息生成 prompt：
   {message_prompt}
3. 按消息生成 prompt 改写成最终飞书消息，保存到 review-queue，文件名以 final-feishu-message.md 结尾。
4. 如果这是格式调试阶段，只返回最终消息和文件路径，不发送。
5. 如果用户已经确认“发送测试飞书消息”，运行：
   python3 "{script}" send --config "{config_path}" --target test --message-file <最终消息文件>
6. 只有测试飞书消息发送成功且用户确认效果满意后，才把 WorkBuddy 自动化改成每日自动运行并发送正式群。
"""
    output = Path(args.output).expanduser() if args.output else Path(env["ACP_HOME"]) / "workbuddy-daily-prompt.md"
    output.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "prompt": str(output)}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TeamSpace GitHub + Feishu daily sync reporter.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create TeamSpace layout and copy this script.")
    p_init.add_argument("--root", default="~/Documents/TeamSpace")
    p_init.add_argument("--repo-name", help="Local mirror name for the primary GitHub repository.")
    p_init.add_argument("--repo-url", help="GitHub clone URL for the primary repository.")
    p_init.set_defaults(func=command_init)

    p_doctor = sub.add_parser("doctor", help="Check tools, GitHub access, Feishu config, and send config.")
    p_doctor.add_argument("--config", required=True)
    p_doctor.set_defaults(func=command_doctor)

    p_sync = sub.add_parser("sync", help="Sync GitHub mirrors and configured Feishu export commands.")
    p_sync.add_argument("--config", required=True)
    p_sync.set_defaults(func=command_sync)

    p_report = sub.add_parser("report", help="Generate a report draft without syncing or sending.")
    p_report.add_argument("--config", required=True)
    p_report.add_argument("--start")
    p_report.add_argument("--end")
    p_report.add_argument("--output")
    p_report.set_defaults(func=command_report)

    p_send = sub.add_parser("send", help="Send a prepared report file.")
    p_send.add_argument("--config", required=True)
    p_send.add_argument("--message-file", required=True)
    p_send.add_argument("--target", choices=["test", "prod"], default="prod")
    p_send.set_defaults(func=command_send)

    p_run = sub.add_parser("run", help="Sync, generate report, and optionally send.")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--start")
    p_run.add_argument("--end")
    p_run.add_argument("--send", action="store_true")
    p_run.add_argument("--target", choices=["test", "prod"], default="prod")
    p_run.set_defaults(func=command_run)

    p_prompt = sub.add_parser("workbuddy-prompt", help="Generate a WorkBuddy daily automation prompt.")
    p_prompt.add_argument("--config", required=True)
    p_prompt.add_argument("--output")
    p_prompt.set_defaults(func=command_workbuddy_prompt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.TimeoutExpired as exc:
        print(json.dumps({"ok": False, "error": "timeout", "cmd": exc.cmd}, ensure_ascii=False))
        return 124
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

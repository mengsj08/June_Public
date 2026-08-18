#!/usr/bin/env python3
"""Thin CLI for real-project intake."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
from contextlib import nullcontext
from pathlib import Path

import attention_gate
import real_projects


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]


def _deps():
    scan_docs = _load_scan_docs()
    config = scan_docs.load_config()
    return {
        "repo_root": REPO_ROOT,
        "runtime_root": REPO_ROOT / ".real-project-state",
        "scan_tasks": lambda: [],
        "roles": config.get("roles"),
        "owner_action_needed": attention_gate.requires_role_action,
        "write_lock": threading.Lock(),
    }


def _print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_scan_docs():
    path = HERE / "scan-docs.py"
    spec = importlib.util.spec_from_file_location("kanban_scan_docs_projectctl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _starter_card(project, args):
    scan_docs = _load_scan_docs()
    config = scan_docs.load_config()
    owner_member = scan_docs.role_policy.member_for_role(config.get('roles'), 'owner')
    title = f"{project['title']} 启动任务"
    ok, message, path = scan_docs.create_document(
        "个人调度",
        title,
        "",
        "todo",
        owner_member,
        "medium",
        workdir=args.workdir or "",
        project_ref=project["project_ref"],
    )
    return {"ok": ok, "message": message, "path": path}


def from_conversation(args):
    deps = _deps()
    owner_actor = real_projects._role_actors(deps)["owner"]
    payload = {
        "project_ref": args.ref,
        "title": args.title,
        "current_intent": args.intent,
        "confirmed_by": owner_actor,
        "origin": {
            "type": "conversation",
            "provider": args.provider,
            "thread_id": args.thread,
            "actor": args.actor,
            "confirmed_by": owner_actor,
            "confirmation_quote": args.quote,
        },
    }
    if args.workdir:
        payload["workdir"] = args.workdir
    if args.dry_run:
        _print_json({"ok": True, "dry_run": True, "payload": payload})
        return 0
    result, status = real_projects.register_project(deps, payload, actor=args.actor)
    if args.starter_card and status in (200, 201) and result.get("ok"):
        result["starter_card"] = _starter_card(result["project"], args)
    _print_json({**result, "status": status})
    return 0 if status < 400 else 1


def build_parser():
    parser = argparse.ArgumentParser(description="Real-project intake helper")
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("from-conversation", help="register a Owner-confirmed conversation intake")
    conv.add_argument("--provider", required=True)
    conv.add_argument("--thread", required=True)
    conv.add_argument("--actor", required=True, help="configured owner/operator/reviewer actor")
    conv.add_argument("--ref", required=True)
    conv.add_argument("--title", required=True)
    conv.add_argument("--intent", required=True)
    conv.add_argument("--quote", required=True)
    conv.add_argument("--workdir", default="")
    conv.add_argument("--dry-run", action="store_true")
    conv.add_argument("--starter-card", action="store_true")
    conv.set_defaults(func=from_conversation)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Finalize route outputs for a meeting case.

This script is the case-level completion adapter between analysis routes and
Feishu return. It does not generate meeting conclusions. It gathers the files
declared by the selected route, copies them into canonical case directories,
writes analysis/route_done.json, and optionally builds/sends the Feishu return
package through return_to_feishu.py.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import filecmp
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from _safety import has_secret_content, is_secret_file, scrub
from provenance_gate import ensure_transcript_available


SCRIPT_DIR = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".md", ".html", ".json", ".txt", ".yaml", ".yml"}
MAX_TEXT_SCAN_BYTES = 2_000_000
EXCLUDED_ROUTE_OUTPUT_NAMES = {
    "agent_handoff.md",
    "collaboration_analysis.md",
    "customer_material.md",
    "route_decision.json",
    "route_done.json",
    "feishu_return_message.md",
    "feishu_return_manifest.json",
    "internal_brief.md",
    "source_paths_for_feishu.md",
}


@dataclass(frozen=True)
class FinalizedOutput:
    source: Path
    canonical: Path
    kind: str
    copied: bool


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_case_dir(raw: str) -> Path:
    case_dir = Path(raw).expanduser().resolve()
    if is_secret_file(case_dir):
        raise SystemExit(f"Refusing secret-like case path: {case_dir}")
    if not case_dir.is_dir():
        raise SystemExit(f"Case directory not found: {case_dir}")
    return case_dir


def rel(path: Path, case_dir: Path) -> str:
    try:
        return path.resolve().relative_to(case_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def read_case_yaml_output_paths(case_dir: Path) -> list[str]:
    path = case_dir / "case.yaml"
    if not path.exists():
        return []
    outputs: list[str] = []
    in_outputs = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not in_outputs:
            if stripped.startswith("output_paths:"):
                remainder = stripped.split(":", 1)[1].strip()
                if remainder and remainder != "[]":
                    if remainder.startswith("[") and remainder.endswith("]"):
                        for item in remainder[1:-1].split(","):
                            cleaned = unquote_yaml_scalar(item)
                            if cleaned:
                                outputs.append(cleaned)
                    else:
                        cleaned = unquote_yaml_scalar(remainder)
                        if cleaned:
                            outputs.append(cleaned)
                in_outputs = True
            continue
        if not line.startswith((" ", "\t")):
            break
        if stripped.startswith("- "):
            cleaned = unquote_yaml_scalar(stripped[2:])
            if cleaned:
                outputs.append(cleaned)
    return outputs


def read_existing_route_done(case_dir: Path) -> dict[str, Any]:
    payload = read_json(case_dir / "analysis" / "route_done.json", {})
    return payload if isinstance(payload, dict) else {}


def route_from_case(case_dir: Path, explicit: str) -> str:
    if explicit:
        return explicit
    route_done = read_existing_route_done(case_dir)
    if isinstance(route_done.get("route"), str) and route_done["route"]:
        return str(route_done["route"])
    decision = read_json(case_dir / "analysis" / "route_decision.json", {})
    if isinstance(decision, dict) and isinstance(decision.get("route"), str):
        return str(decision["route"])
    case_json = read_json(case_dir / "case.json", {})
    route_decision = case_json.get("route_decision") if isinstance(case_json, dict) else {}
    if isinstance(route_decision, dict) and isinstance(route_decision.get("route"), str):
        return str(route_decision["route"])
    return "unknown"


def text_has_secret(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    return has_secret_content(text)


def safe_output(path: Path) -> bool:
    return path.is_file() and not is_secret_file(path) and not text_has_secret(path)


def route_output_candidate(path: Path, case_dir: Path) -> bool:
    if path.name in EXCLUDED_ROUTE_OUTPUT_NAMES:
        return False
    if is_inside(path, case_dir):
        rel_path = rel(path, case_dir)
        if rel_path.startswith("source/"):
            return False
    return True


def safe_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-._")
    return name or "artifact"


def output_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "html"
    if suffix == ".md":
        return "markdown"
    return suffix.lstrip(".") or "file"


def canonical_prefix(route: str) -> str:
    return {
        "crm_skill": "crm_",
        "customer_html_prompt": "visual_",
        "wow_codex": "wow_codex_",
        "wow_claude": "wow_claude_",
    }.get(route, "")


def is_canonical_output(path: Path, case_dir: Path) -> bool:
    if not is_inside(path, case_dir):
        return False
    rel_path = rel(path, case_dir)
    return (
        rel_path.startswith("html/")
        or rel_path.startswith("analysis/crm/")
        or rel_path.startswith("analysis/remote_outputs/")
        or rel_path in {
            "analysis/meeting_analysis.md",
            "analysis/context_materials.md",
            "customer_material.md",
            "collaboration_analysis.md",
            "internal_brief.md",
        }
    )


def unique_target(target: Path, source: Path) -> Path:
    if not target.exists():
        return target
    try:
        if target.is_file() and filecmp.cmp(target, source, shallow=False):
            return target
    except OSError:
        pass
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 1000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Unable to allocate a unique target for: {target}")


def target_for(source: Path, case_dir: Path, route: str) -> Path:
    if is_canonical_output(source, case_dir):
        return source.resolve()
    kind = output_kind(source)
    file_name = safe_name(source.name)
    prefix = canonical_prefix(route)
    if kind == "html":
        return unique_target(case_dir / "html" / f"{prefix}{file_name}", source)
    if kind == "markdown":
        if route in {"wow_codex", "wow_claude"}:
            return unique_target(case_dir / "analysis" / "remote_outputs" / file_name, source)
        if route == "crm_skill" or "agent_output" in source.parts:
            return unique_target(case_dir / "analysis" / "crm" / file_name, source)
        return unique_target(case_dir / "analysis" / file_name, source)
    return unique_target(case_dir / "attachments" / file_name, source)


def resolve_output(case_dir: Path, raw: str) -> Path | None:
    raw = raw.strip()
    if not raw or has_secret_content(raw):
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = case_dir / raw
    candidate = candidate.resolve()
    if safe_output(candidate):
        return candidate
    return None


def collect_declared_outputs(case_dir: Path, args: argparse.Namespace) -> list[Path]:
    raw_outputs: list[str] = []
    raw_outputs.extend(args.output or [])
    if args.include_case_yaml_outputs:
        raw_outputs.extend(read_case_yaml_output_paths(case_dir))
    if args.scan_case:
        for pattern in [
            "agent_output/**/*.html",
            "agent_output/**/*.md",
            "html/**/*.html",
            "html/**/*.md",
            "analysis/meeting_analysis.md",
            "analysis/context_materials.md",
            "analysis/remote_outputs/**/*.md",
            "analysis/crm/**/*.md",
        ]:
            raw_outputs.extend(rel(path, case_dir) for path in sorted(case_dir.glob(pattern)))
    if not raw_outputs:
        existing = read_existing_route_done(case_dir)
        for item in existing.get("outputs", []) if isinstance(existing.get("outputs"), list) else []:
            if isinstance(item, str):
                raw_outputs.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                raw_outputs.append(str(item["path"]))

    resolved: dict[str, Path] = {}
    for raw in raw_outputs:
        path = resolve_output(case_dir, raw)
        if path and route_output_candidate(path, case_dir):
            resolved.setdefault(str(path), path)
    return list(resolved.values())


def copy_outputs(case_dir: Path, route: str, outputs: list[Path]) -> list[FinalizedOutput]:
    finalized: list[FinalizedOutput] = []
    seen_targets: set[str] = set()
    for source in outputs:
        target = target_for(source, case_dir, route)
        target_key = str(target.resolve())
        if target_key in seen_targets:
            continue
        copied = False
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_file() and filecmp.cmp(target, source, shallow=False):
                copied = False
            else:
                shutil.copy2(source, target)
                copied = True
        finalized.append(FinalizedOutput(source.resolve(), target.resolve(), output_kind(target), copied))
        seen_targets.add(target_key)
    return finalized


def review_required(args: argparse.Namespace, route: str, finalized: list[FinalizedOutput]) -> bool:
    if args.approve:
        return False
    if args.needs_review:
        return True
    if route in {"crm_skill", "customer_html_prompt"}:
        return True
    return any(item.kind == "html" and "customer" in rel(item.canonical, Path(args.case_dir)).lower() for item in finalized)


def update_case_json(case_dir: Path, status: str, route_done_rel: str, return_manifest: str) -> None:
    case_json_path = case_dir / "case.json"
    meta = read_json(case_json_path, {})
    if not isinstance(meta, dict):
        meta = {}
    paths = meta.get("paths") if isinstance(meta.get("paths"), dict) else {}
    paths["route_done"] = route_done_rel
    if return_manifest:
        paths["feishu_return_manifest"] = return_manifest
    else:
        paths.pop("feishu_return_manifest", None)
    meta.update(
        {
            "updated_at": now_iso(),
            "analysis_status": status,
            "analysis_stage": "meeting/route_done" if status == "ready_for_review" else "meeting/return_package",
            "paths": paths,
        }
    )
    write_json(case_json_path, meta)


def run_return_to_feishu(case_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    argv = [
        sys.executable,
        str(SCRIPT_DIR / "return_to_feishu.py"),
        "--case-dir",
        str(case_dir),
    ]
    passthrough = [
        ("--profile", args.profile),
        ("--targets-config", args.targets_config),
        ("--as", args.identity),
        ("--message-id", args.message_id),
        ("--chat-id", args.chat_id),
        ("--doc", args.doc),
        ("--folder-token", args.folder_token),
        ("--wiki-token", args.wiki_token),
    ]
    for flag, value in passthrough:
        if value:
            argv.extend([flag, value])
    if args.allow_profile_override:
        argv.append("--allow-profile-override")
    if args.skip_target_validation:
        argv.append("--skip-target-validation")
    if args.include_source_transcript:
        argv.append("--include-source-transcript")
    if args.allow_multi_artifact_upload:
        argv.append("--allow-multi-artifact-upload")
    if args.send:
        argv.append("--send")
    if args.dry_run:
        argv.append("--dry-run")
    if args.reply_in_thread:
        argv.append("--reply-in-thread")
    run = subprocess.run(argv, cwd=str(case_dir), capture_output=True, text=True)
    payload: dict[str, Any] = {
        "ok": run.returncode == 0,
        "returncode": run.returncode,
        "stdout_tail": scrub((run.stdout or "")[-2000:]),
        "stderr_tail": scrub((run.stderr or "")[-2000:]),
    }
    try:
        payload["manifest"] = json.loads(run.stdout)
    except json.JSONDecodeError:
        payload["manifest"] = {}
    return payload


def finalize_case(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = ensure_case_dir(args.case_dir)
    ensure_transcript_available(case_dir, "finalize route outputs")
    route = route_from_case(case_dir, args.route)
    outputs = collect_declared_outputs(case_dir, args)
    if not outputs:
        route_done_path = case_dir / "analysis" / "route_done.json"
        payload = {
            "updated_at": now_iso(),
            "case_dir": str(case_dir),
            "route": route,
            "status": "missing_outputs",
            "outputs": [],
            "canonical_outputs": [],
            "needs_review": bool(args.needs_review),
            "review_approved": bool(args.approve),
            "next_action": "Ask the route Agent to declare output files, or pass --output for each finished artifact.",
        }
        write_json(route_done_path, payload)
        update_case_json(case_dir, "missing_outputs", rel(route_done_path, case_dir), "")
        return {"ok": False, **payload}

    finalized = copy_outputs(case_dir, route, outputs)
    needs_review = review_required(args, route, finalized)
    return_result: dict[str, Any] = {}
    status = "ready_for_review" if needs_review else "return_package_created"
    if not needs_review and not args.no_return:
        return_result = run_return_to_feishu(case_dir, args)
        if args.send and return_result.get("ok"):
            status = "return_dry_run_ok" if args.dry_run else "returned_to_feishu"
        elif not return_result.get("ok"):
            status = "return_failed"

    canonical_outputs = [
        {
            "source": rel(item.source, case_dir),
            "path": rel(item.canonical, case_dir),
            "kind": item.kind,
            "copied": item.copied,
        }
        for item in finalized
    ]
    route_done_path = case_dir / "analysis" / "route_done.json"
    return_manifest = (
        "analysis/feishu_return_manifest.json"
        if return_result and (case_dir / "analysis" / "feishu_return_manifest.json").exists()
        else ""
    )
    next_action = (
        "Ask the user to confirm: 确认，收尾归档并回传飞书. Then rerun finalize_route.py with --approve."
        if needs_review
        else "Review the Feishu return manifest, or pass --send when ready to send/upload."
    )
    payload = {
        "updated_at": now_iso(),
        "case_dir": str(case_dir),
        "route": route,
        "status": status,
        "outputs": [rel(item.source, case_dir) for item in finalized],
        "canonical_outputs": canonical_outputs,
        "needs_review": bool(needs_review),
        "review_approved": bool(args.approve),
        "return_manifest": return_manifest,
        "return_result": return_result,
        "next_action": next_action,
    }
    write_json(route_done_path, payload)
    update_case_json(case_dir, status, rel(route_done_path, case_dir), return_manifest)
    return {"ok": status not in {"missing_outputs", "return_failed"}, **payload}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a meeting route and build the Feishu return package.")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--route", default="", help="Route key, such as agent_default, crm_skill, wow_codex, wow_claude, or customer_html_prompt.")
    parser.add_argument("--output", action="append", default=[], help="Finished route output path. Repeat for multiple artifacts.")
    parser.add_argument("--no-case-yaml-outputs", dest="include_case_yaml_outputs", action="store_false", help="Do not read case.yaml output_paths.")
    parser.set_defaults(include_case_yaml_outputs=True)
    parser.add_argument("--scan-case", action="store_true", help="Also scan html/, analysis/, and agent_output/ for finished outputs.")
    parser.add_argument("--needs-review", action="store_true", help="Mark outputs ready for user review before Feishu return.")
    parser.add_argument("--approve", action="store_true", help="User has approved reviewed outputs; build/send the return package.")
    parser.add_argument("--no-return", action="store_true", help="Only normalize outputs and write route_done.json.")
    parser.add_argument("--profile", default="")
    parser.add_argument("--targets-config", default="")
    parser.add_argument("--allow-profile-override", action="store_true")
    parser.add_argument("--skip-target-validation", action="store_true")
    parser.add_argument("--as", dest="identity", choices=["bot", "user"], default="bot")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--doc", default="", help="Existing Feishu doc URL/token to append the single meeting archive draft to.")
    parser.add_argument("--folder-token", default="", help="Drive folder token used as the parent for one created archive document.")
    parser.add_argument("--wiki-token", default="", help="Wiki node token used as the parent for one created archive document.")
    parser.add_argument("--include-source-transcript", action="store_true")
    parser.add_argument("--allow-multi-artifact-upload", action="store_true", help="Legacy escape hatch: let return_to_feishu.py send/upload every artifact separately.")
    parser.add_argument("--send", action="store_true", help="Pass --send to return_to_feishu.py.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reply-in-thread", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = finalize_case(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

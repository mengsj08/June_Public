#!/usr/bin/env python3
"""Return a meeting case's final artifacts to Feishu/Lark.

This script is delivery-only. It never generates meeting conclusions. It scans
an existing case directory for reviewed Markdown/HTML outputs, writes a return
manifest, and optionally sends/uploads the files through lark-cli.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from _safety import has_secret_content, is_secret_file, scrub
from provenance_gate import ensure_transcript_available


MAX_TEXT_SCAN_BYTES = 2_000_000
TEXT_SUFFIXES = {".md", ".html", ".json", ".txt", ".yaml", ".yml"}
SINGLE_DOCUMENT_INLINE_LIMIT_BYTES = 350_000
SINGLE_DOCUMENT_MAX_CHARS = 240_000
LARK_CLI_ENV = "LARK_CLI"
LARK_CLI_CANDIDATES = [
    "lark-cli",
    "/usr/local/bin/lark-cli",
    "/opt/homebrew/bin/lark-cli",
    "~/.local/bin/lark-cli",
]
AUDIENCE_SCAN_BYTES = 80_000
CUSTOMER_AUDIENCE_ROUTES = {"crm_skill", "customer_html_prompt"}
CUSTOMER_MEETING_TYPES = {"presales", "customer_collaboration", "customer", "client"}
INTERNAL_MEETING_TYPES = {"internal", "team", "ops"}
PARTNER_MEETING_TYPES = {"partner"}
CUSTOMER_AUDIENCE_TERMS = [
    ("客户", 3),
    ("客户会议", 4),
    ("客户拜访", 5),
    ("客户名称", 4),
    ("客户展示", 4),
    ("售前", 4),
    ("面访", 3),
    ("需求", 2),
    ("报价", 3),
    ("预算", 3),
    ("采购", 3),
    ("合同", 3),
    ("成交", 3),
    ("演示", 2),
    ("甲方", 3),
    ("乙方", 2),
    ("对方", 1),
    ("老板", 2),
    ("企业", 1),
    ("合作", 2),
    ("痛点", 3),
    ("交付", 2),
    ("crm", 4),
    ("presales", 4),
    ("customer", 3),
    ("client", 3),
]
PARTNER_AUDIENCE_TERMS = [
    ("合作方", 5),
    ("合作伙伴", 5),
    ("战略伙伴", 5),
    ("生态合作", 4),
    ("渠道合作", 4),
    ("技术合作", 4),
    ("学校合作", 4),
    ("联合开发", 4),
    ("战略合作", 4),
    ("合作会议", 3),
    ("partner", 4),
]
INTERNAL_AUDIENCE_TERMS = [
    ("内部", 3),
    ("内部会议", 4),
    ("周会", 3),
    ("复盘", 2),
    ("排期", 2),
    ("研发", 2),
    ("迭代", 2),
    ("任务", 1),
    ("okr", 3),
    ("立项", 2),
    ("知识库", 2),
    ("论文", 2),
    ("实验", 2),
    ("项目管理", 2),
    ("团队", 2),
    ("治理", 2),
    ("排障", 2),
    ("sprint", 3),
    ("standup", 3),
]
AUDIENCE_ALIASES = {
    "customer": "customer",
    "client": "customer",
    "presales": "customer",
    "sales": "customer",
    "external": "customer",
    "客户": "customer",
    "客户分析": "customer",
    "客户会议": "customer",
    "售前": "customer",
    "partner": "partner",
    "合作方": "partner",
    "合作方会议": "partner",
    "合作方分析": "partner",
    "合作伙伴": "partner",
    "战略伙伴": "partner",
    "生态合作": "partner",
    "内部": "internal",
    "内部分析": "internal",
    "内部会议": "internal",
    "internal": "internal",
    "team": "internal",
    "ops": "internal",
}


@dataclass(frozen=True)
class Artifact:
    path: Path
    kind: str
    label: str


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def candidate_targets_config() -> Path | None:
    env_value = os.environ.get("MEETING_CHAIN_TARGETS_CONFIG", "").strip()
    if env_value:
        env_path = Path(env_value).expanduser()
        if env_path.exists():
            return env_path
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / "config" / "meeting_chain_targets.local.json"
        if candidate.exists():
            return candidate
    default = (
        Path.home()
        / "Documents/AI-Agent-Hub/automation-control-plane/config/meeting_chain_targets.local.json"
    )
    return default if default.exists() else None


def load_targets_config(raw_path: str) -> tuple[dict[str, Any], str]:
    path = Path(raw_path).expanduser() if raw_path else candidate_targets_config()
    if not path:
        return {}, ""
    return read_json(path, {}), str(path)


def apply_target_defaults(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    config, config_path = load_targets_config(getattr(args, "targets_config", ""))
    if not isinstance(config, dict):
        return {}, config_path
    configured_profile = str(config.get("lark_profile") or "")
    allow_profile_override = bool(getattr(args, "allow_profile_override", False))
    if args.profile and configured_profile and args.profile != configured_profile and not allow_profile_override:
        raise SystemExit(
            "Refusing to archive with a non-configured Lark profile. "
            "Use the configured meeting-chain profile or pass --allow-profile-override intentionally."
        )
    if not args.profile:
        args.profile = configured_profile
    meeting = (((config.get("wiki") or {}).get("meeting_pipeline") or {}).get("children") or {})
    args.archive_targets = build_archive_targets(config)
    return config, config_path


def build_archive_targets(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    wiki = config.get("wiki") if isinstance(config.get("wiki"), dict) else {}
    meeting_pipeline = wiki.get("meeting_pipeline") if isinstance(wiki.get("meeting_pipeline"), dict) else {}
    meeting = (meeting_pipeline.get("children") or {}) if isinstance(meeting_pipeline, dict) else {}
    roles = {
        "index": "index",
        "internal_analysis": "internal_analysis",
        "customer_analysis": "customer_analysis",
        "partner_analysis": "partner_analysis",
        "customer_html": "customer_html",
        "context_materials": "context_materials",
        "run_logs": "run_logs",
        "attachments": "attachments",
    }
    targets: dict[str, dict[str, str]] = {}
    pipeline_token = str(meeting_pipeline.get("node_token") or "")
    if pipeline_token:
        targets["single_document"] = {
            "role": "single_document",
            "title": str(meeting_pipeline.get("title") or "meeting_pipeline"),
            "node_token": pipeline_token,
            "url": str(meeting_pipeline.get("url") or ""),
        }
    for role, key in roles.items():
        node = meeting.get(key) if isinstance(meeting.get(key), dict) else {}
        token = str(node.get("node_token") or "")
        if token:
            targets[role] = {
                "role": role,
                "title": str(node.get("title") or role),
                "node_token": token,
                "url": str(node.get("url") or ""),
            }
    return targets


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_case_dir(raw: str) -> Path:
    case_dir = Path(raw).expanduser().resolve()
    if not case_dir.is_dir():
        raise SystemExit(f"Case directory not found: {case_dir}")
    if is_secret_file(case_dir):
        raise SystemExit(f"Refusing secret-like case path: {case_dir}")
    return case_dir


def rel(path: Path, case_dir: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def text_has_secret(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    return has_secret_content(text)


def safe_artifact(path: Path, case_dir: Path) -> bool:
    return (
        path.is_file()
        and is_inside(path, case_dir)
        and not is_secret_file(path)
        and not text_has_secret(path)
    )


def add_if_exists(items: list[Artifact], case_dir: Path, relative_path: str, kind: str, label: str) -> None:
    path = case_dir / relative_path
    if safe_artifact(path, case_dir):
        items.append(Artifact(path.resolve(), kind, label))


def add_glob(items: list[Artifact], case_dir: Path, pattern: str, kind: str, label_prefix: str) -> None:
    for path in sorted(case_dir.glob(pattern)):
        if safe_artifact(path, case_dir):
            label = f"{label_prefix}: {rel(path, case_dir)}"
            items.append(Artifact(path.resolve(), kind, label))


def build_source_paths_doc(case_dir: Path) -> Path:
    case_json = read_json(case_dir / "case.json", {})
    resolution = read_json(case_dir / "source" / "source_resolution.json", {})
    paths = case_json.get("paths") if isinstance(case_json.get("paths"), dict) else {}
    resolution_loaded = bool(resolution)
    source_kind = str(resolution.get("source_kind") or case_json.get("source_kind") or "UNRESOLVED")
    transcript_available = resolution.get("transcript_available", "UNRESOLVED") if resolution_loaded else "UNRESOLVED"
    reason = str(resolution.get("reason") or ("UNRESOLVED" if not resolution_loaded else ""))
    lines = [
        "# 会议链路来源与本地路径附件",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- case_dir: `{case_dir}`",
        f"- title: `{scrub(str(case_json.get('title') or case_dir.name))}`",
        f"- source_kind: `{scrub(source_kind)}`",
        f"- transcript_available: `{scrub(str(transcript_available))}`",
        f"- resolution_status: `{'resolved' if resolution_loaded else 'UNRESOLVED'}`",
        "",
        "## Case 内路径",
        "",
    ]
    if paths:
        for key, value in sorted(paths.items()):
            if value:
                lines.append(f"- {key}: `{scrub(str(value))}`")
    else:
        lines.append("- 未找到 `case.json.paths`。")
    lines.extend(["", "## 来源解析摘要", ""])
    summary_keys = [
        "source_kind",
        "input_kind",
        "transcript_title",
        "title",
        "source_ref",
        "input_ref",
        "transcript_ref",
        "ai_notes_ref",
        "transcript_url",
        "fallback_docx",
        "reason",
    ]
    if not resolution_loaded:
        lines.append("- resolution: `UNRESOLVED`")
    for key in summary_keys:
        value = resolution.get(key)
        display = str(value) if value not in (None, "") else ("UNRESOLVED" if key in {"source_kind", "reason"} and not resolution_loaded else "")
        if display:
            lines.append(f"- {key}: `{scrub(display)}`")
    if reason and reason != "UNRESOLVED":
        lines.append(f"- unavailable_reason: `{scrub(reason)}`")
    lines.extend(
        [
            "",
            "## 安全说明",
            "",
            "- 本附件用于内部追溯，不放入客户展示 HTML。",
            "- 不应包含 app secret、token、cookie、签名媒体 URL 或浏览器配置。",
            "",
        ]
    )
    target = case_dir / "analysis" / "source_paths_for_feishu.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def collect_artifacts(case_dir: Path, include_source_transcript: bool = False) -> list[Artifact]:
    items: list[Artifact] = []
    source_paths = build_source_paths_doc(case_dir)
    if safe_artifact(source_paths, case_dir):
        items.append(Artifact(source_paths.resolve(), "provenance", "来源与本地路径附件"))

    add_if_exists(items, case_dir, "analysis/meeting_analysis.md", "analysis_md", "内部会议分析")
    add_if_exists(items, case_dir, "analysis/context_materials.md", "context_md", "补充资料包")
    add_if_exists(items, case_dir, "customer_material.md", "customer_md", "客户可见材料")
    add_if_exists(items, case_dir, "collaboration_analysis.md", "analysis_md", "协作分析")
    add_if_exists(items, case_dir, "internal_brief.md", "analysis_md", "内部简报")

    add_glob(items, case_dir, "analysis/remote_outputs/**/*.md", "remote_md", "WOW/远程 Agent Markdown")
    add_glob(items, case_dir, "analysis/crm/**/*.md", "crm_md", "客户洽谈 Markdown")
    add_glob(items, case_dir, "html/**/*.html", "html", "HTML 页面")
    add_glob(items, case_dir, "html/**/*.md", "html_md", "HTML 配套 Markdown")

    if include_source_transcript:
        add_if_exists(items, case_dir, "source/meeting_transcript.md", "source_transcript", "会议 transcript 原文")
        add_if_exists(items, case_dir, "source/ai_notes.md", "source_notes", "AI Notes 原文")

    deduped: dict[str, Artifact] = {}
    for item in items:
        deduped.setdefault(rel(item.path, case_dir), item)
    return list(deduped.values())


def build_index_entry_doc(case_dir: Path, artifacts: list[Artifact]) -> Path:
    case_json = read_json(case_dir / "case.json", {})
    resolution = read_json(case_dir / "source" / "source_resolution.json", {})
    title = scrub(str(case_json.get("title") or case_dir.name))
    lines = [
        "# 会议成果索引条目",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- title: `{title}`",
        f"- case_dir: `{case_dir}`",
        f"- source_kind: `{scrub(str(case_json.get('source_kind') or resolution.get('source_kind') or ''))}`",
        f"- status: `{scrub(str(case_json.get('analysis_status') or ''))}`",
        "",
        "## 产物清单",
        "",
    ]
    for item in artifacts:
        lines.append(f"- {item.label}: `{rel(item.path, case_dir)}`")
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本条目用于 `01_会议成果索引` 的归档入口。",
            "- 具体 HTML/Markdown 附件按类型上传到会议分析流水线对应 Wiki 节点。",
            "",
        ]
    )
    target = case_dir / "analysis" / "feishu_index_entry.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def should_inline_in_single_document(item: Artifact) -> bool:
    return item.kind in {"analysis_md", "context_md", "customer_md", "remote_md", "crm_md", "html_md"}


def is_formal_single_document_item(item: Artifact) -> bool:
    return item.kind in {
        "analysis_md",
        "context_md",
        "customer_md",
        "remote_md",
        "crm_md",
        "html",
        "html_md",
    }


def read_inline_document_text(path: Path) -> tuple[str, bool]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return "", False
    try:
        if path.stat().st_size > SINGLE_DOCUMENT_INLINE_LIMIT_BYTES:
            return "", False
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", False
    if has_secret_content(text):
        return "", False
    if len(text) > SINGLE_DOCUMENT_MAX_CHARS:
        return text[:SINGLE_DOCUMENT_MAX_CHARS] + "\n\n[内容过长，已在飞书归档稿中截断；完整版本保留在本地 case。]\n", True
    return text, True


def build_single_document_doc(case_dir: Path, artifacts: list[Artifact], archive_audience: dict[str, Any]) -> Path:
    case_json = read_json(case_dir / "case.json", {})
    resolution = read_json(case_dir / "source" / "source_resolution.json", {})
    title = scrub(str(case_json.get("title") or case_dir.name))
    audience = normalize_audience(archive_audience.get("audience")) if isinstance(archive_audience, dict) else "internal"
    formal_items = [item for item in artifacts if is_formal_single_document_item(item)]
    provenance_items = [item for item in artifacts if item.kind in {"provenance", "index_md"}]

    lines = [
        f"# {title}",
        "",
        "> 飞书侧正式归档采用“一场会议一份文档”。本地 source、analysis、html 与运行清单属于可清理的工作产物；如需追溯，以本 case manifest 和本地 Git/备份为准。",
        "",
        "## 归档摘要",
        "",
        f"- generated_at: `{now_iso()}`",
        f"- archive_audience: `{audience or 'internal'}`",
        f"- source_kind: `{scrub(str(case_json.get('source_kind') or resolution.get('source_kind') or ''))}`",
        f"- case_dir: `{case_dir}`",
        "",
        "## 正式产物",
        "",
    ]
    if not formal_items:
        lines.append("- 当前 case 还没有可归档的正式分析产物。")
    for item in formal_items:
        relative = rel(item.path, case_dir)
        lines.extend([f"### {item.label}", "", f"- local_case_path: `{relative}`", ""])
        if should_inline_in_single_document(item):
            text, ok = read_inline_document_text(item.path)
            if ok and text.strip():
                lines.extend([text.rstrip(), ""])
            else:
                lines.append("- 该 Markdown 文件较大或不适合内联，完整内容保留在本地 case。")
        elif item.kind == "html":
            lines.append("- HTML 不粘贴进飞书正文，完整文件保留在本地 case；如需对外展示，先做人工审阅后再单独发布。")
        lines.append("")

    if provenance_items:
        lines.extend(["## 本地追溯材料", ""])
        for item in provenance_items:
            lines.append(f"- {item.label}: `{rel(item.path, case_dir)}`")
        lines.append("")
    lines.extend(
        [
            "## 清理规则",
            "",
            "- `business_meeting_rawdata/_automation_inbox`、resolver 输出、远程 handoff、route decision、publish request、临时 HTML 等本地产物可以定期清理。",
            "- 飞书空间只保留这份正式归档文档；不要把同一会议的中间产物再拆成多个 Wiki/Drive 文档。",
            "- 如需临时排障，可在本地 manifest 查看 legacy artifact target mapping；不要把排障文件长期留在飞书空间。",
            "",
        ]
    )
    target = case_dir / "analysis" / "feishu_meeting_document.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def add_index_artifact(case_dir: Path, artifacts: list[Artifact]) -> list[Artifact]:
    index_path = build_index_entry_doc(case_dir, artifacts)
    if not safe_artifact(index_path, case_dir):
        return artifacts
    deduped: dict[str, Artifact] = {rel(item.path, case_dir): item for item in artifacts}
    deduped[rel(index_path, case_dir)] = Artifact(index_path.resolve(), "index_md", "会议成果索引条目")
    return list(deduped.values())


def build_return_message(case_dir: Path, artifacts: list[Artifact]) -> str:
    case_json = read_json(case_dir / "case.json", {})
    title = scrub(str(case_json.get("title") or case_dir.name))
    lines = [
        f"会议材料已归档并生成回传包：{title}",
        "",
        f"- case_dir: `{case_dir}`",
        f"- artifacts: `{len(artifacts)}`",
        "",
        "产物清单：",
    ]
    for item in artifacts:
        lines.append(f"- {item.label}: `{rel(item.path, case_dir)}`")
    lines.extend(["", "如需继续生成客户展示页或补资料后的二次分析，请在本消息下继续回复。"])
    return "\n".join(lines)


def resolve_lark_cli() -> str:
    env_value = os.environ.get(LARK_CLI_ENV, "").strip()
    if env_value:
        env_path = Path(env_value).expanduser()
        if env_path.exists():
            return str(env_path)
    for candidate in LARK_CLI_CANDIDATES:
        expanded = Path(candidate).expanduser()
        if expanded.is_absolute() and expanded.exists():
            return str(expanded)
        found = shutil.which(candidate)
        if found:
            return found
    return "lark-cli"


def lark_base(profile: str) -> list[str]:
    argv = [resolve_lark_cli()]
    if profile:
        argv.extend(["--profile", profile])
    return argv


def run_lark(argv: list[str], cwd: Path, dry_run: bool) -> dict[str, Any]:
    final_argv = list(argv)
    if dry_run and "--dry-run" not in final_argv:
        final_argv.append("--dry-run")
    try:
        run = subprocess.run(final_argv, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {"ok": False, "argv": [scrub(item) for item in final_argv[:4]], "error": scrub(str(exc))}
    return {
        "ok": run.returncode == 0,
        "returncode": run.returncode,
        "argv": [scrub(item) for item in final_argv[:4]],
        "stdout_tail": scrub((run.stdout or "")[-1200:]),
        "stderr_tail": scrub((run.stderr or "")[-1200:]),
    }


def loads_lenient_json(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise json.JSONDecodeError("No JSON object found", text, 0)


def normalize_audience(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in AUDIENCE_ALIASES:
        return AUDIENCE_ALIASES[text]
    for alias, audience in AUDIENCE_ALIASES.items():
        if alias and alias in text:
            return audience
    return ""


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def scalar_from_case_yaml(case_dir: Path, *keys: str) -> str:
    path = case_dir / "case.yaml"
    if not path.exists() or is_secret_file(path):
        return ""
    wanted = set(keys)
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, raw_value = stripped.split(":", 1)
            if key.strip() in wanted:
                return raw_value.strip().strip("\"'")
    except OSError:
        return ""
    return ""


def route_from_case(case_dir: Path, case_json: dict[str, Any]) -> str:
    route_done = read_json(case_dir / "analysis" / "route_done.json", {})
    route_decision = read_json(case_dir / "analysis" / "route_decision.json", {})
    nested_decision = case_json.get("route_decision") if isinstance(case_json.get("route_decision"), dict) else {}
    return first_string(
        route_done.get("route") if isinstance(route_done, dict) else "",
        route_decision.get("route") if isinstance(route_decision, dict) else "",
        nested_decision.get("route") if isinstance(nested_decision, dict) else "",
        case_json.get("route"),
        case_json.get("selected_route"),
    )


def artifact_forces_customer(item: Artifact, case_dir: Path) -> bool:
    rel_path = rel(item.path, case_dir).lower()
    name = item.path.name.lower()
    return (
        item.kind == "crm_md"
        or rel_path.startswith("analysis/crm/")
        or rel_path.startswith("html/crm_")
        or rel_path.startswith("html/visual_")
        or name.startswith("crm_")
        or name.startswith("visual_")
    )


def read_text_sample(path: Path) -> str:
    if not path.exists() or not path.is_file() or is_secret_file(path):
        return ""
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    try:
        if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            return ""
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if has_secret_content(text):
        return ""
    return text[:AUDIENCE_SCAN_BYTES]


def score_terms(text: str, terms: list[tuple[str, int]]) -> tuple[int, list[str]]:
    lowered = text.lower()
    score = 0
    matches: list[str] = []
    for term, weight in terms:
        count = lowered.count(term.lower())
        if count:
            score += min(count, 4) * weight
            matches.append(term)
    return score, matches[:8]


def classify_archive_audience(case_dir: Path, artifacts: list[Artifact]) -> dict[str, Any]:
    case_json = read_json(case_dir / "case.json", {})
    if not isinstance(case_json, dict):
        case_json = {}

    route = route_from_case(case_dir, case_json)
    if route in CUSTOMER_AUDIENCE_ROUTES:
        return {
            "audience": "customer",
            "source": "route",
            "route": route,
            "reason": "CRM or meeting-visual-report route is always treated as customer analysis.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }
    if any(artifact_forces_customer(item, case_dir) for item in artifacts):
        return {
            "audience": "customer",
            "source": "artifact_path",
            "route": route,
            "reason": "CRM or meeting-visual-report artifact path was found in the case.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }

    explicit = normalize_audience(
        first_string(
            case_json.get("archive_audience"),
            case_json.get("meeting_audience"),
            case_json.get("audience"),
            scalar_from_case_yaml(case_dir, "archive_audience", "meeting_audience", "audience"),
        )
    )
    if explicit:
        return {
            "audience": explicit,
            "source": "metadata",
            "route": route,
            "reason": "case metadata explicitly set archive audience.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }

    meeting_type = first_string(case_json.get("meeting_type"), scalar_from_case_yaml(case_dir, "meeting_type")).lower()
    if meeting_type in CUSTOMER_MEETING_TYPES:
        return {
            "audience": "customer",
            "source": "meeting_type",
            "route": route,
            "reason": f"meeting_type={meeting_type} maps to customer analysis.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }
    if meeting_type in PARTNER_MEETING_TYPES:
        return {
            "audience": "partner",
            "source": "meeting_type",
            "route": route,
            "reason": f"meeting_type={meeting_type} maps to partner analysis.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }
    if meeting_type in INTERNAL_MEETING_TYPES:
        return {
            "audience": "internal",
            "source": "meeting_type",
            "route": route,
            "reason": f"meeting_type={meeting_type} maps to internal analysis.",
            "customer_score": None,
            "partner_score": None,
            "internal_score": None,
            "customer_terms": [],
            "partner_terms": [],
            "internal_terms": [],
        }

    resolution = read_json(case_dir / "source" / "source_resolution.json", {})
    if not isinstance(resolution, dict):
        resolution = {}
    text_parts = [
        str(case_json.get("title") or ""),
        str(case_json.get("customer_short_name") or ""),
        str(case_json.get("source_kind") or ""),
        str(resolution.get("title") or ""),
        str(resolution.get("transcript_title") or ""),
        str(resolution.get("source_kind") or ""),
    ]
    for relative in [
        "source/meeting_transcript.md",
        "source/ai_notes.md",
        "internal_brief.md",
        "customer_material.md",
        "collaboration_analysis.md",
        "analysis/meeting_analysis.md",
    ]:
        text_parts.append(read_text_sample(case_dir / relative))
    for path in sorted((case_dir / "analysis" / "remote_outputs").glob("**/*.md")):
        text_parts.append(read_text_sample(path))

    scan_text = "\n".join(part for part in text_parts if part)
    customer_score, customer_terms = score_terms(scan_text, CUSTOMER_AUDIENCE_TERMS)
    partner_score, partner_terms = score_terms(scan_text, PARTNER_AUDIENCE_TERMS)
    internal_score, internal_terms = score_terms(scan_text, INTERNAL_AUDIENCE_TERMS)
    if partner_score >= max(customer_score + 2, internal_score + 2, 4):
        audience = "partner"
    elif customer_score >= max(internal_score + 2, 4):
        audience = "customer"
    else:
        audience = "internal"
    return {
        "audience": audience,
        "source": "heuristic",
        "route": route,
        "reason": "default/WOW output audience inferred from meeting content keywords.",
        "customer_score": customer_score,
        "partner_score": partner_score,
        "internal_score": internal_score,
        "customer_terms": customer_terms,
        "partner_terms": partner_terms,
        "internal_terms": internal_terms,
    }


def target_role_for_artifact(item: Artifact, audience: dict[str, Any] | None = None, case_dir: Path | None = None) -> str:
    archive_audience = normalize_audience((audience or {}).get("audience")) or "internal"
    if item.kind in {"index_md"}:
        return "index"
    if item.kind in {"html", "html_md"}:
        if case_dir and artifact_forces_customer(item, case_dir):
            return "customer_html"
        if archive_audience == "customer":
            return "customer_html"
        if archive_audience == "partner":
            return "partner_analysis"
        return "internal_analysis"
    if item.kind in {"crm_md"}:
        return "customer_analysis"
    if item.kind in {"customer_md"}:
        if archive_audience == "partner":
            return "partner_analysis"
        return "customer_analysis"
    if item.kind in {"context_md"}:
        return "context_materials"
    if item.kind in {"provenance"}:
        return "run_logs"
    if item.kind in {"analysis_md", "remote_md", "source_transcript", "source_notes"}:
        if archive_audience == "customer":
            return "customer_analysis"
        if archive_audience == "partner":
            return "partner_analysis"
        return "internal_analysis"
    return "attachments"


def archive_target_for_artifact(args: argparse.Namespace, item: Artifact) -> tuple[str, dict[str, str]]:
    if args.folder_token:
        return "folder", {"role": "folder", "title": "Drive folder", "node_token": args.folder_token, "url": ""}
    if args.wiki_token:
        return "wiki", {"role": "manual_wiki", "title": "Manual Wiki target", "node_token": args.wiki_token, "url": ""}
    targets = getattr(args, "archive_targets", {}) if isinstance(getattr(args, "archive_targets", {}), dict) else {}
    role = target_role_for_artifact(item, getattr(args, "archive_audience", {}), Path(args.case_dir).expanduser().resolve())
    target = targets.get(role) or targets.get("attachments") or {}
    if target.get("node_token"):
        return "wiki", target
    return "", {}


def single_document_parent_target(args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    if args.folder_token:
        return "folder", {"role": "manual_folder", "title": "Manual Drive folder", "node_token": args.folder_token, "url": ""}
    if args.wiki_token:
        return "wiki", {"role": "manual_wiki", "title": "Manual Wiki parent", "node_token": args.wiki_token, "url": ""}
    targets = getattr(args, "archive_targets", {}) if isinstance(getattr(args, "archive_targets", {}), dict) else {}
    target = targets.get("single_document") or {}
    if target.get("node_token"):
        return "wiki", target
    return "", {}


def artifact_target_summaries(args: argparse.Namespace, artifacts: list[Artifact], case_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in artifacts:
        target_type, target = archive_target_for_artifact(args, item)
        rows.append(
            {
                "path": rel(item.path, case_dir),
                "kind": item.kind,
                "target_type": target_type,
                "target_role": target.get("role", ""),
                "target_title": target.get("title", ""),
                "target_present": bool(target.get("node_token")),
                "archive_audience": normalize_audience((getattr(args, "archive_audience", {}) or {}).get("audience"))
                if isinstance(getattr(args, "archive_audience", {}), dict)
                else "",
            }
        )
    return rows


def validate_single_document_parent(args: argparse.Namespace, config: dict[str, Any], parent_type: str, parent: dict[str, str]) -> list[dict[str, Any]]:
    if getattr(args, "skip_target_validation", False) or parent_type != "wiki" or not parent.get("node_token"):
        return []
    expected_space_id = str(((config.get("wiki") or {}).get("space_id") or "") if isinstance(config, dict) else "")
    if not expected_space_id:
        return []
    argv = lark_base(args.profile) + [
        "wiki",
        "+node-get",
        "--node-token",
        parent.get("url") or parent["node_token"],
        "--as",
        args.identity,
    ]
    result = run_lark(argv, Path(args.case_dir).expanduser().resolve(), dry_run=False)
    record: dict[str, Any] = {
        "target_role": parent.get("role", ""),
        "target_title": parent.get("title", ""),
        "ok": bool(result.get("ok")),
        "result": result,
    }
    if result.get("ok"):
        data = loads_lenient_json(str(result.get("stdout_tail") or "")).get("data", {})
        actual_space_id = str(data.get("space_id") or "")
        record["space_match"] = actual_space_id == expected_space_id
        record["space_id_present"] = bool(actual_space_id)
        if actual_space_id != expected_space_id:
            record["ok"] = False
            raise SystemExit(f"Refusing to create a meeting document outside the configured Wiki space: {parent.get('title') or parent.get('role')}")
    if not record["ok"]:
        raise SystemExit(f"Unable to validate single-document archive parent: {parent.get('title') or parent.get('role')}")
    return [record]


def validate_wiki_targets(args: argparse.Namespace, config: dict[str, Any], case_dir: Path, artifacts: list[Artifact]) -> list[dict[str, Any]]:
    if getattr(args, "skip_target_validation", False):
        return []
    expected_space_id = str(((config.get("wiki") or {}).get("space_id") or "") if isinstance(config, dict) else "")
    if not expected_space_id:
        return []
    targets: dict[str, dict[str, str]] = {}
    for item in artifacts:
        target_type, target = archive_target_for_artifact(args, item)
        if target_type == "wiki" and target.get("node_token"):
            key = target.get("url") or target["node_token"]
            targets.setdefault(key, target)
    validations: list[dict[str, Any]] = []
    for key, target in sorted(targets.items()):
        node_ref = target.get("url") or target["node_token"]
        argv = lark_base(args.profile) + [
            "wiki",
            "+node-get",
            "--node-token",
            node_ref,
            "--as",
            args.identity,
        ]
        result = run_lark(argv, case_dir, dry_run=False)
        record: dict[str, Any] = {
            "target_role": target.get("role", ""),
            "target_title": target.get("title", ""),
            "ok": bool(result.get("ok")),
            "result": result,
        }
        if result.get("ok"):
            data = loads_lenient_json(str(result.get("stdout_tail") or "")).get("data", {})
            actual_space_id = str(data.get("space_id") or "")
            record["space_match"] = actual_space_id == expected_space_id
            record["space_id_present"] = bool(actual_space_id)
            if actual_space_id != expected_space_id:
                record["ok"] = False
                validations.append(record)
                raise SystemExit(
                    f"Refusing to archive outside the configured Wiki space: {target.get('title') or target.get('role')}"
                )
        validations.append(record)
        if not record["ok"]:
            raise SystemExit(f"Unable to validate Wiki archive target: {target.get('title') or target.get('role')}")
    return validations


def reply_or_send_summary(args: argparse.Namespace, case_dir: Path, message: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not args.message_id and not args.chat_id:
        return actions
    if args.message_id:
        argv = lark_base(args.profile) + [
            "im",
            "+messages-reply",
            "--message-id",
            args.message_id,
            "--markdown",
            message,
            "--as",
            args.identity,
        ]
        if args.reply_in_thread:
            argv.append("--reply-in-thread")
    else:
        argv = lark_base(args.profile) + [
            "im",
            "+messages-send",
            "--chat-id",
            args.chat_id,
            "--markdown",
            message,
            "--as",
            args.identity,
        ]
    actions.append({"type": "im_summary", "result": run_lark(argv, case_dir, args.dry_run)})
    return actions


def send_file_messages(args: argparse.Namespace, case_dir: Path, artifacts: list[Artifact]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not args.message_id and not args.chat_id:
        return actions
    for item in artifacts:
        file_rel = rel(item.path, case_dir)
        if args.message_id:
            argv = lark_base(args.profile) + [
                "im",
                "+messages-reply",
                "--message-id",
                args.message_id,
                "--file",
                file_rel,
                "--as",
                args.identity,
            ]
            if args.reply_in_thread:
                argv.append("--reply-in-thread")
        else:
            argv = lark_base(args.profile) + [
                "im",
                "+messages-send",
                "--chat-id",
                args.chat_id,
                "--file",
                file_rel,
                "--as",
                args.identity,
            ]
        actions.append({"type": "im_file", "path": file_rel, "result": run_lark(argv, case_dir, args.dry_run)})
    return actions


def send_single_document_file(args: argparse.Namespace, case_dir: Path, document_path: Path) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not args.message_id and not args.chat_id:
        return actions
    file_rel = rel(document_path, case_dir)
    if args.message_id:
        argv = lark_base(args.profile) + [
            "im",
            "+messages-reply",
            "--message-id",
            args.message_id,
            "--file",
            file_rel,
            "--as",
            args.identity,
        ]
        if args.reply_in_thread:
            argv.append("--reply-in-thread")
    else:
        argv = lark_base(args.profile) + [
            "im",
            "+messages-send",
            "--chat-id",
            args.chat_id,
            "--file",
            file_rel,
            "--as",
            args.identity,
        ]
    actions.append({"type": "im_single_document_file", "path": file_rel, "result": run_lark(argv, case_dir, args.dry_run)})
    return actions


def write_single_document_to_feishu(
    args: argparse.Namespace,
    case_dir: Path,
    document_path: Path,
    parent_type: str,
    parent: dict[str, str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    content_ref = f"@{rel(document_path, case_dir)}"
    if args.doc:
        argv = lark_base(args.profile) + [
            "docs",
            "+update",
            "--api-version",
            "v2",
            "--doc",
            args.doc,
            "--command",
            "append",
            "--doc-format",
            "markdown",
            "--content",
            content_ref,
            "--as",
            args.identity,
        ]
        actions.append({"type": "doc_append_single_document", "path": rel(document_path, case_dir), "result": run_lark(argv, case_dir, args.dry_run)})
        return actions
    if parent.get("node_token"):
        argv = lark_base(args.profile) + [
            "docs",
            "+create",
            "--api-version",
            "v2",
            "--doc-format",
            "markdown",
            "--content",
            content_ref,
            "--parent-token",
            parent["node_token"],
            "--as",
            args.identity,
        ]
        actions.append(
            {
                "type": "doc_create_single_document",
                "path": rel(document_path, case_dir),
                "parent_type": parent_type,
                "parent_role": parent.get("role", ""),
                "parent_title": parent.get("title", ""),
                "result": run_lark(argv, case_dir, args.dry_run),
            }
        )
    return actions


def insert_doc_attachments(args: argparse.Namespace, case_dir: Path, artifacts: list[Artifact]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not args.doc:
        return actions
    for item in artifacts:
        argv = lark_base(args.profile) + [
            "docs",
            "+media-insert",
            "--doc",
            args.doc,
            "--type",
            "file",
            "--file",
            str(item.path),
            "--file-view",
            "card",
            "--as",
            args.identity,
        ]
        actions.append({"type": "doc_attachment", "path": rel(item.path, case_dir), "result": run_lark(argv, case_dir, args.dry_run)})
    return actions


def upload_drive_files(args: argparse.Namespace, case_dir: Path, artifacts: list[Artifact]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    has_typed_targets = bool(getattr(args, "archive_targets", {}))
    if not args.folder_token and not args.wiki_token and not has_typed_targets:
        return actions
    for item in artifacts:
        target_type, target = archive_target_for_artifact(args, item)
        if not target_type:
            continue
        argv = lark_base(args.profile) + [
            "drive",
            "+upload",
            "--file",
            str(item.path),
            "--name",
            item.path.name,
            "--as",
            args.identity,
        ]
        if target_type == "folder":
            argv.extend(["--folder-token", target["node_token"]])
        elif target_type == "wiki":
            argv.extend(["--wiki-token", target["node_token"]])
        actions.append(
            {
                "type": "drive_upload",
                "path": rel(item.path, case_dir),
                "target_type": target_type,
                "target_role": target.get("role", ""),
                "target_title": target.get("title", ""),
                "result": run_lark(argv, case_dir, args.dry_run),
            }
        )
    return actions


def build_return_package(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = ensure_case_dir(args.case_dir)
    ensure_transcript_available(case_dir, "build Feishu return package")
    targets_config, targets_config_path = apply_target_defaults(args)
    artifacts = collect_artifacts(case_dir, include_source_transcript=args.include_source_transcript)
    artifacts = add_index_artifact(case_dir, artifacts)
    args.archive_audience = classify_archive_audience(case_dir, artifacts)
    single_document_path = build_single_document_doc(case_dir, artifacts, args.archive_audience)
    parent_type, single_document_parent = single_document_parent_target(args)
    legacy_multi_artifact_upload = bool(getattr(args, "allow_multi_artifact_upload", False))
    target_validations: list[dict[str, Any]] = []
    if args.send:
        if legacy_multi_artifact_upload:
            target_validations = validate_wiki_targets(args, targets_config, case_dir, artifacts)
        else:
            target_validations = validate_single_document_parent(args, targets_config, parent_type, single_document_parent)
    message = build_return_message(case_dir, artifacts)
    message_path = case_dir / "analysis" / "feishu_return_message.md"
    message_path.parent.mkdir(parents=True, exist_ok=True)
    message_path.write_text(message + "\n", encoding="utf-8")

    actions: list[dict[str, Any]] = []
    if args.send:
        if legacy_multi_artifact_upload:
            actions.extend(reply_or_send_summary(args, case_dir, message))
            actions.extend(send_file_messages(args, case_dir, artifacts))
            actions.extend(insert_doc_attachments(args, case_dir, artifacts))
            actions.extend(upload_drive_files(args, case_dir, artifacts))
        else:
            actions.extend(write_single_document_to_feishu(args, case_dir, single_document_path, parent_type, single_document_parent))
            actions.extend(reply_or_send_summary(args, case_dir, message))
            if not args.doc and not single_document_parent.get("node_token"):
                actions.extend(send_single_document_file(args, case_dir, single_document_path))

    manifest = {
        "created_at": now_iso(),
        "case_dir": str(case_dir),
        "profile": scrub(args.profile),
        "profile_present": bool(args.profile),
        "identity": args.identity,
        "targets_config": targets_config_path,
        "dry_run": bool(args.dry_run),
        "send": bool(args.send),
        "targets": {
            "message_id_present": bool(args.message_id),
            "chat_id_present": bool(args.chat_id),
            "doc_present": bool(args.doc),
            "folder_token_present": bool(args.folder_token),
            "wiki_token_present": bool(args.wiki_token),
            "typed_wiki_targets_present": bool(getattr(args, "archive_targets", {})),
        },
        "single_document_policy": {
            "mode": "legacy_multi_artifact_upload" if legacy_multi_artifact_upload else "single_feishu_document",
            "legacy_multi_artifact_upload": legacy_multi_artifact_upload,
            "one_meeting_one_document": not legacy_multi_artifact_upload,
        },
        "single_document": {
            "path": rel(single_document_path, case_dir),
            "parent_type": parent_type,
            "parent_role": single_document_parent.get("role", ""),
            "parent_title": single_document_parent.get("title", ""),
            "parent_present": bool(single_document_parent.get("node_token")),
            "doc_append": bool(args.doc),
        },
        "archive_audience": args.archive_audience,
        "target_validations": target_validations,
        "message": rel(message_path, case_dir),
        "artifacts": [
            {"path": rel(item.path, case_dir), "kind": item.kind, "label": item.label, "bytes": item.path.stat().st_size}
            for item in artifacts
        ],
        "artifact_targets": artifact_target_summaries(args, artifacts, case_dir),
        "actions": actions,
    }
    manifest_path = case_dir / "analysis" / "feishu_return_manifest.json"
    write_json(manifest_path, manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Return meeting case artifacts to Feishu/Lark.")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--profile", default="")
    parser.add_argument("--targets-config", default="", help="Local meeting_chain_targets JSON. Defaults to MEETING_CHAIN_TARGETS_CONFIG or the automation-control-plane local config when present.")
    parser.add_argument("--allow-profile-override", action="store_true", help="Allow archiving with a profile different from the configured meeting-chain profile.")
    parser.add_argument("--skip-target-validation", action="store_true", help="Skip configured Wiki space validation before send/dry-run send.")
    parser.add_argument("--as", dest="identity", choices=["bot", "user"], default="bot")
    parser.add_argument("--message-id", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--doc", default="", help="Existing Feishu doc URL/token to append the single meeting archive draft to.")
    parser.add_argument("--folder-token", default="", help="Drive folder token used as the parent for one created archive document.")
    parser.add_argument("--wiki-token", default="", help="Wiki node token used as the parent for one created archive document.")
    parser.add_argument("--include-source-transcript", action="store_true")
    parser.add_argument("--allow-multi-artifact-upload", action="store_true", help="Legacy escape hatch: send/upload every collected artifact separately instead of the default one-meeting-one-document return.")
    parser.add_argument("--send", action="store_true", help="Actually call lark-cli. Without this, only writes manifest/message files.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to lark-cli write commands.")
    parser.add_argument("--reply-in-thread", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build_return_package(args)
    print(json.dumps(manifest, ensure_ascii=False))
    failed = [
        action
        for action in manifest.get("actions", [])
        if isinstance(action, dict) and not action.get("result", {}).get("ok", False)
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

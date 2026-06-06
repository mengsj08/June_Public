#!/usr/bin/env python3
"""Create a meeting visualization case scaffold.

This script creates local case files only. It does not call Feishu/Lark APIs,
does not call external consultation skills, and does not read credential files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal

from _safety import has_secret_content, is_secret_file


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME_ROOT = Path.cwd() / "meeting-runtime"
DEFAULT_PRE_CONSULT_GIT_URL = "https://github.com/jeffzh0802/skill_pre-consult.git"

MeetingType = Literal["internal", "presales", "customer_collaboration", "special"]


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "meeting"


def ensure_safe_path(path: Path, label: str) -> Path:
    if is_secret_file(path):
        raise SystemExit(f"Refusing secret-like {label} path: {path}")
    return path.expanduser()


# Strong presales signals (weight 2). Ambiguous words like "诊断"/"老板"/"方案"
# are intentionally NOT here — they appear in research/internal meetings too and
# previously short-circuited everything to presales, misrouting to CRM.
PRESALES_STRONG_SIGNALS = ["客户", "customer", "拜访", "售前", "成果页", "问卷", "crm", "报价"]
# Support signals (weight 1) only count toward presales when a customer is present.
PRESALES_SUPPORT_SIGNALS = ["ai 落地", "ai落地", "咨询", "方案", "解决方案", "客户会议", "诊断", "老板"]
COLLABORATION_SIGNALS = ["合作", "共创", "双方", "伙伴", "联合", "分工", "对接"]
INTERNAL_SIGNALS = [
    "内部",
    "周会",
    "复盘",
    "排期",
    "研发",
    "科研",
    "知识库",
    "论文",
    "综述",
    "开题",
    "迭代",
    "任务",
    "sprint",
]


def classify_meeting(text: str, explicit: str = "auto") -> MeetingType:
    if explicit != "auto":
        return explicit  # type: ignore[return-value]

    lower = text.lower()
    has_customer = "客户" in lower or "customer" in lower

    presales = 2 * sum(1 for s in PRESALES_STRONG_SIGNALS if s in lower)
    if has_customer:
        presales += sum(1 for s in PRESALES_SUPPORT_SIGNALS if s in lower)
    internal = sum(1 for s in INTERNAL_SIGNALS if s in lower)
    collaboration = sum(1 for s in COLLABORATION_SIGNALS if s in lower)

    scores: dict[MeetingType, int] = {
        "internal": internal,
        "customer_collaboration": collaboration,
        "presales": presales,
    }
    best_score = max(scores.values())
    if best_score == 0:
        return "special"
    # Tie-break order favours the non-CRM route to avoid accidental customer-facing
    # generation; the AI is expected to pass --meeting-type explicitly when known.
    for candidate in ("internal", "customer_collaboration", "presales"):
        if scores[candidate] == best_score:
            return candidate
    return "special"


def validate_crm_skill_dir(path: Path) -> str:
    skill_dir = ensure_safe_path(path, "CRM skill").resolve()
    if not skill_dir.exists():
        raise SystemExit(f"CRM skill path does not exist: {skill_dir}")
    if not (skill_dir / "SKILL.md").exists():
        raise SystemExit(f"CRM skill path must contain SKILL.md: {skill_dir}")
    return str(skill_dir)


def validate_pre_consult_skill_dir(path: Path) -> str:
    skill_dir = ensure_safe_path(path, "pre-consult skill").resolve()
    if not skill_dir.exists():
        raise SystemExit(f"Pre-consult skill path does not exist: {skill_dir}")
    if not (skill_dir / "SKILL.md").exists():
        raise SystemExit(f"Pre-consult skill path must contain SKILL.md: {skill_dir}")
    return str(skill_dir)


def safe_github_repo_name(git_url: str) -> str:
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", git_url.strip())
    if not match:
        raise SystemExit("Only explicit public GitHub HTTPS repo URLs are supported for external skill Git URLs.")
    owner, repo = match.groups()
    return f"{owner}__{repo}"


def install_crm_skill_from_github(git_url: str, install_dir: Path, subdir: str | None) -> str:
    if has_secret_content(git_url):
        raise SystemExit("Refusing secret-like CRM skill GitHub URL.")

    repo_name = safe_github_repo_name(git_url)
    base_dir = ensure_safe_path(install_dir, "CRM skill install").resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = base_dir / repo_name

    if repo_dir.exists():
        if not (repo_dir / ".git").exists():
            raise SystemExit(f"Install target exists but is not a git repo: {repo_dir}")
    else:
        subprocess.run(["git", "clone", "--depth", "1", git_url, str(repo_dir)], check=True)

    if subdir:
        return validate_crm_skill_dir(repo_dir / subdir)
    if (repo_dir / "SKILL.md").exists():
        return validate_crm_skill_dir(repo_dir)
    named = repo_dir / "skill_客户洽谈"
    if (named / "SKILL.md").exists():
        return validate_crm_skill_dir(named)

    candidates = [path.parent for path in repo_dir.glob("*/SKILL.md")]
    if len(candidates) == 1:
        return validate_crm_skill_dir(candidates[0])
    raise SystemExit(
        "Unable to locate CRM skill after clone. Pass --crm-skill-subdir with the path containing SKILL.md."
    )


def resolve_crm_skill_path(
    explicit_path: str | None = None,
    git_url: str | None = None,
    install_dir: str | None = None,
    subdir: str | None = None,
) -> str:
    env_path = os.environ.get("FEISHU_MEETING_CRM_SKILL_PATH") or os.environ.get("CRM_SKILL_PATH")
    if explicit_path:
        return validate_crm_skill_dir(Path(explicit_path))
    if env_path:
        return validate_crm_skill_dir(Path(env_path))
    if git_url:
        target_dir = Path(install_dir).expanduser() if install_dir else Path.cwd() / "external-skills"
        return install_crm_skill_from_github(git_url, target_dir, subdir)
    return ""


def install_pre_consult_skill_from_github(git_url: str, install_dir: Path, subdir: str | None) -> str:
    if has_secret_content(git_url):
        raise SystemExit("Refusing secret-like pre-consult skill GitHub URL.")

    repo_name = safe_github_repo_name(git_url)
    base_dir = ensure_safe_path(install_dir, "pre-consult skill install").resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = base_dir / repo_name

    if repo_dir.exists():
        if not (repo_dir / ".git").exists():
            raise SystemExit(f"Install target exists but is not a git repo: {repo_dir}")
    else:
        subprocess.run(["git", "clone", "--depth", "1", git_url, str(repo_dir)], check=True)

    if subdir:
        return validate_pre_consult_skill_dir(repo_dir / subdir)
    if (repo_dir / "SKILL.md").exists():
        return validate_pre_consult_skill_dir(repo_dir)

    candidates = [path.parent for path in repo_dir.glob("*/SKILL.md")]
    if len(candidates) == 1:
        return validate_pre_consult_skill_dir(candidates[0])
    raise SystemExit(
        "Unable to locate pre-consult skill after clone. Pass --pre-consult-subdir with the path containing SKILL.md."
    )


def resolve_pre_consult_skill_path(
    explicit_path: str | None = None,
    git_url: str | None = None,
    install_dir: str | None = None,
    subdir: str | None = None,
) -> str:
    env_path = os.environ.get("FEISHU_MEETING_PRE_CONSULT_SKILL_PATH") or os.environ.get("PRE_CONSULT_SKILL_PATH")
    if explicit_path:
        return validate_pre_consult_skill_dir(Path(explicit_path))
    if env_path:
        return validate_pre_consult_skill_dir(Path(env_path))
    if git_url:
        target_dir = Path(install_dir).expanduser() if install_dir else Path.cwd() / "external-skills"
        return install_pre_consult_skill_from_github(git_url, target_dir, subdir)
    return ""


def route_for(
    meeting_type: MeetingType,
    requested_crm_stage: str | None,
    crm_skill_path: str,
    pre_consult_skill_path: str,
    pre_consult_flow: str,
    pre_consult_workspace: Path | None,
) -> dict[str, str]:
    if meeting_type == "presales":
        return {
            "customer_page_generator": "pre_consult" if pre_consult_skill_path else "crm",
            "crm_skill_path": crm_skill_path,
            "crm_stage": requested_crm_stage or "纪要",
            "pre_consult_flow": pre_consult_flow if pre_consult_skill_path else "none",
            "pre_consult_skill_path": pre_consult_skill_path,
            "pre_consult_workspace": str(pre_consult_workspace or ""),
        }
    if meeting_type == "customer_collaboration":
        return {
            "customer_page_generator": "meeting_visualization",
            "crm_skill_path": crm_skill_path,
            "crm_stage": "none",
            "pre_consult_flow": "none",
            "pre_consult_skill_path": "",
            "pre_consult_workspace": "",
        }
    return {
        "customer_page_generator": "none",
        "crm_skill_path": crm_skill_path,
        "crm_stage": "none",
        "pre_consult_flow": "none",
        "pre_consult_skill_path": "",
        "pre_consult_workspace": "",
    }


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_if_absent(path: Path, content: str, force: bool, statuses: list[tuple[str, str]]) -> None:
    """Write content but never silently clobber an existing non-empty file.

    The AI/human writes real analysis into these scaffold files (see SKILL.md
    step 5). Re-running case creation must not destroy that work. Pass --force
    to intentionally regenerate the scaffold.
    """
    has_content = path.exists() and path.read_text(encoding="utf-8").strip() != ""
    if has_content and not force:
        statuses.append((path.name, "skipped (exists)"))
        return
    path.write_text(content, encoding="utf-8")
    statuses.append((path.name, "overwrote" if has_content else "wrote"))


def write_case_yaml(
    case_dir: Path,
    case_id: str,
    title: str,
    source_kind: str,
    source_refs: list[str],
    runtime_dir: Path,
    meeting_type: MeetingType,
    customer_short_name: str,
    route: dict[str, str],
    owner: str,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    refs = "\n".join(f"  - {yaml_quote(ref)}" for ref in source_refs) or "  []"
    content = f"""case_id: {yaml_quote(case_id)}
type: "meeting-visualization"
title: {yaml_quote(title)}
status: "draft"
created_at: "{dt.date.today().isoformat()}"
owner: {yaml_quote(owner)}

source_kind: {yaml_quote(source_kind)}
source_refs:
{refs}
runtime_dir: {yaml_quote(str(runtime_dir))}

meeting_type: {yaml_quote(meeting_type)}
customer_short_name: {yaml_quote(customer_short_name)}
customer_page_generator: {yaml_quote(route["customer_page_generator"])}
crm_skill_path: {yaml_quote(route["crm_skill_path"])}
crm_stage: {yaml_quote(route["crm_stage"])}
pre_consult_flow: {yaml_quote(route["pre_consult_flow"])}
pre_consult_skill_path: {yaml_quote(route["pre_consult_skill_path"])}
pre_consult_workspace: {yaml_quote(route["pre_consult_workspace"])}

output_paths: []
handoff_notes: ""
"""
    write_if_absent(case_dir / "case.yaml", content, force, statuses)


def write_source_index(
    case_dir: Path,
    source_kind: str,
    source_refs: list[str],
    runtime_dir: Path,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    lines = [
        "# Source Index",
        "",
        f"- Source kind: `{source_kind}`",
        f"- Runtime dir: `{runtime_dir}`",
        "",
        "## Source References",
        "",
    ]
    if source_refs:
        lines.extend(f"- `{ref}`" for ref in source_refs)
    else:
        lines.append("- No source reference registered yet.")

    lines.extend(
        [
            "",
            "## Feishu CLI Boundary",
            "",
            "- Feishu meeting: `lark-cli vc +search -> lark-cli vc +recording -> lark-cli vc +notes`",
            "- Feishu Minutes: extract `minute_token -> lark-cli vc +notes`",
            "- Local media: only after confirmation, `lark-cli drive +upload -> lark-cli minutes +upload -> lark-cli vc +notes`",
            "- Do not copy sensitive config files, keys, login material, cookies, or private auth files.",
            "",
        ]
    )
    write_if_absent(case_dir / "source_index.md", "\n".join(lines), force, statuses)


def write_internal_brief(
    case_dir: Path,
    meeting_type: MeetingType,
    route: dict[str, str],
    title: str,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    lines = [
        "# Internal Brief",
        "",
        f"- Title: {title}",
        f"- Meeting type: `{meeting_type}`",
        f"- Customer page generator: `{route['customer_page_generator']}`",
        f"- CRM stage: `{route['crm_stage']}`",
        "",
        "## Internal Notes",
        "",
        "- Add internal judgment, risks, action items, and decisions here.",
        "- Keep sales strategy, budget interpretation, go/no-go logic, and private team notes in this file only.",
        "",
        "## Routing Decision",
        "",
    ]
    if meeting_type == "presales" and route["customer_page_generator"] == "pre_consult":
        lines.append("- Presales customer scenario: prepare full pre-consult handoff; do not write customer pages directly from this scaffold.")
    elif meeting_type == "presales":
        lines.append("- Presales customer scenario: legacy CRM route is available, but pre-consult is the preferred customer-page generator.")
    elif meeting_type == "customer_collaboration":
        lines.append("- Customer collaboration: use meeting visualization draft path, not CRM by default.")
    elif meeting_type == "internal":
        lines.append("- Internal meeting: no customer-facing page by default.")
    else:
        lines.append("- Special case: build questions and clarify before downstream generation.")
    lines.append("")
    write_if_absent(case_dir / "internal_brief.md", "\n".join(lines), force, statuses)


def write_customer_material(
    case_dir: Path,
    meeting_type: MeetingType,
    title: str,
    source_excerpt: str,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    lines = [
        "# Customer Material",
        "",
        f"- Title: {title}",
        f"- Meeting type: `{meeting_type}`",
        "",
        "## Customer-Visible Facts",
        "",
        "- Add facts explicitly supported by transcript or meeting notes.",
        "- Add customer quotes only when they are safe to show back to the customer.",
        "- Do not add internal sales judgment, private risk labels, or unsupported claims.",
        "",
        "## Source Boundary",
        "",
        "- Internal source links and raw transcript excerpts are recorded in `source_index.md` and runtime files.",
        "- Do not paste Feishu docx/minutes links, signed media URLs, auth tokens, or raw private excerpts into customer-facing material.",
        "- Add only curated, customer-safe facts here after the AI has reviewed the transcript.",
        "",
    ]
    write_if_absent(case_dir / "customer_material.md", "\n".join(lines), force, statuses)


def write_crm_handoff(
    case_dir: Path,
    meeting_type: MeetingType,
    route: dict[str, str],
    customer_short_name: str,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    if meeting_type != "presales":
        return
    crm_display = route["crm_skill_path"] or "CRM skill not configured. Pass --crm-skill-path or --crm-skill-git-url."
    lines = [
        "# CRM Handoff",
        "",
        f"- CRM skill path: `{crm_display}`",
        f"- CRM stage: `{route['crm_stage']}`",
        f"- Customer short name: `{customer_short_name or '[fill required]'}`",
        "",
        "## Invocation",
        "",
        f"Use `crm {route['crm_stage']}` with `customer_material.md` as the customer-visible input after CRM skill is configured.",
        "",
        "## Guardrails",
        "",
        "- Do not include internal sales judgment from `internal_brief.md` in customer-facing output.",
        "- Do not write customer-facing phrases such as sales, deal, unit price, or script.",
        "- Do not invent customer pain points, numbers, or commitments.",
        "- Preserve CRM output paths under its own `agent_output/<客户简称>/` convention and record absolute paths back in this case.",
        "",
    ]
    write_if_absent(case_dir / "crm_handoff.md", "\n".join(lines), force, statuses)


def write_pre_consult_handoff(
    case_dir: Path,
    runtime_dir: Path,
    meeting_type: MeetingType,
    route: dict[str, str],
    title: str,
    customer_short_name: str,
    transcript_path: str,
    force: bool,
    statuses: list[tuple[str, str]],
) -> None:
    if meeting_type != "presales" or route["customer_page_generator"] != "pre_consult":
        return

    workspace = Path(route["pre_consult_workspace"])
    output_root = workspace / "agent_output"
    output_root.mkdir(parents=True, exist_ok=True)
    customer_name = customer_short_name or "[fill required]"
    skill_path = route["pre_consult_skill_path"] or "[pre-consult skill not configured]"
    transcript_display = transcript_path or "[transcript path not provided; use source_index.md]"

    lines = [
        "# Pre-Consult Handoff",
        "",
        f"- Title: {title}",
        f"- Customer short name: `{customer_name}`",
        f"- Pre-consult skill path: `{skill_path}`",
        "- Trigger skill name: `crm`",
        f"- Flow: `{route['pre_consult_flow']}`",
        f"- Workspace: `{workspace}`",
        f"- Output root: `{output_root}`",
        f"- Case YAML: `{case_dir / 'case.yaml'}`",
        f"- Meeting transcript: `{transcript_display}`",
        f"- Customer-safe material: `{case_dir / 'customer_material.md'}`",
        f"- Source index: `{case_dir / 'source_index.md'}`",
        "",
        "## Invocation Order",
        "",
        "Run the external `crm` skill from the workspace above. Do not write generated customer artifacts into the skill source directory.",
        "",
        "1. `crm 会前` — build or backfill `agent_output/客户档案/<客户简称>.md` from `case.yaml`, known customer background, and meeting goals.",
        "2. `crm 纪要` — use `meeting_transcript.md` plus `customer_material.md`; output customer-visible `纪要_<日期>.html`.",
        "3. `crm 提问` — use the phase 2 minutes and customer archive; output consultant-only `作战手册_<日期>.html`.",
        "4. `crm 成果` — use phase 2 minutes plus phase 3 notes or transcript-backed deep answers; output customer-visible `成果_<日期>.html`.",
        "5. `crm 问卷` — use the customer archive, minutes, and result page; output customer-visible `问卷_<日期>.md`.",
        "",
        "## Stage Mapping Notes",
        "",
        "- If the meeting already happened, phase 1 is a backfill step; do not pretend it was used live before the meeting.",
        "- Phase 3 output is internal consultant material and must not be copied into customer-facing artifacts.",
        "- If phase 4 lacks enough deep-question notes or customer answers, stop and ask for keywords instead of inventing a result page.",
        "- Record any generated absolute output paths back into `case.yaml` after the external skill finishes.",
        "",
        "## Customer-Safe Guardrails",
        "",
        "- Do not include Feishu doc/minute links, signed media URLs, auth tokens, raw private excerpts, or source credentials in customer-facing pages.",
        "- Do not include internal sales judgment from `internal_brief.md` in customer-facing output.",
        "- Do not write customer-facing phrases such as sales, deal, unit price, or script.",
        "- Do not invent customer pain points, numbers, commitments, budgets, or ROI claims.",
        "",
    ]
    write_if_absent(case_dir / "pre_consult_handoff.md", "\n".join(lines), force, statuses)


def create_case(args: argparse.Namespace) -> tuple[Path, list[tuple[str, str]]]:
    source_text = ""
    transcript_path = ""
    if args.input_file:
        source_path = Path(args.input_file).expanduser()
        if is_secret_file(source_path):
            raise SystemExit(f"Refusing to read secret-like input path: {source_path}")
        source_text = source_path.read_text(encoding="utf-8")
        transcript_path = str(source_path.resolve())
    elif args.input_text:
        source_text = args.input_text

    if has_secret_content(" ".join(args.source_ref or [])):
        raise SystemExit("Refusing to register secret-like source reference.")

    case_id = args.case_id or f"{dt.date.today().isoformat()}-{slugify(args.title)}"
    case_root = Path(getattr(args, "case_root", "") or (Path.cwd() / "meeting-cases")).expanduser()
    case_dir = case_root / case_id
    runtime_dir = Path(args.runtime_root).expanduser() / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pre_consult_workspace = runtime_dir / "pre-consult"

    meeting_type = classify_meeting(source_text + "\n" + args.title, args.meeting_type)
    pre_consult_git_url = args.pre_consult_git_url
    if meeting_type == "presales" and not args.pre_consult_skill_path and not pre_consult_git_url:
        pre_consult_git_url = DEFAULT_PRE_CONSULT_GIT_URL
    pre_consult_install_dir = args.pre_consult_install_dir or str(pre_consult_workspace / "external-skills")
    pre_consult_skill_path = resolve_pre_consult_skill_path(
        explicit_path=args.pre_consult_skill_path,
        git_url=pre_consult_git_url if meeting_type == "presales" else None,
        install_dir=pre_consult_install_dir,
        subdir=args.pre_consult_subdir,
    )
    crm_skill_path = resolve_crm_skill_path(
        explicit_path=args.crm_skill_path,
        git_url=args.crm_skill_git_url,
        install_dir=args.crm_skill_install_dir,
        subdir=args.crm_skill_subdir,
    )
    route = route_for(
        meeting_type,
        args.crm_stage,
        crm_skill_path,
        pre_consult_skill_path,
        args.pre_consult_flow,
        pre_consult_workspace,
    )

    force = bool(getattr(args, "force", False))
    statuses: list[tuple[str, str]] = []
    source_refs = list(args.source_ref or [])
    write_case_yaml(
        case_dir=case_dir,
        case_id=case_id,
        title=args.title,
        source_kind=args.source_kind,
        source_refs=source_refs,
        runtime_dir=runtime_dir,
        meeting_type=meeting_type,
        customer_short_name=args.customer_short_name or "",
        route=route,
        owner=args.owner or getpass.getuser(),
        force=force,
        statuses=statuses,
    )
    write_source_index(case_dir, args.source_kind, source_refs, runtime_dir, force, statuses)
    write_internal_brief(case_dir, meeting_type, route, args.title, force, statuses)
    write_customer_material(case_dir, meeting_type, args.title, source_text, force, statuses)
    write_pre_consult_handoff(
        case_dir=case_dir,
        runtime_dir=runtime_dir,
        meeting_type=meeting_type,
        route=route,
        title=args.title,
        customer_short_name=args.customer_short_name or "",
        transcript_path=transcript_path,
        force=force,
        statuses=statuses,
    )
    if route["customer_page_generator"] != "pre_consult":
        write_crm_handoff(case_dir, meeting_type, route, args.customer_short_name or "", force, statuses)
    return case_dir, statuses


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a meeting visualization case scaffold.")
    parser.add_argument("--case-id")
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--source-kind",
        required=True,
        choices=["feishu_docx", "feishu_meeting", "feishu_minutes", "local_media", "manual_text"],
    )
    parser.add_argument("--source-ref", action="append")
    parser.add_argument("--input-text")
    parser.add_argument("--input-file")
    parser.add_argument(
        "--meeting-type",
        default="auto",
        choices=["auto", "internal", "presales", "customer_collaboration", "special"],
    )
    parser.add_argument("--customer-short-name")
    parser.add_argument("--crm-stage", choices=["会前", "纪要", "提问", "成果", "问卷"])
    parser.add_argument("--crm-skill-path", help="Explicit local CRM skill directory containing SKILL.md.")
    parser.add_argument("--crm-skill-git-url", help="Explicit GitHub HTTPS repo URL to clone for the CRM skill.")
    parser.add_argument("--crm-skill-install-dir", help="Directory used when cloning --crm-skill-git-url. Defaults to ./external-skills.")
    parser.add_argument("--crm-skill-subdir", help="Subdirectory inside the cloned repo that contains the CRM SKILL.md.")
    parser.add_argument("--pre-consult-skill-path", help="Explicit local skill_pre-consult directory containing SKILL.md.")
    parser.add_argument(
        "--pre-consult-git-url",
        help=f"GitHub HTTPS repo URL for skill_pre-consult. Defaults to {DEFAULT_PRE_CONSULT_GIT_URL} for presales cases.",
    )
    parser.add_argument(
        "--pre-consult-install-dir",
        help="Directory used when cloning --pre-consult-git-url. Defaults to <runtime-dir>/pre-consult/external-skills.",
    )
    parser.add_argument("--pre-consult-subdir", help="Subdirectory inside the cloned repo that contains SKILL.md.")
    parser.add_argument("--pre-consult-flow", default="full", choices=["full"])
    parser.add_argument("--owner", help="Optional case owner. Defaults to the current OS user.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--case-root", default=str(Path.cwd() / "meeting-cases"))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate scaffold files even if they already exist. Without this, existing non-empty files (e.g. analysis you already wrote) are preserved.",
    )
    args = parser.parse_args()

    case_dir, statuses = create_case(args)
    for name, status in statuses:
        print(f"{status}: {name}", file=sys.stderr)
    print(str(case_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

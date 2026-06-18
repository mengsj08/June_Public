#!/usr/bin/env python3
"""Record a user's context-gate reply for a meeting case.

This helper is intentionally orchestration-only. It classifies short replies
or route phrases such as "1", "默认", "直接分析", "2", "补资料",
"3", "客户展示HTML", "4", "WOW-Claude", "5", "WOW-Codex", or
"6", "客户洽谈Skill", updates case.json, and writes
handoff files for the next Agent/Skill step.
It does not generate meeting analysis.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

from _safety import has_secret_content, is_secret_file, scrub
from provenance_gate import ensure_source_resolved


DEFAULT_ROUTE = "agent_default"
DEFAULT_ROUTE_LABEL = "当前 Agent 直接分析"
CRM_SKILL_ROUTE_LABEL = "crm / skill_客户洽谈"
VISUAL_ROUTE = "meeting-visual-report"
REMOTE_ROUTES = {"wow_codex": "WOW-Codex", "wow_claude": "WOW-Claude"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sanitize_text(value: Any, limit: int = 600) -> str:
    text = scrub(str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_case_dir(path: str) -> Path:
    case_dir = Path(path).expanduser().resolve()
    if is_secret_file(case_dir):
        raise SystemExit(f"Refusing secret-like case path: {case_dir}")
    if not case_dir.is_dir():
        raise SystemExit(f"Case directory not found: {case_dir}")
    return case_dir


def detect_intents(reply: str) -> list[str]:
    text = reply.strip().lower()
    compact = re.sub(r"\s+", "", text)
    intents: list[str] = []
    if compact in {"1", "1.", "1。", "一", "选1", "选择1"}:
        intents.append("agent_default")
    if compact in {"2", "2.", "2。", "二", "选2", "选择2"}:
        intents.append("supplement_materials")
    if compact in {"3", "3.", "3。", "三", "选3", "选择3"}:
        intents.append("customer_html_prompt")
    if compact in {"4", "4.", "4。", "四", "选4", "选择4"}:
        intents.append("wow_claude")
    if compact in {"5", "5.", "5。", "五", "选5", "选择5"}:
        intents.append("wow_codex")
    if compact in {"6", "6.", "6。", "六", "选6", "选择6"}:
        intents.append("crm_skill")
    if re.search(r"\b(wow[-_\s]*)?claude\b", text) or "claude" in text:
        intents.append("wow_claude")
    if re.search(r"\b(wow[-_\s]*)?codex\b", text) or "codex" in text:
        intents.append("wow_codex")
    if any(
        key in reply
        for key in [
            "补资料",
            "补充资料",
            "查资料",
            "团队资料",
            "既往客户",
            "历史客户",
            "客户背景",
            "本地资料",
            "本地知识库",
            "团队知识库",
            "公开资料",
            "联网",
            "搜索",
            "检索",
        ]
    ):
        intents.append("supplement_materials")
    if any(
        key in reply
        for key in [
            "客户展示",
            "客户页",
            "对外页",
            "展示页",
            "展示HTML",
            "展示 html",
            "成果页",
            "可视化",
            "可视化页",
            "客户报告",
            "生成HTML",
            "生成 html",
            "HTML",
        ]
    ):
        intents.append("customer_html_prompt")
    if reply.strip() in {
        "默认",
        "default",
        "默认路线",
        "不补资料",
        "不用补资料",
        "直接分析",
        "内部分析",
        "先分析",
        "走默认",
    }:
        intents.append("agent_default")
    if any(key in reply for key in ["客户洽谈", "客户洽谈Skill", "客户洽谈 skill", "skill_客户洽谈", "crm"]):
        intents.append("crm_skill")

    deduped: list[str] = []
    for intent in intents:
        if intent not in deduped:
            deduped.append(intent)
    return deduped


def classify_reply(reply: str) -> dict[str, Any]:
    intents = detect_intents(reply)
    priority = [
        "supplement_materials",
        "wow_claude",
        "wow_codex",
        "customer_html_prompt",
        "crm_skill",
        "agent_default",
    ]
    route = next((item for item in priority if item in intents), "ambiguous")

    route_meta = {
        "agent_default": {
            "status": "agent_handoff_ready",
            "stage": "meeting/skill_route",
            "needs_user_context": False,
            "label": DEFAULT_ROUTE_LABEL,
            "next_action": "Use the current Agent's native analysis ability from the transcript/notes. Do not invoke a specialist Skill unless the user explicitly asks.",
        },
        "crm_skill": {
            "status": "agent_handoff_ready",
            "stage": "meeting/skill_route",
            "needs_user_context": False,
            "label": CRM_SKILL_ROUTE_LABEL,
            "next_action": "Use crm / skill_客户洽谈 from the transcript. Write transcript-backed analysis before any customer-facing page.",
        },
        "supplement_materials": {
            "status": "needs_agent_context_materials",
            "stage": "meeting/context_materials",
            "needs_user_context": False,
            "label": "补资料",
            "next_action": "Search and summarize relevant team, prior customer, local, or public web materials before final analysis.",
        },
        "wow_claude": {
            "status": "remote_agent_handoff_ready",
            "stage": "meeting/remote_agent_handoff",
            "needs_user_context": False,
            "label": "WOW-Claude",
            "next_action": "Prepare materials for an interactive WOW Claude session. Do not run it silently in the background.",
        },
        "wow_codex": {
            "status": "remote_agent_handoff_ready",
            "stage": "meeting/remote_agent_handoff",
            "needs_user_context": False,
            "label": "WOW-Codex",
            "next_action": "Prepare materials for an interactive WOW Codex session. Do not run it silently in the background.",
        },
        "customer_html_prompt": {
            "status": "visual_prompt_required",
            "stage": "meeting/visual_prompt",
            "needs_user_context": False,
            "label": VISUAL_ROUTE,
            "next_action": "Use meeting-visual-report to generate a structured Prompt first. Wait for user confirmation before final HTML.",
        },
        "ambiguous": {
            "status": "needs_user_context",
            "stage": "meeting/context",
            "needs_user_context": True,
            "label": "ambiguous",
            "next_action": "Reply with the route menu and ask the user to choose 1/默认, 2/补资料, 3/客户展示HTML, 4/WOW-Claude, 5/WOW-Codex, or 6/客户洽谈Skill.",
        },
    }[route]

    return {"route": route, "intents": intents, **route_meta}


def rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def path_from_case(case_dir: Path, meta: dict[str, Any], key: str, fallback: str) -> str:
    paths = meta.get("paths") if isinstance(meta.get("paths"), dict) else {}
    value = str(paths.get(key) or fallback)
    return value


def build_agent_handoff(case_dir: Path, meta: dict[str, Any], decision: dict[str, Any], note_path: str) -> str:
    title = str(meta.get("title") or case_dir.name)
    transcript = path_from_case(case_dir, meta, "transcript", "source/meeting_transcript.md")
    ai_notes = path_from_case(case_dir, meta, "ai_notes", "source/ai_notes.md")
    analysis_request = path_from_case(case_dir, meta, "analysis_request", "analysis/analysis_request.md")
    remote_handoff = path_from_case(case_dir, meta, "remote_agent_handoff", "analysis/remote_agent_handoff.md")

    lines = [
        f"# Meeting Chain Agent Handoff: {title}",
        "",
        "## Route Decision",
        "",
        f"- route: `{decision['route']}`",
        f"- label: `{decision['label']}`",
        f"- status: `{decision['status']}`",
        f"- stage: `{decision['stage']}`",
        f"- detected_intents: `{', '.join(decision.get('intents') or []) or 'none'}`",
        "",
        "## Case Inputs",
        "",
        f"- case_dir: `{case_dir}`",
        f"- transcript: `{transcript}`",
        f"- ai_notes: `{ai_notes}`",
        f"- analysis_request: `{analysis_request}`",
    ]
    if note_path:
        lines.append(f"- user_context_note: `{note_path}`")
    lines.extend(
        [
            "",
            "## Next Action",
            "",
            f"- {decision['next_action']}",
            "",
            "## Guardrails",
            "",
            "- Read the transcript before writing analysis.",
            "- Do not include app secrets, auth tokens, cookies, raw private logs, or signed Feishu media URLs in outputs.",
            "- Do not make customer-facing claims that are not supported by the transcript or explicit supplementary materials.",
            "- Keep final HTML under `html/` in this case.",
        ]
    )

    route = decision["route"]
    if route == "agent_default":
        lines.extend(
            [
                "",
                "## Default Agent Route",
                "",
                "- Use the current Agent directly for meeting analysis.",
                "- Do not load a specialist analysis skill by default.",
                "- Read the transcript/notes and write `analysis/meeting_analysis.md`.",
                "- Use other skills only if the user explicitly chooses another route.",
            ]
        )
    elif route == "crm_skill":
        lines.extend(
            [
                "",
                "## crm Route",
                "",
                "- Use `crm` / `skill_客户洽谈` because the user explicitly chose it.",
                "- Start with the meeting-minutes style output unless the user asks for the full five-stage customer flow.",
                "- Save or declare all generated outputs in the current case. `agent_output/` alone is not a finished meeting-chain delivery.",
                "- Run `finalize_route.py --case-dir <case-dir> --route crm_skill --scan-case` after outputs exist.",
                "- Ask the user to confirm before Feishu upload/send, then rerun `finalize_route.py --approve`.",
            ]
        )
    elif route == "supplement_materials":
        lines.extend(
            [
                "",
                "## Supplement Route",
                "",
                "- Search the user-approved team/customer/local/web sources.",
                "- Write a concise material pack to `analysis/context_materials.md`.",
                "- If using web sources, include source links and exact access dates.",
                "- After supplementation, ask whether to proceed with `默认`, `WOW-Codex`, `WOW-Claude`, or `客户展示HTML`.",
            ]
        )
    elif route in REMOTE_ROUTES:
        lines.extend(
            [
                "",
                "## WOW Route",
                "",
                f"- Read `{remote_handoff}` before connecting.",
                "- From the old Mac, use `ssh wow-lan` to enter WOW.",
                "- Claude route uses `ccd` and requires the user to enter the WOW login password locally if prompted.",
                "- Codex route uses `codex`.",
                "- Copy remote outputs back into this case under `html/` or `analysis/remote_outputs/`.",
                "- Run `finalize_route.py --case-dir <case-dir> --route " + route + " --scan-case` after outputs are copied back.",
            ]
        )
    elif route == "customer_html_prompt":
        lines.extend(
            [
                "",
                "## meeting-visual-report Route",
                "",
                "- Trigger `meeting-visual-report`.",
                "- Produce the structured Prompt first and wait for user confirmation.",
                "- After confirmation, generate final standalone HTML under `html/`.",
                "- Run `finalize_route.py --case-dir <case-dir> --route customer_html_prompt --scan-case`; wait for final user approval before `--send`.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Clarification Needed",
                "",
                "- Ask the user to choose exactly one route from the menu:",
                "  1. `默认` - internal analysis by the current Agent, no specialist Skill",
                "  2. `补资料` - supplement team/local/web materials before analysis",
                "  3. `客户展示HTML` - use `meeting-visual-report`, Prompt first",
                "  4. `WOW-Claude` - prepare interactive WOW Claude handoff",
                "  5. `WOW-Codex` - prepare interactive WOW Codex handoff",
                "  6. `客户洽谈Skill` - explicitly use `crm` / `skill_客户洽谈`",
            ]
        )
    return "\n".join(lines) + "\n"


def write_context_note(case_dir: Path, note: str) -> str:
    if not note.strip():
        return ""
    if has_secret_content(note):
        raise SystemExit("Refusing to write a context note that looks like it contains credentials or tokens.")
    note_path = case_dir / "analysis" / "user_context_note.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# User Context Note\n\n" + sanitize_text(note, limit=4000) + "\n", encoding="utf-8")
    return rel(note_path, case_dir)


def update_case(case_dir: Path, reply: str, note: str = "") -> dict[str, Any]:
    if has_secret_content(reply):
        raise SystemExit("Refusing to process a reply that looks like it contains credentials or tokens.")
    ensure_source_resolved(case_dir, "record route decision")
    case_json = case_dir / "case.json"
    meta = read_json(case_json, {})
    if not isinstance(meta, dict):
        meta = {}

    decision = classify_reply(reply)
    analysis_dir = case_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    note_rel = write_context_note(case_dir, note)

    decision_payload = {
        "created_at": now_iso(),
        "reply_summary": sanitize_text(reply),
        "route": decision["route"],
        "label": decision["label"],
        "status": decision["status"],
        "stage": decision["stage"],
        "needs_user_context": decision["needs_user_context"],
        "detected_intents": decision["intents"],
        "next_action": decision["next_action"],
    }
    route_decision_path = analysis_dir / "route_decision.json"
    agent_handoff_path = analysis_dir / "agent_handoff.md"
    write_json(route_decision_path, decision_payload)
    agent_handoff_path.write_text(build_agent_handoff(case_dir, meta, decision, note_rel), encoding="utf-8")

    if decision["route"] == "supplement_materials":
        (analysis_dir / "context_materials_request.md").write_text(
            "\n".join(
                [
                    "# Context Materials Request",
                    "",
                    "请先补充与本场会议相关的团队资料、既往客户内容、客户背景、本地资料库或公开网络材料。",
                    "",
                    "## Output",
                    "",
                    "- Write the material pack to `analysis/context_materials.md`.",
                    "- Keep public web source links and access dates.",
                    "- Do not copy credentials, private logs, unrelated customer material, or large binary files into the case.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if decision["route"] == "customer_html_prompt":
        (analysis_dir / "visual_prompt_request.md").write_text(
            "\n".join(
                [
                    "# Visual Report Prompt Request",
                    "",
                    "使用 `meeting-visual-report` 读取 transcript 和 AI Notes，先生成结构化 Prompt 给用户确认。",
                    "用户确认后，才生成最终客户展示 HTML，并保存到 `html/`。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    paths = meta.get("paths") if isinstance(meta.get("paths"), dict) else {}
    paths.update(
        {
            "route_decision": rel(route_decision_path, case_dir),
            "agent_handoff": rel(agent_handoff_path, case_dir),
        }
    )
    if note_rel:
        paths["user_context_note"] = note_rel
    meta.update(
        {
            "updated_at": now_iso(),
            "analysis_status": decision["status"],
            "analysis_stage": decision["stage"],
            "needs_user_context": decision["needs_user_context"],
            "route_decision": {
                "route": decision["route"],
                "label": decision["label"],
                "detected_intents": decision["intents"],
                "created_at": decision_payload["created_at"],
            },
            "paths": paths,
        }
    )
    write_json(case_json, meta)
    return {
        "ok": decision["route"] != "ambiguous",
        "case_dir": str(case_dir),
        "route": decision["route"],
        "status": decision["status"],
        "stage": decision["stage"],
        "needs_user_context": decision["needs_user_context"],
        "route_decision": str(route_decision_path),
        "agent_handoff": str(agent_handoff_path),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a meeting context-gate reply into a case.")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--reply", required=True)
    parser.add_argument("--note", default="", help="Optional user-approved supplemental note to store with the case.")
    parser.add_argument("--output-json", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    case_dir = ensure_case_dir(args.case_dir)
    result = update_case(case_dir, args.reply, args.note)
    if args.output_json:
        write_json(Path(args.output_json).expanduser(), result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

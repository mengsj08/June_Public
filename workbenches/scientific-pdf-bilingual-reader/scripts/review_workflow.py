#!/usr/bin/env python3
"""Persistent human-in-the-loop QA diagnosis and candidate repair workflow."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from artifact_transaction import install_artifact_set, next_version_dir
from qa_contract import (
    QA_RULE_VERSION, attention_summary, build_contract, issue_review_id,
    new_deterministic_visual_violations, sha256_file, sha256_payload, verify_contract,
)
from review_cycle import write_page_manifest

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSIS_SCHEMA = ROOT / "references" / "diagnosis-schema.json"
REPAIR_ADVICE_SCHEMA = ROOT / "references" / "repair-advice-schema.json"
ALLOWED_DECISIONS = {"pending", "ignored", "confirmed_problem"}
ALLOWED_FAMILIES = {
    "unexpected_text", "toc_layout", "rotation_layout", "table_layout",
    "table_untranslated", "form_untranslated", "layout", "untranslated_region",
}
COMPATIBLE_ADVICE_FAMILIES = {
    "untranslated_region": {
        "untranslated_region", "table_untranslated", "form_untranslated",
        "table_layout", "layout",
    },
    "table_untranslated": {"table_untranslated", "table_layout"},
    "table_layout": {"table_layout", "table_untranslated", "layout"},
    "form_untranslated": {"form_untranslated", "layout"},
    "layout": {"layout", "table_layout", "table_untranslated", "form_untranslated"},
}
ATTEMPT_SCHEMA = "repair-attempt/v1"
HUMAN_REVIEW_SCHEMA = "human-page-review/v1"
ATTEMPT_KEY_SCHEMA = "repair-attempt-key/v1"
ADVICE_SCHEMA_VERSION = "claude-repair-strategy-advice/v1"
EXECUTION_SCHEMA_VERSION = "qa-repair-harness-execution/v1"
FAILURE_REPORT_SCHEMA = "repair-failure-report/v1"
JUNE_DECISION_SCHEMA = "repair-escalation-decision/v1"
ADVISOR_RECOVERY_STRATEGY_ID = "retry_claude_advice_after_infra_fix"
OPEN_ATTEMPT_STATUSES = {"advising", "diagnosed", "repairing", "awaiting_acceptance", "repair_escalated"}
TERMINAL_ATTEMPT_STATUSES = {"accepted", "rejected", "stopped", "escalation_decided"}
# Codex/Claude desktop subscriptions are a shared local resource.  Parallel
# ephemeral CLI sessions can make otherwise healthy requests fail upstream,
# so every direct Agent invocation in the workbench is serialized here.
MODEL_CLI_LOCK = threading.Lock()


def ensure_localhost_no_proxy(env: dict[str, str]) -> dict[str, str]:
    required = ("127.0.0.1", "localhost", "::1")
    for key in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in str(env.get(key, "")).split(",") if item.strip()]
        folded = {item.casefold() for item in existing}
        env[key] = ",".join([*existing, *(item for item in required if item.casefold() not in folded)])
    return env


class ProviderInvocationError(RuntimeError):
    """The local model CLI failed before returning usable structured output."""


class AdviceRetriesExhausted(RuntimeError):
    """All bounded Claude advice calls failed, with their audit events attached."""

    def __init__(self, message: str, retry_events: list[dict]):
        super().__init__(message)
        self.retry_events = retry_events


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.is_file() else default
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp.replace(path)


def review_path(folder: Path) -> Path:
    return folder / "review-state.json"


def repair_root(folder: Path) -> Path:
    return folder / "repairs"


def human_review_root(folder: Path) -> Path:
    return folder / "human-reviews"


def human_review_record_path(folder: Path, review_id: str) -> Path:
    return human_review_root(folder) / review_id / "review.json"


def repair_record_path(folder: Path, repair_id: str) -> Path:
    return repair_root(folder) / repair_id / "repair.json"


def failure_report_path(folder: Path, repair_id: str, kind: str = "json") -> Path:
    suffix = "md" if kind == "md" else "json"
    return repair_root(folder) / repair_id / f"failure-report.{suffix}"


def now() -> float:
    return time.time()


def folder_relative_path(folder: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def stable_issue_id(pdf_page: int, issue: dict, index: int) -> str:
    return issue_review_id(pdf_page, issue)


def load_review(folder: Path) -> dict:
    return read_json(review_path(folder), {"version": 1, "issues": {}, "updated_at": None})


def update_decision(folder: Path, issue_id: str, decision: str) -> dict:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("不支持的复核决定")
    review = load_review(folder)
    review["issues"][issue_id] = {"decision": decision, "updated_at": time.time()}
    review["updated_at"] = time.time()
    write_json(review_path(folder), review)
    return review["issues"][issue_id]


def list_human_reviews(folder: Path) -> list[dict]:
    records = []
    root = human_review_root(folder)
    for item in sorted(root.glob("*/review.json")) if root.is_dir() else []:
        record = read_json(item, {})
        if record:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)


def build_review(folder: Path, task: dict) -> dict:
    report = read_json(folder / task.get("qa_alpha_file", "qa-alpha.json"), {})
    document_plan = read_json(folder / task.get("document_plan_file", "document-plan.json"), {})
    routes = {
        int(page.get("page", page.get("pdf_page", 0))): page
        for page in document_plan.get("pages", [])
        if page.get("page", page.get("pdf_page")) is not None
    }
    freshness = verify_contract(
        report,
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=folder / task.get("translated_file", "translated-zh.pdf"),
        plan_path=folder / task.get("page_plan_file", "page-plan.json"),
        task=task,
    ) if report else {"status": "missing", "reason": "missing_report"}
    review = load_review(folder)
    repairs = []
    for item in sorted(repair_root(folder).glob("*/repair.json")) if repair_root(folder).is_dir() else []:
        repair = read_json(item, {})
        if repair:
            repairs.append(repair)
    escalations = [
        repair for repair in repairs
        if repair.get("status") == "repair_escalated" and repair.get("failure_report")
    ]
    human_reviews = list_human_reviews(folder)
    pages = []
    report_pages = {int(page.get("pdf_page", 0)): page for page in report.get("pages", [])}
    page_count = int(report.get("page_count") or max(report_pages, default=0))
    for pdf_page in range(1, page_count + 1):
        page = report_pages.get(pdf_page, {"pdf_page": pdf_page, "status": "pass", "metrics": {}, "issues": []})
        issues_by_id = {}
        for index, raw in enumerate(page.get("issues", [])):
            issue_id = stable_issue_id(page["pdf_page"], raw, index)
            state = review.get("issues", {}).get(issue_id, {"decision": "pending"})
            issues_by_id.setdefault(issue_id, {**raw, "issue_id": issue_id, "review": state})
        issues = list(issues_by_id.values())
        pages.append({
            "pdf_page": page["pdf_page"], "status": page.get("status", "pass"),
            "metrics": page.get("metrics", {}), "issues": issues,
            "route": routes.get(pdf_page, {}).get("route"),
            "human_review_count": sum(
                1 for item in human_reviews if int(item.get("pdf_page", 0)) == pdf_page
            ),
        })
    return {
        "task": {"id": task["id"], "name": task.get("name"), "provider": task.get("provider", "codex")},
        "qa": {
            "status": report.get("status"), "page_count": report.get("page_count"),
            "summary": report.get("summary", {}), "baseline": report.get("baseline"),
            "issue_category_summary": report.get("issue_category_summary", {}),
            "freshness": freshness,
        },
        "attention": attention_summary(pages, report.get("document_issues", [])),
        "pages": pages,
        "human_reviews": human_reviews,
        "repairs": sorted(repairs, key=lambda x: x.get("created_at", 0), reverse=True),
        "escalations": sorted(escalations, key=lambda x: x.get("updated_at", 0), reverse=True),
    }


def list_repairs(folder: Path) -> list[dict]:
    records = []
    for item in sorted(repair_root(folder).glob("*/repair.json")) if repair_root(folder).is_dir() else []:
        record = read_json(item, {})
        if record:
            records.append(record)
    return records


def open_attempts(folder: Path, *, exclude_repair_id: str | None = None) -> list[dict]:
    return [
        record for record in list_repairs(folder)
        if record.get("status") in OPEN_ATTEMPT_STATUSES and record.get("repair_id") != exclude_repair_id
    ]


def require_no_open_attempt(folder: Path, *, exclude_repair_id: str | None = None) -> None:
    active = open_attempts(folder, exclude_repair_id=exclude_repair_id)
    if active:
        current = active[0]
        raise RuntimeError(
            f"已有未关闭 repair attempt：{current.get('repair_id')}（{current.get('status')}），同一任务必须串行处理"
        )


def require_fresh_contract(folder: Path, task: dict, report: dict | None = None) -> dict:
    qa = report or read_json(folder / task.get("qa_alpha_file", "qa-alpha.json"), {})
    if not qa:
        raise RuntimeError("QA 报告缺失，不能建立 repair attempt")
    freshness = verify_contract(
        qa,
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=folder / task.get("translated_file", "translated-zh.pdf"),
        plan_path=folder / task.get("page_plan_file", "page-plan.json"),
        task=task,
    )
    if freshness.get("status") != "fresh":
        raise RuntimeError(f"QA 合同 stale，不能比较红色问题：{freshness.get('message')}")
    contract = qa.get("contract", {})
    if contract.get("qa_rule_version") != QA_RULE_VERSION:
        raise RuntimeError("当前 QA 规则版本与冻结合同不一致，不能修复")
    return {"report": qa, "freshness": freshness, "contract": contract}


def red_pages(report: dict) -> set[int]:
    return {int(page.get("pdf_page")) for page in report.get("pages", []) if page.get("status") == "red"}


def selected_issue_family(folder: Path, task: dict, review: dict, pdf_page: int,
                          issue_ids: list[str]) -> tuple[str, list[dict], dict]:
    page = next(item for item in review["pages"] if int(item["pdf_page"]) == pdf_page)
    selected = [item for item in page["issues"] if item["issue_id"] in issue_ids]
    if not selected:
        raise ValueError("没有选择有效的 QA 问题")
    if not any(item.get("severity") == "red" or page.get("status") == "red" for item in selected):
        raise ValueError("SKL-168 修复入口只处理 qa-contract/v1 的 red hard blocker")
    family = suggested_family([item["issue_type"] for item in selected], page_plan(folder, task, pdf_page))
    return family, selected, page


def execution_strategy(family: str, strategy_id: str | None = None, june_note: str | None = None) -> dict:
    return {
        "schema": EXECUTION_SCHEMA_VERSION,
        "strategy_id": strategy_id or f"claude-primary-{family}",
        "executor": "qa_repair_harness",
        "executor_provider": "codex",
        "family": family,
        "june_note": june_note or "",
    }


def attempt_identity(task: dict, pdf_page: int, family: str, contract: dict,
                     strategy: dict, previous_report_id: str | None = None) -> dict:
    key = {
        "schema": ATTEMPT_KEY_SCHEMA,
        "task_id": task["id"],
        "pdf_page": int(pdf_page),
        "problem_family": family,
        "current_output_contract_sha256": contract.get("contract_sha256"),
        "current_output_pdf_sha256": contract.get("outputs", {}).get("translated_pdf", {}).get("sha256"),
        "qa_rule_version": contract.get("qa_rule_version"),
        "claude_advice_version": ADVICE_SCHEMA_VERSION,
        "execution_strategy": {
            "schema": strategy.get("schema"),
            "strategy_id": strategy.get("strategy_id"),
            "executor": strategy.get("executor"),
            "executor_provider": strategy.get("executor_provider"),
            "family": strategy.get("family"),
        },
        "previous_failure_report_id": previous_report_id,
    }
    digest = sha256_payload(key)[:16]
    return {"attempt_id": f"attempt-{digest}", "attempt_key": key, "attempt_key_sha256": sha256_payload(key)}


def ensure_attempt_not_reused(folder: Path, identity: dict) -> None:
    target_key = identity["attempt_key_sha256"]
    for record in list_repairs(folder):
        if record.get("attempt_key_sha256") == target_key:
            raise RuntimeError(
                f"同一任务、页码、问题族和输入版本已有 repair attempt：{record.get('repair_id')}（{record.get('status')}）"
            )


def model_cli_available(provider: str) -> bool:
    return shutil.which(provider) is not None


def ensure_repair_model_health(*, require_codex: bool = True, require_claude: bool = True) -> None:
    missing = []
    if require_claude and not model_cli_available("claude"):
        missing.append("claude")
    if require_codex and not model_cli_available("codex"):
        missing.append("codex")
    if missing:
        raise RuntimeError(f"修复熔断链路要求本机 CLI 可用，当前缺失：{', '.join(missing)}")


def task_artifact_path(folder: Path, task: dict, key: str, default: str) -> Path:
    relative = Path(task.get(key) or default)
    if relative.is_absolute():
        raise RuntimeError("任务文件引用必须位于任务目录内")
    target = (folder / relative).resolve()
    if folder.resolve() not in target.parents:
        raise RuntimeError("任务文件引用越出任务目录")
    if not target.is_file():
        raise FileNotFoundError(f"任务文件不存在：{relative}")
    return target


def render_page_images(
    folder: Path, task: dict, pdf_page: int, repair_id: str,
    *, artifact_root: Path | None = None,
) -> tuple[Path, Path]:
    import fitz

    output = (artifact_root or repair_root(folder)) / repair_id / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    sources = (
        (task_artifact_path(folder, task, "original_file", "original.pdf"), "source.png"),
        (task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"), "translated.png"),
    )
    for source, name in sources:
        document = fitz.open(source)
        if pdf_page < 1 or pdf_page > len(document):
            raise ValueError("页码超出 PDF 范围")
        pixmap = document[pdf_page - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        target = output / name
        pixmap.save(target)
        paths.append(target)
    return paths[0], paths[1]


def suggested_family(issue_types: list[str], plan: dict | None) -> str:
    joined = " ".join(issue_types)
    if "unexpected_repetition" in joined or "unexpected_control_characters" in joined:
        return "unexpected_text"
    if "toc_layout" in joined:
        return "toc_layout"
    if "rotation" in joined or "text_direction" in joined:
        return "rotation_layout"
    if "untranslated" in joined or "translation_coverage" in joined:
        return "untranslated_region"
    page_type = (plan or {}).get("type", "")
    if page_type in {"cell_table", "dense_table", "dense_table_continuation"}:
        return "table_layout"
    if "structure" in joined or "crowded" in joined or "missing" in joined:
        return "layout"
    return "untranslated_region"


def page_plan(folder: Path, task: dict, pdf_page: int) -> dict | None:
    plan = read_json(task_artifact_path(folder, task, "page_plan_file", "page-plan.json"), {})
    return next((item for item in plan.get("pages", []) if int(item.get("pdf_page", 0)) == pdf_page), None)


def diagnosis_prompt(task: dict, page: dict, selected: list[dict], feedback: str, family: str) -> str:
    compact = [{key: issue.get(key) for key in ("issue_id", "issue_type", "severity", "evidence", "region")} for issue in selected]
    return f"""你是科研 PDF 翻译质量复核员。只诊断第 {page['pdf_page']} 页，不修改文件，也不要扩大范围。

文档：{task.get('name')}
确定性 QA：{json.dumps(compact, ensure_ascii=False)}
页面指标：{json.dumps(page.get('metrics', {}), ensure_ascii=False)}
用户补充：{feedback or '无'}
规则建议的问题族：{family}

结合两张附件（原文页、当前中文页）判断：这是否是真问题、根因、建议的页面级修复策略、风险与消耗等级。保留数字、金额、日期、法规编号、缩略语和专有名词。repair_family 必须从以下值选择：{', '.join(sorted(ALLOWED_FAMILIES))}。只输出符合 schema 的 JSON。"""


def human_review_prompt(task: dict, page: dict, feedback: str, family: str) -> str:
    return f"""你是科研 PDF 翻译质量复核员。June 主动报告了第 {page['pdf_page']} 页的阅读体验问题。只做只读分析，不修改 PDF，不生成候选，也不要扩大到其他页面。

文档：{task.get('name')}
June 的人工发现：{feedback}
页面指标（仅供参考，不得用“机器未报警”否定人工发现）：{json.dumps(page.get('metrics', {}), ensure_ascii=False)}
页面策略建议的问题族：{family}

结合两张附件（原文页、当前中文页）判断：人工发现是否成立、视觉或翻译根因、下一轮应重点处理的页面级范围、必须保护的数字/金额/日期/法规编号/缩略语/专有名词，以及风险和消耗等级。repair_family 必须从以下值选择：{', '.join(sorted(ALLOWED_FAMILIES))}。只输出符合 schema 的 JSON。"""


def create_human_review(folder: Path, task: dict, pdf_page: int, feedback: str) -> dict:
    feedback = str(feedback).strip()
    if not feedback:
        raise ValueError("请先填写本页的人工发现")
    review = build_review(folder, task)
    page = next((item for item in review["pages"] if int(item["pdf_page"]) == int(pdf_page)), None)
    if page is None:
        raise ValueError("页码超出当前 PDF 范围")
    created_at = now()
    review_id = "human-" + sha256_payload({
        "task_id": task["id"], "pdf_page": int(pdf_page),
        "feedback": feedback, "created_at": created_at,
    })[:16]
    record = {
        "schema": HUMAN_REVIEW_SCHEMA,
        "review_id": review_id,
        "task_id": task["id"],
        "pdf_page": int(pdf_page),
        "feedback": feedback[:2000],
        "status": "advising",
        "advisor_provider": "claude",
        "next_repair_input": True,
        "current_output_sha256": sha256_file(
            task_artifact_path(folder, task, "translated_file", "translated-zh.pdf")
        ).get("sha256"),
        "created_at": created_at,
        "updated_at": created_at,
    }
    write_json(human_review_record_path(folder, review_id), record)
    return record


def diagnose_human_review(folder: Path, task: dict, review_id: str) -> None:
    record_path = human_review_record_path(folder, review_id)
    record = read_json(record_path, {})
    try:
        ensure_repair_model_health(require_codex=False, require_claude=True)
        review = build_review(folder, task)
        pdf_page = int(record.get("pdf_page", 0))
        page = next(item for item in review["pages"] if int(item["pdf_page"]) == pdf_page)
        family = suggested_family(["user_reported_page_issue"], page_plan(folder, task, pdf_page))
        source_image, translated_image = render_page_images(
            folder, task, pdf_page, review_id, artifact_root=human_review_root(folder),
        )
        output = record_path.parent / "diagnosis.json"
        diagnosis = run_model(
            "claude",
            human_review_prompt(task, page, record.get("feedback", ""), family),
            source_image,
            translated_image,
            output,
            DIAGNOSIS_SCHEMA,
        )
        write_json(output, diagnosis)
        record.update(
            status="diagnosed",
            diagnosis=diagnosis,
            evidence={
                "source_image": str(source_image.relative_to(folder)),
                "translated_image": str(translated_image.relative_to(folder)),
                "diagnosis": str(output.relative_to(folder)),
            },
            updated_at=now(),
        )
    except Exception as exc:
        record.update(status="failed", error=str(exc)[:1000], updated_at=now())
    write_json(record_path, record)


def advice_prompt(task: dict, page: dict, selected: list[dict], feedback: str,
                  family: str, previous_report: dict | None = None) -> str:
    compact = [{key: issue.get(key) for key in ("issue_id", "issue_type", "severity", "issue_category", "user_impact", "evidence", "region")} for issue in selected]
    prior = json.dumps(previous_report or {}, ensure_ascii=False)[:6000] if previous_report else "无"
    return f"""你是科研 PDF 修复策略顾问。只读分析，不修改 PDF，不输出任何文件操作命令。

目标：为第 {page['pdf_page']} 页 qa-contract/v1 红色 hard blocker 提出一次有边界的修复策略；Claude 只给建议，后续由 Codex/确定性 harness 执行一次候选。

文档：{task.get('name')}
QA 规则版本：{QA_RULE_VERSION}
问题族候选：{family}
选中的红色问题：{json.dumps(compact, ensure_ascii=False)}
页面指标：{json.dumps(page.get('metrics', {}), ensure_ascii=False)}
June 补充：{feedback or '无'}
上一失败报告：{prior}

要求：
1. schema 固定为 {ADVICE_SCHEMA_VERSION}。
2. execution_family 必须从以下值选择：{', '.join(sorted(ALLOWED_FAMILIES))}。默认保持 {family}；只有同一页的视觉证据要求更具体处理时，才可在这些兼容族内收窄：{', '.join(sorted(COMPATIBLE_ADVICE_FAMILIES.get(family, {family})))}。
3. bounded_steps 只描述本页、本问题族、一次候选内能执行的动作，不扩大到整本文档。
4. alternatives 最多 3 个，必须有明确边界、风险和成本；不要自动选择第二方案。
5. 永远不要建议覆盖正式 PDF 或清空历史。
只输出符合 schema 的 JSON。"""


def run_model(provider: str, prompt: str, source_image: Path, translated_image: Path,
              output_file: Path, schema_file: Path = DIAGNOSIS_SCHEMA) -> dict:
    isolated_workspace = None
    run_input = None
    run_cwd = None
    if provider == "codex":
        isolated_workspace = tempfile.TemporaryDirectory(prefix="pdf-reader-review-")
        cmd = [
            "codex", "exec", "--ephemeral", "--ignore-rules", "--ignore-user-config",
            "--skip-git-repo-check", "-C", isolated_workspace.name, "-s", "read-only",
            "--disable", "shell_tool", "--disable", "unified_exec",
            "--disable", "apps", "--disable", "browser_use",
            "--disable", "in_app_browser", "--disable", "multi_agent",
            "--output-schema", str(schema_file), "-i", str(source_image),
            "-i", str(translated_image), "-o", str(output_file), "-",
        ]
        run_input = prompt
    elif provider == "claude":
        isolated_workspace = tempfile.TemporaryDirectory(prefix="pdf-reader-claude-review-")
        shutil.copy2(source_image, Path(isolated_workspace.name) / "source-page.png")
        shutil.copy2(translated_image, Path(isolated_workspace.name) / "translated-page.png")
        schema_payload = read_json(schema_file, {})
        if not isinstance(schema_payload, dict) or not schema_payload:
            raise RuntimeError("Claude 结构化输出 schema 缺失或不是 JSON object")
        # Claude CLI validates the supplied schema with its own validator and
        # does not load the draft 2020-12 meta-schema URI. Keep the canonical
        # repository schema intact, but omit that annotation in the CLI copy.
        schema_payload = {key: value for key, value in schema_payload.items() if key != "$schema"}
        schema = json.dumps(schema_payload, ensure_ascii=False)
        cmd = [
            "claude", "-p", "--safe-mode", "--setting-sources", "",
            "--strict-mcp-config", "--tools", "Read", "--allowedTools", "Read",
            "--permission-mode", "dontAsk", "--no-session-persistence",
            "--json-schema", schema,
            prompt + "\n图片路径：source-page.png\ntranslated-page.png",
        ]
        run_cwd = isolated_workspace.name
    else:
        raise ValueError("不支持的模型提供方")
    try:
        with MODEL_CLI_LOCK:
            done = subprocess.run(
                cmd, capture_output=True, text=True, timeout=360,
                input=run_input, cwd=run_cwd,
            )
    finally:
        if isolated_workspace is not None:
            isolated_workspace.cleanup()
    if done.returncode:
        raise ProviderInvocationError((done.stderr or done.stdout)[-1000:])
    raw = output_file.read_text() if provider == "codex" and output_file.is_file() else done.stdout
    payload = json.loads(raw)
    if provider == "claude" and isinstance(payload, dict) and "structured_output" in payload:
        payload = payload["structured_output"]
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    candidates = reviews if isinstance(reviews, list) else [payload]
    if not candidates or any(
        not isinstance(item, dict)
        or (item.get("repair_family") or item.get("execution_family")) not in ALLOWED_FAMILIES
        for item in candidates
    ):
        raise RuntimeError("模型返回了不支持的修复类型")
    return payload


def normalize_advice(raw: dict, expected_family: str) -> dict:
    family = raw.get("execution_family") or raw.get("repair_family") or expected_family
    if family not in ALLOWED_FAMILIES:
        raise RuntimeError("Claude 建议返回了不支持的问题族")
    compatible = COMPATIBLE_ADVICE_FAMILIES.get(expected_family, {expected_family})
    if family not in compatible:
        raise RuntimeError(f"Claude 建议越过当前 attempt 兼容问题族：{expected_family} -> {family}")
    alternatives = raw.get("alternatives") or []
    if not isinstance(alternatives, list):
        alternatives = []
    normalized = {
        "schema": ADVICE_SCHEMA_VERSION,
        "is_repairable": bool(raw.get("is_repairable", raw.get("is_real_problem", True))),
        "problem_family": raw.get("problem_family") or expected_family,
        "strategy_summary": raw.get("strategy_summary") or raw.get("recommended_action") or "",
        "execution_family": family,
        "bounded_steps": raw.get("bounded_steps") or [raw.get("recommended_action") or f"按 {family} 生成一次候选修复"],
        "validation_expectations": raw.get("validation_expectations") or ["目标页不再为 red", "全篇不新增 red", "等待 June 人工接受"],
        "protected_content": raw.get("protected_content") or [],
        "risks": raw.get("risks") or [raw.get("risk") or "需要人工查看候选页确认视觉结果"],
        "alternatives": alternatives[:3],
    }
    if not normalized["strategy_summary"]:
        raise RuntimeError("Claude 建议缺少 strategy_summary")
    return normalized


def inspect_execution_readiness(folder: Path, task: dict, record: dict) -> dict:
    family = (record.get("execution_strategy") or {}).get("family")
    pdf_page = int(record.get("pdf_page") or 0)
    if family not in {"table_layout", "table_untranslated"}:
        return {
            "schema": "repair-execution-readiness/v1",
            "checked": True,
            "ready": True,
            "family": family,
            "pdf_page": pdf_page,
            "capability": "family_handler_available",
        }
    try:
        import fitz

        source_path = task_artifact_path(
            folder, task, "translation_source_file", task.get("original_file", "original.pdf")
        )
        document = fitz.open(source_path)
        try:
            if pdf_page < 1 or pdf_page > len(document):
                raise RuntimeError("目标页超出源 PDF 页数")
            tables = document[pdf_page - 1].find_tables(strategy="lines_strict").tables
            english_cells = 0
            for table in tables:
                for row in table.extract():
                    english_cells += sum(
                        1 for value in row
                        if value and len(re.findall(r"[A-Za-z]", str(value))) >= 3
                    )
        finally:
            document.close()
    except Exception as exc:
        return {
            "schema": "repair-execution-readiness/v1",
            "checked": True,
            "ready": False,
            "family": family,
            "pdf_page": pdf_page,
            "capability": "table_cell_inplace_replace",
            "reason_code": "table_preflight_error",
            "reason": f"表格执行能力预检失败：{exc}",
        }
    if not tables:
        return {
            "schema": "repair-execution-readiness/v1",
            "checked": True,
            "ready": False,
            "family": family,
            "pdf_page": pdf_page,
            "capability": "table_cell_inplace_replace",
            "detected_tables": 0,
            "english_cells": 0,
            "reason_code": "strict_table_detection_missing",
            "reason": "当前 harness 未在目标页检测到可原位替换的严格线框表格，禁止退回通用悬浮覆盖。",
        }
    if family == "table_untranslated" and not english_cells:
        return {
            "schema": "repair-execution-readiness/v1",
            "checked": True,
            "ready": False,
            "family": family,
            "pdf_page": pdf_page,
            "capability": "table_cell_inplace_replace",
            "detected_tables": len(tables),
            "english_cells": 0,
            "reason_code": "table_translation_targets_missing",
            "reason": "目标页虽检测到表格，但没有可确定性原位替换的英文单元格。",
        }
    return {
        "schema": "repair-execution-readiness/v1",
        "checked": True,
        "ready": True,
        "family": family,
        "pdf_page": pdf_page,
        "capability": "table_cell_inplace_replace",
        "detected_tables": len(tables),
        "english_cells": english_cells,
    }


def enforce_execution_readiness(folder: Path, task: dict, record: dict) -> dict:
    readiness = inspect_execution_readiness(folder, task, record)
    record["execution_readiness"] = readiness
    if readiness.get("ready"):
        return record
    return escalate_repair(
        folder,
        record,
        failure_stage="executor_capability",
        error=readiness.get("reason") or "当前确定性 harness 不具备已保存策略所需能力",
        unresolved=[readiness.get("reason") or "需要新增确定性执行能力"],
    )


def run_claude_advice(prompt: str, source_image: Path, translated_image: Path, output_file: Path,
                      expected_family: str, max_retries: int = 1,
                      advice_provider=None) -> tuple[dict, list[dict]]:
    retry_events = []
    for attempt in range(max_retries + 1):
        try:
            raw = advice_provider() if advice_provider else run_model(
                "claude", prompt, source_image, translated_image, output_file, REPAIR_ADVICE_SCHEMA,
            )
            advice = normalize_advice(raw, expected_family)
            return advice, retry_events
        except ProviderInvocationError as exc:
            retry_events.append({
                "kind": "provider_or_network_error",
                "attempt": attempt + 1,
                "error": str(exc)[:500],
                "at": now(),
            })
            if attempt >= max_retries:
                raise AdviceRetriesExhausted(str(exc), retry_events) from exc
        except (json.JSONDecodeError, KeyError, RuntimeError) as exc:
            retry_events.append({
                "kind": "structured_missing_or_invalid",
                "attempt": attempt + 1,
                "error": str(exc)[:500],
                "at": now(),
            })
            if attempt >= max_retries:
                raise AdviceRetriesExhausted(str(exc), retry_events) from exc
        except Exception as exc:
            retry_events.append({
                "kind": "provider_or_network_error",
                "attempt": attempt + 1,
                "error": str(exc)[:500],
                "at": now(),
            })
            if attempt >= max_retries:
                raise AdviceRetriesExhausted(str(exc), retry_events) from exc
    raise RuntimeError("Claude 建议重试预算耗尽")


def diagnosis_from_advice(advice: dict) -> dict:
    return {
        "is_real_problem": advice.get("is_repairable", True),
        "explanation": advice.get("strategy_summary", ""),
        "root_cause": advice.get("problem_family", ""),
        "recommended_action": "; ".join(advice.get("bounded_steps", [])),
        "scope": "single_page_problem_family",
        "risk": "; ".join(advice.get("risks", [])),
        "cost_level": "bounded_single_attempt",
        "repair_family": advice.get("execution_family"),
    }


def diagnose(folder: Path, task: dict, repair_id: str, pdf_page: int,
             issue_ids: list[str], provider: str, feedback: str, advice_provider=None) -> None:
    record_path = repair_record_path(folder, repair_id)
    record = read_json(record_path, {})
    try:
        if advice_provider is None:
            ensure_repair_model_health(require_codex=False, require_claude=True)
        review = build_review(folder, task)
        family, selected, page = selected_issue_family(folder, task, review, pdf_page, issue_ids)
        if record.get("evidence"):
            source_image = folder_relative_path(folder, record["evidence"]["source_image"])
            translated_image = folder_relative_path(folder, record["evidence"]["translated_image"])
        elif advice_provider is not None:
            source_image = record_path.parent / "evidence" / "source-not-rendered.png"
            translated_image = record_path.parent / "evidence" / "translated-not-rendered.png"
        else:
            source_image, translated_image = render_page_images(folder, task, pdf_page, repair_id)
        output = record_path.parent / "diagnosis.json"
        previous_report = read_json(folder_relative_path(folder, record["previous_failure_report"]), {}) if record.get("previous_failure_report") else None
        human_context = record.get("human_review_context") or []
        prompt_feedback = feedback
        if human_context:
            prompt_feedback = (
                f"{feedback}\n\n同页已保存的人工复核上下文："
                f"{json.dumps(human_context, ensure_ascii=False)}"
            ).strip()
        advice, retry_events = run_claude_advice(
            advice_prompt(task, page, selected, prompt_feedback, family, previous_report),
            source_image,
            translated_image,
            output,
            family,
            advice_provider=advice_provider,
        )
        write_json(record_path.parent / "claude-advice.json", advice)
        record.update(
            status="diagnosed",
            provider="claude",
            advisor_provider="claude",
            claude_advice=advice,
            diagnosis=diagnosis_from_advice(advice),
            execution_strategy={
                **(record.get("execution_strategy") or {}),
                "family": advice["execution_family"],
                "advisor_refinement": {
                    "from_family": family,
                    "to_family": advice["execution_family"],
                    "changed": advice["execution_family"] != family,
                },
            },
            provider_retry_events=[*(record.get("provider_retry_events") or []), *retry_events],
            evidence={
                **(record.get("evidence") or {}),
                "source_image": str(source_image.relative_to(folder)) if folder.resolve() in source_image.resolve().parents else str(source_image),
                "translated_image": str(translated_image.relative_to(folder)) if folder.resolve() in translated_image.resolve().parents else str(translated_image),
                "claude_advice": str((record_path.parent / "claude-advice.json").relative_to(folder)),
            },
            updated_at=now(),
        )
        if advice_provider is None:
            record = enforce_execution_readiness(folder, task, record)
            if record.get("status") == "repair_escalated":
                return
    except Exception as exc:
        if record:
            retry_events = list(getattr(exc, "retry_events", []))
            if retry_events:
                record["provider_retry_events"] = [
                    *(record.get("provider_retry_events") or []),
                    *retry_events,
                ]
            escalate_repair(
                folder,
                record,
                failure_stage="claude_advice",
                error=str(exc),
                unresolved=[str(exc)],
            )
            return
        record.update(status="repair_escalated", failure_stage="claude_advice", error=str(exc), updated_at=now())
    write_json(record_path, record)


def create_diagnosis(folder: Path, task: dict, pdf_page: int, issue_ids: list[str],
                     provider: str, feedback: str, *, strategy_id: str | None = None,
                     previous_report_id: str | None = None) -> dict:
    require_no_open_attempt(folder)
    current = require_fresh_contract(folder, task)
    review = build_review(folder, task)
    family, selected, page = selected_issue_family(folder, task, review, pdf_page, issue_ids)
    if int(pdf_page) not in red_pages(current["report"]):
        raise ValueError("目标页当前不是 red hard blocker，不能进入 SKL-168 修复熔断")
    strategy = execution_strategy(family, strategy_id=strategy_id)
    identity = attempt_identity(task, pdf_page, family, current["contract"], strategy, previous_report_id)
    ensure_attempt_not_reused(folder, identity)
    repair_id = identity["attempt_id"]
    record_path = repair_record_path(folder, repair_id)
    if record_path.exists():
        raise RuntimeError(f"repair attempt 已存在：{repair_id}")
    current_output_sha256 = current["contract"].get("outputs", {}).get("translated_pdf", {}).get("sha256")
    human_context = [
        {
            "review_id": item.get("review_id"),
            "feedback": item.get("feedback"),
            "diagnosis": item.get("diagnosis"),
        }
        for item in list_human_reviews(folder)
        if int(item.get("pdf_page", 0)) == int(pdf_page)
        and item.get("next_repair_input") is True
        and item.get("current_output_sha256") == current_output_sha256
    ]
    record = {
        "schema": ATTEMPT_SCHEMA,
        "repair_id": repair_id,
        "attempt_id": repair_id,
        "task_id": task["id"],
        "pdf_page": pdf_page,
        "issue_ids": issue_ids,
        "provider": "claude",
        "advisor_provider": "claude",
        "executor_provider": strategy["executor_provider"],
        "feedback": feedback,
        "human_review_refs": [item["review_id"] for item in human_context],
        "human_review_context": human_context,
        "status": "advising",
        "problem_family": family,
        "selected_issues": selected,
        "target_page_status_before": page.get("status"),
        "attempt_key": identity["attempt_key"],
        "attempt_key_sha256": identity["attempt_key_sha256"],
        "current_qa_contract": {
            "schema": current["contract"].get("schema"),
            "qa_rule_version": current["contract"].get("qa_rule_version"),
            "contract_sha256": current["contract"].get("contract_sha256"),
            "output_sha256": current["contract"].get("outputs", {}).get("translated_pdf", {}).get("sha256"),
        },
        "execution_strategy": strategy,
        "previous_failure_report_id": previous_report_id,
        "previous_failure_report": f"repairs/{previous_report_id}/failure-report.json" if previous_report_id else None,
        "created_at": now(),
        "updated_at": now(),
    }
    write_json(record_path, record)
    return record


def critical_count(report: dict) -> int:
    summary = report.get("summary", {})
    return int(summary.get("red", summary.get("critical", 0)))


def same_qa_rule_or_raise(before: dict, after: dict) -> str:
    before_rule = before.get("contract", {}).get("qa_rule_version")
    after_rule = after.get("contract", {}).get("qa_rule_version")
    if before_rule != QA_RULE_VERSION or after_rule != QA_RULE_VERSION or before_rule != after_rule:
        raise RuntimeError("修复前后 QA 规则版本不一致，按 stale 处理，不能比较红色问题")
    return before_rule


def qa_comparison(before: dict, after: dict, target_page: int) -> dict:
    rule = same_qa_rule_or_raise(before, after)
    before_red = red_pages(before)
    after_red = red_pages(after)
    target_red_remaining = int(target_page) in after_red
    new_red = sorted(after_red - before_red)
    new_visual = new_deterministic_visual_violations(before, after, target_page)
    return {
        "qa_rule_version": rule,
        "before": {
            "summary": before.get("summary", {}),
            "red_pages": sorted(before_red),
            "status": before.get("status"),
        },
        "candidate": {
            "summary": after.get("summary", {}),
            "red_pages": sorted(after_red),
            "status": after.get("status"),
        },
        "target_red_remaining": target_red_remaining,
        "new_red_pages": new_red,
        "new_deterministic_visual_violations": new_visual,
        "machine_gate": "pass" if not target_red_remaining and not new_red and not new_visual else "fail",
    }


def advisor_recovery_alternative() -> dict:
    return {
        "strategy_id": ADVISOR_RECOVERY_STRATEGY_ID,
        "label": "修复本机 Claude 建议链后重试",
        "boundary": "仅为同一页、同一问题族新建一次 Claude 只读建议 attempt；不自动启动 Codex 候选",
        "risk": "若本机 CLI 或结构化返回仍异常，新 attempt 将再次 fail-closed",
        "cost": "最多两次 Claude 只读建议调用，不生成候选 PDF",
    }


def bounded_alternatives(record: dict, failure_stage: str | None = None) -> list[dict]:
    advice = record.get("claude_advice") or {}
    alternatives = []
    for item in advice.get("alternatives", [])[:3]:
        alternatives.append({
            "strategy_id": item.get("strategy_id") or f"alternative-{len(alternatives) + 1}",
            "label": item.get("label") or "替代策略",
            "boundary": item.get("boundary") or "仅限当前页与当前问题族",
            "risk": item.get("risk") or "需要 June 再次验收",
            "cost": item.get("cost") or "一次新候选",
        })
    if not alternatives and failure_stage == "claude_advice":
        alternatives.append(advisor_recovery_alternative())
    return alternatives


def make_failure_report(record: dict, *, failure_stage: str, error: str,
                        current_qa: dict | None = None, candidate_qa: dict | None = None,
                        comparison: dict | None = None, unresolved: list[str] | None = None) -> dict:
    report_id = record["repair_id"]
    return {
        "schema": FAILURE_REPORT_SCHEMA,
        "report_id": report_id,
        "attempt_id": record["repair_id"],
        "task_id": record.get("task_id"),
        "pdf_page": record.get("pdf_page"),
        "problem_family": record.get("problem_family"),
        "issue_ids": record.get("issue_ids", []),
        "selected_issues": record.get("selected_issues", []),
        "feedback": record.get("feedback", ""),
        "previous_failure_report_id": record.get("previous_failure_report_id"),
        "claude_advice": record.get("claude_advice"),
        "actual_execution_strategy": record.get("execution_strategy"),
        "execution_readiness": record.get("execution_readiness"),
        "attempt_key_sha256": record.get("attempt_key_sha256"),
        "qa_rule_version": (comparison or {}).get("qa_rule_version") or QA_RULE_VERSION,
        "evidence": record.get("evidence", {}),
        "before_qa": qa_summary_for_task(current_qa or {}),
        "candidate_qa": qa_summary_for_task(candidate_qa or {}),
        "qa_comparison": comparison,
        "failure_stage": failure_stage,
        "error": error,
        "provider_retry_events": record.get("provider_retry_events", []),
        "unresolved": unresolved or [error],
        "options": {
            "alternatives": bounded_alternatives(record, failure_stage),
            "stop": {
                "strategy_id": "stop_keep_current",
                "label": "停止修复、保留当前版本",
                "boundary": "不创建新 attempt，不覆盖正式产物，保留当前 PDF 与失败候选",
            },
        },
        "june_decision": None,
        "created_at": now(),
    }


def report_markdown(report: dict) -> str:
    alternatives = report.get("options", {}).get("alternatives", [])
    alt_lines = "\n".join(
        f"- `{item.get('strategy_id')}`：{item.get('label')}；边界：{item.get('boundary')}；风险：{item.get('risk')}；成本：{item.get('cost')}"
        for item in alternatives
    ) or "- 无 Claude 建议的替代策略"
    comparison = report.get("qa_comparison") or {}
    retry_events = report.get("provider_retry_events") or []
    retry_lines = "\n".join(
        f"- {item.get('kind')} attempt {item.get('attempt')}: {item.get('error')}"
        for item in retry_events
    ) or "- 无可用重试事件（可能由修复前版本产生）"
    return f"""# 待 June 拍板：repair escalated

- attempt_id: `{report.get('attempt_id')}`
- task_id: `{report.get('task_id')}`
- page: `{report.get('pdf_page')}`
- problem_family: `{report.get('problem_family')}`
- failure_stage: `{report.get('failure_stage')}`
- error: {report.get('error')}

## Claude 原建议

{(report.get('claude_advice') or {}).get('strategy_summary', '无')}

## 实际执行

`{(report.get('actual_execution_strategy') or {}).get('strategy_id')}` / `{(report.get('actual_execution_strategy') or {}).get('family')}`

## QA 对照

- QA rule: `{comparison.get('qa_rule_version')}`
- before red pages: `{(comparison.get('before') or {}).get('red_pages')}`
- candidate red pages: `{(comparison.get('candidate') or {}).get('red_pages')}`
- target red remaining: `{comparison.get('target_red_remaining')}`
- new red pages: `{comparison.get('new_red_pages')}`

## 未解决项

{chr(10).join(f"- {item}" for item in report.get('unresolved', []))}

## Provider 有限重试

{retry_lines}

## 可选下一步

{alt_lines}
- `stop_keep_current`：停止修复、保留当前版本。
"""


def revise_advisor_failure_report(folder: Path, repair_id: str, reason: str) -> dict:
    """Idempotently add the bounded advisor-recovery option to a legacy report."""
    record = read_json(repair_record_path(folder, repair_id), {})
    if record.get("status") != "repair_escalated" or record.get("failure_stage") != "claude_advice":
        raise ValueError("只有 Claude 建议阶段的 repair_escalated 报告可补充恢复选项")
    report_path = failure_report_path(folder, repair_id, "json")
    report = read_json(report_path, {})
    if report.get("schema") != FAILURE_REPORT_SCHEMA:
        raise RuntimeError("失败报告缺失或 schema 不正确")
    alternatives = report.setdefault("options", {}).setdefault("alternatives", [])
    changed = False
    if not any(item.get("strategy_id") == ADVISOR_RECOVERY_STRATEGY_ID for item in alternatives):
        if len(alternatives) >= 3:
            raise RuntimeError("失败报告已有 3 个替代策略，不能补充恢复选项")
        alternatives.append(advisor_recovery_alternative())
        changed = True
    retry_events = record.get("provider_retry_events", [])
    if report.get("provider_retry_events") != retry_events:
        report["provider_retry_events"] = retry_events
        changed = True
    if changed:
        report.setdefault("revision_history", []).append({
            "kind": "advisor_recovery_option_added",
            "reason": str(reason)[:1000],
            "at": now(),
        })
        write_json(report_path, report)
        failure_report_path(folder, repair_id, "md").write_text(report_markdown(report))
        record["escalation_options"] = report.get("options", {})
        record["updated_at"] = now()
        write_json(repair_record_path(folder, repair_id), record)
    return report


def escalate_repair(folder: Path, record: dict, *, failure_stage: str, error: str,
                    current_qa: dict | None = None, candidate_qa: dict | None = None,
                    comparison: dict | None = None, unresolved: list[str] | None = None) -> dict:
    report = make_failure_report(
        record,
        failure_stage=failure_stage,
        error=error,
        current_qa=current_qa,
        candidate_qa=candidate_qa,
        comparison=comparison,
        unresolved=unresolved,
    )
    report_json = failure_report_path(folder, record["repair_id"], "json")
    report_md = failure_report_path(folder, record["repair_id"], "md")
    write_json(report_json, report)
    report_md.write_text(report_markdown(report))
    record.update(
        status="repair_escalated",
        failure_stage=failure_stage,
        error=error,
        failure_report={
            "schema": FAILURE_REPORT_SCHEMA,
            "report_id": report["report_id"],
            "json": str(report_json.relative_to(folder)),
            "markdown": str(report_md.relative_to(folder)),
        },
        escalation_options=report.get("options", {}),
        updated_at=now(),
    )
    write_json(repair_record_path(folder, record["repair_id"]), record)
    return record


def qa_summary_for_task(qa: dict) -> dict:
    return {
        "status": qa.get("status"),
        "summary": qa.get("summary", {}),
        "issue_category_summary": qa.get("issue_category_summary", {}),
        "flagged_pages": qa.get("flagged_pages", []),
        "baseline": qa.get("baseline"),
        "contract": {
            "schema": qa.get("contract", {}).get("schema"),
            "qa_rule_version": qa.get("contract", {}).get("qa_rule_version"),
            "contract_sha256": qa.get("contract", {}).get("contract_sha256"),
        } if qa.get("contract") else None,
    }


def execute_repair_harness(folder: Path, task: dict, record: dict, staging: Path,
                           workbench_port: int, python_executable: str | None) -> tuple[dict, dict]:
    family = record.get("execution_strategy", {}).get("family") or record.get("diagnosis", {}).get("repair_family")
    cases = repair_record_path(folder, record["repair_id"]).parent / "cases.json"
    write_json(cases, {"cases": [{"pdf_page": record["pdf_page"], "family": family}]})
    env = ensure_localhost_no_proxy(os.environ.copy())
    env.update(
        OPENAILIKED_BASE_URL=f"http://127.0.0.1:{workbench_port}/v1",
        OPENAILIKED_API_KEY=task["id"],
        OPENAILIKED_MODEL=record.get("executor_provider", "codex"),
    )
    python = python_executable or sys.executable
    cmd = [
        python, str(ROOT / "scripts" / "qa_repair_harness.py"), str(folder),
        "--cases", str(cases), "--output", str(staging), "--full", "--task-id", task["id"],
    ]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env=env)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout)[-1200:])
    result = read_json(staging / "full-repair-result.json", {})
    expected_current = str(Path(task.get("translated_file") or "translated-zh.pdf"))
    actual_current = (result.get("input_files") or {}).get("current", {}).get("path")
    if actual_current != expected_current:
        raise RuntimeError(f"候选基线文件错误：{actual_current or '未记录'} != {expected_current}")
    integrity = result.get("non_target_integrity") or {}
    if integrity.get("mismatched_pages") or "checked_pages" not in integrity:
        raise RuntimeError("候选缺少非目标页不变的完整性证据")
    candidate = staging / result.get("repaired_file", "")
    if not candidate.is_file():
        raise RuntimeError("候选中文 PDF 未生成")
    dual = staging / "bilingual-side-by-side.candidate.pdf"
    merged = subprocess.run([
        python, str(ROOT / "scripts" / "dual_pdf.py"),
        str(task_artifact_path(folder, task, "original_file", "original.pdf")), str(candidate), str(dual),
    ], capture_output=True, text=True, timeout=600)
    if merged.returncode or not dual.is_file():
        raise RuntimeError("候选双语 PDF 未生成")
    return result, {
        "translated": candidate,
        "dual": dual,
        "qa": staging / result.get("qa_file", "qa-repaired.json"),
        "plan": staging / result.get("repaired_plan", "page-plan.repaired.json"),
    }


def run_repair(folder: Path, task: dict, repair_id: str, workbench_port: int = 8765,
               python_executable: str | None = None, repair_executor=None) -> None:
    record_path = repair_record_path(folder, repair_id)
    record = read_json(record_path, {})
    current_qa = read_json(folder / task.get("qa_alpha_file", "qa-alpha.json"), {})
    try:
        if record.get("status") not in {"repairing", "diagnosed"}:
            raise ValueError("诊断尚未完成")
        if repair_executor is None:
            ensure_repair_model_health(require_codex=True, require_claude=True)
        require_no_open_attempt(folder, exclude_repair_id=repair_id)
        current = require_fresh_contract(folder, task, current_qa)
        current_qa = current["report"]
        diagnosis = record.get("diagnosis", {})
        if not diagnosis.get("is_real_problem"):
            raise ValueError("模型未确认这是真问题")
        family = record.get("execution_strategy", {}).get("family") or diagnosis.get("repair_family")
        if family not in ALLOWED_FAMILIES:
            raise ValueError("修复类型无效")
        if int(record["pdf_page"]) not in red_pages(current_qa):
            raise ValueError("目标红色页在当前 QA 中已不存在；需要重新建立新鲜 QA 后再判断")
        if record.get("strategy_attempted_at"):
            raise RuntimeError("同一 attempt 的完整修复策略已经执行过，不能再次执行")
        record.update(strategy_attempted_at=now(), updated_at=now())
        write_json(record_path, record)
        staging = record_path.parent / "candidate"
        if repair_executor:
            result, files = repair_executor(folder, task, record, staging)
        else:
            result, files = execute_repair_harness(folder, task, record, staging, workbench_port, python_executable)
        for label, path in files.items():
            if not path or not Path(path).is_file():
                raise RuntimeError(f"候选版本文件不完整：{label}")
        candidate_qa = read_json(staging / result.get("qa_file", "qa-repaired.json"), {})
        comparison = qa_comparison(current_qa, candidate_qa, int(record["pdf_page"]))
        unresolved = []
        if comparison["target_red_remaining"]:
            unresolved.append("目标 red hard blocker 未消除")
        if comparison["new_red_pages"]:
            unresolved.append(f"候选版本新增 red 页面：{comparison['new_red_pages']}")
        if comparison.get("new_deterministic_visual_violations"):
            kinds = sorted({item.get("issue_type") for item in comparison["new_deterministic_visual_violations"]})
            unresolved.append(f"候选页新增确定性视觉违规：{', '.join(kinds)}")
        if unresolved:
            escalate_repair(
                folder,
                record,
                failure_stage="qa_machine_gate",
                error="；".join(unresolved),
                current_qa=current_qa,
                candidate_qa=candidate_qa,
                comparison=comparison,
                unresolved=unresolved,
            )
            return
        record.update(
            status="awaiting_acceptance", candidate={
                "translated": str(Path(files["translated"]).relative_to(folder)),
                "dual": str(Path(files["dual"]).relative_to(folder)),
                "qa": str(Path(files["qa"]).relative_to(folder)),
                "plan": str(Path(files["plan"]).relative_to(folder)),
                "qa_summary": candidate_qa.get("summary", {}),
            },
            qa_comparison=comparison,
            harness=result,
            updated_at=now(),
        )
    except Exception as exc:
        try:
            escalate_repair(
                folder,
                record if record else {"repair_id": repair_id, "task_id": task.get("id"), "pdf_page": None},
                failure_stage=record.get("failure_stage") or "candidate_generation",
                error=str(exc),
                current_qa=current_qa,
                unresolved=[str(exc)],
            )
            return
        except Exception:
            record.update(status="repair_escalated", failure_stage="candidate_generation", error=str(exc), updated_at=now())
    write_json(record_path, record)


def start_repair(folder: Path, repair_id: str) -> dict:
    path = repair_record_path(folder, repair_id)
    record = read_json(path, {})
    if record.get("status") != "diagnosed":
        raise ValueError("必须先完成 Claude 结构化策略建议")
    if not record.get("diagnosis", {}).get("is_real_problem"):
        raise ValueError("Claude 未确认需要修复")
    require_no_open_attempt(folder, exclude_repair_id=repair_id)
    if record.get("strategy_attempted_at"):
        raise RuntimeError("同一 attempt 已执行过完整修复策略，不能再次启动")
    record.update(status="repairing", updated_at=now())
    write_json(path, record)
    return record


def candidate_file(folder: Path, repair_id: str, kind: str) -> Path | None:
    record = read_json(repair_record_path(folder, repair_id), {})
    relative = record.get("candidate", {}).get(kind)
    if not relative:
        return None
    target = (folder / relative).resolve()
    return target if folder.resolve() in target.parents else None


def repair_file(folder: Path, repair_id: str, kind: str) -> Path | None:
    if kind == "failure-json":
        target = failure_report_path(folder, repair_id, "json")
    elif kind == "failure-md":
        target = failure_report_path(folder, repair_id, "md")
    else:
        return candidate_file(folder, repair_id, kind)
    return target if target.is_file() else None


def accept_repair(folder: Path, task: dict, repair_id: str) -> dict:
    path = repair_record_path(folder, repair_id)
    record = read_json(path, {})
    if record.get("status") != "awaiting_acceptance":
        raise ValueError("没有等待验收的候选版本")
    comparison = record.get("qa_comparison") or {}
    if comparison.get("machine_gate") != "pass":
        raise RuntimeError("候选版本未通过机器红色熔断门，不能接受")
    files = {
        "translated-zh.pdf": candidate_file(folder, repair_id, "translated"),
        "bilingual-side-by-side.pdf": candidate_file(folder, repair_id, "dual"),
        "qa-alpha.json": candidate_file(folder, repair_id, "qa"),
        "page-plan.json": candidate_file(folder, repair_id, "plan"),
    }
    if not all(value and value.is_file() for value in files.values()):
        raise RuntimeError("候选版本文件不完整")
    current_files = {
        "translated-zh.pdf": task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"),
        "bilingual-side-by-side.pdf": task_artifact_path(folder, task, "dual_file", "bilingual-side-by-side.pdf"),
        "qa-alpha.json": task_artifact_path(folder, task, "qa_alpha_file", "qa-alpha.json"),
        "page-plan.json": task_artifact_path(folder, task, "page_plan_file", "page-plan.json"),
    }
    qa = read_json(files["qa-alpha.json"], {})
    final_task_projection = dict(task)
    final_task_projection.update(
        translated_file="translated-zh.pdf",
        dual_file="bilingual-side-by-side.pdf",
        page_plan_file="page-plan.json",
        qa_alpha_file="qa-alpha.json",
    )
    qa["contract"] = build_contract(
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=files["translated-zh.pdf"],
        plan_path=files["page-plan.json"],
        task=final_task_projection,
    )
    version = next_version_dir(folder, repair_id)
    receipt = {
        "schema": "repair-acceptance-receipt/v1",
        "repair_id": repair_id,
        "accepted_at": time.time(),
        "backup_dir": str(version),
        "pre_accept_hashes": {
            name: sha256_file(source) for name, source in current_files.items()
        },
        "pre_accept_files": {
            name: str(source.relative_to(folder.resolve())) for name, source in current_files.items()
        },
        "candidate_hashes": {
            name: sha256_file(source) for name, source in files.items()
        },
        "qa_contract": {
            "schema": qa.get("contract", {}).get("schema"),
            "qa_rule_version": qa.get("contract", {}).get("qa_rule_version"),
            "contract_sha256": qa.get("contract", {}).get("contract_sha256"),
        },
    }
    copied_names = set()
    for current in current_files.values():
        if current.name not in copied_names:
            shutil.copy2(current, version / current.name)
            copied_names.add(current.name)
    prepared = dict(files)
    qa_candidate = version / "qa-alpha.candidate.json"
    qa_candidate.write_text(json.dumps(qa, ensure_ascii=False, indent=2))
    prepared["qa-alpha.json"] = qa_candidate
    install_artifact_set(folder, prepared, version)
    manifest_ref = write_page_manifest(folder, final_task_projection, folder / "translated-zh.pdf", qa.get("contract"))
    installed_qa = read_json(folder / "qa-alpha.json", {})
    installed_qa["page_manifest"] = manifest_ref
    write_json(folder / "qa-alpha.json", installed_qa)
    receipt["page_manifest"] = manifest_ref
    receipt["installed_hashes"] = {name: sha256_file(folder / name) for name in files}
    receipt["freshness_after_install"] = verify_contract(
        installed_qa,
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=folder / "translated-zh.pdf",
        plan_path=folder / "page-plan.json",
        task=final_task_projection,
    )
    write_json(version / "acceptance-receipt.json", receipt)
    status_map = {"needs_review": "needs_review", "passed_with_warnings": "completed_with_warnings", "passed": "completed"}
    flagged = installed_qa.get("flagged_pages", [])
    task.update(
        status=status_map.get(installed_qa.get("status"), "needs_review"),
        qa_alpha=qa_summary_for_task(installed_qa),
        page_manifest_file="page-manifest.json",
        message=f"已接受第 {record['pdf_page']} 页候选修复；确定性 QA 仍标记 {len(flagged)} 页",
    )
    record.update(
        status="accepted",
        accepted_by="june",
        accepted_at=now(),
        backup=str(version),
        receipt=str(version / "acceptance-receipt.json"),
        updated_at=now(),
    )
    write_json(path, record)
    return task


def reject_repair(folder: Path, repair_id: str) -> dict:
    path = repair_record_path(folder, repair_id)
    record = read_json(path, {})
    if record.get("status") == "awaiting_acceptance":
        candidate_qa = read_json(candidate_file(folder, repair_id, "qa") or Path(), {})
        current_qa = read_json(folder / "qa-alpha.json", {})
        comparison = record.get("qa_comparison")
        return escalate_repair(
            folder,
            record,
            failure_stage="june_visual_rejected",
            error="June 未接受受影响页视觉检查，候选不得覆盖正式产物",
            current_qa=current_qa,
            candidate_qa=candidate_qa,
            comparison=comparison,
            unresolved=["受影响页视觉检查未通过或未被 June 接受"],
        )
    if record.get("status") not in {"diagnosed", "failed"}:
        raise ValueError("当前状态不能拒绝")
    record.update(status="rejected", rejected_at=now(), updated_at=now())
    write_json(path, record)
    return record


def decide_escalation(folder: Path, task: dict, repair_id: str, decision: dict) -> dict:
    path = repair_record_path(folder, repair_id)
    record = read_json(path, {})
    if record.get("status") != "repair_escalated":
        raise ValueError("只有 repair_escalated 状态能由 June 拍板")
    report_file = failure_report_path(folder, repair_id, "json")
    report = read_json(report_file, {})
    if report.get("schema") != FAILURE_REPORT_SCHEMA:
        raise RuntimeError("失败报告缺失或 schema 不正确")
    choice = decision.get("choice")
    note = str(decision.get("note", ""))[:2000]
    allowed = {item.get("strategy_id") for item in report.get("options", {}).get("alternatives", [])}
    allowed.add("stop_keep_current")
    if choice not in allowed:
        raise ValueError("June 决策必须明确选择报告中的策略或停止")
    receipt = {
        "schema": JUNE_DECISION_SCHEMA,
        "repair_id": repair_id,
        "choice": choice,
        "note": note,
        "decided_at": now(),
    }
    report["june_decision"] = receipt
    write_json(report_file, report)
    failure_report_path(folder, repair_id, "md").write_text(report_markdown(report))
    if choice == "stop_keep_current":
        record.update(status="stopped", june_decision=receipt, updated_at=now())
        write_json(path, record)
        return {"decision": receipt, "created_attempt": None}
    record.update(status="escalation_decided", june_decision=receipt, updated_at=now())
    write_json(path, record)
    prior_feedback = str(record.get("feedback", "")).strip()
    successor_feedback = (
        f"{prior_feedback}\n\n本次补充：{note}" if prior_feedback and note
        else prior_feedback or note
    )[:2000]
    next_record = create_diagnosis(
        folder,
        task,
        int(record["pdf_page"]),
        list(record.get("issue_ids", [])),
        "claude",
        successor_feedback,
        strategy_id=choice,
        previous_report_id=repair_id,
    )
    return {"decision": receipt, "created_attempt": next_record}

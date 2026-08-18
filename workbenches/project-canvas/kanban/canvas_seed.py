"""Agent-driven task-card to canvas seed helpers.

This module owns the seed-intent context, agent seed prompt contract, and
merge-preservation audit. scan-docs.py should only route requests into these
helpers or enqueue the returned prompt through the existing AI queue.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


CANVAS_SEED_PROMPT_VERSION = "kanban-canvas-agent-seed-v1"
CANVAS_SEED_V2_PROMPT_VERSION = "kanban-canvas-seed-v0.2"
LOCAL_SUMMARIZER_ACTOR = "local-summarizer"
LOCAL_SUMMARIZER_MODEL = "GLM-5.2"
MANUAL_ORIGINS = {"manual", "owner"}
GENERATED_ORIGINS = {"", "generated", "generate", "codex", "claude", "agent"}
TEXT_SUMMARY_EXTS = {
    ".md", ".markdown", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".jsonl", ".yaml", ".yml", ".html", ".css", ".csv",
}
SECRETISH_RE = re.compile(r"(\.env|secret|token|credential|cookie|key)", re.I)


def _single_line(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _strip_frontmatter(raw: str) -> str:
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", raw or "", re.DOTALL)
    return raw[match.end() :] if match else raw


def _markdown_sections(body: str, *, max_chars: int = 9000) -> str:
    lines = []
    current = []
    current_heading = "正文开头"
    budget = max_chars

    def flush() -> None:
        nonlocal budget
        if budget <= 0:
            return
        text = "\n".join(current).strip()
        if not text and current_heading != "正文开头":
            text = "(空)"
        if not text:
            return
        block = f"## {current_heading}\n{text}"
        if len(block) > budget:
            block = block[:budget].rstrip() + "\n…"
        lines.append(block)
        budget -= len(block)

    for raw_line in _strip_frontmatter(body).splitlines():
        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", raw_line)
        if heading:
            flush()
            current_heading = _single_line(heading.group(2), 120)
            current = []
            continue
        current.append(raw_line.rstrip())
    flush()
    return "\n\n".join(lines).strip()


def _wiki_links(raw: str) -> list[str]:
    links = []
    seen = set()
    for match in re.finditer(r"\[\[([^\]]+)\]\]", raw or ""):
        value = _single_line(match.group(1), 180)
        if value and value not in seen:
            seen.add(value)
            links.append(value)
    return links[:80]


def _frontmatter_list(fm: dict[str, Any], key: str) -> list[str]:
    value = fm.get(key)
    if isinstance(value, list):
        return [_single_line(item, 240) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [_single_line(value, 240)]
    return []


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dir_tree(root: Path, *, label: str, repo_root: Path, max_entries: int = 120, max_depth: int = 2) -> list[str]:
    if not root.exists() or not root.is_dir():
        return [f"{label}: (missing) {root}"]
    skip_names = {".git", "node_modules", "vendor", ".venv", ".deps", "__pycache__", "dist"}
    rows = [f"{label}: {_safe_rel(root, repo_root)}"]
    base_depth = len(root.parts)
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        dirs[:] = sorted(
            d for d in dirs
            if d not in skip_names and not d.startswith(".") and not d.startswith("_")
        )
        names = [(name, "dir") for name in dirs] + [(name, "file") for name in sorted(files)]
        for name, kind in names:
            rel = _safe_rel(current_path / name, repo_root)
            rows.append(f"{'  ' * (depth + 1)}- [{kind}] {rel}")
            if len(rows) >= max_entries:
                rows.append("  - …")
                return rows
    return rows


def _resolve_workdir_tree(deps: dict[str, Any], rel_path: str, fm: dict[str, Any]) -> list[str]:
    workdir_value = str(fm.get("workdir") or "").strip()
    if not workdir_value:
        return []
    resolve_workdir = deps.get("resolve_workdir")
    repo_root = Path(deps["repo_root"]).resolve()
    if not callable(resolve_workdir):
        return [f"workdir: {workdir_value}"]
    resolved, err = resolve_workdir(workdir_value, rel_path)
    if err or not resolved:
        return [f"workdir: (unresolved) {workdir_value}"]
    return _dir_tree(Path(resolved).resolve(), label="workdir tree", repo_root=repo_root)


def _related_path_rows(deps: dict[str, Any], fm: dict[str, Any]) -> list[str]:
    rows = []
    repo_root = Path(deps["repo_root"]).resolve()
    for item in _frontmatter_list(fm, "related_paths")[:30]:
        expanded = Path(os.path.expanduser(item))
        candidate = expanded if expanded.is_absolute() else (repo_root / expanded)
        if candidate.is_dir():
            rows.extend(_dir_tree(candidate.resolve(), label=f"related dir {item}", repo_root=repo_root, max_entries=40, max_depth=1))
        else:
            rows.append(f"- {item}")
    return rows


def build_seed_intent_context(deps: dict[str, Any], rel_path: str, task_file: dict[str, Any]) -> dict[str, Any]:
    fm = task_file.get("frontmatter") or {}
    raw = task_file.get("raw") or ""
    body = task_file.get("body")
    if body is None:
        body = _strip_frontmatter(raw)
    fields = {
        "task_id": fm.get("task_id") or "",
        "title": fm.get("title") or "",
        "status": fm.get("status") or "",
        "assignee": fm.get("assignee") or "",
        "priority": fm.get("priority") or "",
        "workdir": fm.get("workdir") or "",
        "next_action": fm.get("next_action") or "",
    }
    return {
        "path": rel_path,
        "frontmatter": {key: _single_line(value, 240) for key, value in fields.items() if str(value or "").strip()},
        "sections": _markdown_sections(str(body or "")),
        "workdir_tree": _resolve_workdir_tree(deps, rel_path, fm),
        "related_paths": _related_path_rows(deps, fm),
        "wiki_links": _wiki_links(raw or str(body or "")),
    }


def _context_to_prompt(context: dict[str, Any]) -> str:
    parts = [
        "<task_frontmatter>",
        json.dumps(context.get("frontmatter") or {}, ensure_ascii=False, indent=2),
        "</task_frontmatter>",
        "<task_sections>",
        str(context.get("sections") or "(empty)"),
        "</task_sections>",
        "<workdir_tree>",
        "\n".join(context.get("workdir_tree") or ["(none)"]),
        "</workdir_tree>",
        "<related_paths>",
        "\n".join(context.get("related_paths") or ["(none)"]),
        "</related_paths>",
        "<wiki_links>",
        "\n".join(f"- {item}" for item in (context.get("wiki_links") or [])) or "(none)",
        "</wiki_links>",
    ]
    return "\n".join(parts)


def infer_seed_intent(deps: dict[str, Any], path_value: str) -> tuple[dict[str, Any], int]:
    resolve_active = deps["resolve_active_task_card_path"]
    read_task = deps["read_task_file"]
    load_config = deps["load_config"]
    llm_chat = deps["llm_chat"]
    _task_path, rel_path, err, status = resolve_active(path_value)
    if err:
        return {"ok": False, "error": err}, status
    task_file, read_err = read_task(rel_path)
    if not task_file:
        return {"ok": False, "error": read_err}, 404 if read_err == "文件不存在" else 400
    context = build_seed_intent_context(deps, rel_path, task_file)
    config = load_config() if callable(load_config) else {}
    provider = str((config or {}).get("ai_provider") or "deepseek").strip() or "deepseek"
    messages = [
        {
            "role": "system",
            "content": (
                "你是任务卡到工作台画布的意图归纳器。只返回一句中文意图草稿，"
                "不列字段，不解释，不承诺完成；用来指导 agent 排布材料画布。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请基于以下任务卡上下文生成一句话画布 seed 意图。"
                "上下文的 workdir 只有文件名/目录名层，不能推断未读内容。\n\n"
                f"{_context_to_prompt(context)}"
            ),
        },
    ]
    ok, content = llm_chat(provider, messages, max_tokens=120, temperature=0.2)
    if not ok:
        return {"ok": False, "error": content or "seed intent LLM failed"}, 502
    draft = _single_line(content, 220)
    draft = re.sub(r"^[\"'“”]+|[\"'“”]+$", "", draft).strip()
    execution_brief = build_execution_brief(context, draft)
    return {
        "ok": True,
        "path": rel_path,
        "intent": draft,
        "draft": draft,
        "execution_brief": execution_brief,
        "provider": provider,
        "context": context,
    }, 200


def choose_seed_recipe(intent: str) -> str:
    text = str(intent or "")
    triage_words = ("分诊", "判断", "盘点", "筛选", "验收", "复核", "诊断", "风险")
    composition_words = ("生成", "备料", "撰写", "输出", "页面", "提案", "课程", "方案", "论点")
    consultation_words = ("商量", "咨询", "讨论", "请教", "一起想", "共同判断", "给建议")
    research_words = ("研究", "调研", "探索", "推演", "假设", "证据链", "文献", "思考")
    if any(word in text for word in consultation_words):
        return "consultation"
    if any(word in text for word in research_words):
        return "research-thinking"
    if any(word in text for word in triage_words):
        return "triage"
    if any(word in text for word in composition_words):
        return "composition"
    return "general"


def build_execution_brief(context: dict[str, Any], raw_intent: str) -> dict[str, Any]:
    """Turn the preserved user intent and card context into a deterministic brief."""
    intent = str(raw_intent or "").strip()
    fm = context.get("frontmatter") if isinstance(context.get("frontmatter"), dict) else {}
    sources = [{"role": "card", "path": str(context.get("path") or "")}]
    workdir = str(fm.get("workdir") or "").strip()
    if workdir:
        sources.append({"role": "workdir", "path": workdir})
    for item in (context.get("related_paths") or [])[:12]:
        value = _single_line(item, 240).lstrip("- ")
        if value:
            sources.append({"role": "related_path", "summary": value})
    for item in (context.get("wiki_links") or [])[:12]:
        sources.append({"role": "wiki_link", "path": str(item)})
    recipe = choose_seed_recipe(intent)
    action_by_recipe = {
        "triage": ["核对已登记来源", "按判断问题组织材料", "标出风险与待确认项"],
        "composition": ["核对已登记来源", "组织证据与内容骨架", "形成可继续编辑的交付物"],
        "consultation": ["核对已登记来源", "整理待商量的问题与分歧", "形成建议和待拍板项"],
        "research-thinking": ["核对已登记来源", "组织问题、证据与假设", "形成可追溯的研究判断"],
        "general": ["核对已登记来源", "按原始意图组织工作区", "形成可继续执行的结果"],
    }
    deliverable_by_recipe = {
        "triage": "带来源、判断与待确认项的工作台画布",
        "composition": "带证据来源和内容骨架的可编辑工作台画布",
        "consultation": "带问题、建议和待拍板项的协商工作台画布",
        "research-thinking": "带问题、证据、假设和判断链的研究工作台画布",
        "general": "与原始意图一致、可继续执行的工作台画布",
    }
    return {
        "goal": intent,
        "source_summary": sources,
        "actions": action_by_recipe[recipe],
        "deliverable": deliverable_by_recipe[recipe],
        "completion_gate": [
            "原始意图完整保留且交付物与其一致",
            "使用的材料均可追溯到任务卡或显式来源",
            "manual/owner 节点与边完整保留",
            "AI 判断运行成功且最低质量检查通过后才可标记 usable",
        ],
        "recipe": recipe,
    }


def seed_stage(*, ai_run_succeeded: bool, quality_passed: bool, run_finished: bool = True) -> str:
    """Return the public seed stage without allowing failed AI work to look usable."""
    if not run_finished:
        return "executing"
    if not ai_run_succeeded:
        return "failed"
    return "usable" if quality_passed else "draft_ready"


def minimum_seed_quality(canvas: dict[str, Any], *, ai_run_succeeded: bool) -> dict[str, Any]:
    """Apply the small, explicit quality gate shared by seed implementations."""
    metadata = canvas.get("metadata") if isinstance(canvas.get("metadata"), dict) else {}
    missing = []
    if not metadata.get("raw_intent"):
        missing.append("raw_intent")
    brief = metadata.get("execution_brief")
    if not isinstance(brief, dict):
        missing.append("execution_brief")
    else:
        for key in ("goal", "source_summary", "actions", "deliverable", "completion_gate"):
            if not brief.get(key):
                missing.append(f"execution_brief.{key}")
    if not (canvas.get("nodes") or []):
        missing.append("nodes")
    substantive_nodes = []
    for node in canvas.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type") or "") == "ref":
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        content = " ".join(str(data.get(key) or "") for key in ("text", "content", "body", "summary"))
        if len(re.sub(r"\s+", " ", content).strip()) >= 12:
            substantive_nodes.append(node)
    if not substantive_nodes:
        missing.append("actionable_output")
    passed = bool(ai_run_succeeded and not missing)
    return {
        "passed": passed,
        "stage": seed_stage(ai_run_succeeded=ai_run_succeeded, quality_passed=passed),
        "ai_run_succeeded": bool(ai_run_succeeded),
        "missing": missing,
    }


def _safe_id(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-._")
    return text or fallback


def _basename(path_value: str) -> str:
    text = str(path_value or "").strip().rstrip("/\\")
    if not text:
        return ""
    if re.match(r"^https?://", text, re.I):
        return text.split("//", 1)[-1].split("/", 1)[0]
    return Path(os.path.expanduser(text)).name or text


def _node_summary_status(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return str(metadata.get("local_summary_status") or "").strip()


def seed_summary_counts(canvas: dict[str, Any]) -> dict[str, int]:
    counts = {"total": 0, "pending": 0, "done": 0, "skipped": 0, "failed": 0}
    for node in canvas.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if not metadata.get("local_summary_required"):
            continue
        counts["total"] += 1
        status = _node_summary_status(node) or "pending"
        if status not in counts:
            status = "failed"
        counts[status] += 1
    return counts


def _source_registry_paths(deps: dict[str, Any], rel_path: str, fm: dict[str, Any]) -> list[Path]:
    repo_root = Path(deps["repo_root"]).resolve()
    out: list[Path] = []
    workdir_value = str(fm.get("workdir") or "").strip()
    resolve_workdir = deps.get("resolve_workdir")
    if workdir_value and callable(resolve_workdir):
        resolved, err = resolve_workdir(workdir_value, rel_path)
        if not err and resolved:
            out.append(Path(resolved).resolve() / "sources" / "source-registry.jsonl")
    for item in _frontmatter_list(fm, "related_paths"):
        if not item.endswith("source-registry.jsonl"):
            continue
        candidate = Path(os.path.expanduser(item))
        out.append(candidate if candidate.is_absolute() else repo_root / candidate)
    return out


def _registry_usage(item: dict[str, Any]) -> str:
    for key in ("purpose", "usage", "use", "用途", "description", "summary", "role"):
        value = _single_line(item.get(key), 260)
        if value:
            return value
    return ""


def _read_source_registry_entries(deps: dict[str, Any], rel_path: str, fm: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for registry in _source_registry_paths(deps, rel_path, fm):
        try:
            lines = registry.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            path_value = _single_line(item.get("source_path") or item.get("path") or item.get("file") or item.get("source"), 500)
            if not path_value or path_value in seen:
                continue
            seen.add(path_value)
            entries.append({
                "path": path_value,
                "usage": _registry_usage(item),
                "registry": str(registry),
                "registry_line": str(line_no),
            })
    return entries[:60]


def _ref_node(
    node_id: str,
    *,
    kind: str,
    path_value: str,
    title: str,
    role: str,
    x: int,
    y: int,
    summary: str = "",
    relation_note: str = "",
    metadata: dict[str, Any] | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    source_ref: dict[str, Any] = {
        "kind": kind,
        "path": path_value,
        "status": "pending",
    }
    if line is not None:
        source_ref["line"] = line
    data_meta = {"role": role, **(metadata or {})}
    return {
        "id": _safe_id(node_id),
        "type": "ref",
        "position": {"x": int(x), "y": int(y)},
        "data": {
            "kind": kind,
            "label": _single_line(title, 90),
            "title": _single_line(title, 90),
            "summary": _single_line(summary, 360),
            "relation_note": _single_line(relation_note, 260),
            "readonly": True,
            "origin": "generated",
            "source_ref": source_ref,
            "metadata": data_meta,
        },
    }


def _edge(edge_id: str, source: str, target: str, label: str = "上下文") -> dict[str, Any]:
    return {
        "id": _safe_id(edge_id),
        "source": source,
        "target": target,
        "type": "default",
        "label": label,
        "data": {"origin": "generated"},
    }


def _existing_positions(existing_canvas: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    positions = {}
    for node in (existing_canvas or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        pos = node.get("position")
        if node_id and isinstance(pos, dict):
            positions[node_id] = {"x": int(float(pos.get("x") or 0)), "y": int(float(pos.get("y") or 0))}
    return positions


def _merge_generated_with_existing(
    generated_nodes: list[dict[str, Any]],
    generated_edges: list[dict[str, Any]],
    existing_canvas: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not existing_canvas:
        return generated_nodes, generated_edges
    positions = _existing_positions(existing_canvas)
    for node in generated_nodes:
        if node.get("id") in positions:
            node["position"] = positions[node["id"]]
    generated_ids = {str(node.get("id") or "") for node in generated_nodes}
    kept_nodes = [
        node for node in existing_canvas.get("nodes") or []
        if isinstance(node, dict) and str(node.get("id") or "") not in generated_ids
    ]
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(existing_canvas.get("edges") or []) + generated_edges:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or f"{item.get('source')}->{item.get('target')}")
        pair_key = f"{item.get('source')}->{item.get('target')}"
        if key in seen or pair_key in seen:
            continue
        seen.add(key)
        seen.add(pair_key)
        edges.append(item)
    return generated_nodes + kept_nodes, edges


def build_seed_skeleton(
    deps: dict[str, Any],
    path_value: str,
    intent: str,
    *,
    existing_canvas: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Build the v0.2 deterministic seed skeleton.

    This layer is deliberately model-free: it reads task metadata, registered
    source rows, and filesystem existence only. Judgment and summaries are
    handled by later layers.
    """
    resolve_active = deps["resolve_active_task_card_path"]
    read_task = deps["read_task_file"]
    _task_path, rel_path, err, status = resolve_active(path_value)
    if err:
        return {"ok": False, "error": err}, status
    task_file, read_err = read_task(rel_path)
    if not task_file:
        return {"ok": False, "error": read_err}, 404 if read_err == "文件不存在" else 400
    fm = task_file.get("frontmatter") or {}
    task_id = _single_line(fm.get("task_id") or Path(rel_path).stem, 120)
    title = _single_line(fm.get("title") or task_id, 180)
    clean_intent = _single_line(intent, 260)
    if not clean_intent:
        return {"ok": False, "error": "缺少 seed intent"}, 400
    raw_intent = str(intent).strip()
    context = build_seed_intent_context(deps, rel_path, task_file)
    execution_brief = build_execution_brief(context, raw_intent)

    nodes: list[dict[str, Any]] = [
        _ref_node(
            "card",
            kind="card",
            path_value=rel_path,
            title=f"{task_id} 任务卡" if task_id else Path(rel_path).name,
            role="card",
            x=0,
            y=0,
            summary=f"当前任务事实源: {title}",
            relation_note="这是当前画布的起点；其它节点围绕这张任务卡组织。",
            line=1,
        )
    ]
    edges: list[dict[str, Any]] = []
    seed_sources = [{"role": "card", "path": rel_path}]

    workdir_value = _single_line(fm.get("workdir"), 500)
    if workdir_value:
        nodes.append(_ref_node(
            "workdir",
            kind="dir",
            path_value=workdir_value,
            title=_basename(workdir_value) or "workdir",
            role="workdir",
            x=300,
            y=0,
            summary="",
            relation_note="来自卡片 frontmatter 的 workdir；作为下游文件节点的父级上下文。",
        ))
        edges.append(_edge("edge-card-workdir", "card", "workdir"))
        seed_sources.append({"role": "workdir", "path": workdir_value})

    explicit_paths: list[tuple[str, str, str]] = []
    for key, role in (("source_path", "source_path"), ("landing_page", "landing_page")):
        value = _single_line(fm.get(key), 500)
        if value:
            explicit_paths.append((role, value, "file"))
    related_paths = fm.get("related_paths") if isinstance(fm.get("related_paths"), list) else []
    if not related_paths:
        raw_related = deps.get("frontmatter_block_list_values")
        if callable(raw_related):
            related_paths = raw_related(task_file.get("frontmatter_block"), "related_paths")
    for idx, item in enumerate(related_paths or [], start=1):
        value = _single_line(item, 500)
        if value:
            explicit_paths.append((f"related_path:{idx}", value, "file"))

    for idx, (role, value, kind) in enumerate(explicit_paths[:30], start=1):
        node_id = f"related-{idx}"
        nodes.append(_ref_node(
            node_id,
            kind=kind,
            path_value=value,
            title=_basename(value) or role,
            role=role.split(":", 1)[0],
            x=300 + (idx % 2) * 300,
            y=170 + ((idx - 1) // 2) * 150,
            summary="",
            relation_note="来自任务卡显式路径字段；可作为下游判断的上下文。",
            metadata={"local_summary_required": kind == "file", "local_summary_status": "pending" if kind == "file" else ""},
        ))
        edges.append(_edge(f"edge-card-{node_id}", "card", node_id))
        seed_sources.append({"role": role, "path": value})

    registry_entries = _read_source_registry_entries(deps, rel_path, fm)
    for idx, item in enumerate(registry_entries, start=1):
        value = item["path"]
        node_id = f"registry-{idx}"
        usage = item.get("usage") or ""
        nodes.append(_ref_node(
            node_id,
            kind="file",
            path_value=value,
            title=_basename(value) or f"registry {idx}",
            role="source_registry",
            x=640,
            y=(idx - 1) * 150,
            summary=usage,
            relation_note="来自 source-registry/manifest 已登记源；登记用途为空时由本地链补摘要。",
            metadata={
                "registry": item.get("registry"),
                "registry_line": item.get("registry_line"),
                "registered_usage": bool(usage),
                "local_summary_required": not bool(usage),
                "local_summary_status": "" if usage else "pending",
            },
        ))
        edges.append(_edge(f"edge-workdir-{node_id}", "workdir" if workdir_value else "card", node_id))
        seed_sources.append({"role": "source_registry", "path": value, "registry": item.get("registry", "")})

    nodes, edges = _merge_generated_with_existing(nodes, edges, existing_canvas)
    now = datetime.now().replace(microsecond=0).isoformat()
    metadata = {
        "generator": "kanban-canvas-seed-v0.2",
        "seed_intent": clean_intent,
        "raw_intent": raw_intent,
        "execution_brief": execution_brief,
        "seed_recipe": execution_brief["recipe"],
        "seed_sources": seed_sources,
        "seed_prompt_version": CANVAS_SEED_V2_PROMPT_VERSION,
        "seeded_at": now,
        "seed_status": {
            "stage": "skeleton_ready",
            "label": "骨架已出",
            "updated_at": now,
            "summary": seed_summary_counts({"nodes": nodes}),
        },
    }
    canvas = {
        "schema": deps.get("canvas_schema") or "kanban.canvas/v1",
        "id": _safe_id(task_id, "canvas"),
        "name": title,
        "scope": {"type": "card", "task_id": task_id, "task_path": rel_path},
        "nodes": nodes,
        "edges": edges,
        "viewport": (existing_canvas or {}).get("viewport") or {"x": 0, "y": 0, "zoom": 1},
        "metadata": metadata,
        "meta": dict(metadata),
        "timestamps": {
            "createdAt": ((existing_canvas or {}).get("timestamps") or {}).get("createdAt") or now,
            "updatedAt": now,
        },
    }
    return {
        "ok": True,
        "path": rel_path,
        "intent": clean_intent,
        "raw_intent": raw_intent,
        "execution_brief": execution_brief,
        "recipe": metadata["seed_recipe"],
        "canvas": canvas,
        "summary_counts": metadata["seed_status"]["summary"],
    }, 200


def build_judgment_prompt(path_value: str, canvas: dict[str, Any], intent: str, *, actor: str = "codex") -> str:
    metadata = canvas.get("metadata") if isinstance(canvas.get("metadata"), dict) else {}
    raw_intent = str(metadata.get("raw_intent") or intent or "").strip()
    execution_brief = metadata.get("execution_brief") if isinstance(metadata.get("execution_brief"), dict) else {}
    nodes = []
    for node in canvas.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        ref = data.get("source_ref") if isinstance(data.get("source_ref"), dict) else {}
        nodes.append({
            "id": node.get("id"),
            "type": node.get("type"),
            "title": data.get("title") or data.get("label"),
            "summary": data.get("summary") or "",
            "role": (data.get("metadata") or {}).get("role") if isinstance(data.get("metadata"), dict) else "",
            "source_ref": {"kind": ref.get("kind"), "path": ref.get("path"), "status": ref.get("status")},
        })
    edges = [
        {"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target"), "label": edge.get("label")}
        for edge in canvas.get("edges") or []
        if isinstance(edge, dict)
    ]
    return f"""你正在执行 kanban Context Canvas seed v0.2 的意图执行口。

硬约束:
- 目标不是整理骨架，而是按原始意图与 execution brief 产出可继续行动的工作台结果。
- 可以读取任务卡与骨架中已登记、已解析的必要来源；不要无界扫描目录，也不要读取密钥、token、cookie、.env。
- 若原始意图要求与特定模型或角色会商，只有实际完成调用后才能声称其参与；当前能力不足时必须在结果中明确标为未完成，禁止角色扮演冒充真实会商。
- 写画布只能走 kanban HTTP API: 先 GET /api/canvas?path={path_value}，再 PUT /api/canvas，body 必须包含 actor: "{actor}" 且带 base_rev。
- merge 红线: data.origin 为 "manual" 或 "owner" 的节点必须原样保留；data.origin 为 "manual" 或 "owner" 的边也必须原样保留；其它既有非本次 generated 刷新层也保留。
- 不新增 fact-* / 原子事实节点。

任务卡路径: {path_value}
原始意图（原样保留）: {json.dumps(raw_intent, ensure_ascii=False)}
执行 brief: {json.dumps(execution_brief, ensure_ascii=False, indent=2)}

<skeleton_nodes>
{json.dumps(nodes, ensure_ascii=False, indent=2)}
</skeleton_nodes>

<skeleton_edges>
{json.dumps(edges, ensure_ascii=False, indent=2)}
</skeleton_edges>

输出要求:
1. 先核对来源是否足够支撑原始意图；不足时把缺口做成醒目的待确认节点，不得假装完成。
2. 新增必要的 note/ref 节点承载 execution brief 中的动作、交付和待拍板项；节点必须有实质内容，不能只写入口或模板句。
3. 调整布局与 edges，让用户打开后能直接进行下一步判断或操作；可把不相关候选标记 hidden。
4. PUT 成功后简短回复: 节点数、边数、来源覆盖、完成门逐项结果、manual/owner 是否保真。
"""


def _read_env_values(paths: list[Path]) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                continue
            values[key] = value.strip().strip("'\"")
    return values


def _summarizer_integration(config: dict[str, Any] | None, provider: str) -> dict[str, Any]:
    integrations = (config or {}).get("integrations")
    summarizers = integrations.get("summarizers") if isinstance(integrations, dict) else None
    settings = summarizers.get(provider) if isinstance(summarizers, dict) else None
    return settings if isinstance(settings, dict) else {}


def _local_summarizer_settings(config: dict[str, Any] | None = None) -> dict[str, str] | None:
    settings = _summarizer_integration(config, "local")
    if settings.get("enabled") is not True:
        return None
    raw_files = settings.get("env_files")
    env_files = [Path(str(path)).expanduser() for path in raw_files] if isinstance(raw_files, list) else []
    env = _read_env_values(env_files)
    base_url = env.get("X_AIO_BASE_URL") or env.get("OPENCODE_BASE_URL") or env.get("GLM_BASE_URL") or ""
    api_key = env.get("X_AIO_API_KEY") or env.get("OPENCODE_API_KEY") or env.get("GLM_API_KEY") or ""
    model = env.get("X_AIO_MODEL") or env.get("OPENCODE_MODEL") or env.get("GLM_MODEL") or LOCAL_SUMMARIZER_MODEL
    if not base_url or not api_key:
        return None
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    return {"provider": "x-aio", "url": url, "key": api_key, "model": model}


def _deepseek_summarizer_settings(deps: dict[str, Any]) -> dict[str, str] | None:
    load_config = deps.get("load_config")
    config = load_config() if callable(load_config) else {}
    settings = _summarizer_integration(config, "deepseek")
    if settings.get("enabled") is not True:
        return None
    key = str(settings.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None
    return {"provider": "deepseek"}


def _local_summary_provider_chain(deps: dict[str, Any]) -> list[dict[str, str]]:
    load_config = deps.get("load_config")
    config = load_config() if callable(load_config) else {}
    providers = []
    x_aio = _local_summarizer_settings(config)
    if x_aio:
        providers.append(x_aio)
    deepseek = _deepseek_summarizer_settings(deps)
    if deepseek:
        providers.append(deepseek)
    return providers


def _snippet_with_anchors(path: Path, max_lines: int = 24, max_chars: int = 3600) -> tuple[str, str]:
    if not path.is_file() or SECRETISH_RE.search(path.name) or path.suffix.lower() not in TEXT_SUMMARY_EXTS:
        return "", ""
    rows = []
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            rows.append(f"{path}:{line_no}: {stripped[:240]}")
            if len(rows) >= max_lines or sum(len(row) for row in rows) >= max_chars:
                break
    except OSError:
        return "", ""
    if not rows:
        return "", ""
    return "\n".join(rows), f"{path}:1"


def _local_summary_messages(title: str, snippet: str) -> list[dict[str, str]]:
    return [
            {
                "role": "system",
                "content": "你只根据给定带行号片段写一句中文用途摘要。必须包含一个 file:line 锚。无法判断就返回空字符串。",
            },
            {
                "role": "user",
                "content": f"文件名: {title}\n\n带锚片段:\n{snippet}\n\n只输出一句用途摘要，句末保留 file:line 锚。",
            },
    ]


def _provider_label(settings: dict[str, str]) -> str:
    provider = str(settings.get("provider") or "x-aio").strip() or "x-aio"
    model = str(settings.get("model") or "").strip()
    return f"{provider}:{model}" if model else provider


def _is_empty_summary_error(error: str) -> bool:
    text = str(error or "").lower()
    return "empty" in text or "空内容" in text or "空字符串" in text


def _call_local_summary_model(
    settings: dict[str, str],
    title: str,
    snippet: str,
    *,
    llm_chat=None,
) -> tuple[bool, str, str]:
    provider = str(settings.get("provider") or "x-aio").strip() or "x-aio"
    label = _provider_label(settings)
    messages = _local_summary_messages(title, snippet)
    if provider == "deepseek":
        if not callable(llm_chat):
            return False, "missing_llm_chat", label
        ok, content = llm_chat("deepseek", messages, max_tokens=220, temperature=0.1)
        if not ok:
            return False, content or "deepseek_failed", label
        text = _single_line(content, 220).strip()
        if not text:
            return False, "empty", label
        if not re.search(r":[0-9]+\b", text):
            return False, "missing_anchor", label
        return True, text, label

    payload = json.dumps({
        "model": settings["model"],
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        settings["url"],
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings['key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return False, exc.__class__.__name__, label
    content = (((result.get("choices") or [{}])[0]).get("message") or {}).get("content")
    text = _single_line(content, 220).strip()
    if not text:
        return False, "empty", label
    if not re.search(r":[0-9]+\b", text):
        return False, "missing_anchor", label
    return True, text, label


def _call_summary_provider_with_empty_retry(
    settings: dict[str, str],
    title: str,
    snippet: str,
    *,
    llm_chat=None,
) -> tuple[bool, str, str, int]:
    attempts = 0
    last_error = ""
    label = _provider_label(settings)
    for attempt in range(2):
        attempts += 1
        result = _call_local_summary_model(settings, title, snippet, llm_chat=llm_chat)
        if len(result) == 2:
            ok, text = result
            provider = label
        else:
            ok, text, provider = result
        label = provider or label
        if ok:
            return True, text, label, attempts
        last_error = text or "failed"
        if attempt == 0 and _is_empty_summary_error(last_error):
            continue
        break
    return False, last_error or "failed", label, attempts


def _call_summary_chain(
    providers: list[dict[str, str]],
    deps: dict[str, Any],
    title: str,
    snippet: str,
) -> dict[str, Any]:
    failures = []
    total_attempts = 0
    llm_chat = deps.get("llm_chat")
    for provider_settings in providers:
        ok, text, provider, attempts = _call_summary_provider_with_empty_retry(
            provider_settings,
            title,
            snippet,
            llm_chat=llm_chat,
        )
        total_attempts += attempts
        if ok:
            return {
                "ok": True,
                "summary": text,
                "provider": provider,
                "attempts": total_attempts,
                "failures": failures,
            }
        failures.append({"provider": provider, "error": _single_line(text, 120), "attempts": attempts})
    error = "; ".join(f"{item['provider']}:{item['error']}" for item in failures) or "no_summary_provider"
    failed_chain = ">".join(item["provider"] for item in failures if item.get("provider"))
    return {"ok": False, "summary": "", "provider": failed_chain, "error": error, "attempts": total_attempts, "failures": failures}


def _summary_node_update(node: dict[str, Any], *, status: str, summary: str = "", error: str = "", provider: str = "") -> dict[str, Any]:
    updated = json.loads(json.dumps(node, ensure_ascii=False))
    data = updated.setdefault("data", {})
    metadata = data.setdefault("metadata", {})
    metadata["local_summary_status"] = status
    metadata["local_summary_actor"] = LOCAL_SUMMARIZER_ACTOR
    metadata["local_summary_updated_at"] = datetime.now().replace(microsecond=0).isoformat()
    if provider:
        metadata["local_summary_provider"] = _single_line(provider, 80)
    if error:
        metadata["local_summary_error"] = _single_line(error, 80)
    else:
        metadata.pop("local_summary_error", None)
    if summary:
        data["summary"] = summary
    return updated


def run_local_summary_backfill(deps: dict[str, Any], path_value: str, *, max_nodes: int = 40) -> dict[str, Any]:
    started = time.monotonic()
    providers = _local_summary_provider_chain(deps)
    get_canvas = deps.get("get_canvas_for_task")
    put_node = deps.get("put_canvas_node")
    if not providers and (not callable(get_canvas) or not callable(put_node)):
        return {"ok": True, "skipped": True, "reason": "local_summarizer_unconfigured"}
    if not callable(get_canvas) or not callable(put_node):
        return {"ok": False, "error": "missing_canvas_node_api"}
    payload, status = get_canvas(path_value)
    if status != 200 or not payload.get("canvas"):
        return {"ok": False, "error": "canvas_not_found", "status": status}
    canvas = payload["canvas"]
    canvas_rev = payload.get("canvas_rev") or payload.get("rev") or ""
    done = failed = skipped = 0
    failure_details: list[dict[str, Any]] = []
    if not providers:
        for node in list(canvas.get("nodes") or [])[:max_nodes]:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            if not metadata.get("local_summary_required") or data.get("summary"):
                continue
            result, result_status = put_node({
                "path": path_value,
                "node_id": node.get("id"),
                "node": _summary_node_update(node, status="skipped", error="local_summarizer_unconfigured"),
                "base_node": node,
                "base_rev": canvas_rev,
                "actor": LOCAL_SUMMARIZER_ACTOR,
            })
            if isinstance(result, dict):
                canvas_rev = result.get("canvas_rev") or result.get("rev") or canvas_rev
            skipped += 1 if result_status == 200 else 0
        return {"ok": True, "done": 0, "failed": 0, "skipped": skipped, "reason": "local_summarizer_unconfigured", "elapsed_ms": int((time.monotonic() - started) * 1000)}
    for node in list(canvas.get("nodes") or [])[:max_nodes]:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        ref = data.get("source_ref") if isinstance(data.get("source_ref"), dict) else {}
        if not metadata.get("local_summary_required") or data.get("summary"):
            continue
        if str(ref.get("kind") or "") != "file" or str(ref.get("status") or "") not in {"resolved", "corrected"}:
            result, result_status = put_node({
                "path": path_value,
                "node_id": node.get("id"),
                "node": _summary_node_update(node, status="skipped", error="unresolved_source"),
                "base_node": node,
                "base_rev": canvas_rev,
                "actor": LOCAL_SUMMARIZER_ACTOR,
            })
            canvas_rev = result.get("canvas_rev") or result.get("rev") or canvas_rev if isinstance(result, dict) else canvas_rev
            skipped += 1 if result_status == 200 else 0
            continue
        snippet, _anchor = _snippet_with_anchors(Path(str(ref.get("resolved_path") or "")))
        if not snippet:
            result, result_status = put_node({
                "path": path_value,
                "node_id": node.get("id"),
                "node": _summary_node_update(node, status="skipped", error="no_readable_snippet"),
                "base_node": node,
                "base_rev": canvas_rev,
                "actor": LOCAL_SUMMARIZER_ACTOR,
            })
            canvas_rev = result.get("canvas_rev") or result.get("rev") or canvas_rev if isinstance(result, dict) else canvas_rev
            skipped += 1 if result_status == 200 else 0
            continue
        chain_result = _call_summary_chain(
            providers,
            deps,
            str(data.get("title") or data.get("label") or node.get("id")),
            snippet,
        )
        ok = bool(chain_result.get("ok"))
        summary = str(chain_result.get("summary") or "")
        provider = str(chain_result.get("provider") or "")
        error = "" if ok else str(chain_result.get("error") or "summary_failed")
        if not ok:
            failure_details.append({
                "node_id": node.get("id"),
                "failures": chain_result.get("failures") or [],
            })
        update = _summary_node_update(
            node,
            status="done" if ok else "failed",
            summary=summary if ok else "",
            error=error,
            provider=provider,
        )
        result, result_status = put_node({
            "path": path_value,
            "node_id": node.get("id"),
            "node": update,
            "base_node": node,
            "base_rev": canvas_rev,
            "actor": LOCAL_SUMMARIZER_ACTOR,
        })
        if isinstance(result, dict):
            canvas_rev = result.get("canvas_rev") or result.get("rev") or canvas_rev
        if result_status == 200 and ok:
            done += 1
        elif result_status == 200:
            failed += 1
    result = {"ok": True, "done": done, "failed": failed, "skipped": skipped, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    if failure_details:
        result["failure_details"] = failure_details
    return result


def start_local_summary_backfill(deps: dict[str, Any], path_value: str) -> None:
    def worker() -> None:
        try:
            run_local_summary_backfill(deps, path_value)
        except Exception:
            return

    threading.Thread(target=worker, name="canvas-seed-local-summary", daemon=True).start()


def build_seed_prompt(deps: dict[str, Any], path_value: str, intent: str, *, actor: str = "codex") -> tuple[dict[str, Any], int]:
    resolve_active = deps["resolve_active_task_card_path"]
    read_task = deps["read_task_file"]
    _task_path, rel_path, err, status = resolve_active(path_value)
    if err:
        return {"ok": False, "error": err}, status
    task_file, read_err = read_task(rel_path)
    if not task_file:
        return {"ok": False, "error": read_err}, 404 if read_err == "文件不存在" else 400
    clean_intent = _single_line(intent, 260)
    if not clean_intent:
        return {"ok": False, "error": "缺少 seed intent"}, 400
    raw_intent = str(intent).strip()
    context = build_seed_intent_context(deps, rel_path, task_file)
    execution_brief = build_execution_brief(context, raw_intent)
    recipe = execution_brief["recipe"]
    now = datetime.now().replace(microsecond=0).isoformat()
    prompt = f"""你正在执行 kanban Context Canvas 的 agent seed。

<seed_contract version="{CANVAS_SEED_PROMPT_VERSION}">
- 目标: 把任务卡 × Owner 确认意图 转成一张可复用工作台画布。
- 卡片路径: {rel_path}
- 确认意图: {clean_intent}
- 原始意图(必须原样保留): {raw_intent}
- 执行 brief: {json.dumps(execution_brief, ensure_ascii=False)}
- 配方标识: {recipe}
- 只通过 kanban HTTP API 写画布: PUT /api/canvas, body 必须包含 actor: "{actor}"。禁止直接编辑 project/*/.canvas/*.json。
- 写入前先 GET /api/canvas?path={rel_path} 读取已有画布和 canvas_rev；写入时带 base_rev。
- merge 红线: 任何 data.origin 为 "manual" 或 "owner" 的节点必须原样保留；任何 data.origin 为 "manual" 或 "owner" 的边必须原样保留；无 origin 但不属于本次 generated 刷新层的现有节点/边也保留。丢 Owner 判断就是事故。
- 可读: 任务卡正文、workdir 材料(可以读标题/开头；引用原文必须写 file:line 锚)、[[链接]] 卡、*.jsonl ledger/registry 逐条读。
- 不可做: 代画判断边；写"通常承载…"这类模板句；搬/拷文件；读取或外泄密钥、token、cookie、.env。
- 节点: 默认只生成文件/目录/链接 REF 节点，source_ref 齐全；不要把 fact-ledger 里的原子事实铺成 fact-* 节点，原子事实只作为 AI 消费材料。
- 文件节点显示: 标题用文件名/目录名/链接名，不把完整绝对路径放标题；可确认用途时写一句 summary，无法确认就留空，不写模板句。
- 布局: {recipe}。triage=原料列 + 判断锚列；composition=证据引文区 + 论点骨架区；consultation=问题区 + 建议区 + 待拍板区；research-thinking=问题 + 证据 + 假设 + 判断链；general=按执行 brief 组织。固定列 x，按高排 y，零重叠。
- meta: 在 canvas.metadata 至少写 raw_intent、execution_brief、seed_intent、seed_recipe、seed_sources、seed_prompt_version、seeded_at；为兼容客户端可同步写 canvas.meta 同字段。
</seed_contract>

<available_context>
{_context_to_prompt(context)}
</available_context>

交付步骤:
1. 读取卡片和必要材料，记录 seed_sources。
2. 读取现有画布，按 merge 红线构造新 canvas。
3. 用 PUT /api/canvas 写入，actor="{actor}"，带 base_rev。
4. 返回简短结果: 画布节点/边数、seed_recipe、seed_sources 摘要、manual/owner 保真是否通过。
"""
    return {
        "ok": True,
        "path": rel_path,
        "intent": clean_intent,
        "raw_intent": raw_intent,
        "execution_brief": execution_brief,
        "recipe": recipe,
        "prompt": prompt,
        "display_message": f"按意图生成画布: {clean_intent}",
        "metadata": {
            "canvas_seed": {
                "intent": clean_intent,
                "raw_intent": raw_intent,
                "execution_brief": execution_brief,
                "recipe": recipe,
                "prompt_version": CANVAS_SEED_PROMPT_VERSION,
                "queued_at": now,
            }
        },
    }, 200


def node_origin(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("origin") or "").strip().lower()


def edge_origin(edge: dict[str, Any]) -> str:
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    return str(data.get("origin") or edge.get("origin") or "").strip().lower()


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manual_lineage_snapshot(canvas: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = {}
    edges = {}
    for node in canvas.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        origin = node_origin(node)
        if origin in MANUAL_ORIGINS:
            node_id = str(node.get("id") or "")
            if node_id:
                nodes[node_id] = node
    for edge in canvas.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        origin = edge_origin(edge)
        if origin in MANUAL_ORIGINS:
            edge_id = str(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}")
            if edge_id:
                edges[edge_id] = edge
    return {"nodes": nodes, "edges": edges}


def check_manual_lineage_preserved(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    expected = manual_lineage_snapshot(before)
    actual = manual_lineage_snapshot(after)
    missing_nodes = sorted(set(expected["nodes"]) - set(actual["nodes"]))
    missing_edges = sorted(set(expected["edges"]) - set(actual["edges"]))
    changed_nodes = sorted(
        node_id for node_id in (set(expected["nodes"]) & set(actual["nodes"]))
        if _stable(expected["nodes"][node_id]) != _stable(actual["nodes"][node_id])
    )
    changed_edges = sorted(
        edge_id for edge_id in (set(expected["edges"]) & set(actual["edges"]))
        if _stable(expected["edges"][edge_id]) != _stable(actual["edges"][edge_id])
    )
    ok = not (missing_nodes or missing_edges or changed_nodes or changed_edges)
    return {
        "ok": ok,
        "manual_nodes": len(expected["nodes"]),
        "manual_edges": len(expected["edges"]),
        "missing_nodes": missing_nodes,
        "missing_edges": missing_edges,
        "changed_nodes": changed_nodes,
        "changed_edges": changed_edges,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canvas seed helper checks")
    parser.add_argument("--check-merge", action="store_true", help="verify manual/owner nodes and edges are preserved")
    parser.add_argument("--before", help="before canvas JSON")
    parser.add_argument("--after", help="after canvas JSON")
    args = parser.parse_args(argv)
    if args.check_merge:
        if not args.before or not args.after:
            parser.error("--check-merge requires --before and --after")
        report = check_manual_lineage_preserved(_read_json(Path(args.before)), _read_json(Path(args.after)))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Project-level projection over Conversation Maps, task cards, and documents.

Session manifests remain independent source artifacts.  This module builds a
replayable aggregate graph and keeps only cross-object judgments in an
append-only relation ledger.  AI-inferred relations are never upgraded to
facts by presentation code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


GRAPH_SCHEMA = "conversation-project-graph/v1"
RELATION_SCHEMA = "graph-relation/v1"
EVENT_SCHEMA = "graph-relation-event/v1"
LEDGER_REL = Path("_project_graph") / "relations.jsonl"
PROMOTED_DIR = Path("_project_graph") / "promoted"
PROMOTED_SCHEMA = "promoted-branch-snapshot/v1"
SNAPSHOT_FILE = "card-snapshots.json"
ENTITY_TYPES = {"session", "branch", "task", "document", "selection", "artifact"}
RELATION_TYPES = {"branch_from", "supports", "produces", "belongs_to", "references", "supersedes"}
ASSERTIONS = {"hard_evidence", "ai_archived", "human_confirmed"}
# 同一 relation_id 只允许向更强断言升级(人工确认 > 硬证据 > AI 归档),弱断言永不覆盖强断言
ASSERTION_RANK = {"ai_archived": 0, "hard_evidence": 1, "human_confirmed": 2}
# hard_evidence 必须携带至少一条可核验种类的证据;语义相似/时间邻近等弱证据只能走 ai_archived
HARD_EVIDENCE_KINDS = {
    "explicit_keep_to_map", "parent_run_id", "queue_run", "native_metadata",
    "archive_manifest", "selection_anchor", "task_frontmatter", "related_path",
}
STATUSES = {"active", "invalidated", "abandoned"}
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(value):
    text = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or "").strip()).strip("-._:")
    return text or "unknown"


def _maps_root(deps):
    return Path(deps["maps_root"]()).resolve()


def _ledger_path(deps):
    return _maps_root(deps) / LEDGER_REL


def _atomic_append_jsonl(path, event, lock=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    if lock:
        with lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _read_events(path):
    events = []
    if not path.exists():
        return events
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    event.setdefault("ledger_line", line_number)
                    events.append(event)
    except OSError:
        return []
    return events


def _current_relations(events):
    current = {}
    for event in events:
        relation = event.get("relation") if isinstance(event.get("relation"), dict) else None
        relation_id = str((relation or {}).get("relation_id") or event.get("relation_id") or "").strip()
        if relation_id and relation:
            current[relation_id] = dict(relation)
    return current


def _node(node_id, kind, title, **data):
    return {
        "id": node_id,
        "type": kind,
        "title": str(title or node_id),
        **data,
    }


def _edge(edge_id, source, target, relation, assertion="hard_evidence", status="active", **data):
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "relation": relation,
        "assertion": assertion,
        "status": status,
        **data,
    }


def _task_node_id(task_id):
    return "task:" + _slug(task_id)


def _session_node_id(session_id):
    return "session:" + _slug(session_id)


def _branch_node_id(session_id, branch_id):
    return "branch:" + _slug(session_id) + ":" + _slug(branch_id)


def _document_node_id(path):
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return "document:" + digest


def _task_indexes(tasks):
    by_id = {}
    by_path = {}
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        path = str(task.get("path") or "").strip()
        if task_id:
            by_id[task_id] = task
        if path:
            by_path[path] = task
    return by_id, by_path


def _load_card_snapshots(manifest_abs_path):
    path = Path(manifest_abs_path).parent / SNAPSHOT_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    rows = data.get("cards") if isinstance(data, dict) else []
    return {
        str(row.get("task_id") or ""): row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("task_id")
    }


def _safe_related_paths(task):
    value = task.get("related_paths") if isinstance(task, dict) else []
    return [str(path).strip() for path in value if str(path).strip()] if isinstance(value, list) else []


def _live_task_payload(task, repo_root):
    path = str(task.get("path") or "")
    absolute = (Path(repo_root) / path).resolve() if path else None
    sha = ""
    if absolute and absolute.is_file():
        try:
            sha = hashlib.sha256(absolute.read_bytes()).hexdigest()
        except OSError:
            sha = ""
    return {
        "path": path,
        "title": task.get("title") or task.get("display_title") or task.get("task_id"),
        "status": task.get("status") or "",
        "updated": task.get("updated") or "",
        "sha256": sha,
    }


def _project_base(deps):
    tasks = deps["scan_tasks"]() or []
    task_by_id, task_by_path = _task_indexes(tasks)
    nodes = {}
    edges = {}
    session_ids = set()

    def add_node(node):
        existing = nodes.get(node["id"])
        if not existing or (
            existing.get("archive_state") == "parent_reference_only"
            and node.get("archive_state") != "parent_reference_only"
        ):
            nodes[node["id"]] = node

    def add_edge(edge):
        edges.setdefault(edge["id"], edge)

    maps_result, maps_status = deps["list_conversation_maps"]()
    map_rows = maps_result.get("maps") if maps_status == 200 and isinstance(maps_result, dict) else []
    for map_row in map_rows or []:
        manifest_path = map_row.get("path")
        manifest, status = deps["get_conversation_map"](manifest_path)
        if status != 200 or not isinstance(manifest, dict):
            continue
        thread = manifest.get("thread") if isinstance(manifest.get("thread"), dict) else {}
        session_id = str(thread.get("id") or map_row.get("thread_id") or map_row.get("canvas_scope") or "").strip()
        if not session_id:
            continue
        session_ids.add(session_id)
        session_node = _session_node_id(session_id)
        add_node(_node(
            session_node,
            "session_map",
            thread.get("title") or map_row.get("title") or session_id,
            session_id=session_id,
            agent=thread.get("agent") or "",
            status=manifest.get("status") or "archived",
            archive_state="formal",
            manifest_path=manifest.get("manifest_path") or manifest_path,
            manifest_abs_path=manifest.get("manifest_abs_path") or "",
            canvas_scope=manifest.get("canvas_scope") or map_row.get("canvas_scope") or "",
            generated_at=manifest.get("generated_at") or "",
            assertion="hard_evidence",
        ))
        snapshots = _load_card_snapshots(manifest.get("manifest_abs_path") or "")
        manifest_nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), list) else []
        known_branch_ids = {
            str(item.get("id") or "")
            for item in manifest_nodes
            if isinstance(item, dict) and (item.get("branch_from") or item.get("type") == "branch")
        }
        for item in manifest_nodes:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            branch_from = str(item.get("branch_from") or "").strip()
            if item_id in known_branch_ids:
                branch_node = _branch_node_id(session_id, item_id)
                add_node(_node(
                    branch_node,
                    "archived_branch",
                    item.get("title") or item_id,
                    session_id=session_id,
                    branch_id=item_id,
                    branch_from_node=branch_from or None,
                    status=item.get("status") or "archived",
                    summary=item.get("summary") or "",
                    source=item.get("source") or [],
                    assertion="hard_evidence",
                ))
                add_edge(_edge(
                    f"contains:{session_node}->{branch_node}",
                    session_node,
                    branch_node,
                    "contains_branch",
                ))
                if branch_from and branch_from in known_branch_ids:
                    parent = _branch_node_id(session_id, branch_from)
                    add_edge(_edge(
                        f"branch_from:{parent}->{branch_node}",
                        parent,
                        branch_node,
                        "branch_from",
                    ))
            card_id = str(item.get("card") or "").strip()
            if not TASK_ID_RE.match(card_id):
                continue
            task_node = _task_node_id(card_id)
            live_task = task_by_id.get(card_id)
            snapshot = snapshots.get(card_id) or {
                "task_id": card_id,
                "captured_at": manifest.get("generated_at") or "",
                "source": "manifest_card_mention",
                "map_node": item_id,
                "title": item.get("title") or "",
                "summary": item.get("summary") or "",
            }
            live = _live_task_payload(live_task, deps["repo_root"]) if live_task else None
            drift = {
                "state": "unknown",
                "changed": None,
            }
            if live and snapshot.get("sha256"):
                changed = live.get("sha256") != snapshot.get("sha256")
                drift = {"state": "changed" if changed else "same", "changed": changed}
            add_node(_node(
                task_node,
                "task",
                (live_task or {}).get("title") or snapshot.get("title") or card_id,
                task_id=card_id,
                live_ref=live,
                snapshot_at_archive=snapshot,
                drift=drift,
                assertion="hard_evidence",
            ))
            source = _branch_node_id(session_id, item_id) if item_id in known_branch_ids else session_node
            add_edge(_edge(
                f"card:{source}->{task_node}:{item_id}",
                source,
                task_node,
                "references",
                evidence=[{"manifest": manifest_path, "node_id": item_id, "field": "card"}],
            ))

    for task in tasks:
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            continue
        task_node = _task_node_id(task_id)
        related_paths = _safe_related_paths(task)
        # The aggregate graph is relation-driven. Do not turn the full kanban
        # inventory into a disconnected card wall; an unreferenced task enters
        # only when it has an explicit document link or an active run below.
        if task_node not in nodes and not related_paths:
            continue
        live = _live_task_payload(task, deps["repo_root"])
        if task_node not in nodes:
            add_node(_node(
                task_node,
                "task",
                task.get("title") or task_id,
                task_id=task_id,
                live_ref=live,
                snapshot_at_archive=None,
                drift={"state": "not_archived", "changed": None},
                assertion="hard_evidence",
            ))
        for raw_path in related_paths:
            if Path(raw_path).suffix.lower() not in {".md", ".markdown"}:
                continue
            expanded = Path(os.path.expanduser(raw_path))
            if not expanded.is_absolute():
                workdir = Path(os.path.expanduser(str(task.get("workdir") or "")))
                expanded = (workdir / expanded) if str(workdir) else (Path(deps["repo_root"]) / expanded)
            resolved = expanded.resolve()
            document_node = _document_node_id(resolved)
            add_node(_node(
                document_node,
                "document",
                resolved.name,
                path=str(resolved),
                exists=resolved.is_file(),
                assertion="hard_evidence",
            ))
            add_edge(_edge(
                f"task_document:{task_node}->{document_node}",
                task_node,
                document_node,
                "references",
                evidence=[{"task_path": task.get("path"), "field": "related_paths"}],
            ))

    queue = deps["queue_snapshot"]() or {}
    for entry in queue.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        dialogue = ((entry.get("metadata") or {}).get("dialogue") or {}) if isinstance(entry.get("metadata"), dict) else {}
        if dialogue.get("lifecycle") in {"transient", "durable_on_promotion"}:
            continue
        run_id = str(entry.get("id") or entry.get("run_id") or "").strip()
        if not run_id:
            continue
        native_session = str(entry.get("session_id") or "").strip()
        if native_session and native_session in session_ids and entry.get("status") not in {"queued", "running"}:
            continue
        run_node = "run:" + _slug(run_id)
        run_status = str(entry.get("status") or "unknown")
        archive_state = "active_placeholder" if run_status in {"queued", "running"} else "awaiting_archive"
        if run_status in {"killed", "error", "timeout"}:
            archive_state = "abandoned"
        add_node(_node(
            run_node,
            "branch_placeholder",
            entry.get("title") or run_id,
            run_id=run_id,
            session_id=native_session or None,
            agent=entry.get("tool") or "",
            status=run_status,
            archive_state=archive_state,
            created_at=entry.get("timestamp") or "",
            workdir=entry.get("workdir") or "",
            assertion="hard_evidence",
        ))
        fork = ((entry.get("metadata") or {}).get("fork") or {}) if isinstance(entry.get("metadata"), dict) else {}
        parent_run = str(fork.get("parent_run_id") or "").strip()
        if parent_run:
            parent_node = "run:" + _slug(parent_run)
            add_node(_node(
                parent_node,
                "branch_placeholder",
                parent_run,
                run_id=parent_run,
                status="unknown",
                archive_state="parent_reference_only",
                assertion="hard_evidence",
            ))
            add_edge(_edge(
                f"branch_from:{parent_node}->{run_node}",
                parent_node,
                run_node,
                "branch_from",
                evidence=[{"queue_run": run_id, "parent_run_id": parent_run}],
            ))
        task = task_by_path.get(str(entry.get("path") or ""))
        if task and task.get("task_id"):
            task_node = _task_node_id(task.get("task_id"))
            if task_node not in nodes:
                add_node(_node(
                    task_node,
                    "task",
                    task.get("title") or task.get("task_id"),
                    task_id=task.get("task_id"),
                    live_ref=_live_task_payload(task, deps["repo_root"]),
                    snapshot_at_archive=None,
                    drift={"state": "not_archived", "changed": None},
                    assertion="hard_evidence",
                ))
            add_edge(_edge(
                f"run_task:{run_node}->{task_node}",
                run_node,
                task_node,
                "belongs_to",
                evidence=[{"queue_run": run_id, "task_path": entry.get("path")}],
            ))
    return nodes, edges


def build_project_graph(deps):
    nodes, edges = _project_base(deps)
    events = _read_events(_ledger_path(deps))
    relations = _current_relations(events)
    for relation in relations.values():
        source = relation["from"]["id"]
        target = relation["to"]["id"]
        for endpoint in (relation["from"], relation["to"]):
            if endpoint["id"] not in nodes:
                snapshot = None
                if endpoint["id"].startswith("run:"):
                    snapshot = _load_promoted_snapshot(deps, endpoint["id"][len("run:"):])
                if snapshot:
                    first_user = next(
                        (row for row in snapshot.get("messages") or []
                         if isinstance(row, dict) and row.get("role") == "user"),
                        {},
                    )
                    title = (
                        str(snapshot.get("title") or "").strip()
                        or str(first_user.get("content") or "").strip()[:120]
                        or endpoint["id"]
                    )
                    nodes[endpoint["id"]] = _node(
                        endpoint["id"],
                        endpoint.get("type") or "branch",
                        title,
                        run_id=snapshot.get("run_id"),
                        agent=snapshot.get("tool") or "",
                        task_path=snapshot.get("task_path") or "",
                        message_count=len(snapshot.get("messages") or []),
                        promoted_at=snapshot.get("captured_at"),
                        snapshot_ref=str(PROMOTED_DIR / (_slug(snapshot.get("run_id") or "") + ".json")),
                        assertion=relation.get("assertion"),
                    )
                    continue
                evidence = relation.get("evidence") or []
                first_evidence = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
                quote = first_evidence.get("source_quote") if isinstance(first_evidence.get("source_quote"), dict) else {}
                title = (
                    str(quote.get("quote_text") or "").strip()[:120]
                    or str(first_evidence.get("title") or "").strip()[:120]
                    or endpoint["id"]
                )
                nodes[endpoint["id"]] = _node(
                    endpoint["id"],
                    endpoint.get("type") or "external_ref",
                    title,
                    assertion=relation.get("assertion"),
                    unresolved=True,
                )
        edge = _edge(
            "relation:" + relation["relation_id"],
            source,
            target,
            relation["relation"],
            assertion=relation["assertion"],
            status=relation["status"],
            confidence=relation.get("confidence"),
            evidence=relation.get("evidence") or [],
            relation_id=relation["relation_id"],
            created_at=relation.get("created_at"),
            supersedes=relation.get("supersedes"),
        )
        edges[edge["id"]] = edge
    node_rows = sorted(nodes.values(), key=lambda row: (row.get("type", ""), row.get("title", ""), row["id"]))
    edge_rows = sorted(edges.values(), key=lambda row: (row.get("relation", ""), row["id"]))
    return {
        "ok": True,
        "schema": GRAPH_SCHEMA,
        "generated_at": _now(),
        "nodes": node_rows,
        "edges": edge_rows,
        "relations": sorted(relations.values(), key=lambda row: row.get("created_at") or ""),
        "ledger_path": str(_ledger_path(deps)),
        "counts": {
            "nodes": len(node_rows),
            "edges": len(edge_rows),
            "ai_archived": sum(1 for row in relations.values() if row.get("assertion") == "ai_archived" and row.get("status") == "active"),
            "active_placeholders": sum(1 for row in node_rows if row.get("archive_state") == "active_placeholder"),
        },
    }, 200


def _endpoint(value):
    if not isinstance(value, dict):
        return None
    kind = str(value.get("type") or "").strip()
    entity_id = str(value.get("id") or "").strip()
    if kind not in ENTITY_TYPES or not entity_id or len(entity_id) > 512:
        return None
    return {"type": kind, "id": entity_id}


def _relation_id(source, target, relation):
    raw = json.dumps([source, target, relation], ensure_ascii=False, sort_keys=True)
    return "rel_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _promoted_snapshot_path(deps, run_id):
    return _maps_root(deps) / PROMOTED_DIR / (_slug(run_id) + ".json")


def _load_promoted_snapshot(deps, run_id):
    path = _promoted_snapshot_path(deps, run_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _snapshot_promoted_runs(deps, endpoints, relation_id):
    """晋升时把旁聊正文快照进地图工作台。

    队列结果(*.ai-results/.ai-queue)不进 git 且可被清理;human_confirmed 关系
    引用的对话必须有账本侧的耐久正文,否则「保留到地图」只留下锚。幂等:已有
    快照不覆盖(首次晋升内容不可变);dedup 路径也调用,给历史晋升自愈回填。"""
    for endpoint in endpoints:
        entity_id = str((endpoint or {}).get("id") or "")
        if not entity_id.startswith("run:"):
            continue
        run_id = entity_id[len("run:"):]
        path = _promoted_snapshot_path(deps, run_id)
        if path.exists():
            continue
        queue = deps["queue_snapshot"]() or {}
        entry = next(
            (row for row in queue.get("entries") or []
             if isinstance(row, dict) and str(row.get("id") or row.get("run_id") or "") == run_id),
            None,
        )
        if not entry:
            continue
        snapshot = {
            "schema": PROMOTED_SCHEMA,
            "run_id": run_id,
            "relation_id": relation_id,
            "tool": entry.get("tool") or "",
            "title": entry.get("title") or "",
            "task_path": entry.get("path") or "",
            "workdir": entry.get("workdir") or "",
            "status": entry.get("status") or "",
            "dialogue": ((entry.get("metadata") or {}).get("dialogue")
                         if isinstance(entry.get("metadata"), dict) else None),
            "messages": entry.get("messages") or [],
            "captured_at": _now(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            "w", dir=str(path.parent), suffix=".tmp", delete=False, encoding="utf-8",
        )
        try:
            json.dump(snapshot, tmp, ensure_ascii=False, indent=1)
            tmp.close()
            os.replace(tmp.name, path)
        finally:
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except OSError:
                pass


def append_relation(deps, payload, actor="human"):
    source = _endpoint(payload.get("from"))
    target = _endpoint(payload.get("to"))
    relation_type = str(payload.get("relation") or "").strip()
    assertion = str(payload.get("assertion") or "ai_archived").strip()
    if not source or not target or source == target:
        return {"ok": False, "error": "关系端点无效"}, 400
    if relation_type not in RELATION_TYPES:
        return {"ok": False, "error": "关系类型无效"}, 400
    if assertion not in ASSERTIONS:
        return {"ok": False, "error": "断言类型无效"}, 400
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    evidence = evidence[:20]
    if assertion == "ai_archived" and not evidence:
        return {"ok": False, "error": "AI 归档关系必须提供证据"}, 400
    if assertion == "hard_evidence":
        kinds = {str(row.get("kind") or "").strip() for row in evidence if isinstance(row, dict)}
        if not kinds & HARD_EVIDENCE_KINDS:
            return {
                "ok": False,
                "error": "hard_evidence 断言必须携带可核验证据(kind ∈ "
                         + "/".join(sorted(HARD_EVIDENCE_KINDS)) + ");弱证据请用 ai_archived",
            }, 400
    try:
        confidence = float(payload.get("confidence", 1 if assertion != "ai_archived" else 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0.0, min(1.0, confidence))
    relation_id = str(payload.get("relation_id") or _relation_id(source, target, relation_type)).strip()
    if assertion == "human_confirmed":
        # dedup 之前执行:重复点击「保留到地图」也能给缺快照的历史晋升自愈回填
        _snapshot_promoted_runs(deps, (source, target), relation_id)
    current = _current_relations(_read_events(_ledger_path(deps)))
    existing = current.get(relation_id)
    upgraded_from = None
    if existing and existing.get("status") == "active":
        existing_rank = ASSERTION_RANK.get(str(existing.get("assertion") or ""), 0)
        if ASSERTION_RANK.get(assertion, 0) <= existing_rank:
            return {"ok": True, "deduped": True, "relation": existing}, 200
        upgraded_from = str(existing.get("assertion") or "")
    relation = {
        "schema": RELATION_SCHEMA,
        "relation_id": relation_id,
        "from": source,
        "to": target,
        "relation": relation_type,
        "status": "active",
        "assertion": assertion,
        "confidence": confidence,
        "evidence": evidence,
        "created_at": _now(),
        "created_by": str(actor or "ai")[:80],
        "model": str(payload.get("model") or "")[:200] or None,
        "rule_version": str(payload.get("rule_version") or "")[:120] or None,
        "supersedes": str(payload.get("supersedes") or "")[:200] or None,
    }
    if upgraded_from:
        relation["upgraded_from"] = upgraded_from
    event = {
        "schema": EVENT_SCHEMA,
        "event": "relation_asserted",
        "at": relation["created_at"],
        "actor": relation["created_by"],
        "relation": relation,
    }
    _atomic_append_jsonl(_ledger_path(deps), event, deps.get("write_lock"))
    result = {"ok": True, "deduped": False, "relation": relation}
    if upgraded_from:
        result["upgraded"] = True
    return result, 200


def audit_relations(deps, payload=None, actor="ai_auditor"):
    payload = payload if isinstance(payload, dict) else {}
    path = _ledger_path(deps)
    events = _read_events(path)
    current = _current_relations(events)
    base_nodes, base_edges = _project_base(deps)
    stronger = {
        (row.get("from", {}).get("id"), row.get("to", {}).get("id"), row.get("relation")): row
        for row in current.values()
        if row.get("status") == "active" and row.get("assertion") in {"hard_evidence", "human_confirmed"}
    }
    invalidated = []
    kept = []
    for relation in current.values():
        if relation.get("status") != "active" or relation.get("assertion") != "ai_archived":
            continue
        source = relation.get("from", {}).get("id")
        target = relation.get("to", {}).get("id")
        key = (source, target, relation.get("relation"))
        reason = ""
        superseded_by = None

        def _endpoint_exists(node_id):
            if node_id in base_nodes:
                return True
            # 晋升快照物化的分支不在基础图里,但它是耐久归档事实,不算端点缺失
            text = str(node_id or "")
            return text.startswith("run:") and _load_promoted_snapshot(deps, text[len("run:"):]) is not None

        if not _endpoint_exists(source) or not _endpoint_exists(target):
            reason = "endpoint_missing_from_current_project_graph"
        elif key in stronger:
            reason = "stronger_relation_available"
            superseded_by = stronger[key].get("relation_id")
        if not reason:
            kept.append(relation["relation_id"])
            continue
        replacement = dict(relation)
        replacement["status"] = "invalidated"
        replacement["invalidated_at"] = _now()
        replacement["invalidated_reason"] = reason
        replacement["superseded_by"] = superseded_by
        event = {
            "schema": EVENT_SCHEMA,
            "event": "relation_invalidated",
            "at": replacement["invalidated_at"],
            "actor": str(actor or "ai_auditor")[:80],
            "audit_run_id": str(payload.get("audit_run_id") or "audit_" + hashlib.sha256(_now().encode()).hexdigest()[:12]),
            "model": str(payload.get("model") or "")[:200] or None,
            "rule_version": str(payload.get("rule_version") or "project-graph-audit/v1")[:120],
            "relation": replacement,
        }
        _atomic_append_jsonl(path, event, deps.get("write_lock"))
        invalidated.append(relation["relation_id"])
    return {
        "ok": True,
        "schema": "graph-relation-audit/v1",
        "audited_at": _now(),
        "invalidated": invalidated,
        "kept": kept,
        "note": "语义重评可由定期 AI 调用同一端点提交新关系；此处先执行确定性证据自检。",
    }, 200

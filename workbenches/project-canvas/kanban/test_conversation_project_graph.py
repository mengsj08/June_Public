import importlib.util
import json
import threading
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("conversation_project_graph_test", HERE / "conversation_project_graph.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _deps(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    maps = tmp_path / "maps"
    map_dir = maps / "sid-1"
    map_dir.mkdir(parents=True)
    manifest = map_dir / "manifest.yaml"
    manifest.write_text("thread: sid-1\n", encoding="utf-8")
    (map_dir / "card-snapshots.json").write_text(json.dumps({
        "cards": [{
            "task_id": "KAN-9",
            "path": "project/X/card.md",
            "title": "Archived title",
            "status": "todo",
            "sha256": "old-sha",
            "captured_at": "2026-07-10T00:00:00+08:00",
        }],
    }), encoding="utf-8")
    card = repo / "project" / "X" / "card.md"
    card.parent.mkdir(parents=True)
    card.write_text("live card\n", encoding="utf-8")
    doc = tmp_path / "context.md"
    doc.write_text("# Context\n", encoding="utf-8")
    tasks = [{
        "task_id": "KAN-9",
        "path": "project/X/card.md",
        "title": "Live title",
        "status": "in-progress",
        "workdir": str(tmp_path),
        "related_paths": [str(doc)],
    }]
    manifest_payload = {
        "thread": {"id": "sid-1", "title": "Archived session", "agent": "codex"},
        "status": "archived",
        "generated_at": "2026-07-10T00:00:00+08:00",
        "manifest_path": "sid-1/manifest.yaml",
        "manifest_abs_path": str(manifest),
        "canvas_scope": "sid-1",
        "nodes": [{
            "id": "branch-a",
            "type": "branch",
            "title": "Branch A",
            "status": "recorded",
            "branch_from": "node-root",
            "card": "KAN-9",
            "summary": "Created the task",
            "source": ["L10..L20"],
        }],
    }
    queue = {
        "entries": [{
            "id": "run-child",
            "path": "project/X/card.md",
            "tool": "claude",
            "status": "running",
            "timestamp": "2026-07-11T00:00:00",
            "metadata": {"fork": {"parent_run_id": "run-parent"}},
        }, {
            "id": "quick",
            "path": "project/X/card.md",
            "tool": "codex",
            "status": "completed",
            "metadata": {"dialogue": {"lifecycle": "transient"}},
        }, {
            "id": "unpromoted-side-chat",
            "path": "project/X/card.md",
            "tool": "claude",
            "status": "completed",
            "metadata": {"dialogue": {"lifecycle": "durable_on_promotion"}},
        }],
    }
    return {
        "repo_root": repo,
        "maps_root": lambda: maps,
        "scan_tasks": lambda: tasks,
        "queue_snapshot": lambda: queue,
        "list_conversation_maps": lambda: ({"maps": [{"path": "sid-1/manifest.yaml"}]}, 200),
        "get_conversation_map": lambda path: (manifest_payload, 200),
        "write_lock": threading.Lock(),
    }


def test_project_graph_links_sessions_branches_tasks_documents_and_active_runs(tmp_path):
    graph, status = MODULE.build_project_graph(_deps(tmp_path))
    assert status == 200
    node_ids = {node["id"] for node in graph["nodes"]}
    assert "session:sid-1" in node_ids
    assert "branch:sid-1:branch-a" in node_ids
    assert "task:KAN-9" in node_ids
    assert "run:run-child" in node_ids
    assert "run:quick" not in node_ids
    assert "run:unpromoted-side-chat" not in node_ids
    task = next(node for node in graph["nodes"] if node["id"] == "task:KAN-9")
    assert task["snapshot_at_archive"]["sha256"] == "old-sha"
    assert task["drift"]["state"] == "changed"
    assert graph["counts"]["active_placeholders"] == 1
    relations = {(edge["source"], edge["target"], edge["relation"]) for edge in graph["edges"]}
    assert ("branch:sid-1:branch-a", "task:KAN-9", "references") in relations
    assert ("run:run-parent", "run:run-child", "branch_from") in relations


def test_ai_archived_relation_is_idempotent_and_self_invalidates_missing_endpoint(tmp_path):
    deps = _deps(tmp_path)
    payload = {
        "from": {"type": "session", "id": "session:sid-1"},
        "to": {"type": "task", "id": "task:MISSING-1"},
        "relation": "supports",
        "assertion": "ai_archived",
        "confidence": 0.72,
        "evidence": [{"kind": "semantic_similarity", "score": 0.72}],
        "model": "test-model",
        "rule_version": "test/v1",
    }
    first, status = MODULE.append_relation(deps, payload, actor="ai")
    second, second_status = MODULE.append_relation(deps, payload, actor="ai")
    assert status == second_status == 200
    assert first["deduped"] is False
    assert second["deduped"] is True

    audit, audit_status = MODULE.audit_relations(deps, {"audit_run_id": "audit-1"})
    assert audit_status == 200
    assert audit["invalidated"] == [first["relation"]["relation_id"]]
    graph, _ = MODULE.build_project_graph(deps)
    relation = next(row for row in graph["relations"] if row["relation_id"] == first["relation"]["relation_id"])
    assert relation["status"] == "invalidated"
    assert relation["invalidated_reason"] == "endpoint_missing_from_current_project_graph"


def test_human_confirmed_upgrades_active_ai_archived_and_never_downgrades(tmp_path):
    deps = _deps(tmp_path)
    triple = {
        "from": {"type": "selection", "id": "selection:quote-1"},
        "to": {"type": "branch", "id": "run:side-chat-1"},
        "relation": "branch_from",
    }
    ai_payload = {
        **triple,
        "assertion": "ai_archived",
        "confidence": 0.6,
        "evidence": [{"kind": "semantic_similarity", "score": 0.6}],
    }
    first, status = MODULE.append_relation(deps, ai_payload, actor="ai")
    assert status == 200
    assert first["deduped"] is False

    human_payload = {
        **triple,
        "assertion": "human_confirmed",
        "confidence": 1,
        "evidence": [{"kind": "explicit_keep_to_map"}],
    }
    upgraded, status = MODULE.append_relation(deps, human_payload, actor="Owner")
    assert status == 200
    assert upgraded["deduped"] is False
    assert upgraded.get("upgraded") is True
    relation = upgraded["relation"]
    assert relation["relation_id"] == first["relation"]["relation_id"]
    assert relation["assertion"] == "human_confirmed"
    assert relation["upgraded_from"] == "ai_archived"

    # 同强度重复提交 → 幂等
    again, _ = MODULE.append_relation(deps, human_payload, actor="Owner")
    assert again["deduped"] is True

    # 降级尝试(AI 覆盖人工确认)被挡，账面仍是 human_confirmed
    downgrade, _ = MODULE.append_relation(deps, ai_payload, actor="ai")
    assert downgrade["deduped"] is True
    assert downgrade["relation"]["assertion"] == "human_confirmed"

    # 折叠进图后的账本边以最新(更强)断言呈现
    graph, _ = MODULE.build_project_graph(deps)
    edge = next(row for row in graph["edges"] if row.get("relation_id") == relation["relation_id"])
    assert edge["assertion"] == "human_confirmed"


def test_hard_evidence_requires_verifiable_evidence_kind(tmp_path):
    deps = _deps(tmp_path)
    payload = {
        "from": {"type": "session", "id": "session:sid-1"},
        "to": {"type": "task", "id": "task:KAN-9"},
        "relation": "supports",
        "assertion": "hard_evidence",
    }
    rejected, status = MODULE.append_relation(deps, {**payload, "evidence": []}, actor="ai")
    assert status == 400
    assert "hard_evidence" in rejected["error"]

    weak, status = MODULE.append_relation(
        deps, {**payload, "evidence": [{"kind": "semantic_similarity", "score": 0.9}]}, actor="ai",
    )
    assert status == 400
    assert "ai_archived" in weak["error"]

    accepted, status = MODULE.append_relation(
        deps, {**payload, "evidence": [{"kind": "parent_run_id", "parent_run_id": "run-parent"}]}, actor="ai",
    )
    assert status == 200
    assert accepted["deduped"] is False


def test_promotion_snapshots_side_chat_and_survives_queue_cleanup(tmp_path):
    deps = _deps(tmp_path)
    queue = deps["queue_snapshot"]()
    queue["entries"].append({
        "id": "side-chat-live",
        "path": "project/X/card.md",
        "tool": "claude",
        "status": "completed",
        "title": "旁聊:锚点问题",
        "workdir": str(tmp_path),
        "metadata": {"dialogue": {"origin": "selection_side_chat", "lifecycle": "durable_on_promotion"}},
        "messages": [
            {"role": "user", "content": "围绕锚点继续问"},
            {"role": "ai", "content": "这是旁聊正文"},
        ],
    })
    payload = {
        "from": {"type": "selection", "id": "selection:quote-live"},
        "to": {"type": "branch", "id": "run:side-chat-live"},
        "relation": "branch_from",
        "assertion": "human_confirmed",
        "confidence": 1,
        "evidence": [{"kind": "explicit_keep_to_map", "run_id": "side-chat-live"}],
    }
    first, status = MODULE.append_relation(deps, payload, actor="Owner")
    assert status == 200 and first["deduped"] is False

    snapshot_path = tmp_path / "maps" / "_project_graph" / "promoted" / "side-chat-live.json"
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["schema"] == "promoted-branch-snapshot/v1"
    assert len(snapshot["messages"]) == 2

    # 队列被清理后,晋升分支仍从快照物化,不再是 unresolved 占位
    queue["entries"] = [row for row in queue["entries"] if row.get("id") != "side-chat-live"]
    graph, _ = MODULE.build_project_graph(deps)
    node = next(row for row in graph["nodes"] if row["id"] == "run:side-chat-live")
    assert not node.get("unresolved")
    assert node["message_count"] == 2
    assert node["title"] == "旁聊:锚点问题"

    # 有快照背书的端点不被 audit 当作缺失端点扫掉
    ai_rel = {
        "from": {"type": "session", "id": "session:sid-1"},
        "to": {"type": "branch", "id": "run:side-chat-live"},
        "relation": "supports",
        "assertion": "ai_archived",
        "confidence": 0.5,
        "evidence": [{"kind": "semantic_similarity", "score": 0.5}],
    }
    appended, status = MODULE.append_relation(deps, ai_rel, actor="ai")
    assert status == 200
    audit, _ = MODULE.audit_relations(deps, {"audit_run_id": "audit-2"})
    assert appended["relation"]["relation_id"] in audit["kept"]

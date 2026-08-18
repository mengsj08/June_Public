import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("session_evidence_adapter_test", HERE / "session_evidence_adapter.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_adapter_merges_fleet_line_evidence_agent_mail_coverage_and_archive_state():
    deps = {
        "agent_mail_cli": Path("/unused/am.py"),
        "fleet_search": lambda query, limit: [{
            "platform": "claude",
            "session_id": "abcdef12-0000-0000-0000-000000000000",
            "path": "/transcripts/abcdef12.jsonl",
            "line": 42,
            "project_slug": "demo",
            "ts": "2026-07-11T01:00:00",
            "excerpt": "selected phrase",
            "context": [{"line": 42, "text": "selected phrase", "is_match": True}],
        }],
        "agent_mail_search": lambda query, days, limit, cli: (
            "聊过「selected」的会话(新→旧):\n"
            "  [cl] 07-11 abcdef12 Archived title\n"
            "        …selected phrase…\n"
            "  [cx] 07-10 019f0000 Codex title\n"
        ),
        "list_conversation_maps": lambda: ({"maps": [{
            "thread_id": "abcdef12-0000-0000-0000-000000000000",
            "path": "abcdef12/manifest.yaml",
            "title": "Archived title",
        }]}, 200),
    }

    result, status = MODULE.search(deps, "selected", days=90, limit=10)

    assert status == 200
    assert result["fact_policy"] == "read_only_observation_not_task_truth"
    assert len(result["results"]) == 2
    fleet = next(row for row in result["results"] if row["source"] == "claude_fleet")
    assert fleet["physical_line"] == 42
    assert fleet["archive"]["path"] == "abcdef12/manifest.yaml"
    codex = next(row for row in result["results"] if row["platform"] == "codex")
    assert codex["session_id_prefix"] == "019f0000"
    assert codex["evidence_kind"] == "archive_coverage_deduped"


def test_adapter_rejects_empty_or_oversized_query():
    deps = {"list_conversation_maps": lambda: ({"maps": []}, 200)}
    assert MODULE.search(deps, "")[1] == 400
    assert MODULE.search(deps, "x" * 201)[1] == 400


def test_adapter_marks_unreachable_sources_instead_of_claiming_them():
    deps = {
        "fleet_search": lambda query, limit: None,
        "agent_mail_search": lambda query, days, limit, cli: "",
        "list_conversation_maps": lambda: ({"maps": []}, 200),
    }
    result, status = MODULE.search(deps, "anything")
    assert status == 200
    assert result["results"] == []
    assert result["sources"]["claude_fleet"].startswith("unavailable")
    assert not result["sources"]["agent_mail"].startswith("unavailable")


def test_adapter_marks_agent_mail_failure_distinct_from_empty_output():
    deps = {
        "fleet_search": lambda query, limit: [],
        "agent_mail_search": lambda query, days, limit, cli: None,
        "list_conversation_maps": lambda: ({"maps": []}, 200),
    }
    result, status = MODULE.search(deps, "anything")
    assert status == 200
    assert result["sources"]["agent_mail"].startswith("unavailable")
    assert not result["sources"]["claude_fleet"].startswith("unavailable")

import importlib.util
import threading
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("kanban_task_document_links_test", HERE / "task_document_links.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _deps(tmp_path, task_file):
    return {
        "allowed_roots": [tmp_path],
        "write_lock": threading.Lock(),
        "read_task_file": lambda path: (task_file, None) if path == "project/X/card.md" else (None, "文件不存在"),
        "frontmatter_block_list_values": lambda block, key: [],
    }


def test_list_only_exposes_linked_markdown_documents(tmp_path):
    linked = tmp_path / "linked.md"
    linked.write_text("# Linked\n", encoding="utf-8")
    ignored = tmp_path / "code.py"
    ignored.write_text("pass\n", encoding="utf-8")
    task_file = {
        "path": tmp_path / "card.md",
        "frontmatter": {
            "task_id": "KAN-1",
            "workdir": str(tmp_path),
            "related_paths": [str(ignored), str(linked)],
            "default_context_doc": str(linked),
        },
        "frontmatter_block": "---\n---\n",
    }

    result, status = MODULE.list_linked_documents(_deps(tmp_path, task_file), "project/X/card.md")

    assert status == 200
    assert result["ok"] is True
    assert [row["path"] for row in result["documents"]] == [str(linked)]
    assert result["documents"][0]["is_default"] is True
    assert result["documents"][0]["writable"] is True


def test_append_selection_requires_task_allowlist_and_writes_provenance(tmp_path):
    linked = tmp_path / "linked.md"
    linked.write_text("# Notes\n", encoding="utf-8")
    other = tmp_path / "other.md"
    other.write_text("# Other\n", encoding="utf-8")
    task_file = {
        "path": tmp_path / "card.md",
        "frontmatter": {
            "task_id": "KAN-2",
            "workdir": str(tmp_path),
            "related_paths": [str(linked)],
        },
        "frontmatter_block": "---\n---\n",
    }
    deps = _deps(tmp_path, task_file)
    source_quote = {
        "quote_text": "first line\nsecond line",
        "section": "Decision",
        "context": {"prefix": "before", "suffix": "after"},
        "source_locator": {
            "task_path": "project/X/card.md",
            "body_rev": "rev-1",
            "text_index": 12,
            "block_index": 3,
        },
    }

    denied, denied_status = MODULE.append_selection(deps, {
        "path": "project/X/card.md",
        "document_path": str(other),
        "source_quote": source_quote,
    })
    assert denied_status == 403
    assert denied["ok"] is False
    assert other.read_text(encoding="utf-8") == "# Other\n"

    result, status = MODULE.append_selection(deps, {
        "path": "project/X/card.md",
        "document_path": str(linked),
        "source_quote": source_quote,
        "session_id": "session-7",
        "branch_id": "branch-2",
        "actor": "owner",
    })
    assert status == 200
    assert result["ok"] is True
    content = linked.read_text(encoding="utf-8")
    assert "> first line\n> second line" in content
    assert '"schema": "selection-anchor/v1"' in content
    assert '"task_id": "KAN-2"' in content
    assert '"session_id": "session-7"' in content
    assert '"branch_id": "branch-2"' in content
    assert '"exact": "first line\\nsecond line"' in content


def test_outside_allowed_root_is_visible_but_not_writable(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    task_file = {
        "path": allowed / "card.md",
        "frontmatter": {
            "task_id": "KAN-3",
            "workdir": str(allowed),
            "related_paths": [str(outside)],
        },
        "frontmatter_block": "---\n---\n",
    }
    deps = _deps(allowed, task_file)

    result, status = MODULE.list_linked_documents(deps, "project/X/card.md")

    assert status == 200
    assert result["documents"][0]["exists"] is True
    assert result["documents"][0]["writable"] is False
    assert "允许根目录" in result["documents"][0]["reason"]

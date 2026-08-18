#!/usr/bin/env python3
"""Tests for governance provenance/freshness probe."""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_PROBE = _HERE.parent / "governance" / "provenance_probe.py"
if not _PROBE.is_file():
    pytest.skip("missing optional source path: governance/provenance_probe.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("provenance_probe", _PROBE)
provenance_probe = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = provenance_probe
_spec.loader.exec_module(provenance_probe)


def _write_task(path, title, task_id, status, **fields):
    lines = [
        "---",
        f"title: {title}",
        f"task_id: {task_id}",
        f"status: {status}",
        "assignee: Codex",
        "priority: medium",
    ]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", "", "## 执行结果", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def test_good_reference_passes_and_dead_reference_fails(tmp_path):
    repo = tmp_path
    project = repo / "project" / "个人调度"
    good_material = repo / "materials" / "source.md"
    good_material.parent.mkdir()
    good_material.write_text("source\n", encoding="utf-8")
    projection = repo / "project" / "个人调度" / ".canvas" / "GOOD-1" / "main.canvas.json"
    projection.parent.mkdir(parents=True)
    projection.write_text(
        json.dumps(
            {
                "schema": "kanban.canvas/v1",
                "generated_at": "2026-07-07T09:00:00+08:00",
                "nodes": [
                    {"data": {"source_ref": {"kind": "file", "path": "materials/source.md"}}},
                    {"data": {"source_ref": {"kind": "file", "path": "missing/from-canvas.md"}}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_task(
        project / "GOOD-1_good.md",
        "good",
        "GOOD-1",
        "todo",
        workdir=str(repo),
        related_paths=["materials/source.md"],
        canvas_ref="project/个人调度/.canvas/GOOD-1/main.canvas.json",
        canvas_updated="2026-07-07",
    )
    _write_task(
        project / "BAD-1_bad.md",
        "bad",
        "BAD-1",
        "todo",
        workdir=str(repo),
        related_paths=["materials/missing.md"],
    )
    config = repo / ".kanban.config.json"
    config.write_text(json.dumps({"scan_dirs": ["project/个人调度"]}), encoding="utf-8")
    manifest = repo / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_state_items": [],
                "projection_sources": {
                    "canvas_refs": {"enabled": True, "freshness_days": 14},
                    "landing_pages": {"enabled": False},
                    "canvas_json_globs": [],
                },
            }
        ),
        encoding="utf-8",
    )

    result = provenance_probe.build_probe(
        repo_root=repo,
        manifest_path=manifest,
        config_path=config,
        now=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )

    pointers = result["pointers"]
    assert any(item["ok"] and item["value"].endswith("materials/source.md") for item in pointers)
    assert any((not item["ok"]) and item["value"].endswith("materials/missing.md") for item in pointers)
    assert any((not item["ok"]) and item["value"].endswith("missing/from-canvas.md") for item in pointers)
    assert result["metrics"]["M07"]["numerator"] < result["metrics"]["M07"]["denominator"]


def test_freshness_manifest_reports_fresh_and_stale_state(tmp_path):
    repo = tmp_path
    config = repo / ".kanban.config.json"
    config.write_text(json.dumps({"scan_dirs": ["project"]}), encoding="utf-8")
    fresh = repo / "fresh.json"
    stale = repo / "stale.json"
    fresh.write_text(json.dumps({"generated_at": "2026-07-07T09:00:00+08:00"}), encoding="utf-8")
    stale.write_text(json.dumps({"generated_at": "2026-06-01T09:00:00+08:00"}), encoding="utf-8")
    manifest = repo / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_state_items": [
                    {"id": "fresh", "path": "fresh.json", "freshness_days": 3, "timestamp_fields": ["generated_at"]},
                    {"id": "stale", "path": "stale.json", "freshness_days": 3, "timestamp_fields": ["generated_at"]},
                ],
                "projection_sources": {"landing_pages": {"enabled": False}, "canvas_refs": {"enabled": False}},
            }
        ),
        encoding="utf-8",
    )

    result = provenance_probe.build_probe(
        repo_root=repo,
        manifest_path=manifest,
        config_path=config,
        now=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )

    states = {item["id"]: item["state"] for item in result["freshness"]}
    assert states == {"fresh": "fresh", "stale": "stale"}
    assert result["metrics"]["M14"]["numerator"] == 1
    assert result["metrics"]["M14"]["denominator"] == 2

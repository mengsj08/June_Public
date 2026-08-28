"""End-to-end orchestration for the public SIH reference pipeline."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .core import (
    apply_incremental,
    classify_daily_health,
    deduplicate,
    generated_at,
    normalize_item,
    public_item,
    score_item,
    text,
    write_json_atomic,
    write_jsonl,
)
from .delivery import publish_webhook, write_local_outputs
from .intelligence import llm_triage
from .sources import collect_source


TIER_ORDER = {"must_read": 0, "skim": 1, "collapsed": 2, "archive": 3}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration must be a JSON object: {path}")
    return payload


def _safe_segment(value: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", text(value)).strip(".-")
    return cleaned[:80] or "unnamed-source"


def _source_manifest(source: Mapping[str, Any], result: Any, *, run_at: str) -> dict[str, Any]:
    return {
        "source_id": text(source.get("id")),
        "source_kind": text(source.get("kind")),
        "enabled": bool(source.get("enabled", False)),
        "required": bool(source.get("required", False)),
        "role": text(source.get("role") or "supplemental"),
        "status": result.status,
        "item_count": len(result.items),
        "checks": result.checks,
        "error": text(result.error),
        "generated_at": run_at,
    }


def run_pipeline(
    *,
    config_path: Path,
    profile_path: Path,
    output_dir: Path,
    as_of: date,
    live: bool = False,
    llm_enabled: bool = False,
    publish: bool = False,
    stateless: bool = False,
    deterministic: bool = False,
) -> dict[str, Any]:
    """Run every enabled stage while keeping network gates independent."""
    config_path = config_path.resolve()
    profile_path = profile_path.resolve()
    config = load_json(config_path)
    profile = load_json(profile_path)
    sources = config.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise ValueError("Configuration requires a non-empty sources list")
    run_at = generated_at(as_of, deterministic)
    base_dir = config_path.parent
    source_health: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []

    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each source configuration must be an object")
        source_id = text(source.get("id"))
        if not source_id:
            raise ValueError("Each source requires a non-empty id")
        result = collect_source(source, base_dir=base_dir, live=live, as_of=as_of)
        manifest = _source_manifest(source, result, run_at=run_at)
        source_health.append(manifest)
        source_dir = output_dir / "sources" / _safe_segment(source_id)
        write_json_atomic(source_dir / "manifest.json", manifest)
        write_jsonl(source_dir / "items.raw.jsonl", result.items)
        source_items = [normalize_item(item, source) for item in result.items]
        source_items = apply_incremental(
            source_items,
            None if stateless else output_dir / ".state" / f"{_safe_segment(source_id)}.json",
            persist=not stateless,
        )
        normalized.extend(source_items)

    assembled = [score_item(item, profile, as_of) for item in deduplicate(normalized)]
    provider = config.get("llm") or {}
    llm_status: dict[str, Any] = {"status": "disabled"}
    if llm_enabled and not provider.get("enabled", False):
        llm_status = {"status": "inactive", "reason": "disabled_by_config"}
    elif llm_enabled:
        try:
            decisions = llm_triage(assembled, profile, provider, enabled=True)
            for item in assembled:
                decision = decisions.get(text(item.get("item_id")))
                if decision:
                    item["llm_triage"] = decision
            llm_status = {"status": "ok", "decision_count": len(decisions)}
        except Exception as exc:
            llm_status = {"status": "warning", "error": f"{type(exc).__name__}: {text(exc)}"}

    public_items = [public_item(item) for item in assembled]
    public_items.sort(
        key=lambda item: (
            TIER_ORDER.get(text(item.get("reading_tier")), 99),
            -float(item.get("topic_relevance") or 0),
            text(item.get("published_at")),
            text(item.get("title")).lower(),
        )
    )
    active_health = [entry for entry in source_health if entry["enabled"]]
    daily_status = classify_daily_health(active_health)
    if llm_status["status"] == "warning" and daily_status == "complete":
        daily_status = "complete_with_warning"
    health = {
        "schema_version": "1.0",
        "as_of": as_of.isoformat(),
        "generated_at": run_at,
        "daily_status": daily_status,
        "source_count": len([source for source in sources if source.get("enabled", False)]),
        "loaded_source_count": len(
            [entry for entry in source_health if entry["status"] in {"ok", "ok_no_updates"}]
        ),
        "sources": source_health,
        "extensions": {"llm_triage": llm_status},
    }
    outputs = write_local_outputs(
        output_dir,
        public_items,
        health,
        as_of=as_of.isoformat(),
        synthetic_demo=bool(config.get("synthetic_demo", False)),
    )
    sink_result = publish_webhook(
        {
            "schema_version": "1.0",
            "as_of": as_of.isoformat(),
            "daily_status": daily_status,
            "item_count": len(public_items),
            "items": public_items,
        },
        config.get("delivery") or {},
        publish=publish,
    )
    return {
        "daily_status": daily_status,
        "item_count": len(public_items),
        "outputs": outputs,
        "sink": sink_result,
    }

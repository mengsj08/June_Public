"""Local projections, public-content packages, and explicitly gated sinks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .core import text, write_json_atomic, write_jsonl
from .render import render_markdown, render_site


def public_content_candidates(items: Sequence[Mapping[str, Any]], *, as_of: str) -> list[dict[str, Any]]:
    """Build review candidates without creating platform drafts or publishing."""
    candidates: list[dict[str, Any]] = []
    for item in items:
        if item.get("reading_tier") not in {"must_read", "skim"}:
            continue
        candidates.append(
            {
                "candidate_id": f"content:{item.get('item_id')}",
                "source_item_id": item.get("item_id"),
                "source_url": item.get("url"),
                "title": item.get("title"),
                "angle_hint": "Explain what changed, why it matters, and what remains uncertain.",
                "audience": "researchers_and_builders",
                "status": "needs_human_review",
                "as_of": as_of,
            }
        )
    return candidates


def write_local_outputs(
    output_dir: Path,
    items: Sequence[Mapping[str, Any]],
    health: Mapping[str, Any],
    *,
    as_of: str,
    synthetic_demo: bool,
) -> dict[str, str]:
    """Write every local projection from the same item pool."""
    output_dir.mkdir(parents=True, exist_ok=True)
    items_path = output_dir / "daily_items.jsonl"
    health_path = output_dir / "source_health.json"
    briefing_path = output_dir / "daily_briefing.md"
    site_path = output_dir / "site" / "index.html"
    content_path = output_dir / "public_content_candidates.jsonl"
    write_jsonl(items_path, items)
    write_json_atomic(health_path, health)
    briefing_path.write_text(render_markdown(items, health, as_of=as_of), encoding="utf-8")
    site_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.write_text(render_site(items, health, as_of=as_of, synthetic_demo=synthetic_demo), encoding="utf-8")
    write_jsonl(content_path, public_content_candidates(items, as_of=as_of))
    return {
        "items": str(items_path),
        "health": str(health_path),
        "briefing": str(briefing_path),
        "site": str(site_path),
        "public_content_candidates": str(content_path),
    }


def publish_webhook(
    payload: Mapping[str, Any],
    sink: Mapping[str, Any],
    *,
    publish: bool,
) -> dict[str, Any]:
    """Send only with three explicit gates: enabled, --publish, endpoint_env."""
    if not sink.get("enabled", False):
        return {"status": "disabled"}
    if not publish:
        return {"status": "dry_run", "payload_keys": sorted(payload.keys())}
    endpoint_env = text(sink.get("endpoint_env"))
    endpoint = os.environ.get(endpoint_env, "") if endpoint_env else ""
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Webhook publishing requires an HTTPS endpoint from endpoint_env")
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=int(sink.get("timeout_seconds") or 20)) as response:  # noqa: S310 - explicit user config
        status_code = int(response.status)
    return {"status": "published" if 200 <= status_code < 300 else "failed", "status_code": status_code}

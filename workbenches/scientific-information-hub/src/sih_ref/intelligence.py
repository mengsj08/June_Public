"""Profile loading and explicitly opt-in OpenAI-compatible LLM triage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .core import text


VALID_DECISIONS = {"prioritize", "skim", "hold", "exclude"}


def load_profile(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Profile must be a JSON object: {path}")
    return payload


def _endpoint(provider: Mapping[str, Any]) -> str:
    endpoint_env = text(provider.get("endpoint_env"))
    endpoint = os.environ.get(endpoint_env, "") if endpoint_env else text(provider.get("endpoint"))
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LLM endpoint must be an explicit http(s) URL or endpoint_env")
    return endpoint.rstrip("/")


def _extract_json(value: str) -> Any:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(value)


def llm_triage(
    items: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    provider: Mapping[str, Any],
    *,
    enabled: bool,
) -> dict[str, dict[str, Any]]:
    """Return validated per-item judgments; never mutate deterministic tiers."""
    if not enabled or not items:
        return {}
    endpoint = _endpoint(provider)
    api_key_env = text(provider.get("api_key_env"))
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""
    model = text(provider.get("model") or os.environ.get(text(provider.get("model_env")), ""))
    if not model:
        raise ValueError("LLM provider requires model or model_env")
    if provider.get("requires_api_key", True) and not api_key:
        raise ValueError("LLM API key environment variable is not set")

    compact_items = [
        {
            "item_id": text(item.get("item_id")),
            "title": text(item.get("title"))[:300],
            "summary": text(item.get("summary"))[:900],
            "tags": item.get("tags") or [],
            "deterministic_tier": text(item.get("reading_tier")),
            "topic_relevance": item.get("topic_relevance"),
        }
        for item in items
    ]
    system = (
        "You triage scientific-information metadata. Return JSON only: an array of objects with "
        "item_id, decision, confidence, reason. decision must be prioritize, skim, hold, or exclude. "
        "Do not claim scientific validity or clinical evidence quality. Keep each reason under 40 words."
    )
    user = json.dumps(
        {
            "profile_name": text(profile.get("name") or "custom"),
            "profile_terms": sorted((profile.get("topic_terms") or {}).keys()),
            "items": compact_items,
        },
        ensure_ascii=False,
    )
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    request = Request(
        f"{endpoint}/chat/completions" if not endpoint.endswith("/chat/completions") else endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    with urlopen(request, timeout=int(provider.get("timeout_seconds") or 60)) as response:  # noqa: S310 - explicit user config
        parsed = json.loads(response.read().decode("utf-8"))
    content = (((parsed.get("choices") or [{}])[0].get("message") or {}).get("content"))
    decisions = _extract_json(text(content))
    if not isinstance(decisions, list):
        raise ValueError("LLM triage must return a JSON array")
    allowed_ids = {text(item.get("item_id")) for item in items}
    result: dict[str, dict[str, Any]] = {}
    for raw in decisions:
        if not isinstance(raw, dict):
            continue
        item_id = text(raw.get("item_id"))
        decision = text(raw.get("decision")).lower()
        if item_id not in allowed_ids or decision not in VALID_DECISIONS:
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        result[item_id] = {
            "decision": decision,
            "confidence": round(confidence, 3),
            "reason": text(raw.get("reason"))[:300],
            "model": model,
        }
    return result

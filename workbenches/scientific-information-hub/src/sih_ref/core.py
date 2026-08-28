"""Deterministic item normalization, identity, freshness, and selection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


PUBLIC_ITEM_FIELDS = (
    "item_id",
    "source_id",
    "source_kind",
    "title",
    "url",
    "published_at",
    "summary",
    "authors",
    "tags",
    "event_type",
    "provenance",
    "topic_relevance",
    "method_novelty_hint",
    "reading_tier",
    "freshness_gate",
    "llm_triage",
)


def text(value: Any) -> str:
    """Return compact, control-character-free display text."""
    if value is None:
        return ""
    value_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(value))
    return " ".join(value_text.split())


def normalize_url(value: Any) -> str:
    """Normalize one public HTTP(S) URL and reject other schemes."""
    raw = text(value)
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((scheme, host, path, parts.query, ""))


def _clean_identifier(value: Any) -> str:
    return text(value).strip().lower().removeprefix("https://doi.org/")


def stable_identity(item: Mapping[str, Any]) -> str:
    """Return a stable identity from public scholarly identifiers or URL."""
    candidates = (
        ("pmid", _clean_identifier(item.get("pmid"))),
        ("doi", _clean_identifier(item.get("doi"))),
        ("arxiv", _clean_identifier(item.get("arxiv_id"))),
        ("url", normalize_url(item.get("canonical_url") or item.get("url"))),
    )
    for kind, value in candidates:
        if value:
            return f"{kind}:{value}"
    fallback = text(item.get("title")).lower()
    source = text(item.get("source_id")).lower()
    if not fallback:
        return ""
    digest = hashlib.sha256(f"{source}|{fallback}".encode("utf-8")).hexdigest()[:20]
    return f"fallback:{digest}"


def stable_fingerprint(item: Mapping[str, Any]) -> str:
    """Fingerprint fields whose change is meaningful across source runs."""
    payload = {
        "title": text(item.get("title")),
        "summary": text(item.get("summary")),
        "published_at": text(item.get("published_at"))[:10],
        "url": normalize_url(item.get("canonical_url") or item.get("url")),
        "doi": _clean_identifier(item.get("doi")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_date(value: Any) -> str:
    """Normalize common source date strings to YYYY-MM-DD when possible."""
    raw = text(value)
    if not raw:
        return ""
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", raw)
    if match:
        year, month, day_value = map(int, match.groups())
        try:
            return date(year, month, day_value).isoformat()
        except ValueError:
            return ""
    match = re.search(r"\b(20\d{2})\s+([A-Za-z]{3,9})\s+(\d{1,2})\b", raw)
    if match:
        for fmt in ("%Y %b %d", "%Y %B %d"):
            try:
                return datetime.strptime(" ".join(match.groups()), fmt).date().isoformat()
            except ValueError:
                pass
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def normalize_item(raw: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Project heterogeneous source fields into the public item contract."""
    authors_value = raw.get("authors") or []
    if isinstance(authors_value, str):
        authors = [part.strip() for part in re.split(r"[;,|]", authors_value) if part.strip()]
    elif isinstance(authors_value, Sequence):
        authors = [text(author) for author in authors_value if text(author)]
    else:
        authors = []
    tags_value = raw.get("tags") or source.get("tags") or []
    if isinstance(tags_value, str):
        tags = [part.strip().lower() for part in re.split(r"[;,|]", tags_value) if part.strip()]
    elif isinstance(tags_value, Sequence):
        tags = [text(tag).lower() for tag in tags_value if text(tag)]
    else:
        tags = []
    item = {
        "source_id": text(source.get("id") or raw.get("source_id")),
        "source_kind": text(source.get("kind") or raw.get("source_kind") or "unknown"),
        "title": text(raw.get("title") or raw.get("name")),
        "url": normalize_url(raw.get("canonical_url") or raw.get("url") or raw.get("link")),
        "published_at": normalize_date(raw.get("published_at") or raw.get("published") or raw.get("date")),
        "summary": text(raw.get("summary") or raw.get("abstract") or raw.get("description")),
        "authors": authors[:30],
        "tags": list(dict.fromkeys(tags))[:20],
        "pmid": _clean_identifier(raw.get("pmid")),
        "doi": _clean_identifier(raw.get("doi")),
        "arxiv_id": _clean_identifier(raw.get("arxiv_id")),
        "provenance": {
            "source_id": text(source.get("id") or raw.get("source_id")),
            "upstream_id": text(raw.get("upstream_id") or raw.get("id")),
            "retrieved_via": text(source.get("kind") or "unknown"),
        },
    }
    item["item_id"] = stable_identity(item)
    item["fingerprint"] = stable_fingerprint(item)
    return item


def apply_incremental(
    items: Sequence[dict[str, Any]],
    state_path: Path | None,
    *,
    persist: bool,
) -> list[dict[str, Any]]:
    """Stamp new/updated/seen using an optional local fingerprint state."""
    previous: dict[str, str] = {}
    if state_path and state_path.exists():
        try:
            parsed = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                previous = {text(k): text(v) for k, v in parsed.items() if text(k) and text(v)}
        except (OSError, json.JSONDecodeError):
            raise ValueError(f"Invalid incremental state: {state_path}") from None
    current: dict[str, str] = {}
    stamped: list[dict[str, Any]] = []
    for item in items:
        item_id = text(item.get("item_id"))
        fingerprint = text(item.get("fingerprint"))
        if not item_id or not fingerprint:
            continue
        current[item_id] = fingerprint
        event = "new" if item_id not in previous else "seen" if previous[item_id] == fingerprint else "updated"
        stamped_item = dict(item)
        stamped_item["event_type"] = event
        stamped.append(stamped_item)
    if state_path and persist:
        write_json_atomic(state_path, current)
    return stamped


def deduplicate(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the richest record per stable identity and preserve source lineage."""
    chosen: dict[str, dict[str, Any]] = {}
    source_sets: dict[str, set[str]] = {}
    for item in items:
        item_id = text(item.get("item_id"))
        if not item_id:
            continue
        source_sets.setdefault(item_id, set()).add(text(item.get("source_id")))
        existing = chosen.get(item_id)
        richness = len(text(item.get("summary"))) + len(item.get("authors") or []) * 12 + bool(item.get("doi")) * 30
        existing_richness = -1 if existing is None else len(text(existing.get("summary"))) + len(existing.get("authors") or []) * 12 + bool(existing.get("doi")) * 30
        if existing is None or richness > existing_richness:
            chosen[item_id] = item
    result: list[dict[str, Any]] = []
    for item_id, item in chosen.items():
        merged = dict(item)
        provenance = dict(merged.get("provenance") or {})
        provenance["observed_in_sources"] = sorted(value for value in source_sets[item_id] if value)
        merged["provenance"] = provenance
        result.append(merged)
    return result


def freshness_gate(item: Mapping[str, Any], as_of: date, lookback_days: int) -> str:
    """Return fresh, stale, future, or undated without inventing a date."""
    normalized = normalize_date(item.get("published_at"))
    if not normalized:
        return "undated"
    published = date.fromisoformat(normalized)
    age = (as_of - published).days
    if age < -1:
        return "future"
    return "fresh" if age <= lookback_days else "stale"


def score_item(item: Mapping[str, Any], profile: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    """Apply a transparent profile match and reading-tier policy."""
    haystack = " ".join(
        [text(item.get("title")), text(item.get("summary")), " ".join(item.get("tags") or [])]
    ).lower()
    topic_score = 0.0
    matched: list[str] = []
    for term, weight in (profile.get("topic_terms") or {}).items():
        normalized_term = text(term).lower()
        if normalized_term and normalized_term in haystack:
            topic_score += float(weight)
            matched.append(normalized_term)
    for term, penalty in (profile.get("negative_terms") or {}).items():
        normalized_term = text(term).lower()
        if normalized_term and normalized_term in haystack:
            topic_score -= abs(float(penalty))
    source_weight = float((profile.get("source_weights") or {}).get(text(item.get("source_kind")), 0.0))
    topic_score = max(0.0, min(1.0, topic_score + source_weight))
    novelty_terms = [text(term).lower() for term in profile.get("novelty_terms") or [] if text(term)]
    novelty_matches = [term for term in novelty_terms if term in haystack]
    novelty_hint = min(1.0, len(novelty_matches) * 0.25)
    lookback_days = int(profile.get("freshness_days") or 30)
    gate = freshness_gate(item, as_of, lookback_days)
    thresholds = profile.get("thresholds") or {}
    must_relevance = float((thresholds.get("must_read") or {}).get("topic_relevance", 0.62))
    must_novelty = float((thresholds.get("must_read") or {}).get("method_novelty_hint", 0.40))
    skim_relevance = float((thresholds.get("skim") or {}).get("topic_relevance", 0.30))
    collapsed_relevance = float((thresholds.get("collapsed") or {}).get("topic_relevance", 0.10))
    if gate in {"stale", "future"}:
        tier = "archive"
    elif topic_score >= must_relevance and novelty_hint >= must_novelty:
        tier = "must_read"
    elif topic_score >= skim_relevance:
        tier = "skim"
    elif topic_score >= collapsed_relevance:
        tier = "collapsed"
    else:
        tier = "archive"
    enriched = dict(item)
    enriched.update(
        {
            "topic_relevance": round(topic_score, 4),
            "method_novelty_hint": round(novelty_hint, 4),
            "reading_tier": tier,
            "freshness_gate": gate,
            "matched_profile_terms": matched,
            "matched_novelty_terms": novelty_matches,
        }
    )
    return enriched


def public_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the positive output-field allowlist."""
    return {field: item.get(field) for field in PUBLIC_ITEM_FIELDS}


def classify_daily_health(source_health: Sequence[Mapping[str, Any]]) -> str:
    """Classify a day without flattening optional warnings into hard failure."""
    required = [item for item in source_health if item.get("required")]
    required_failed = [item for item in required if item.get("status") in {"failed", "missing"}]
    required_ok = [item for item in required if item.get("status") in {"ok", "ok_no_updates"}]
    warnings = [
        item
        for item in source_health
        if item.get("status") in {"partial", "warning"}
        or (not item.get("required") and item.get("status") in {"failed", "missing"})
    ]
    if not required:
        hard_failures = [item for item in source_health if item.get("status") in {"failed", "missing"}]
        if source_health and len(hard_failures) == len(source_health):
            return "failed"
        return "complete_with_warning" if warnings else "complete"
    if required and len(required_failed) == len(required):
        return "failed"
    if required_failed:
        return "degraded"
    if warnings:
        return "complete_with_warning"
    if required_ok:
        return "complete"
    return "degraded"


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write JSON atomically without exposing partial state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def generated_at(as_of: date, deterministic: bool) -> str:
    if deterministic:
        return f"{as_of.isoformat()}T00:00:00+00:00"
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

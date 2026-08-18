"""Build a deterministic, presentation-only Mario game projection.

The projection does not own facts. It arranges one Mario Unit's approved
relationship facts into reusable map primitives for renderers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = "mario.game-projection/v1"


def _stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _projection_hash(value):
    payload = _stable_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_refs_for_links(links, sources):
    source_by_path = {
        str(Path(str(source.get("path") or "")).expanduser()): str(source.get("role") or "")
        for source in sources
        if source.get("path") and source.get("role")
    }
    refs = []
    for link in links:
        raw_path = str(link.get("path") or "")
        if not raw_path:
            continue
        normalized = str(Path(raw_path).expanduser())
        role = source_by_path.get(normalized)
        if role and role not in refs:
            refs.append(role)
    return refs


def _participant_sort_key(row):
    if row.get("is_subject"):
        return 0, str(row.get("role_label") or "")
    if row.get("is_owner"):
        return 1, str(row.get("role_label") or "")
    return 2, str(row.get("role_label") or "")


def _relation_label(relation):
    return {
        "supporting_infrastructure": "支持该项目",
        "event_evidence": "真实反馈进入项目",
        "upstream_discovery": "上游需求发现",
        "scene_projection": "形成场景投影",
        "opportunity_projection": "开启机会支线",
    }.get(relation, relation)


def _gate_title(statement, index):
    text = str(statement or "")
    if any(keyword in text for keyword in ("机构", "职务", "联系方式")):
        return "身份门"
    if any(keyword in text for keyword in ("交付", "投稿", "项目")):
        return "项目门"
    if any(keyword in text for keyword in ("独立", "重复使用", "采用")):
        return "采用门"
    return f"未知门 {index}"


def _project_worlds(facts):
    return [
        {
            "world_ref": str(row.get("project_ref") or ""),
            "world_type": str(row.get("presentation_kind") or "project"),
            "title": str(row.get("title") or row.get("project_ref") or ""),
            "state": str(row.get("lifecycle") or "unknown"),
            "health": str(row.get("health") or "unknown"),
            "current_intent": str(row.get("current_intent") or ""),
            "latest_update": str(row.get("latest_update") or ""),
            "main_action": str((row.get("primary_action") or {}).get("summary") or ""),
            "checkpoint": str((row.get("checkpoint") or {}).get("reason") or ""),
            "unknowns": list(row.get("unknowns") or []),
            "milestones": list(row.get("milestones") or []),
            "event_refs": list(row.get("event_refs") or []),
        }
        for row in facts.get("project_summaries") or []
        if row.get("project_ref")
    ]


def _related_units(facts):
    worlds = []
    quests = []
    for row in facts.get("related_unit_summaries") or []:
        unit_type = str(row.get("unit_type") or "").strip().lower()
        unit_ref = str(row.get("unit_ref") or "")
        item = {
            "unit_ref": unit_ref,
            "title": str(row.get("title") or "")
            or unit_ref.rsplit(":", 1)[-1].replace("-", " "),
            "state": str(row.get("state") or ""),
            "linked_event_ids": list(row.get("linked_event_ids") or []),
        }
        if unit_type == "scene":
            worlds.append({
                "world_ref": unit_ref,
                "world_type": "scene",
                "title": item["title"],
                "state": item["state"],
                "health": "normal",
                "current_intent": str(row.get("current_intent") or ""),
                "latest_update": item["state"],
                "main_action": "",
                "checkpoint": "",
                "unknowns": [],
                "milestones": [],
                "event_refs": item["linked_event_ids"],
            })
        elif unit_type == "opportunity":
            quests.append({
                "quest_ref": unit_ref,
                "title": item["title"],
                "state": item["state"],
                "linked_event_ids": item["linked_event_ids"],
                "proof": str(row.get("proof") or ""),
                "blocker": str(row.get("blocker") or ""),
            })
    return worlds, quests


def _world_links(event, worlds, quests):
    event_id = str(event.get("event_id") or "")
    project_ref = str(event.get("project_ref") or "")
    candidate_refs = [str(value) for value in event.get("project_candidate_refs") or []]
    links = []
    for world in worlds:
        world_ref = str(world.get("world_ref") or "")
        relation = ""
        if world.get("world_type") == "scene" and event_id in world.get("event_refs", []):
            relation = "scene_projection"
        elif project_ref and project_ref == world_ref:
            relation = "supporting_infrastructure"
        elif event_id in world.get("event_refs", []):
            relation = "event_evidence"
        elif any(world_ref and world_ref in candidate for candidate in candidate_refs):
            relation = "upstream_discovery"
        if relation:
            links.append({
                "target_ref": world_ref,
                "relation": relation,
                "label": _relation_label(relation),
            })
    for quest in quests:
        if event_id in quest.get("linked_event_ids", []):
            links.append({
                "target_ref": quest["quest_ref"],
                "relation": "opportunity_projection",
                "label": _relation_label("opportunity_projection"),
            })
    return links


def build_game_projection(level):
    facts = level.get("facts") or {}
    if str(level.get("unit_type") or "") != "relationship":
        raise ValueError("mario.game-projection/v1 currently requires a relationship Unit")

    sources = list((level.get("source_snapshot") or {}).get("sources") or [])
    interactions = {
        str(row.get("event_id") or ""): row
        for row in facts.get("interaction_summaries") or []
        if row.get("event_id")
    }
    participants = list(facts.get("event_participants") or [])
    assets = list(facts.get("event_assets") or [])
    project_worlds = _project_worlds(facts)
    related_worlds, quests = _related_units(facts)
    worlds = project_worlds + related_worlds

    levels = []
    for index, event in enumerate(facts.get("event_summaries") or [], start=1):
        event_id = str(event.get("event_id") or "")
        interaction = interactions.get(event_id) or {}
        event_participants = sorted(
            [row for row in participants if str(row.get("event_id") or "") == event_id],
            key=_participant_sort_key,
        )
        direct_source_refs = _source_refs_for_links(
            interaction.get("evidence_links") or [],
            sources,
        )
        if not direct_source_refs:
            direct_source_refs = ["relationship_boundary"]
        fact_drops = [
            {
                "fact_id": f"{event_id}:fact-{fact_index}",
                "text": str(text),
                "evidence_refs": direct_source_refs,
            }
            for fact_index, text in enumerate(interaction.get("facts") or [], start=1)
        ]
        asset_drops = [
            {
                key: asset.get(key)
                for key in (
                    "asset_id",
                    "label",
                    "kind",
                    "stage",
                    "origin",
                    "sensitivity",
                    "interaction_effect",
                    "world_links",
                    "source_role",
                    "canonical_path",
                    "sha256",
                    "size_bytes",
                )
            }
            for asset in assets
            if str(asset.get("event_ref") or "") == event_id
        ]
        levels.append({
            "level_id": event_id,
            "level_number": index,
            "canonical_time": str(event.get("canonical_time") or ""),
            "title": str(interaction.get("heading") or event.get("title") or event_id),
            "event_type": str(event.get("event_type") or ""),
            "status": str(event.get("status") or "unknown"),
            "participants": event_participants,
            "segments": list(event.get("segments") or []),
            "fact_drops": fact_drops,
            "asset_drops": asset_drops,
            "world_links": _world_links(event, worlds, quests),
            "source_refs": direct_source_refs,
        })

    payload = {
        "schema_version": SCHEMA_VERSION,
        "projection_id": "game:" + str(level.get("unit_id") or level.get("level_id") or ""),
        "unit_ref": str(level.get("unit_id") or level.get("level_id") or ""),
        "subject": {
            "ref": str(facts.get("person_ref") or ""),
            "label": str(facts.get("person_label") or ""),
            "role": str(facts.get("relationship_label") or ""),
        },
        "status": {
            "checkpoint": str((level.get("official_state") or {}).get("checkpoint") or ""),
            "label": str((level.get("official_state") or {}).get("checkpoint_label") or ""),
            "as_of": str(facts.get("as_of") or ""),
            "confirmed_interaction_count": len(facts.get("confirmed_event_ids") or []),
            "interaction_count_basis": "按确认 Event 计数，不按录音发言轮次计数",
        },
        "levels": levels,
        "worlds": worlds,
        "quests": quests,
        "gates": [
            {
                "gate_id": f"gate-{index}",
                "title": _gate_title(item, index),
                "unlock_condition": str(item),
                "state": "locked",
            }
            for index, item in enumerate(facts.get("relationship_unknowns") or [], start=1)
        ],
        "excluded_signals": [
            {
                "signal_id": f"excluded-{index}",
                "statement": str(item),
                "reason": "没有形成双方真实互动 Event",
            }
            for index, item in enumerate(facts.get("excluded_interaction_signals") or [], start=1)
        ],
        "sources": [
            {
                key: source.get(key)
                for key in ("label", "role", "path", "status", "sha256")
                if source.get(key) is not None
            }
            for source in sources
        ],
        "renderer_hints": {
            "layout": "person_world_map",
            "show_participant_roles": True,
            "show_excluded_signals": True,
        },
    }
    payload["projection_hash"] = _projection_hash(payload)
    errors = validate_game_projection(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def validate_game_projection(projection):
    errors = []
    required = {
        "schema_version",
        "projection_id",
        "unit_ref",
        "subject",
        "status",
        "levels",
        "worlds",
        "quests",
        "gates",
        "excluded_signals",
        "sources",
        "renderer_hints",
        "projection_hash",
    }
    if not isinstance(projection, dict):
        return ["Mario game projection must be an object"]
    errors.extend(
        f"Missing Mario game projection field: {key}"
        for key in sorted(required - set(projection))
    )
    if projection.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(projection.get("levels"), list):
        errors.append("levels must be a list")
    if not isinstance(projection.get("worlds"), list):
        errors.append("worlds must be a list")
    if not isinstance(projection.get("gates"), list):
        errors.append("gates must be a list")
    for level in projection.get("levels") or []:
        if not isinstance(level, dict):
            errors.append("levels entries must be objects")
            continue
        if not isinstance(level.get("asset_drops"), list):
            errors.append("level.asset_drops must be a list")
    level_ids = [
        str(row.get("level_id") or "")
        for row in projection.get("levels") or []
        if isinstance(row, dict)
    ]
    if len(level_ids) != len(set(level_ids)):
        errors.append("level_id values must be unique")
    digest = str(projection.get("projection_hash") or "").removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        errors.append("projection_hash must be sha256:<64 lowercase hex>")
    return errors

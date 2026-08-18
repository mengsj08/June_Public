#!/usr/bin/env python3
"""Build and validate a reusable Mario person-world strategy projection.

The strategy projection is presentation-only. It does not own Event facts,
relationship facts, project state, or evidence files. Those stay in their
upstream Mario Unit / game projection and source records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = "mario.strategy-map/v1"
SPEC_SCHEMA_VERSION = "mario.strategy-map-spec/v1"
MISSION_KINDS = {"event", "candidate_event", "episode", "checkpoint", "gate"}
BASIS_KINDS = {"source_backed", "owner_confirmed", "derived", "unknown"}
MOVE_ACTORS = ("对方", "我们", "世界变化")


def _stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _projection_hash(value):
    payload = dict(value)
    payload.pop("projection_hash", None)
    return "sha256:" + hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _spec_hash(value):
    payload = dict(value)
    payload.pop("spec_hash", None)
    return "sha256:" + hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_strategy_spec(spec):
    """Validate the authoring spec envelope before materializing a projection."""

    errors = []
    if not isinstance(spec, dict):
        return ["Mario strategy map spec must be an object"]
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        errors.append(f"spec.schema_version must be {SPEC_SCHEMA_VERSION}")
    expected_hash = str(spec.get("spec_hash") or "")
    if not expected_hash:
        errors.append("spec.spec_hash must be non-empty")
    elif expected_hash != _spec_hash(spec):
        errors.append(
            f"spec_hash does not match spec content expected={expected_hash} actual={_spec_hash(spec)}"
        )
    return errors


def verify_source_inputs(spec):
    """Verify that each declared upstream snapshot still matches its source."""

    errors = []
    source_event_ids = set()
    for source in spec.get("source_inputs") or []:
        path = Path(str(source.get("path") or "")).expanduser()
        label = str(source.get("label") or source.get("input_ref") or path)
        expected = str(source.get("sha256") or "").removeprefix("sha256:")
        if not path.is_absolute():
            errors.append(f"Source input must use an absolute path: {label}")
            continue
        if not path.is_file():
            errors.append(f"Source input is missing: {label}")
            continue
        actual = _sha256_file(path)
        if expected != actual:
            errors.append(
                f"Source input hash drifted: {label} expected={expected} actual={actual}"
            )
            continue
        if path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Source input JSON is unreadable: {label}: {exc}")
            continue
        for level in payload.get("levels") or []:
            event_id = str(level.get("level_id") or "")
            if event_id:
                source_event_ids.add(event_id)
    for source in spec.get("sources") or []:
        path = Path(str(source.get("path") or "")).expanduser()
        label = str(source.get("label") or source.get("source_ref") or path)
        expected = str(source.get("sha256") or "").removeprefix("sha256:")
        if not path.is_absolute():
            errors.append(f"Source fact must use an absolute path: {label}")
            continue
        if not path.is_file():
            errors.append(f"Source fact is missing: {label}")
            continue
        actual = _sha256_file(path)
        if expected != actual:
            errors.append(
                f"Source fact hash drifted: {label} expected={expected} actual={actual}"
            )
    return errors, source_event_ids


def stamp_sources(projection):
    """Return projection with facts sources carrying sha256 when paths are readable."""

    stamped = json.loads(json.dumps(projection, ensure_ascii=False))
    for source in stamped.get("sources") or []:
        path_value = str(source.get("path") or "")
        if source.get("sha256") or not path_value:
            continue
        path = Path(path_value).expanduser()
        if path.is_file():
            source["sha256"] = _sha256_file(path)
    return stamped


def build_strategy_map(spec, *, verify_sources=True):
    """Return a stamped, validated strategy projection from an authoring spec."""

    spec_errors = validate_strategy_spec(spec)
    if spec_errors:
        raise ValueError("; ".join(spec_errors))
    projection = json.loads(json.dumps(spec, ensure_ascii=False))
    projection.pop("spec_hash", None)
    projection["schema_version"] = SCHEMA_VERSION
    projection.pop("projection_hash", None)
    projection = stamp_sources(projection)
    source_errors = []
    source_event_ids = set()
    if verify_sources:
        source_errors, source_event_ids = verify_source_inputs(projection)
    projection["projection_hash"] = _projection_hash(projection)
    errors = source_errors + validate_strategy_map(
        projection,
        source_event_ids=source_event_ids if verify_sources else None,
    )
    if errors:
        raise ValueError("; ".join(errors))
    return projection


def validate_strategy_map(projection, *, source_event_ids=None):
    errors = []
    if not isinstance(projection, dict):
        return ["Mario strategy map must be an object"]

    required = {
        "schema_version",
        "map_id",
        "subject",
        "status",
        "source_inputs",
        "sources",
        "worlds",
        "boundaries",
        "projection_hash",
    }
    errors.extend(
        f"Missing Mario strategy map field: {key}"
        for key in sorted(required - set(projection))
    )
    if projection.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    map_id = str(projection.get("map_id") or "")
    if not map_id:
        errors.append("map_id must be non-empty")
    subject = projection.get("subject")
    if not isinstance(subject, dict) or not str(subject.get("label") or ""):
        errors.append("subject.label must be non-empty")
    status = projection.get("status")
    if not isinstance(status, dict):
        errors.append("status must be an object")
        status = {}
    for field in ("as_of", "checkpoint", "main_quest"):
        if not str(status.get(field) or ""):
            errors.append(f"status.{field} must be non-empty")

    source_inputs = projection.get("source_inputs")
    if not isinstance(source_inputs, list) or not source_inputs:
        errors.append("source_inputs must be a non-empty list")
        source_inputs = []
    input_refs = []
    for source in source_inputs:
        if not isinstance(source, dict):
            errors.append("source_inputs entries must be objects")
            continue
        input_ref = str(source.get("input_ref") or "")
        input_refs.append(input_ref)
        if not input_ref:
            errors.append("source_inputs.input_ref must be non-empty")
        digest = str(source.get("sha256") or "").removeprefix("sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append(f"source_inputs.sha256 must be 64 lowercase hex: {input_ref}")
    if len(input_refs) != len(set(input_refs)):
        errors.append("source_inputs.input_ref values must be unique")

    sources = projection.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    source_refs = []
    for source in sources:
        if not isinstance(source, dict):
            errors.append("sources entries must be objects")
            continue
        source_ref = str(source.get("source_ref") or "")
        source_refs.append(source_ref)
        if not source_ref:
            errors.append("sources.source_ref must be non-empty")
        if not str(source.get("label") or ""):
            errors.append(f"sources.label must be non-empty: {source_ref}")
        if not str(source.get("path") or ""):
            errors.append(f"sources.path must be non-empty: {source_ref}")
        if source.get("sha256"):
            digest = str(source.get("sha256") or "").removeprefix("sha256:")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                errors.append(f"sources.sha256 must be 64 lowercase hex: {source_ref}")
    if len(source_refs) != len(set(source_refs)):
        errors.append("sources.source_ref values must be unique")
    known_source_refs = set(source_refs)

    worlds = projection.get("worlds")
    if not isinstance(worlds, list) or not worlds:
        errors.append("worlds must be a non-empty list")
        worlds = []
    world_ids = []
    mission_ids = []
    seen_event_refs = set()
    confirmed_events = 0
    candidate_events = 0
    for world in worlds:
        if not isinstance(world, dict):
            errors.append("worlds entries must be objects")
            continue
        world_id = str(world.get("world_id") or "")
        world_ids.append(world_id)
        if not world_id:
            errors.append("world.world_id must be non-empty")
        for field in ("title", "state", "main_quest"):
            if not str(world.get(field) or ""):
                errors.append(f"world.{field} must be non-empty: {world_id}")
        missions = world.get("missions")
        if not isinstance(missions, list) or not missions:
            errors.append(f"world.missions must be a non-empty list: {world_id}")
            continue
        for mission in missions:
            if not isinstance(mission, dict):
                errors.append(f"mission entries must be objects: {world_id}")
                continue
            mission_id = str(mission.get("mission_id") or "")
            mission_ids.append(mission_id)
            kind = str(mission.get("kind") or "")
            event_refs = list(mission.get("event_refs") or [])
            if not mission_id:
                errors.append(f"mission_id must be non-empty: {world_id}")
            if kind not in MISSION_KINDS:
                errors.append(f"Unsupported mission kind: {mission_id}={kind}")
            for field in ("code", "label", "status"):
                if not str(mission.get(field) or ""):
                    errors.append(f"mission.{field} must be non-empty: {mission_id}")
            if kind in {"event", "candidate_event"} and len(event_refs) != 1:
                errors.append(f"{kind} mission must bind exactly one Event: {mission_id}")
            if kind in {"episode", "checkpoint", "gate"} and event_refs:
                errors.append(f"{kind} mission must not claim an Event ref: {mission_id}")
            for event_ref in event_refs:
                event_ref = str(event_ref)
                if event_ref in seen_event_refs:
                    errors.append(f"Event appears in more than one mission: {event_ref}")
                seen_event_refs.add(event_ref)
                if source_event_ids is not None and event_ref not in source_event_ids:
                    errors.append(f"Mission Event is absent from source projections: {event_ref}")
            if kind == "event":
                confirmed_events += 1
            elif kind == "candidate_event":
                candidate_events += 1

            lenses = mission.get("lenses")
            if not isinstance(lenses, dict):
                errors.append(f"mission.lenses must be an object: {mission_id}")
                continue
            action = lenses.get("action")
            if not isinstance(action, dict):
                errors.append(f"mission action lens must be an object: {mission_id}")
            else:
                moves = action.get("moves")
                if not isinstance(moves, list) or len(moves) != 3:
                    errors.append(f"mission action lens must contain three moves: {mission_id}")
                elif tuple(str(move.get("actor") or "") for move in moves) != MOVE_ACTORS:
                    errors.append(
                        f"mission moves must be 对方 -> 我们 -> 世界变化: {mission_id}"
                    )
                for move in moves or []:
                    errors.extend(_validate_claim(move, f"{mission_id}.action"))
            for lens_name in ("relationship", "capability"):
                lens = lenses.get(lens_name)
                if not isinstance(lens, dict):
                    errors.append(f"mission {lens_name} lens must be an object: {mission_id}")
                    continue
                items = lens.get("items")
                if not isinstance(items, list) or not items:
                    errors.append(
                        f"mission {lens_name} lens must contain items: {mission_id}"
                    )
                    continue
                for item in items:
                    errors.extend(_validate_claim(item, f"{mission_id}.{lens_name}"))
            evidence = lenses.get("evidence")
            if not isinstance(evidence, dict):
                errors.append(f"mission evidence lens must be an object: {mission_id}")
            else:
                evidence_refs = evidence.get("source_refs")
                if not isinstance(evidence_refs, list) or not evidence_refs:
                    errors.append(f"mission evidence needs source_refs: {mission_id}")
                for source_ref in evidence_refs or []:
                    if str(source_ref) not in known_source_refs:
                        errors.append(
                            f"mission evidence has unknown source_ref: {mission_id}={source_ref}"
                        )
                if not str(evidence.get("boundary") or ""):
                    errors.append(f"mission evidence.boundary must be non-empty: {mission_id}")

    if len(world_ids) != len(set(world_ids)):
        errors.append("world_id values must be unique")
    if len(mission_ids) != len(set(mission_ids)):
        errors.append("mission_id values must be unique")
    expected_confirmed = status.get("confirmed_event_count")
    expected_candidate = status.get("candidate_event_count")
    if expected_confirmed != confirmed_events:
        errors.append(
            f"status.confirmed_event_count={expected_confirmed} but missions contain "
            f"{confirmed_events} confirmed Events"
        )
    if expected_candidate != candidate_events:
        errors.append(
            f"status.candidate_event_count={expected_candidate} but missions contain "
            f"{candidate_events} candidate Events"
        )

    digest = str(projection.get("projection_hash") or "").removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        errors.append("projection_hash must be sha256:<64 lowercase hex>")
    elif projection.get("projection_hash") != _projection_hash(projection):
        errors.append("projection_hash does not match projection content")
    return errors


def _validate_claim(claim, location):
    if not isinstance(claim, dict):
        return [f"claim must be an object: {location}"]
    errors = []
    if not str(claim.get("text") or ""):
        errors.append(f"claim.text must be non-empty: {location}")
    basis = str(claim.get("basis") or "")
    if basis not in BASIS_KINDS:
        errors.append(f"claim.basis is invalid: {location}={basis}")
    return errors

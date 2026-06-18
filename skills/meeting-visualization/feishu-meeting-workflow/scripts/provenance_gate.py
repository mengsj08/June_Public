"""Shared transcript provenance checks for meeting workflow scripts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from _safety import is_secret_file, scrub


@dataclass(frozen=True)
class ProvenanceStatus:
    has_transcript: bool
    transcript_path: Path | None
    resolution_path: Path | None
    transcript_available: bool | None
    reason: str


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.read_text(encoding="utf-8", errors="ignore").strip() != ""
    except OSError:
        return False


def unquote_scalar(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def scalar_from_case_yaml(case_dir: Path, key: str) -> str:
    path = case_dir / "case.yaml"
    if not path.exists() or is_secret_file(path):
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            raw_key, raw_value = line.split(":", 1)
            if raw_key.strip() == key:
                return unquote_scalar(raw_value)
    except OSError:
        return ""
    return ""


def resolve_case_path(case_dir: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = case_dir / path
    return path.resolve()


def candidate_source_dirs(case_dir: Path) -> list[Path]:
    candidates: list[Path] = [case_dir / "source"]
    case_json = read_json(case_dir / "case.json")
    paths = case_json.get("paths") if isinstance(case_json.get("paths"), dict) else {}

    transcript = resolve_case_path(case_dir, paths.get("transcript") if isinstance(paths, dict) else "")
    if transcript:
        candidates.append(transcript.parent)

    for raw_runtime in [case_json.get("runtime_dir"), scalar_from_case_yaml(case_dir, "runtime_dir")]:
        runtime_dir = resolve_case_path(case_dir, raw_runtime)
        if runtime_dir:
            candidates.append(runtime_dir / "source")

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def transcript_provenance_status(case_dir: Path) -> ProvenanceStatus:
    case_dir = case_dir.expanduser().resolve()
    transcript_candidates = [source_dir / "meeting_transcript.md" for source_dir in candidate_source_dirs(case_dir)]
    for path in transcript_candidates:
        if is_nonempty_file(path):
            resolution = path.parent / "source_resolution.json"
            data = read_json(resolution)
            return ProvenanceStatus(
                has_transcript=True,
                transcript_path=path,
                resolution_path=resolution if resolution.exists() else None,
                transcript_available=data.get("transcript_available") if isinstance(data.get("transcript_available"), bool) else True,
                reason=str(data.get("reason") or ""),
            )

    for source_dir in candidate_source_dirs(case_dir):
        resolution = source_dir / "source_resolution.json"
        data = read_json(resolution)
        if data.get("transcript_available") is False and str(data.get("reason") or "").strip():
            return ProvenanceStatus(
                has_transcript=False,
                transcript_path=None,
                resolution_path=resolution,
                transcript_available=False,
                reason=str(data.get("reason") or "").strip(),
            )

    existing_resolution = next((source_dir / "source_resolution.json" for source_dir in candidate_source_dirs(case_dir) if (source_dir / "source_resolution.json").exists()), None)
    return ProvenanceStatus(
        has_transcript=False,
        transcript_path=None,
        resolution_path=existing_resolution,
        transcript_available=None,
        reason="",
    )


def ensure_source_resolved(case_dir: Path, action: str) -> ProvenanceStatus:
    status = transcript_provenance_status(case_dir)
    if status.has_transcript or (status.transcript_available is False and status.reason):
        return status
    checked = ", ".join(str(path / "meeting_transcript.md") for path in candidate_source_dirs(case_dir))
    raise SystemExit(
        f"Provenance gate blocked {action}: source/meeting_transcript.md is missing or empty, "
        "and source/source_resolution.json does not contain transcript_available:false with a reason. "
        f"Run scripts/resolve_meeting_source.py first. Checked: {scrub(checked)}"
    )


def ensure_transcript_available(case_dir: Path, action: str) -> ProvenanceStatus:
    status = ensure_source_resolved(case_dir, action)
    if status.has_transcript:
        return status
    resolution_display = str(status.resolution_path) if status.resolution_path else "source/source_resolution.json"
    raise SystemExit(
        f"Transcript gate blocked {action}: transcript_available=false in {scrub(resolution_display)}; "
        f"reason={scrub(status.reason)}. Resolve source/meeting_transcript.md before analysis, "
        "review approval, or return package creation."
    )

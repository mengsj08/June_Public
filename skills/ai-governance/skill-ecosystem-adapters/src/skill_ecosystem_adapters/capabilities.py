"""Capability evidence model shared by all adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass

LEVELS = frozenset({"native", "verified_fallback", "read_only", "unsupported", "unknown"})


@dataclass(frozen=True)
class CapabilityEvidence:
    level: str
    verified_at: str | None
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"invalid capability level: {self.level}")
        if not self.evidence_ref:
            raise ValueError("evidence_ref is required")

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def capability(level: str, evidence_ref: str, verified_at: str | None = None) -> dict[str, str | None]:
    return CapabilityEvidence(level, verified_at, evidence_ref).as_dict()

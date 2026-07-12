"""Standalone, standard-library-only skill ecosystem adapters."""

from .bigapple import BigAppleAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .generic import GenericAdapter
from .workbuddy import WorkBuddyAdapter

__all__ = ["BigAppleAdapter", "ClaudeAdapter", "CodexAdapter", "GenericAdapter", "WorkBuddyAdapter"]

"""Disk-aware task_id sequence allocation helpers."""

import re
from pathlib import Path


_PREFIX_RE = re.compile(r"^[A-Z]{3}$")


def max_task_sequence_on_disk(repo_root, prefix):
    """Return the largest sequence in project/**/{prefix}-*.md filenames."""
    prefix = str(prefix or "").strip()
    if not _PREFIX_RE.fullmatch(prefix):
        raise ValueError(f"invalid task_id prefix: {prefix!r}")

    project_root = Path(repo_root) / "project"
    if not project_root.is_dir():
        return 0

    filename_re = re.compile(rf"^{re.escape(prefix)}-(\d+)(?:_|\.md$)")
    max_sequence = 0
    for path in project_root.rglob(f"{prefix}-*.md"):
        match = filename_re.match(path.name)
        if match:
            max_sequence = max(max_sequence, int(match.group(1)))
    return max_sequence


def next_task_sequence(repo_root, prefix, counter_value=0):
    """Allocate after both the persisted counter and the on-disk maximum."""
    counter_sequence = counter_value if isinstance(counter_value, int) else 0
    counter_sequence = max(counter_sequence, 0)
    disk_sequence = max_task_sequence_on_disk(repo_root, prefix)
    return max(counter_sequence, disk_sequence) + 1

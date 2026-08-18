"""In-memory cache for the Markdown task-card scanner.

The filesystem remains authoritative.  Every scan walks card metadata and builds
a conservative directory signature; file contents are only read again when a
``(path, mtime_ns, size)`` key changes or an in-process writer invalidates it.
Nothing is persisted across server restarts.
"""

from __future__ import annotations

import copy
import hashlib
import os
import threading
from pathlib import Path


_LOCK = threading.RLock()
_FILE_CACHE = {}
_PATH_KEYS = {}
_DIRECTORY_CACHE = {}
_STATS = {
    'scans': 0,
    'directory_hits': 0,
    'directory_misses': 0,
    'file_hits': 0,
    'file_misses': 0,
    'parsed_files': 0,
    'invalidations': 0,
}


def _clone(value):
    return copy.deepcopy(value)


def _normalize_path(path, repo_root=None):
    candidate = Path(path)
    if not candidate.is_absolute() and repo_root is not None:
        candidate = Path(repo_root) / candidate
    return str(candidate.resolve(strict=False))


def _drop_path_locked(path_text):
    keys = _PATH_KEYS.pop(path_text, set())
    for key in keys:
        _FILE_CACHE.pop(key, None)


def reset():
    """Clear cached documents and counters (used by tests and cold benchmarks)."""
    with _LOCK:
        _FILE_CACHE.clear()
        _PATH_KEYS.clear()
        _DIRECTORY_CACHE.clear()
        for name in _STATS:
            _STATS[name] = 0


def stats():
    with _LOCK:
        result = dict(_STATS)
        result['file_entries'] = len(_FILE_CACHE)
        result['directory_entries'] = len(_DIRECTORY_CACHE)
        return result


def invalidate(path=None, *, repo_root=None):
    """Invalidate one Markdown path, or the complete cache when path is omitted."""
    with _LOCK:
        _STATS['invalidations'] += 1
        if path is None:
            _FILE_CACHE.clear()
            _PATH_KEYS.clear()
            _DIRECTORY_CACHE.clear()
            return

        path_text = _normalize_path(path, repo_root)
        _drop_path_locked(path_text)
        target = Path(path_text)
        for directory in list(_DIRECTORY_CACHE):
            try:
                target.relative_to(Path(directory))
            except ValueError:
                continue
            _DIRECTORY_CACHE.pop(directory, None)


def _collect_files(project_dir, repo_root, skip_patterns, should_skip):
    records = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(x for x in dirs if not x.startswith('.') and x != 'vendor')
        for filename in sorted(files):
            if not filename.endswith('.md'):
                continue
            path = Path(root) / filename
            if skip_patterns and should_skip(path, skip_patterns):
                continue
            try:
                stat = path.stat()
            except OSError:
                # A concurrent rename/delete is a normal cache miss.  The next
                # request will observe the settled filesystem state.
                continue
            path_text = _normalize_path(path)
            rel_path = str(path.relative_to(repo_root))
            key = (path_text, stat.st_mtime_ns, stat.st_size)
            records.append((path, path_text, rel_path, key))
    return records


def _directory_signature(records, policy_key):
    """Count + max mtime, strengthened with a full metadata digest.

    The digest prevents a same-count rename/replacement, or a change to a file
    other than the max-mtime file, from being mistaken for an unchanged tree.
    It hashes metadata only; file contents remain untouched on the hot path.
    """
    digest = hashlib.blake2b(digest_size=16)
    digest.update(repr(policy_key).encode('utf-8', errors='replace'))
    max_mtime_ns = 0
    for _path, _path_text, rel_path, key in records:
        _absolute_path, mtime_ns, size = key
        max_mtime_ns = max(max_mtime_ns, mtime_ns)
        digest.update(rel_path.encode('utf-8', errors='surrogateescape'))
        digest.update(b'\0')
        digest.update(str(mtime_ns).encode('ascii'))
        digest.update(b':')
        digest.update(str(size).encode('ascii'))
        digest.update(b'\0')
    return (len(records), max_mtime_ns, digest.digest())


def scan_projects(
    repo_root,
    project_dirs,
    *,
    skip_patterns,
    should_skip,
    parse_file,
):
    """Return parsed task documents for the supplied project directories."""
    # Keep the caller's spelling for traversal/relative paths.  On macOS,
    # resolving a temporary directory rewrites /var to /private/var; mixing
    # those spellings would break scan-docs' existing relative-path guard.
    # Cache keys are still normalized independently by _normalize_path().
    repo_root = Path(repo_root)
    policy_key = tuple(str(item) for item in (skip_patterns or []))
    documents = []

    with _LOCK:
        _STATS['scans'] += 1
        live_directories = set()
        live_paths = set()

        for project_dir in project_dirs:
            project_dir = Path(project_dir)
            directory_key = _normalize_path(project_dir)
            live_directories.add(directory_key)
            records = _collect_files(
                project_dir,
                repo_root,
                skip_patterns,
                should_skip,
            )
            signature = _directory_signature(records, policy_key)
            previous = _DIRECTORY_CACHE.get(directory_key)
            if previous and previous['signature'] == signature:
                _STATS['directory_hits'] += 1
                live_paths.update(previous['paths'])
                documents.extend(previous['documents'])
                continue

            _STATS['directory_misses'] += 1
            project_documents = []
            project_paths = set()
            for path, path_text, _rel_path, key in records:
                live_paths.add(path_text)
                project_paths.add(path_text)
                if key in _FILE_CACHE:
                    _STATS['file_hits'] += 1
                    parsed = _FILE_CACHE[key]
                else:
                    _STATS['file_misses'] += 1
                    parsed = parse_file(path, project_dir.name)
                    _STATS['parsed_files'] += 1
                    _drop_path_locked(path_text)
                    _FILE_CACHE[key] = parsed
                    _PATH_KEYS.setdefault(path_text, set()).add(key)
                if parsed is not None:
                    project_documents.append(parsed)

            if previous:
                for removed_path in previous['paths'] - project_paths:
                    _drop_path_locked(removed_path)
            _DIRECTORY_CACHE[directory_key] = {
                'signature': signature,
                'paths': project_paths,
                # These objects remain private to the cache.  The public return
                # value is deep-copied once below so callers can safely add
                # display-only fields without poisoning future cache hits.
                'documents': project_documents,
            }
            documents.extend(project_documents)

        for directory in list(_DIRECTORY_CACHE):
            if directory not in live_directories:
                stale = _DIRECTORY_CACHE.pop(directory)
                for path_text in stale['paths']:
                    if path_text not in live_paths:
                        _drop_path_locked(path_text)

    return _clone(documents)

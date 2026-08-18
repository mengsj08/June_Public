"""Single-instance guard for the kanban HTTP server.

This module keeps process lifecycle concerns out of scan-docs.py: pidfile
ownership, port probing, and explicit process-group restart.
"""

from __future__ import annotations

import http.client
import json
import os
import shlex
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


PIDFILE_NAME = ".kanban-server.pid"
HEALTH_PATH = "/api/health"
HEALTH_FINGERPRINT = "project-canvas/health-v1"


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def pidfile_path(repo_root: Path) -> Path:
    return Path(repo_root) / PIDFILE_NAME


def process_exists(pid: int | str | None) -> bool:
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return not process_is_zombie(pid_int)


def process_is_zombie(pid: int | str | None) -> bool:
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, Exception):
        return False
    if proc.returncode != 0:
        return False
    return (proc.stdout or "").strip().startswith("Z")


def process_start_time(pid: int | str | None) -> str:
    """Return a best-effort OS start time string for pid, or empty if unknown."""
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return ""
    if pid_int <= 0:
        return ""
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, Exception):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def process_command(pid: int | str | None) -> str:
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return ""
    if pid_int <= 0:
        return ""
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, Exception):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _parse_time(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%a %b %d %H:%M:%S %Y"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    return None


def process_matches_started_at(pid: int | str | None, started_at: str, *, tolerance_seconds: int = 5) -> bool:
    """Protect against obvious pid reuse when both timestamps are available."""
    if not process_exists(pid):
        return False
    proc_started = _parse_time(process_start_time(pid))
    entry_started = _parse_time(started_at)
    if proc_started is None or entry_started is None:
        return False
    return abs(proc_started - entry_started) <= tolerance_seconds


def port_accepts_connection(port: int, *, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def probe_product_instance(port: int, *, host: str = "127.0.0.1", timeout: float = 0.75) -> bool:
    """Verify that a listener exposes this product's explicit health fingerprint."""
    connection = http.client.HTTPConnection(host, int(port), timeout=timeout)
    try:
        connection.request("GET", HEALTH_PATH, headers={"Host": f"127.0.0.1:{int(port)}"})
        response = connection.getresponse()
        if response.status != 200:
            return False
        raw = response.read(16 * 1024)
        payload = json.loads(raw.decode("utf-8"))
        return (
            isinstance(payload, dict)
            and payload.get("product") == "project-canvas"
            and payload.get("fingerprint") == HEALTH_FINGERPRINT
        )
    except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def port_owner_pids(port: int) -> list[int]:
    """Return listener pids for a TCP port using lsof when available."""
    try:
        proc = subprocess.run(
            ["lsof", "-nP", "-ti", f"tcp:{int(port)}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode not in (0, 1):
        return []
    pids = []
    for line in (proc.stdout or "").splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def process_cwd(pid: int | str | None) -> Path | None:
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return None
    if pid_int <= 0:
        return None
    try:
        proc = subprocess.run(
            ["lsof", "-a", "-p", str(pid_int), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("n"):
            try:
                return Path(line[1:]).resolve()
            except OSError:
                return None
    return None


def process_is_scan_docs_serve(pid: int | str | None, repo_root: Path) -> bool:
    """Return true only when pid is this repo's scan-docs.py --serve process."""
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0 or pid_int == os.getpid() or not process_exists(pid_int):
        return False
    repo_root = Path(repo_root).resolve()
    expected_scripts = {
        (repo_root / "kanban/scan-docs.py").resolve(),
        # Backward-compatible recognition for pre-public-layout installs.
        (repo_root / "shared/toolkit/kanban/scan-docs.py").resolve(),
    }
    command = process_command(pid_int)
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = command.split()
    if "--serve" not in argv:
        return False
    cwd = process_cwd(pid_int)
    for arg in argv:
        if Path(arg).name != "scan-docs.py":
            continue
        candidate = Path(arg)
        if not candidate.is_absolute():
            if cwd is None:
                continue
            candidate = cwd / candidate
        try:
            if candidate.resolve() in expected_scripts:
                return True
        except OSError:
            continue
    return False


def scan_docs_serve_pids(repo_root: Path) -> list[int]:
    """Find same-repo scan-docs.py --serve processes, including lost-port orphans."""
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        first, _, command = line.partition(" ")
        try:
            pid = int(first)
        except ValueError:
            continue
        if pid <= 0 or pid == os.getpid():
            continue
        if not process_is_scan_docs_serve(pid, repo_root):
            continue
        if pid not in pids:
            pids.append(pid)
    return pids


def read_pidfile(repo_root: Path) -> dict:
    path = pidfile_path(repo_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_pidfile(repo_root: Path, port: int) -> None:
    path = pidfile_path(repo_root)
    data = {
        "pid": os.getpid(),
        "pgid": os.getpgid(os.getpid()),
        "port": int(port),
        "started_at": _now_iso(),
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def ensure_pidfile_owner(repo_root: Path, port: int) -> bool:
    """Keep the running server's pidfile lease present and accurate.

    Returns true when the file had to be recreated.  The pidfile is an
    operational mutex, so a one-shot startup write is insufficient: if the
    file disappears while the listener remains alive, later starts lose the
    strongest same-instance identity check.
    """
    data = read_pidfile(repo_root)
    try:
        is_owner = (
            int(data.get("pid") or 0) == os.getpid()
            and int(data.get("pgid") or 0) == os.getpgid(os.getpid())
            and int(data.get("port") or 0) == int(port)
            and bool(str(data.get("started_at") or "").strip())
        )
    except (TypeError, ValueError, OSError):
        is_owner = False
    if is_owner:
        return False
    write_pidfile(repo_root, port)
    return True


def remove_pidfile_if_owner(repo_root: Path) -> None:
    path = pidfile_path(repo_root)
    data = read_pidfile(repo_root)
    try:
        if int(data.get("pid") or 0) != os.getpid():
            return
    except (TypeError, ValueError):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@dataclass
class ExistingInstance:
    pid: int | None
    port: int
    source: str
    port_owner_pids: list[int]


def _remove_stale_pidfile(repo_root: Path) -> None:
    try:
        pidfile_path(repo_root).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _pidfile_stale_reason(
    repo_root: Path,
    pid: int | None,
    port: int,
    owners: list[int],
    port_alive: bool,
) -> str | None:
    if not pid:
        return "missing pid"
    if not process_exists(pid):
        return f"pid {pid} is not alive"
    if not process_is_scan_docs_serve(pid, repo_root):
        return f"pid {pid} is not this repo's scan-docs.py --serve"
    if not port_alive and not owners:
        return f"port {port} is not listening"
    if owners and pid not in owners:
        return f"port {port} is owned by {owners}, not pid {pid}"
    return None


def detect_existing_instance(
    repo_root: Path,
    port: int,
    *,
    logger: Callable[[str], None] = print,
) -> ExistingInstance | None:
    owners = [pid for pid in port_owner_pids(port) if process_exists(pid)]
    info = read_pidfile(repo_root)
    pid = None
    try:
        pid = int(info.get("pid") or 0) or None
    except (TypeError, ValueError):
        pid = None
    pidfile_port = info.get("port")
    pidfile_matches_port = str(pidfile_port or "") == str(int(port))
    port_alive = port_accepts_connection(port)
    stale_pid = None
    if pidfile_matches_port and info:
        stale_reason = _pidfile_stale_reason(Path(repo_root), pid, int(port), owners, port_alive)
        if stale_reason:
            stale_pid = pid
            logger(f"[kanban] stale pidfile detected ({stale_reason}); taking over.")
            _remove_stale_pidfile(repo_root)
        else:
            source = "pidfile"
            return ExistingInstance(pid=pid, port=int(port), source=source, port_owner_pids=owners)

    serve_pids = [pid for pid in scan_docs_serve_pids(repo_root) if pid != stale_pid]
    for pid in serve_pids:
        if pid not in owners:
            owners.append(pid)
    if owners:
        existing_pid = serve_pids[0] if serve_pids else owners[0]
        source = "port" if port_alive else "process"
        if existing_pid in serve_pids and not port_alive:
            source = "process"
        return ExistingInstance(pid=existing_pid, port=int(port), source=source, port_owner_pids=owners)
    if port_alive:
        return ExistingInstance(pid=pid, port=int(port), source="socket", port_owner_pids=owners)
    return None


def terminate_process_group(pid: int, *, timeout_seconds: float = 10.0, logger: Callable[[str], None] = print) -> bool:
    try:
        pgid = os.getpgid(int(pid))
    except OSError:
        return True
    if pgid == os.getpgrp():
        logger(f"[kanban] old pid={pid} is in current process group; stopping pid only")
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not process_exists(pid):
                return True
            time.sleep(0.1)
        try:
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not process_exists(pid):
                return True
            time.sleep(0.1)
        return not process_exists(pid)
    logger(f"[kanban] stopping existing process group pgid={pgid} pid={pid}")
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError as exc:
        logger(f"[kanban] cannot signal process group pgid={pgid}: {exc}")
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not process_exists(pid):
            return True
        time.sleep(0.1)
    logger(f"[kanban] process group pgid={pgid} still alive; sending SIGKILL")
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError as exc:
        logger(f"[kanban] cannot kill process group pgid={pgid}: {exc}")
        return False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not process_exists(pid):
            return True
        time.sleep(0.1)
    return not process_exists(pid)


def live_running_entries(entries: Iterable[dict]) -> list[dict]:
    live = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") != "running":
            continue
        pid = entry.get("pid")
        started_at = str(entry.get("pid_started_at") or entry.get("started_at") or "")
        if process_matches_started_at(pid, started_at):
            live.append(entry)
    return live


def stop_existing_instance(
    instance: ExistingInstance,
    *,
    logger: Callable[[str], None] = print,
    timeout_seconds: float = 10.0,
) -> bool:
    targets = []
    if instance.pid:
        targets.append(instance.pid)
    targets.extend(instance.port_owner_pids)
    unique_targets = []
    for pid in targets:
        if pid and pid != os.getpid() and pid not in unique_targets:
            unique_targets.append(pid)
    ok = True
    for pid in unique_targets:
        if process_exists(pid):
            ok = terminate_process_group(pid, timeout_seconds=timeout_seconds, logger=logger) and ok
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not port_accepts_connection(instance.port):
            break
        time.sleep(0.1)
    return ok and not port_accepts_connection(instance.port)

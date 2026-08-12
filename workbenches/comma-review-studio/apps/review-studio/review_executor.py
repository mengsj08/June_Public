#!/usr/bin/env python3
"""Background provider execution for Comma Review Studio.

This module owns provider process lifetime, trace capture, cancellation, and
receipt assembly. The HTTP server should only translate review-run state into
calls here.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


TERMINAL_STATES = {"completed", "failed", "cancelled"}
ACTIVE_STATES = {"queued", "running", "cancelling"}
EXECUTOR_VERSION = "comma-review-executor/v1"


class ProviderExecutionError(RuntimeError):
    def __init__(self, message: str, *, receipt: dict | None = None):
        super().__init__(message)
        self.receipt = receipt or {}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_path(path: str | Path) -> str:
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def file_size(path: str | Path) -> int:
    target = Path(path)
    return target.stat().st_size if target.is_file() else 0


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _contains_web_search_event(payload: Any) -> bool:
    if isinstance(payload, dict):
        event_type = payload.get("type")
        if isinstance(event_type, str) and "web_search" in event_type.lower():
            return True
        return any(_contains_web_search_event(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_web_search_event(value) for value in payload)
    return False


_TASK_CONTEXT = threading.local()


def _task_context():
    return getattr(_TASK_CONTEXT, "value", None)


def _is_windows() -> bool:
    return os.name == "nt"


def provider_command(tool: str, executable: str, prompt: str, schema: dict | None = None,
                     output_path: str = "", schema_path: str = "") -> list[str]:
    if tool == "claude":
        command = [
            executable,
            "--safe-mode",
            "--no-chrome",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--print",
            "--output-format",
            "text",
        ]
        if schema:
            command = [
                executable,
                "--safe-mode",
                "--no-chrome",
                "--no-session-persistence",
                "--disable-slash-commands",
                "--tools",
                "",
                "--permission-mode",
                "dontAsk",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                "--print",
            ]
        command.append(prompt)
        return command
    if tool == "codex":
        command = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-rules",
            "--ignore-user-config",
            "--color",
            "never",
            "--json",
        ]
        if output_path:
            command.extend(["--output-last-message", output_path])
        if schema:
            if not schema_path:
                raise ValueError("codex output schema requires a schema file path")
            command.extend(["--output-schema", schema_path])
        command.append(prompt)
        return command
    raise ValueError(f"unknown provider tool: {tool}")


def platform_command(command: list[str]) -> list[str]:
    """Adapt Windows launcher scripts while avoiding an interactive shell."""
    if not _is_windows() or not command:
        return command
    executable = command[0]
    suffix = Path(executable).suffix.lower()
    if suffix in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", *command]
    if suffix not in {".exe", ".com"}:
        try:
            with open(executable, "rb") as handle:
                first_line = handle.readline(512).decode("utf-8", errors="ignore").lower()
            if first_line.startswith("#!") and "python" in first_line:
                return [sys.executable, *command]
        except OSError:
            pass
    return command


def _provider_version(executable: str, env: dict | None = None) -> str:
    if executable.startswith("http://") or executable.startswith("https://"):
        return "BigApple Desktop Gateway"
    try:
        completed = subprocess.run(
            platform_command([executable, "--version"]),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=env,
        )
        return (completed.stdout or completed.stderr or "unknown").strip()[:240] or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _default_receipt(metadata: dict, *, status: str, started_at: str = "",
                     completed_at: str = "", elapsed_ms: int = 0,
                     returncode: int | None = None, error: str = "") -> dict:
    trace = metadata.get("trace") or {}
    result_path = metadata.get("result_path") or ""
    schema_path = metadata.get("schema_path") or ""
    events_path = trace.get("events_path") or ""
    stderr_path = trace.get("stderr_path") or ""
    return {
        "schema_version": "comma-review-run-receipt/v1",
        "executor_version": EXECUTOR_VERSION,
        "status": status,
        "run_id": metadata.get("run_id") or "",
        "adapter": metadata.get("adapter") or {},
        "profile": metadata.get("profile") or {},
        "skill": metadata.get("skill") or {},
        "provider": metadata.get("provider") or {},
        "input_manifest": metadata.get("input_manifest") or {},
        "prompt_template_hash": metadata.get("prompt_template_hash") or "",
        "prompt_hash": metadata.get("prompt_hash") or "",
        "sandbox": metadata.get("sandbox") or {"mode": "read-only"},
        "web_policy": metadata.get("web_policy") or {"mode": "disabled", "web_search_used": False},
        "timing": {
            "queued_at": metadata.get("queued_at") or "",
            "started_at": started_at,
            "completed_at": completed_at,
            "elapsed_ms": elapsed_ms,
        },
        "exit": {"returncode": returncode, "status": status},
        "result": {
            "path": result_path,
            "sha256": sha256_path(result_path),
            "bytes": file_size(result_path),
        },
        "output_schema": {
            "path": schema_path,
            "sha256": sha256_path(schema_path),
            "bytes": file_size(schema_path),
        },
        "trace": {
            "events_path": events_path,
            "events_sha256": sha256_path(events_path),
            "stderr_path": stderr_path,
            "stderr_sha256": sha256_path(stderr_path),
        },
        "recovery": metadata.get("recovery") or {"recovered": False, "reason": ""},
        "error": error,
    }


def invoke_provider(tool: str, prompt: str, *, timeout: int, schema: dict | None,
                    executable: str, cwd: str, metadata: dict,
                    env: dict | None = None) -> dict:
    started_at = now()
    start = time.monotonic()
    trace_root = Path(metadata["trace_root"])
    trace_root.mkdir(parents=True, exist_ok=True)
    result_path = trace_root / "result.txt"
    schema_path = trace_root / "output_schema.json" if schema and tool == "codex" else None
    events_path = trace_root / "provider_events.jsonl"
    stderr_path = trace_root / "provider_stderr.log"
    if schema_path is not None:
        write_json(schema_path, schema)
    metadata = {
        **metadata,
        "result_path": str(result_path),
        "schema_path": str(schema_path) if schema_path is not None else "",
        "trace": {"events_path": str(events_path), "stderr_path": str(stderr_path)},
    }
    if tool == "bigapple":
        return _invoke_bigapple_gateway(
            prompt, timeout=timeout, schema=schema, executable=executable,
            cwd=cwd, metadata=metadata, trace_root=trace_root,
            result_path=result_path, events_path=events_path,
            stderr_path=stderr_path, started_at=started_at, start=start,
        )
    command = provider_command(
        tool, executable, prompt, schema=schema, output_path=str(result_path),
        schema_path=str(schema_path) if schema_path is not None else "",
    )
    metadata["provider"] = {
        **(metadata.get("provider") or {}),
        "tool": tool,
        "transport": f"{tool}_cli",
        "executable": executable,
        "version": _provider_version(executable, env=env),
        "command_shape": command[:3],
    }

    context = _task_context()
    process = None
    try:
        popen_options = (
            {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
            if _is_windows()
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            platform_command(command),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env,
            **popen_options,
        )
        if context:
            context["executor"].register_process(context["task_id"], process)
        stdout, stderr = process.communicate(timeout=timeout)
        events_path.write_text(stdout or "", encoding="utf-8")
        stderr_path.write_text(stderr or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            terminate_process_tree(process)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        receipt = _default_receipt(
            metadata, status="failed", started_at=started_at, completed_at=now(),
            elapsed_ms=elapsed_ms, returncode=None,
            error=f"{tool} timed out after {timeout}s",
        )
        write_json(trace_root / "receipt.json", receipt)
        raise ProviderExecutionError(receipt["error"], receipt=receipt) from exc
    finally:
        if context:
            context["executor"].register_process(context["task_id"], None)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    returncode = process.returncode if process is not None else None
    output = result_path.read_text(encoding="utf-8") if result_path.is_file() else (stdout or "")
    status = "completed" if returncode == 0 else "failed"
    error = ""
    if returncode != 0:
        error = (stderr or stdout or f"{tool} exited {returncode}").strip()[-2000:]

    web_search_used = False
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        web_search_used = web_search_used or _contains_web_search_event(event)
    if web_search_used:
        status = "failed"
        error = "provider trace contains a web_search event while web policy is disabled"
    receipt = _default_receipt(
        {
            **metadata,
            "web_policy": {
                **(metadata.get("web_policy") or {}),
                "mode": "disabled",
                "web_search_used": web_search_used,
            },
        },
        status=status,
        started_at=started_at,
        completed_at=now(),
        elapsed_ms=elapsed_ms,
        returncode=returncode,
        error=error,
    )
    write_json(trace_root / "receipt.json", receipt)
    if status != "completed":
        raise ProviderExecutionError(error or f"{tool} execution failed", receipt=receipt)
    return {
        "tool": tool,
        "output": output,
        "returncode": returncode,
        "elapsed_ms": elapsed_ms,
        "receipt": receipt,
        "trace_root": str(trace_root),
    }


def _invoke_bigapple_gateway(prompt: str, *, timeout: int, schema: dict | None,
                             executable: str, cwd: str, metadata: dict,
                             trace_root: Path, result_path: Path,
                             events_path: Path, stderr_path: Path,
                             started_at: str, start: float) -> dict:
    from bigapple_gateway import BigAppleGatewayError, submit_task

    metadata["provider"] = {
        **(metadata.get("provider") or {}),
        "tool": "bigapple",
        "transport": "bigapple_gateway",
        "gateway_url": executable,
        "version": _provider_version(executable),
        "command_shape": ["bigapple_gateway", "/api/chat"],
    }
    try:
        gateway_result = submit_task(
            prompt, working_directory=cwd, timeout=timeout, schema=schema,
            base_url=executable)
        output = gateway_result["output"]
        result_path.write_text(output, encoding="utf-8")
        trace_events = [
            {
                "type": "bigapple.gateway.task",
                "gateway_url": gateway_result.get("gateway_url") or executable,
                "session_id": gateway_result.get("session_id") or "",
                "request_id": gateway_result.get("request_id") or "",
                "provider_id": gateway_result.get("provider_id") or "",
                "model": gateway_result.get("model") or "",
            },
            *list(gateway_result.get("events") or []),
        ]
        events_path.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in trace_events),
            encoding="utf-8",
        )
        stderr_path.write_text("", encoding="utf-8")
    except BigAppleGatewayError as exc:
        stderr_path.write_text(str(exc), encoding="utf-8")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        receipt = _default_receipt(
            metadata, status="failed", started_at=started_at, completed_at=now(),
            elapsed_ms=elapsed_ms, returncode=None, error=str(exc)[:2000],
        )
        write_json(trace_root / "receipt.json", receipt)
        raise ProviderExecutionError(receipt["error"], receipt=receipt) from exc

    elapsed_ms = int((time.monotonic() - start) * 1000)
    receipt = _default_receipt(
        {
            **metadata,
            "provider": {
                **metadata["provider"],
                "gateway_url": gateway_result.get("gateway_url") or executable,
                "session_id": gateway_result.get("session_id") or "",
                "request_id": gateway_result.get("request_id") or "",
                "provider_id": gateway_result.get("provider_id") or "",
                "model": gateway_result.get("model") or "",
            },
            "web_policy": {
                **(metadata.get("web_policy") or {}),
                "mode": "disabled",
                "web_search_used": False,
            },
        },
        status="completed",
        started_at=started_at,
        completed_at=now(),
        elapsed_ms=elapsed_ms,
        returncode=0,
        error="",
    )
    write_json(trace_root / "receipt.json", receipt)
    return {
        "tool": "bigapple",
        "output": output,
        "returncode": 0,
        "elapsed_ms": elapsed_ms,
        "receipt": receipt,
        "trace_root": str(trace_root),
    }


def terminate_process_tree(process: subprocess.Popen, *, grace_seconds: float = 1.0) -> None:
    if process.poll() is not None:
        return
    if _is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(2.0, grace_seconds + 1.0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


class ReviewExecutor:
    def __init__(self, trace_root: str | Path):
        self.trace_root = Path(trace_root)
        self.trace_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tasks: dict[str, dict] = {}

    def submit(self, task_id: str, provider: Callable[[], dict], metadata: dict) -> dict:
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing and existing["state"] in ACTIVE_STATES:
                return self.snapshot(task_id)
            task = {
                "id": task_id,
                "state": "queued",
                "provider": provider,
                "metadata": {**metadata, "queued_at": metadata.get("queued_at") or now()},
                "result": None,
                "error": "",
                "process": None,
                "thread": None,
            }
            self._tasks[task_id] = task
            thread = threading.Thread(target=self._run_task, args=(task_id,), daemon=True)
            task["thread"] = thread
            thread.start()
            return self.snapshot(task_id)

    def _run_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["state"] = "running"
        _TASK_CONTEXT.value = {"executor": self, "task_id": task_id}
        try:
            result = task["provider"]()
            with self._lock:
                task = self._tasks.get(task_id)
                if task and task["state"] == "cancelling":
                    task["state"] = "cancelled"
                elif task:
                    task["state"] = "completed"
                if task:
                    task["result"] = result
        except ProviderExecutionError as exc:
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task["state"] = "cancelled" if task["state"] == "cancelling" else "failed"
                    task["error"] = str(exc)
                    receipt = dict(exc.receipt)
                    if task["state"] == "cancelled":
                        receipt["status"] = "cancelled"
                        receipt["exit"] = {**(receipt.get("exit") or {}), "status": "cancelled"}
                    task["result"] = {"receipt": receipt, "output": ""}
        except Exception as exc:  # pragma: no cover - defensive boundary
            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    task["state"] = "cancelled" if task["state"] == "cancelling" else "failed"
                    task["error"] = str(exc)
                    receipt = _default_receipt(
                        task.get("metadata") or {}, status=task["state"],
                        completed_at=now(), error=str(exc)[:500],
                    )
                    task["result"] = {"receipt": receipt, "output": ""}
        finally:
            _TASK_CONTEXT.value = None

    def register_process(self, task_id: str, process: subprocess.Popen | None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["process"] = process

    def cancel(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"id": task_id, "state": "failed", "error": "executor task not found"}
            if task["state"] in TERMINAL_STATES:
                return self.snapshot(task_id)
            task["state"] = "cancelling"
            process = task.get("process")
        if process is not None:
            terminate_process_tree(process)
        return self.snapshot(task_id)

    def snapshot(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"id": task_id, "state": "failed", "error": "executor task not found"}
            return {
                "id": task_id,
                "state": task["state"],
                "error": task.get("error") or "",
                "result": task.get("result"),
                "queued_at": (task.get("metadata") or {}).get("queued_at") or "",
            }

    def wait(self, task_id: str, timeout: float = 0.0) -> dict:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            snapshot = self.snapshot(task_id)
            if snapshot["state"] in TERMINAL_STATES or time.monotonic() >= deadline:
                return snapshot
            time.sleep(0.01)


def temp_trace_root(prefix: str = "comma-review-executor-") -> str:
    return tempfile.mkdtemp(prefix=prefix)

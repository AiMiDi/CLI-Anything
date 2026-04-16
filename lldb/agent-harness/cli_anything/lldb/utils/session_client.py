"""
Client-side helpers for the persistent LLDB session daemon.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any


def resolve_session_file(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_override = os.environ.get("CLI_ANYTHING_LLDB_SESSION_FILE")
    if env_override:
        return Path(env_override).expanduser().resolve()

    scope = os.environ.get("CLI_ANYTHING_LLDB_SESSION_SCOPE") or os.getcwd()
    digest = hashlib.sha256(os.path.abspath(scope).encode("utf-8")).hexdigest()[:12]
    root = Path(tempfile.gettempdir()) / "cli-anything-lldb"
    return (root / f"session-{digest}.json").resolve()


def _load_state_file(state_file: Path) -> dict[str, Any]:
    return json.loads(state_file.read_text(encoding="utf-8"))


def _connect(state_file: Path):
    state = _load_state_file(state_file)
    authkey = base64.b64decode(state["authkey"])
    return Client((state["host"], state["port"]), authkey=authkey)


def _spawn_server(state_file: Path):
    cmd = [
        sys.executable,
        "-m",
        "cli_anything.lldb.utils.session_server",
        "--state-file",
        str(state_file),
    ]
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **popen_kwargs)


def ensure_server(state_file: Path, timeout: float = 10.0):
    if state_file.exists():
        try:
            with _connect(state_file) as conn:
                conn.send({"method": "ping", "args": [], "kwargs": {}})
                response = conn.recv()
            if response.get("ok"):
                return
        except Exception:
            try:
                state_file.unlink()
            except FileNotFoundError:
                pass

    _spawn_server(state_file)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if state_file.exists():
            try:
                with _connect(state_file) as conn:
                    conn.send({"method": "ping", "args": [], "kwargs": {}})
                    response = conn.recv()
                if response.get("ok"):
                    return
            except Exception:
                pass
        time.sleep(0.1)
    raise RuntimeError("Timed out starting the LLDB session daemon")


class RemoteLLDBSessionProxy:
    """Thin RPC proxy that mirrors LLDBSession methods."""

    def __init__(self, state_file: Path):
        self._state_file = state_file

    def call(self, method: str, *args, **kwargs):
        ensure_server(self._state_file)
        with _connect(self._state_file) as conn:
            conn.send({"method": method, "args": list(args), "kwargs": kwargs})
            response = conn.recv()
        if response.get("ok"):
            return response.get("data")
        raise RuntimeError(response.get("error") or f"Remote call failed: {method}")

    def session_status(self):
        return self.call("session_status")

    def shutdown(self):
        try:
            return self.call("shutdown")
        finally:
            try:
                self._state_file.unlink()
            except FileNotFoundError:
                pass

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: self.call(name, *args, **kwargs)

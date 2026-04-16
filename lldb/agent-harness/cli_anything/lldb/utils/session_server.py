"""
Background LLDB session server for persistent non-REPL workflows.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any

from cli_anything.lldb.core.session import LLDBSession


def _encode_authkey(authkey: bytes) -> str:
    return base64.b64encode(authkey).decode("ascii")


def _write_state_file(state_file: Path, address: tuple[str, int], authkey: bytes):
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": address[0],
        "port": address[1],
        "authkey": _encode_authkey(authkey),
        "pid": os.getpid(),
    }
    state_file.write_text(json.dumps(payload), encoding="utf-8")


def _remove_state_file(state_file: Path):
    try:
        state_file.unlink()
    except FileNotFoundError:
        pass


class SessionServer:
    """Owns one persistent LLDBSession inside a lightweight RPC daemon."""

    def __init__(self):
        self._session: LLDBSession | None = None

    def handle(self, request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        method = request.get("method")
        args = request.get("args", [])
        kwargs = request.get("kwargs", {})

        if method == "ping":
            return {"ok": True, "data": {"status": "ok"}}, False

        if method == "session_status":
            status = self._session.session_status() if self._session is not None else {
                "has_target": False,
                "has_process": False,
                "process_origin": None,
            }
            return {"ok": True, "data": status}, False

        if method == "shutdown":
            self.close()
            return {"ok": True, "data": {"status": "closed"}}, True

        if method == "target_create" and self._session is not None:
            self.close()

        try:
            if self._session is None:
                self._session = LLDBSession()

            handler = getattr(self._session, method)
            data = handler(*args, **kwargs)
            return {"ok": True, "data": data}, False
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "type": exc.__class__.__name__,
            }, False

    def close(self):
        if self._session is not None:
            self._session.destroy()
            self._session = None


def serve(state_file: Path, idle_timeout: int = 300):
    authkey = os.urandom(32)
    listener = Listener(("127.0.0.1", 0), authkey=authkey)
    raw_socket = listener._listener._socket  # type: ignore[attr-defined]
    raw_socket.settimeout(1.0)
    _write_state_file(state_file, listener.address, authkey)

    server = SessionServer()
    last_activity = time.time()

    try:
        while True:
            try:
                conn = listener.accept()
            except socket.timeout:
                if time.time() - last_activity >= idle_timeout:
                    break
                continue

            last_activity = time.time()
            with conn:
                request = conn.recv()
                response, should_stop = server.handle(request)
                conn.send(response)
            if should_stop:
                break
    finally:
        server.close()
        listener.close()
        _remove_state_file(state_file)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Internal LLDB session daemon")
    parser.add_argument("--state-file", required=True, help="Session state file path")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=int(os.environ.get("CLI_ANYTHING_LLDB_IDLE_TIMEOUT", "300")),
        help="Seconds of inactivity before daemon exits",
    )
    args = parser.parse_args(argv)
    serve(Path(args.state_file), idle_timeout=args.idle_timeout)


if __name__ == "__main__":
    main(sys.argv[1:])

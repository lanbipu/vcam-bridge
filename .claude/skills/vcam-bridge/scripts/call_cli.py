"""Minimal fallback wrapper: run vcam CLI and return the parsed envelope.

Usage:
    from call_cli import call_vcam
    result = call_vcam(["manifest"])
    result = call_vcam(["targets", "list", "--director", "10.0.0.1:80"])
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


class VcamCLIError(Exception):
    def __init__(self, code: str, exit_code: int, message: str, envelope: dict):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.envelope = envelope


def call_vcam(args: list[str], *, stdin_data: Any = None,
              timeout: float = 60.0) -> dict[str, Any]:
    """Run `vcam <args> --output json --no-input` and return the parsed envelope.

    Raises VcamCLIError on non-zero exit (includes error envelope in the exception).
    """
    cmd = ["vcam"] + list(args) + ["--output", "json", "--no-input"]
    inp = json.dumps(stdin_data).encode() if stdin_data is not None else None
    result = subprocess.run(
        cmd,
        input=inp,
        capture_output=True,
        timeout=timeout,
    )
    try:
        envelope = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise VcamCLIError(
            "PARSE_ERROR", result.returncode,
            "vcam output was not valid JSON: %s" % exc,
            {"stdout": result.stdout.decode("utf-8", errors="replace")[:2000]},
        ) from exc

    if result.returncode != 0:
        err = envelope.get("error", {})
        raise VcamCLIError(
            err.get("code", "UNKNOWN"),
            result.returncode,
            err.get("message", "vcam exited %d" % result.returncode),
            envelope,
        )
    return envelope

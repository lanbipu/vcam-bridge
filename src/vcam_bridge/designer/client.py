from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from vcam_bridge.designer.transport import Transport
from vcam_bridge.domain.errors import DesignerTimeoutError, ExternalError

_LINE_RE = re.compile(r"line (\d+)")


@dataclass
class ExecuteResult:
    return_value: Any
    d3_log: str
    python_log: str


class DesignerClient:
    """Wraps a Transport: solo/director routing + /execute call with parsing, error
    mapping, userScript line-offset correction, and (no client-level retry; chunk-level
    timeout recovery lives in inject.py's bisect logic)."""

    def __init__(self, transport: Transport, host: str, *, timeout_s: float = 30.0):
        self._t = transport
        self.host = host
        self._timeout_s = timeout_s

    def resolve_routing(self) -> None:
        st = self._t.get_json(self.host, "/api/session/status/session", self._timeout_s)
        if not st.get("isRunningSolo", True):
            hostname = st["director"]["hostname"]
            if ":" not in hostname and ":" in self.host:
                hostname = "%s:%s" % (hostname, self.host.rsplit(":", 1)[1])
            self.host = hostname

    @staticmethod
    def _fix_line_offset(msg: str) -> str:
        # Designer wraps the script in def userScript(): so reported lines are +10.
        def repl(m: re.Match) -> str:
            return "line %d" % max(int(m.group(1)) - 10, 1)
        return _LINE_RE.sub(repl, msg)

    def execute(self, script: str, module_name: str | None = None) -> ExecuteResult:
        resp = self._t.post_execute(self.host, script, module_name, self._timeout_s)
        status = resp.get("status", {}) or {}
        code = status.get("code", 0)
        if code == 0:
            rv = resp.get("returnValue", "null")
            value = None if rv in (None, "null", "") else json.loads(rv)
            return ExecuteResult(value, resp.get("d3Log", ""), resp.get("pythonLog", ""))
        msg = self._fix_line_offset(status.get("message", "") or "")
        details = {"code": code, "details": status.get("details", []),
                   "d3Log": resp.get("d3Log", ""), "pythonLog": resp.get("pythonLog", "")}
        if "TimeoutError" in msg or "KeyboardInterrupt" in msg:
            raise DesignerTimeoutError(msg or "Designer python execution timed out", details=details)
        raise ExternalError(msg or "Designer execute failed", details=details)

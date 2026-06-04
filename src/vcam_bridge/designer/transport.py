from __future__ import annotations

from typing import Any, Protocol

from vcam_bridge.domain.errors import ExternalError


class Transport(Protocol):
    """IO port: HTTP to a Designer Service/Session API. Adapters implement this."""

    def post_execute(self, host: str, script: str, module_name: str | None = None,
                     timeout_s: float | None = None) -> dict[str, Any]: ...

    def get_json(self, host: str, path: str, timeout_s: float | None = None) -> dict[str, Any]: ...

    def post_json(self, host: str, path: str, body: dict, timeout_s: float | None = None) -> dict[str, Any]: ...


class RequestsTransport:
    """Real HTTP transport using a persistent requests.Session for connection reuse."""

    def __init__(self) -> None:
        import requests
        self._session = requests.Session()

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        import requests
        body: dict[str, Any] = {"script": script}
        if module_name:
            body["moduleName"] = module_name
        try:
            r = self._session.post(f"http://{host}/api/session/python/execute", json=body, timeout=timeout_s)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise ExternalError("Designer HTTP request failed: %s" % exc, details={"host": host}) from exc
        except ValueError as exc:
            raise ExternalError("Designer returned a non-JSON response", details={"host": host}) from exc

    def get_json(self, host, path, timeout_s=None):
        import requests
        try:
            r = self._session.get(f"http://{host}{path}", timeout=timeout_s)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise ExternalError("Designer HTTP request failed: %s" % exc, details={"host": host, "path": path}) from exc
        except ValueError as exc:
            raise ExternalError("Designer returned a non-JSON response", details={"host": host, "path": path}) from exc

    def post_json(self, host, path, body, timeout_s=None):
        import requests
        try:
            r = self._session.post(f"http://{host}{path}", json=body, timeout=timeout_s)
            r.raise_for_status()
            return r.json() if r.content else {}
        except requests.RequestException as exc:
            raise ExternalError("Designer HTTP POST failed: %s" % exc, details={"host": host, "path": path}) from exc
        except ValueError as exc:
            raise ExternalError("Designer returned a non-JSON response", details={"host": host, "path": path}) from exc


class CurlTransport:
    """Fallback HTTP transport using curl subprocess.
    Works around macOS network restrictions on ad-hoc signed Python binaries."""

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        import json, subprocess
        body: dict[str, Any] = {"script": script}
        if module_name:
            body["moduleName"] = module_name
        cmd = ["curl", "-s", "-X", "POST", f"http://{host}/api/session/python/execute",
               "-H", "Content-Type: application/json", "-d", json.dumps(body)]
        if timeout_s:
            cmd += ["--connect-timeout", str(int(timeout_s)), "-m", str(int(timeout_s))]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s or 30)
            if proc.returncode != 0:
                raise ExternalError("curl failed (rc=%s): %s" % (proc.returncode, proc.stderr),
                                    details={"host": host})
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            raise ExternalError("curl timed out", details={"host": host, "timeout": timeout_s})
        except (json.JSONDecodeError, OSError) as exc:
            raise ExternalError("curl transport error: %s" % exc, details={"host": host}) from exc

    def get_json(self, host, path, timeout_s=None):
        import json, subprocess
        cmd = ["curl", "-s", f"http://{host}{path}"]
        if timeout_s:
            cmd += ["--connect-timeout", str(int(timeout_s)), "-m", str(int(timeout_s))]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s or 30)
            if proc.returncode != 0:
                raise ExternalError("curl failed (rc=%s): %s" % (proc.returncode, proc.stderr),
                                    details={"host": host, "path": path})
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            raise ExternalError("curl timed out", details={"host": host, "path": path, "timeout": timeout_s})
        except (json.JSONDecodeError, OSError) as exc:
            raise ExternalError("curl transport error: %s" % exc, details={"host": host, "path": path}) from exc

    def post_json(self, host, path, body, timeout_s=None):
        import json, subprocess
        cmd = ["curl", "-s", "-X", "POST", f"http://{host}{path}",
               "-H", "Content-Type: application/json", "-d", json.dumps(body)]
        if timeout_s:
            cmd += ["--connect-timeout", str(int(timeout_s)), "-m", str(int(timeout_s))]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s or 30)
            if proc.returncode != 0:
                raise ExternalError("curl failed (rc=%s): %s" % (proc.returncode, proc.stderr),
                                    details={"host": host, "path": path})
            return json.loads(proc.stdout) if proc.stdout.strip() else {}
        except subprocess.TimeoutExpired:
            raise ExternalError("curl timed out", details={"host": host, "path": path, "timeout": timeout_s})
        except (json.JSONDecodeError, OSError) as exc:
            raise ExternalError("curl transport error: %s" % exc, details={"host": host, "path": path}) from exc


class FakeTransport:
    """Test double. execute_responses are returned in order; json_responses keyed by path."""

    def __init__(self, execute_responses=None, json_responses=None):
        self._execute = list(execute_responses or [])
        self._json = dict(json_responses or {})
        self.executed: list[dict[str, Any]] = []
        self.posted_json: list = []
        self.idx = 0

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        self.executed.append({"host": host, "script": script, "module_name": module_name})
        resp = self._execute[self.idx]   # IndexError when exhausted (test relies on this)
        self.idx += 1
        return resp

    def get_json(self, host, path, timeout_s=None):
        return self._json[path]

    def post_json(self, host, path, body, timeout_s=None):
        self.posted_json.append((host, path, body, timeout_s))
        return {}

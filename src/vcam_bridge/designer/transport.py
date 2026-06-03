from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    """IO port: HTTP to a Designer Service/Session API. Adapters implement this."""

    def post_execute(self, host: str, script: str, module_name: str | None = None,
                     timeout_s: float | None = None) -> dict[str, Any]: ...

    def get_json(self, host: str, path: str, timeout_s: float | None = None) -> dict[str, Any]: ...


class RequestsTransport:
    """Real HTTP transport using a persistent requests.Session for connection reuse."""

    def __init__(self) -> None:
        import requests
        self._session = requests.Session()

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        body: dict[str, Any] = {"script": script}
        if module_name:
            body["moduleName"] = module_name
        r = self._session.post(f"http://{host}/api/session/python/execute", json=body, timeout=timeout_s)
        return r.json()

    def get_json(self, host, path, timeout_s=None):
        r = self._session.get(f"http://{host}{path}", timeout=timeout_s)
        return r.json()


class FakeTransport:
    """Test double. execute_responses are returned in order; json_responses keyed by path."""

    def __init__(self, execute_responses=None, json_responses=None):
        self._execute = list(execute_responses or [])
        self._json = dict(json_responses or {})
        self.executed: list[dict[str, Any]] = []
        self.idx = 0

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        self.executed.append({"host": host, "script": script, "module_name": module_name})
        resp = self._execute[self.idx]   # IndexError when exhausted (test relies on this)
        self.idx += 1
        return resp

    def get_json(self, host, path, timeout_s=None):
        return self._json[path]

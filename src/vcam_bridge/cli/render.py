from __future__ import annotations

import json
from typing import Any


def _text_success(env: dict[str, Any]) -> str:
    lines = [f"[ok] {env['operation_id']} ({env['meta']['duration_ms']}ms)"]
    data = env.get("data", {})
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(v, (dict, list)):
                lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _text_error(env: dict[str, Any]) -> str:
    err = env["error"]
    return f"[error] {env['operation_id']}: {err['code']} (exit {err['exit_code']}) - {err['message']}"


def render_success(env: dict[str, Any], fmt: str) -> str:
    if fmt in ("json", "ndjson"):
        return json.dumps(env, ensure_ascii=False)
    return _text_success(env)


def render_error(env: dict[str, Any], fmt: str) -> str:
    if fmt in ("json", "ndjson"):
        return json.dumps(env, ensure_ascii=False)
    return _text_error(env)

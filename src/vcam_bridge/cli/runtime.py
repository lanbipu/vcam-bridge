from __future__ import annotations

import datetime
import uuid


def new_request_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_output(explicit: str | None, *, ai_agent_env: bool, is_tty: bool) -> str:
    if explicit:
        return explicit
    if ai_agent_env:
        return "json"
    return "text"

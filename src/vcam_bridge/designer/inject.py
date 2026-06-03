from __future__ import annotations

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.codegen import build_inject_script
from vcam_bridge.domain.errors import DesignerTimeoutError, PartialError


def chunk_keys(keys: list[dict], size: int) -> list[list[dict]]:
    if size < 1:
        size = 1
    return [keys[i:i + size] for i in range(0, len(keys), size)]


def _write_chunk(client: DesignerClient, layer_uid, fields, chunk, start_offset_sec) -> int:
    payload = {"layer_uid": layer_uid, "start_offset_sec": start_offset_sec,
               "fields": fields, "keys": chunk}
    script = build_inject_script(payload)
    res = client.execute(script).return_value or {}
    if not res.get("ok"):
        raise PartialError("inject chunk failed: %s" % res.get("error", "unknown"),
                           details={"missing": res.get("missing")})
    return int(res.get("written", 0))


def inject_keys(client: DesignerClient, *, layer_uid: str, fields: dict, keys: list[dict],
                start_offset_sec: float, chunk_size: int, min_chunk: int = 8) -> int:
    """Inject keyframes in chunks (one /execute per chunk). On a chunk TimeoutError,
    halve that chunk and retry its halves (not a blind re-send), down to min_chunk."""
    total = 0
    pending = chunk_keys(keys, chunk_size)
    while pending:
        chunk = pending.pop(0)
        try:
            total += _write_chunk(client, layer_uid, fields, chunk, start_offset_sec)
        except DesignerTimeoutError:
            if len(chunk) <= min_chunk:
                raise
            mid = len(chunk) // 2
            pending.insert(0, chunk[mid:])
            pending.insert(0, chunk[:mid])
    return total

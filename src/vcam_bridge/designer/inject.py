from __future__ import annotations

import numpy as np

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.codegen import build_inject_script
from vcam_bridge.domain.errors import DesignerTimeoutError, PartialError, VerifyToleranceError


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


_TOL_GROUPS = {
    "pivot.x": "pos", "pivot.y": "pos", "pivot.z": "pos",
    "rotation.x": "rot", "rotation.y": "rot", "rotation.z": "rot",
    "distance": "zoom", "zoom": "zoom",
}

_VERIFY_BODY = '''
import json
local_state = state.localOrDirectorState()
track = local_state.track
target = None
for layer in track.layers:
    if layer.uid == int(payload["layer_uid"], 16):
        target = layer
        break
if target is None:
    result = {"error": "layer not found"}
else:
    fieldmap = payload["fields"]
    seqs = {}
    for key in fieldmap:
        fs = target.findSequence(fieldmap[key])
        if fs is not None:
            seqs[key] = fs
    max_errors = {}
    start_offset = payload["start_offset_sec"]
    total = 0
    for kf in payload["keys"]:
        beat = track.timeToBeat(start_offset + kf["t_sec"])
        vals = kf["values"]
        for key in vals:
            if key in seqs:
                actual = seqs[key].eval(beat, 0.0)
                err = abs(actual - vals[key])
                if key not in max_errors or err > max_errors[key]:
                    max_errors[key] = err
                total = total + 1
    result = {"max_errors": max_errors, "total_keys": total}
'''


def verify_keys_persistence(client: DesignerClient, *, layer_uid: str, fields: dict,
                            keys: list[dict], start_offset_sec: float,
                            tol_pos: float, tol_rot: float, tol_zoom: float) -> dict:
    import json as _json
    payload = {"layer_uid": layer_uid, "start_offset_sec": start_offset_sec,
               "fields": fields, "keys": keys}
    json_str = _json.dumps(payload)
    script = "import json\npayload = json.loads(" + repr(json_str) + ")\n" + _VERIFY_BODY + "\nreturn json.dumps(result)\n"
    res = client.execute(script).return_value or {}
    if "error" in res:
        raise PartialError("verify failed: %s" % res["error"])
    tols = {"pos": tol_pos, "rot": tol_rot, "zoom": tol_zoom}
    max_errors = res.get("max_errors", {})
    exceeded = {}
    for field, err in max_errors.items():
        group = _TOL_GROUPS.get(field, "zoom")
        if err > tols[group]:
            exceeded[field] = {"error": err, "tolerance": tols[group]}
    if exceeded:
        raise VerifyToleranceError("verify tolerance exceeded",
                                   details={"exceeded": exceeded, "max_errors": max_errors})
    return {"ok": True, "max_errors": max_errors, "total_keys": res.get("total_keys", 0)}


def verify_world_pose(client: DesignerClient, *, vc_uid: str, keys: list[dict],
                      start_offset_sec: float, expected_positions: list,
                      tol_pos: float) -> dict:
    indices = [0]
    if len(keys) > 2:
        indices.append(len(keys) // 2)
    if len(keys) > 1:
        indices.append(len(keys) - 1)
    import json as _json
    max_err = 0.0
    for idx in indices:
        if idx >= len(expected_positions):
            continue
        t_sec = start_offset_sec + keys[idx]["t_sec"]
        try:
            import requests as _req
            _req.post("http://%s/api/session/transport/gototime" % client.host,
                      json={"time": t_sec}, timeout=5)
        except Exception:
            pass
        payload = {"vc_uid": vc_uid}
        script = ("import json\npayload = json.loads(" + repr(_json.dumps(payload)) + ")\n"
                  "vc = None\nfor c in state.stage.cameras:\n"
                  "    if c.uid == int(payload['vc_uid'], 16):\n        vc = c\n        break\n"
                  "w = vc.world\nt = w.getTranslation()\n"
                  "return json.dumps({'pos': [t.x, t.y, t.z]})")
        res = client.execute(script).return_value or {}
        actual = np.array(res.get("pos", [0, 0, 0]))
        expected = np.array(expected_positions[idx])
        err = float(np.linalg.norm(actual - expected))
        if err > max_err:
            max_err = err
    if max_err > tol_pos:
        raise VerifyToleranceError("world pose tolerance exceeded",
                                   details={"max_pos_error": max_err, "tol_pos": tol_pos})
    return {"ok": True, "sampled": len(indices), "max_pos_error": max_err}

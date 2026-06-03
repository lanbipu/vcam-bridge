from __future__ import annotations

from vcam_bridge.designer.client import DesignerClient

# ACC moduleType identifier is confirmed at runtime (P1); accept either historical/new name.
_ACC_ENUM_SCRIPT = '''
import json
local_state = state.localOrDirectorState()
out = []
for track in [local_state.track]:
    for layer in track.layers:
        mt = str(layer.moduleType())
        if "AnimateCamera" in mt:
            out.append([layer.name, hex(layer.uid)])
return json.dumps(out)
'''

_VC_ENUM_SCRIPT = '''
import json
out = []
for cam in state.stage.cameras:
    if getattr(cam, "isVirtual", False) or "Virtual" in str(type(cam).__name__):
        out.append([cam.name, hex(cam.uid)])
return json.dumps(out)
'''


def list_tracks(client: DesignerClient) -> list[dict]:
    resp = client._t.get_json(client.host, "/api/session/transport/tracks", client._timeout_s)
    return [{"uid": t["uid"], "name": t["name"]} for t in resp.get("result", [])]


def list_acc_layers(client: DesignerClient) -> list[dict]:
    rows = client.execute(_ACC_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u in rows]


def list_vcs(client: DesignerClient) -> list[dict]:
    rows = client.execute(_VC_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u in rows]

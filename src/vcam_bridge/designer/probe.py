from __future__ import annotations

from dataclasses import dataclass, field

from vcam_bridge.designer.client import DesignerClient

_FIELD_DUMP = '''
import json
local_state = state.localOrDirectorState()
target = None
for layer in local_state.track.layers:
    if hex(layer.uid) == %r:
        target = layer
        break
if target is None:
    return json.dumps([])
out = []
for fs in target.sequences:
    out.append(str(fs))
return json.dumps(out)
'''

_MODULE_TYPE = '''
import json
local_state = state.localOrDirectorState()
for layer in local_state.track.layers:
    if hex(layer.uid) == %r:
        return json.dumps(str(layer.moduleType()))
return json.dumps(None)
'''


@dataclass
class ProbeReport:
    version: str
    legacy_vc: bool
    module_type: str | None
    field_names: list[str]
    notes: list[str] = field(default_factory=list)


def probe_module_type(client: DesignerClient, *, layer_uid: str) -> str | None:
    return client.execute(_MODULE_TYPE % layer_uid).return_value


def probe_field_set(client: DesignerClient, *, layer_uid: str) -> list[str]:
    """P2 — dump decorated FieldSequence names on the probe ACC layer."""
    return client.execute(_FIELD_DUMP % layer_uid).return_value or []

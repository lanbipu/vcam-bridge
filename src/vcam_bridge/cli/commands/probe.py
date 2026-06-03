from __future__ import annotations

from typing import Any

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.probe import probe_module_type, probe_field_set


def run_probe(transport, *, host: str, probe_layer_uid: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "probe", {
        "module_type": probe_module_type(client, layer_uid=probe_layer_uid),
        "field_names": probe_field_set(client, layer_uid=probe_layer_uid),
    }

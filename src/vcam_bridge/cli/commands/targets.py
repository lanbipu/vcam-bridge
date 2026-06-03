from __future__ import annotations

from typing import Any

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_acc_layers


def list_targets(transport, *, host: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "targets.list", {"layers": list_acc_layers(client)}

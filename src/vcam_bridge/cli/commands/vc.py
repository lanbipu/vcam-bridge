from __future__ import annotations

from typing import Any

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_vcs


def list_vcams(transport, *, host: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "vc.list", {"virtual_cameras": list_vcs(client)}

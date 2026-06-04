from __future__ import annotations

from typing import Any

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_cameras


def list_vcams(transport, *, host: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    cams = list_cameras(client)
    return "vc.list", {
        "cameras": cams,                                                # 全部相机（live + virtual）
        "virtual_cameras": [c for c in cams if c["type"] == "virtual"],  # 废弃别名，向后兼容保留一版
    }

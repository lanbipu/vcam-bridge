from __future__ import annotations

from typing import Any
from vcam_bridge import __version__
from vcam_bridge.manifest import build_manifest


def manifest() -> tuple[str, Any]:
    return "meta.manifest", build_manifest()


def version() -> tuple[str, Any]:
    return "meta.version", {"name": "vcam-bridge", "version": __version__}


def schema() -> tuple[str, Any]:
    return "meta.schema", {"operations": [op["operation_id"] for op in build_manifest()["operations"]]}

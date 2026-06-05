from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import ConflictError
from vcam_bridge.domain.models import Config


def config_init(path: str, *, dry_run: bool = False) -> tuple[str, Any]:
    p = Path(path)
    exists = p.exists()
    if exists and not dry_run:
        raise ConflictError(f"config file already exists: {path}",
                            details={"path": path, "hint": "delete it first or use config show"})
    data = Config().model_dump(mode="json")
    if dry_run:
        return "config.init", {"path": path, "would_write": data, "would_conflict": exists}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return "config.init", {"path": path, "written": data}


def config_show(path: str | None) -> tuple[str, Any]:
    cfg = load_config(path)
    return "config.show", {"effective": cfg.model_dump(mode="json"), "source": path or "(defaults)"}


def config_validate(path: str) -> tuple[str, Any]:
    cfg = load_config(path)
    return "config.validate", {"valid": True, "path": path, "effective": cfg.model_dump(mode="json")}

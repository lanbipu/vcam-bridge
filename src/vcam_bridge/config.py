from __future__ import annotations

from pathlib import Path
import yaml

from vcam_bridge.domain.errors import ConfigError
from vcam_bridge.domain.models import Config


def load_config(path: str | None) -> Config:
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {path}", details={"path": path})
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config: {exc}", details={"path": path}) from exc
    try:
        return Config.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid config schema: {exc}", details={"path": path}) from exc

from __future__ import annotations

from typing import Any
from vcam_bridge.envelope import CONTRACT_VERSION


def _op(operation_id: str, summary: str, *, writes: bool, idempotent: bool,
        destructive: bool, external: bool, exit_codes: list[int],
        dry_run: bool, stdin: bool) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "summary": summary,
        "input_schema": {"$ref": f"#/schemas/{operation_id}/input"},
        "output_schema": {"$ref": f"#/schemas/{operation_id}/output"},
        "error_schema": {"$ref": "#/schemas/error"},
        "side_effects": {"writes": writes, "external_calls": external,
                         "idempotent": idempotent, "destructive": destructive},
        "exit_codes": exit_codes,
        "cli": {"supports_dry_run": dry_run, "supports_stdin": stdin},
    }


def build_manifest() -> dict[str, Any]:
    ops = [
        _op("convert", "Convert FBX camera animation and inject as ACC keyframes",
            writes=True, idempotent=True, destructive=True, external=True,
            exit_codes=[0, 2, 3, 5, 7, 8, 11, 13], dry_run=True, stdin=True),
        _op("probe", "Calibrate Designer conventions (P0-P9) on a scratch ACC layer",
            writes=True, idempotent=False, destructive=True, external=True,
            exit_codes=[0, 2, 3, 4, 8, 10, 12], dry_run=True, stdin=False),
        _op("targets.list", "Enumerate AnimateCameraControl layers",
            writes=False, idempotent=True, destructive=False, external=True,
            exit_codes=[0, 2, 4, 8], dry_run=False, stdin=False),
        _op("vc.list", "Enumerate stage cameras (live + virtual)",
            writes=False, idempotent=True, destructive=False, external=True,
            exit_codes=[0, 2, 4, 8], dry_run=False, stdin=False),
        _op("config.init", "Write a default configuration file",
            writes=True, idempotent=True, destructive=False, external=False,
            exit_codes=[0, 2, 3, 6], dry_run=True, stdin=False),
        _op("config.show", "Show the effective merged configuration",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0, 2, 3], dry_run=False, stdin=False),
        _op("config.validate", "Validate a configuration file",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0, 2, 3], dry_run=False, stdin=False),
        _op("meta.manifest", "Output the contract manifest",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0], dry_run=False, stdin=False),
        _op("meta.schema", "Output the CLI structure JSON schema",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0], dry_run=False, stdin=False),
        _op("meta.version", "Output version metadata",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0], dry_run=False, stdin=False),
        _op("meta.completion", "Output shell completion script",
            writes=False, idempotent=True, destructive=False, external=False,
            exit_codes=[0], dry_run=False, stdin=False),
    ]
    return {"contract_version": CONTRACT_VERSION, "operations": ops}

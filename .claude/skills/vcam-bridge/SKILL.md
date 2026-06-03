---
name: vcam-bridge
description: Convert UE Sequencer FBX camera animation into Disguise AnimateCameraControl keyframes. Use when injecting camera moves into a Disguise Virtual Camera, calibrating conventions (probe), or enumerating ACC layers / virtual cameras.
---

# vcam-bridge

## Transport policy
1. CLI-first. Always: `vcam <cmd> --output json --no-color --no-input`.
2. Complex input via stdin JSON. Parse ONLY stdout JSON (the envelope).
3. There is no MCP server; do not assume one.

## Error policy
1. Check `exit_code` / `error.code` in the envelope (never parse natural-language text).
2. Retry ONLY when `error.retryable: true`.
3. Destructive ops (`convert`, `probe`) MUST be run with `--dry-run` first; show the dry_run_plan summary and get user confirmation before the live run.

## Operations
See `reference/contract-manifest.json` (synced from `vcam manifest`). Key ops:
- `vcam convert --fbx F --target-uid U --vc-uid V [--dry-run]` — inject (destructive).
- `vcam probe --director H:P --probe-layer-uid U` — calibrate (writes a scratch layer).
- `vcam targets list --director H:P` / `vcam vc list --director H:P` — enumerate (read-only).

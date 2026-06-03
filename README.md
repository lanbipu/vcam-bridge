# vcam-bridge

UE Sequencer FBX camera animation → Disguise AnimateCameraControl keyframe injector.

See `docs/superpowers/specs/2026-06-03-vcam-bridge-design.md`.

## Usage (Plan 1 — offline dry-run)

```bash
uv venv && uv pip install -e ".[dev]"
uv run vcam convert --fbx track.csv --target-uid 0x1a2b --dry-run --output json
uv run vcam manifest --output json
```

`--dry-run` 算出 ACC pivot/rotation/distance/FOV 并生成 Py2.7 注入脚本，不触真机。
真机注入/probe（连接层、P0–P10、Blender 原生 FBX、Skill）见 Plan 2。

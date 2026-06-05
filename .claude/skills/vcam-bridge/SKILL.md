---
name: vcam-bridge
description: >-
  Convert UE Sequencer FBX camera animation into Disguise AnimateCameraControl
  keyframes — including trimming static hold frames and manual frame-range
  selection. Use whenever the user wants to import/inject camera animation into
  Disguise Designer, list ACC layers or virtual cameras, trim or crop FBX
  animation, remove static/hold frames, decimate/subsample keyframes to reduce
  playback load, calibrate conventions (probe), or mentions FBX + Disguise in
  any combination. Also trigger for phrases like "put this camera move into
  Designer", "import FBX", "list cameras in Designer", "check what ACC layers
  exist", "trim the static part", "cut the hold frames", "only inject frames
  100-300", "reduce keyframe density", "decimate frames", "subsample", "every
  other frame", or "drop frame rate for injection".
---

# vcam-bridge

## CLI invocation

The `vcam` entry point lives inside the project virtualenv. Always invoke via
the absolute path so it works regardless of cwd or PATH:

```
/Users/bip.lan/AIWorkspace/vp/d3/vcam-bridge/.venv/bin/vcam
```

Standard flags appended to every call:
```
--output json --no-color --no-input --curl
```

`--curl` is mandatory on macOS — it routes HTTP through a curl subprocess
instead of `requests`, bypassing Surge / network-policy interception that
silently drops requests on this machine.

Full boilerplate for copy-paste:
```bash
/Users/bip.lan/AIWorkspace/vp/d3/vcam-bridge/.venv/bin/vcam <cmd> [args] --output json --no-color --no-input --curl
```

## Transport policy
1. CLI-first. Parse ONLY stdout JSON (the envelope).
2. Complex input via stdin JSON.
3. There is no MCP server; do not assume one.

## Error policy
1. Check `exit_code` / `error.code` in the envelope (never parse natural-language text).
2. Retry ONLY when `error.retryable: true`.
3. Destructive ops (`convert`) run with `--dry-run` first; show the dry_run_plan summary and get user confirmation before the live run. (`probe` is read-only — safe to run anytime.)
4. See `references/errors.md` for the full exit-code table and agent decision rules.

## Operations
See `references/contract-manifest.json` (synced from `vcam manifest`). Key ops:
- `vcam convert --fbx F --target-uid U --vc-uid V [--dry-run] [--trim-hold] [--start-frame N] [--end-frame N] [--decimate N]` — inject (destructive).
- `vcam probe --director H:P --probe-layer-uid U` — dump a layer's module type + field names (read-only).
- `vcam targets list --director H:P` — enumerate ACC layers with coord_mode + n_keys (read-only).
- `vcam vc list --director H:P` — enumerate cameras with focal_mm/zoom_scale/sensor_mm/parent_uid (read-only).
- `vcam config init --path P` / `vcam config show` / `vcam config validate --path P` — config management.

---

## FBX Import Workflow

Complete step-by-step for injecting a UE FBX camera animation into Designer.

### Prerequisites
- Disguise Designer running with a project open
- FBX file exported from UE Sequencer (CineCameraActor)
- Blender installed locally (auto-detected at `/Applications/Blender.app` on macOS, or `$BLENDER`)

### Step 0 — Resolve Director address

The Director address (`HOST:PORT`, typically `HOST:80`) is required for all
remote operations. Resolve it in this priority order:

1. If the user provided it in the prompt, use it directly.
2. Ask the user via AskUserQuestion — suggest known machines (e.g. `192.168.10.20:80` for lanPC).

### Step 1 — Enumerate targets (read-only)
```bash
vcam targets list --director HOST:PORT ...
vcam vc list --director HOST:PORT ...
```
Parse `data.layers[].{name, uid, coord_mode, n_keys}` and
`data.cameras[].{name, uid, type, focal_mm, zoom_scale, sensor_mm, parent_uid}`.

Present both lists to user via AskUserQuestion for selection — one question
for ACC layer, one for camera. Include `coord_mode` and `n_keys` in the layer
descriptions (helps decide whether `--overwrite` is needed). For virtual cameras,
note `focal_mm` and `zoom_scale` — these are needed for baseline calibration.

### Step 2 — Dry-run preview (read-only)
```bash
vcam convert --fbx /path/to.fbx --target-uid 0x... --dry-run ...
```
> `--dry-run` does not require `--director` when using `--target-uid`. But if
> using `--target-name` instead, `--director` is needed for name resolution.
>
> **Keyframe decimation** — if the user asks to reduce keyframe density (e.g.
> "every other frame", "reduce frame rate", "decimate"), add `--decimate N`
> (N=2 keeps every 2nd frame, N=3 every 3rd, etc.). First and last frames are
> always preserved. Do NOT add `--decimate` unless the user explicitly requests
> it — full frame density is the default and usually correct.
Extract summary from `data.dry_run_plan` and present as a compact table:
- `frame_count`, `fps`, `fov_control`
- First and last keyframe (position, rotation, zoom)
- Duration = `keyframes[-1].t_sec - keyframes[0].t_sec`

Do NOT dump the full keyframe array (can be 90KB+ even for short clips).

#### Static hold analysis

To check for static hold frames, re-run the dry-run with `--trim-hold`:
```bash
vcam convert --fbx /path/to.fbx --target-uid 0x... --trim-hold --dry-run ...
```

Read `data.dry_run_plan.trim` — the report has a consistent shape:
```json
{
  "orig_count": 324,
  "new_count": 151,
  "range": null,
  "hold": {
    "trimmed": true,
    "orig_count": 324,
    "new_count": 151,
    "leading_removed": 171,
    "trailing_removed": 2,
    "leading_hold_sec": 5.7,
    "trailing_hold_sec": 0.067
  },
  "decimate": null
}
```

If `hold.leading_removed` or `hold.trailing_removed` > 0, present the finding:
```
Detected: 171 leading + 2 trailing static hold frames removed (324 → 151, saves 5.77s).
```

Do NOT scan the keyframes array yourself — the CLI's hold detection uses
calibrated thresholds on the raw transform matrix; manual comparison may disagree.

For precise manual control, suggest `--start-frame N --end-frame N` instead.
Both flags can be combined: range is applied first, then hold-trim on the result.
When both are used, `data.dry_run_plan.trim` has both `range` and `hold` populated.

### Step 3 — Live inject (destructive, requires `--yes`)
```bash
vcam convert --fbx /path/to.fbx \
  --target-uid 0x... --vc-uid 0x... \
  --director HOST:PORT \
  --yes --verify [--trim-hold] [--start-frame N --end-frame N] [--decimate N] ...
```

> **Trim flags carry over from dry-run.** If `--trim-hold` or
> `--start-frame`/`--end-frame` was used in the Step 2 dry-run, include the
> same flags in the live inject command so the injected keyframes match the
> previewed count.

> **Switching takes or cameras? Add `--overwrite`.** By default new keys are
> *appended* onto whatever is already on the layer — stale residual keys remain
> (observed: a 151-frame take left the layer at 191 keys). `--overwrite` strips
> old keys first. Re-running the same FBX on the same layer is idempotent and
> doesn't need it.

> **Injecting a VirtualCamera?** `convert` auto-calibrates `baseline_focal_mm`
> from the VC's live `focal_mm / zoom_scale` — no manual config needed.
> If the VC's Lens Source is not "Local intrinsics", `convert` automatically
> changes it to Local (required for `view angle` FOV injection) and reports
> the change in `data.warnings[]` and `data.calibration.lens_source_change`.

### Step 4 — Present result

After a successful inject, parse the envelope and present this summary:

```
| Item              | Value                          |
|-------------------|--------------------------------|
| Status            | data.target_setup.ok           |
| Written keys      | data.written                   |
| Frames            | data.frames (fps, duration)    |
| Trim              | data.trim.{orig_count, new_count, hold.leading_removed, hold.trailing_removed} (if used) |
| Camera bound      | data.target_setup.note[]       |
| Lens source       | data.calibration.lens_source_change |
| Verify            | data.verify.ok / .level        |
| Aspect source     | data.aspect_source             |
| Sensor / Focal    | data.sensor_width_mm / focal_mm|
| Warnings          | data.warnings[] (if any)       |
```

Key checks:
- `data.target_setup.ok` — camera bound and coord set to Global
- `data.calibration.lens_source_change` — if not null, VC Lens Source was changed to Local (report `from_name` → `to_name` to user)
- `data.verify.ok` — persistence verification passed
- `data.verify.world_pose.skipped == "solo"` — triggered by `isRunningSolo` (the **session** run mode), which is true even on a Director machine when no render node is refreshing the camera. The pose readback would be stale, so it's skipped — confirm the pose visually in the Designer GUI.
- `data.warnings[]` — surface to user (e.g. lens source change, aspect fallback on non-16:9 output)

### Virtual Camera vs Live Camera

Pivot/rotation/distance mapping is identical for both. What differs:

- **FOV driver** — a Live Camera's FOV is driven by ACC `view angle` (vertical
  FOV); a VirtualCamera's by `virtual camera zoom` (a scale on its parent-camera
  lens). vcam injects both (dual-FOV) so either type renders; ACC layers always
  expose both fields, so neither errors on a missing field.
- **Lens Source forced to Local** — VirtualCamera has three Lens Source modes:
  Local intrinsics (0), Zoom from parent (1), Intrinsics from parent (2).
  Only Local mode allows ACC `view angle` to directly drive FOV. `convert`
  auto-detects the current mode and forces it to Local if needed; the change
  is reported in `data.calibration.lens_source_change` and `data.warnings[]`.
  The original value is **not restored** after injection.
- **VC baseline auto-calibrated** — `virtual camera zoom = target_focal /
  baseline_focal_mm`. `convert` auto-reads the VC's `focal_mm` and `zoom_scale`
  from Designer and computes `baseline = focal_mm / zoom_scale`. No manual
  config is needed. Override via `calibration.baseline_focal_mm` in config if
  auto-calibration is wrong. Live Cameras don't need this.
- **Coordinate system is forced to Global** — vcam sets the ACC `virtual camera
  coordinates` field to **1** (=Global; **0 = Relative**). Mandatory: vcam emits
  global stage coordinates, so a Relative VC gets offset by its parent camera.
  Confirm the VC editor shows **Global** in the GUI.

### Optional flags
| Flag | When to use |
|------|-------------|
| `--target-name "Name"` | Instead of `--target-uid` (exact match, requires `--director`) |
| `--camera-name "Name"` | Instead of `--vc-uid` (exact match, requires `--director`) |
| `--trim-hold` | Auto-remove leading/trailing static hold frames (each end keeps 1 anchor frame); suggest when dry-run shows >10% static frames |
| `--start-frame N` | Manual trim: keep frames starting from idx N (0-based, inclusive) |
| `--end-frame N` | Manual trim: keep frames up to idx N (0-based, inclusive) |
| `--decimate N` | Keep every Nth frame (2=half, 3=third, etc.); first+last always kept. Only use when user explicitly asks to reduce keyframe density for playback performance. Do NOT suggest proactively |
| `--overwrite` | Clear existing keyframes before inject (switching takes **or cameras**; see Step 3 note) |
| `--chunk-size N` | Reduce from default 200 if Designer times out on long animations |
| `--pivot-distance focus` | Use FBX focus distance as orbit pivot distance |
| `--pivot-distance const=M` | Fixed pivot distance in meters |

### Error recovery
- **Exit 7 (TIMEOUT)**: retry with `--chunk-size` halved (e.g. 200 -> 100 -> 50)
- **Exit 8 (EXTERNAL)**: check Designer connectivity (`curl http://HOST:PORT/api/session/status/health`)
- **Exit 9 (PARTIAL)**: some chunks written; re-run same command (idempotent)
- **Exit 13 (INVALID_FBX)**: FBX has no camera or Blender extraction failed; check `error.details.stderr`

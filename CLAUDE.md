# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

vcam-bridge converts UE Sequencer FBX camera animations into Disguise Designer AnimateCameraControl (ACC) keyframes. It extracts camera transforms via the `ufbx` native reader by default (`--reader native`; a headless Blender subprocess remains as the `--reader blender` fallback), maps UE coordinates to Disguise stage space, decomposes free-camera poses into pivot-orbit form, and injects keyframes through Designer's Python `/execute` API.

## Parent Project References

vcam-bridge 是上级项目 `vp/d3/` (disguise Open Source Ecosystem) 的子项目。开发时可参考同级仓库的源码和知识库：

### Sibling Repos (Source Reference)

| Repo | What to look at | When |
|------|----------------|------|
| `python-plugin/` | `designer-plugin` 的 DNS-SD 发现、`/execute` 调用、Py3→Py2.7 AST 转换 | 修改 Designer 通信层 (`designer/client.py`, `transport.py`)，或需要理解 Py2.7 限制 |
| `vue-liveupdate/` | LiveUpdate WebSocket 协议、属性订阅机制 | 如果需要实时读回 Designer 属性（如 verify world-pose） |
| `RenderStream-UE/` | UE5 nDisplay 集成、相机坐标系约定 | 调试 UE→Disguise 坐标变换 (`transform/register.py`) |

### Knowledge Base (上级项目)

上级项目在 `../` 维护了一套已索引的文档知识库，覆盖 Disguise API、Designer Python API、UE 5.7 文档等。查询路径：

1. 读 `../.claude/knowledge/_INDEX.md` 定位来源
2. 读 `<source>/_INDEX.md` 缩小到目标文档
3. 先看 TL;DR，再按需读全文

与 vcam-bridge 开发最相关的来源：
- `developer-disguise-one/` — Designer REST API (`/execute`, `/status/health`, routing)
- `disguise_python_api/` — Designer 内嵌 Python API (`state.stage.cameras`, `layer.findSequence`, `sequence.setFloat`)
- `help-disguise-one/` — ACC 层行为、Virtual Camera 配置、timeline/beat 系统
- `ue57-docs/` — UE 5.7 Sequencer、CineCameraActor、FBX 导出格式

## Commands

```bash
# Setup
uv venv && uv pip install -e ".[dev]"

# Run CLI
uv run vcam convert --fbx track.fbx --target-uid 0x1a2b --dry-run --output json
uv run vcam manifest --output json

# Tests
uv run pytest                              # all unit tests
uv run pytest tests/test_decompose.py      # single file
uv run pytest -k "test_euler_roundtrip"    # single test by name
uv run pytest -m "not integration"         # skip tests needing Blender / live hardware
uv run pytest -m integration               # only integration tests
```

The `integration` marker flags tests requiring Blender or a live Designer instance.

## Architecture

### Data Pipeline

```
FBX file
  → ingest/blender_fbx.py    (subprocess: Blender --background --python blender_extract.py)
  → ingest/blender_extract.py (bpy: extract matrix_world, FOV, focal/sensor per frame)
  → domain/models.CameraTrack (schema "vcam.track/1": fps, camera name, Frame[])
  → cli/commands/convert.py   (build_keyframes: apply M, decompose, compute zoom)
  → designer/codegen.py       (generate Py2.7 injection script with JSON payload)
  → designer/inject.py        (chunked HTTP /execute calls with timeout-bisect retry)
  → Designer ACC timeline     (keyframes at beat positions via track.timeToBeat)
```

### Coordinate Transform Chain

The UE→Disguise mapping has three non-obvious steps:

1. **Blender undo** — FBX import bakes a 0.01 scale into `matrix_world`; `blender_extract.py` divides it back out so downstream gets raw UE-centimeter coordinates.
2. **`default_M()`** — A 4×4 similarity transform (cm→m + axis remap + reflection). The reflection (`det(M) < 0`) is intentional — it undoes Blender's Y-axis flip. This matrix lives in `transform/register.py`.
3. **Pivot-orbit decompose** — `transform/decompose.py` converts a free camera position + rotation matrix into Disguise's (pivot, elevation/heading/roll, distance) representation. The Euler convention is `disguise_zxy` — a custom order where elevation=X, heading=Y, roll=Z, different from scipy's standard ZXY.

### Designer Communication

`designer/client.py` wraps the REST API with solo/director routing:
- Solo mode: direct HTTP to the machine
- Director mode: discovers the session host via `/api/session/status/health`, then routes `/execute` calls there

All Designer-side code must be **Python 2.7 compatible** — Designer's embedded interpreter runs Py2.7. The injection scripts in `codegen.py` avoid f-strings, walrus operators, type hints, and async/await. Dynamic data enters only via `json.loads(repr(...))`, never string interpolation into code.

### Transport Abstraction

`designer/transport.py` provides three backends:
- `RequestsTransport` — standard `requests` library
- `CurlTransport` — shell out to `curl` (mandatory on macOS where Surge/network policies silently drop `requests` calls)
- `FakeTransport` — for testing; records calls and returns scripted responses

### Envelope Protocol

Every CLI output is a JSON envelope: `{schema_version, status, operation_id, data|error, meta}`. The `meta` block carries `request_id` (UUID), `duration_ms`, and `timestamp`. Error envelopes include `error.code`, `error.retryable`, and `error.details`. See `envelope.py` for constants and builders.

## Error Hierarchy

All errors extend `VcamError(code, exit_code, retryable, message, details)`. Only three exit codes are retryable:
- **7 (TIMEOUT)** — Designer script execution timed out; halve `--chunk-size`
- **8 (EXTERNAL)** — network/HTTP failure; check connectivity
- **9 (PARTIAL)** — some chunks written; re-run (idempotent)

## Key Design Decisions

- **Time-based injection, not frame-based** — keyframes are placed at `t_sec` positions converted to Designer beats via `timeToBeat()`. UE fps and Designer fps don't need to match.
- **Chunk + bisect retry** — injection splits keyframes into chunks (default 200). On timeout, the failing chunk is halved and retried, down to `min_chunk=8`.
- **FBX cache** — Blender extraction results are cached by SHA256(fbx + script + blender version) in `~/.cache/vcam_bridge/fbx/`. Same FBX won't re-extract.
- **Dual FOV injection** — both `view_angle` (vertical, for Live Cameras) and `zoom` (for Virtual Cameras) are written, so either camera type renders correct FOV.
- **`--overwrite` semantics** — `stripToFirstKey()` runs only on the first chunk of a convert; subsequent chunks must not re-strip or they'd erase what earlier chunks wrote.

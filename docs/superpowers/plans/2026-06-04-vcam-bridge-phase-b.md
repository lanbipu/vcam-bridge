# Phase B: 真机适配实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 vcam-bridge 代码从 spec 猜测对齐到 Designer R33 真机实测的约定——Euler ZXY(heading 取反) + R^T position + zoom scale FOV + 含空格字段名——使 `vcam convert` 能正确注入 keyframe。

**Architecture:** 8 文件改动 + 1 删除，不改架构。自底向上：先改 transform 层（decompose/fov），再改 codegen/models，再改 convert 编排，最后加 verify + CLI flag。每步 TDD。

**Tech Stack:** Python 3.11+, pydantic v2, numpy, scipy, pytest. 真机 fixture 在 `tests/fixtures/live/`。

参照 spec：`docs/superpowers/specs/2026-06-04-vcam-bridge-phase-b-adaptation.md`（v2）。

---

## 文件结构（本计划修改）

```
删除:
  src/vcam_bridge/transform/convention.py
  tests/test_convention.py

修改:
  src/vcam_bridge/transform/decompose.py
  src/vcam_bridge/transform/fov.py
  src/vcam_bridge/designer/codegen.py
  src/vcam_bridge/domain/models.py
  src/vcam_bridge/cli/commands/convert.py
  src/vcam_bridge/designer/inject.py
  src/vcam_bridge/cli/main.py
  tests/test_decompose.py
  tests/test_fov.py
  tests/test_codegen.py
  tests/test_models.py
  tests/test_cli_convert.py
  tests/test_pipeline_e2e.py
  tests/test_live_simulation.py
  tests/test_cli_live.py

新增:
  tests/test_verify.py
```

---

## Task 1: 删除 convention solver + 清理引用

**Files:**
- Delete: `src/vcam_bridge/transform/convention.py`
- Delete: `tests/test_convention.py`
- Modify: `tests/test_live_simulation.py`

- [ ] **Step 1: 删除 convention.py 和 test_convention.py**

```bash
rm src/vcam_bridge/transform/convention.py tests/test_convention.py
```

- [ ] **Step 2: 清理 test_live_simulation.py 中引用 convention 的代码**

从 `tests/test_live_simulation.py` 中删除：
- import 行 `from vcam_bridge.transform.convention import solve_convention`
- `_synth_convention_samples` 辅助函数
- `test_synthetic_convention_solve` 测试
- `test_convention_solver_all_axes` 参数化测试（6 个）

保留：`test_synthetic_umeyama_calibration`、`test_convert_live_full_flow`、`test_timeout_bisect_then_succeed`、`test_double_timeout_cascading_bisect`、`test_convert_live_director_routing`、`test_build_keyframes_all_canonical_fields`。

- [ ] **Step 3: 运行测试确认删除后仍通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/ -q --ignore=tests/test_convention.py 2>&1 | tail -5`
Expected: 所有剩余测试 PASS（convention 相关测试已删）。

- [ ] **Step 4: Commit**

```bash
git add -u && git status
git commit -m "refactor: remove convention solver (Designer convention hardcoded from real-machine calibration)"
```

---

## Task 2: 改写 decompose.py（Euler ZXY + R^T 位置公式）

**Files:**
- Modify: `src/vcam_bridge/transform/decompose.py`
- Modify: `tests/test_decompose.py`

- [ ] **Step 1: 写 disguise euler roundtrip 失败测试**

在 `tests/test_decompose.py` 顶部追加 import 并新增测试：

```python
from vcam_bridge.transform.decompose import disguise_euler_to_matrix, disguise_matrix_to_euler

def test_disguise_euler_roundtrip():
    cases = [(0, 0, 0), (10, 0, 0), (0, 20, 0), (0, 0, 5),
             (20, -10, 5), (-5, 45, -10), (30, -20, 15), (-25, 15, -5)]
    for elev, head, roll in cases:
        R = disguise_euler_to_matrix(elev, head, roll)
        e2, h2, r2 = disguise_matrix_to_euler(R)
        assert abs(e2 - elev) < 1e-9, f"elev {elev} -> {e2}"
        assert abs(h2 - head) < 1e-9, f"head {head} -> {h2}"
        assert abs(r2 - roll) < 1e-9, f"roll {roll} -> {r2}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_decompose.py::test_disguise_euler_roundtrip -q`
Expected: FAIL（`ImportError: cannot import name 'disguise_euler_to_matrix'`）

- [ ] **Step 3: 实现 disguise euler 函数**

在 `src/vcam_bridge/transform/decompose.py` 中新增（在 `forward_vector` 之后、`decompose_pivot_orbit` 之前）：

```python
from scipy.spatial.transform import Rotation


def disguise_euler_to_matrix(elev_deg: float, heading_deg: float, roll_deg: float) -> np.ndarray:
    return Rotation.from_euler('ZXY', [roll_deg, elev_deg, -heading_deg], degrees=True).as_matrix()


def disguise_matrix_to_euler(R: np.ndarray) -> tuple[float, float, float]:
    angles = Rotation.from_matrix(np.asarray(R, dtype=float)).as_euler('ZXY', degrees=True)
    return (float(angles[1]), float(-angles[2]), float(angles[0]))
```

- [ ] **Step 4: 运行 roundtrip 测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_decompose.py::test_disguise_euler_roundtrip -q`
Expected: PASS

- [ ] **Step 5: 写真机 fixture 验证测试**

在 `tests/test_decompose.py` 新增：

```python
import json
from pathlib import Path

def test_disguise_euler_matches_real_machine_fixtures():
    samples = json.loads(Path("tests/fixtures/live/convention_samples.json").read_text())
    for i, s in enumerate(samples):
        R_expected = np.array(s["world"]["rotation_matrix"])
        rx, ry, rz = s["written"]["rotation"]
        R_built = disguise_euler_to_matrix(rx, ry, rz)
        assert np.allclose(R_built, R_expected, atol=1e-6), f"sample {i} rotation mismatch"
```

- [ ] **Step 6: 运行 fixture 测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_decompose.py::test_disguise_euler_matches_real_machine_fixtures -q`
Expected: PASS

- [ ] **Step 7: 改写 decompose_pivot_orbit 和 recompose 使用 R.T**

替换 `decompose_pivot_orbit` 和 `recompose` 函数体：

```python
def decompose_pivot_orbit(C: np.ndarray, R: np.ndarray, d: float, *,
                          forward_axis: str, euler_order: str) -> dict:
    C = np.asarray(C, dtype=float)
    R = np.asarray(R, dtype=float)
    f = R.T @ forward_vector(forward_axis)
    pivot = C + d * f
    rot = disguise_matrix_to_euler(R)
    return {"pivot": tuple(float(x) for x in pivot),
            "rotation": rot, "distance": float(d)}


def recompose(pose: dict, *, forward_axis: str, euler_order: str) -> tuple[np.ndarray, np.ndarray]:
    R = disguise_euler_to_matrix(*pose["rotation"])
    f = R.T @ forward_vector(forward_axis)
    pivot = np.asarray(pose["pivot"], dtype=float)
    C = pivot - pose["distance"] * f
    return C, R
```

- [ ] **Step 8: 更新现有 decompose 测试适配新公式**

`test_decompose_recompose_invertible` 和 `test_decompose_recompose_various_conventions` 里的 `euler_to_matrix` 调用改为 `disguise_euler_to_matrix`，forward_axis 改为 `"+Z"`，euler_order 改为 `"disguise_zxy"`。`test_decompose_steep_angles` 同理。

把所有测试中 `forward_axis="+X", euler_order="XYZ"` 改为 `forward_axis="+Z", euler_order="disguise_zxy"`，角度用 `disguise_euler_to_matrix(elev, head, roll)` 构造 R。

对于参数化测试 `test_decompose_recompose_various_conventions`，由于 Euler 约定现在是固定的 disguise_zxy，不再需要参数化多种约定——改为一个用随机角度的 invertibility 测试即可。

- [ ] **Step 9: 写真机 fixture 的 position 精度测试**

```python
def test_decompose_position_matches_real_machine():
    samples = json.loads(Path("tests/fixtures/live/convention_samples.json").read_text())
    for i, s in enumerate(samples):
        rx, ry, rz = s["written"]["rotation"]
        R = disguise_euler_to_matrix(rx, ry, rz)
        pivot = np.array(s["written"]["pivot"], dtype=float)
        dist = s["written"]["distance"]
        C_actual = np.array(s["world"]["position"])
        f = R.T @ forward_vector("+Z")
        C_pred = pivot - dist * f
        assert np.allclose(C_pred, C_actual, atol=0.05), f"sample {i}: pred={C_pred} actual={C_actual}"
```

- [ ] **Step 10: 运行全部 decompose 测试**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_decompose.py -v`
Expected: 全部 PASS

- [ ] **Step 11: Commit**

```bash
git add src/vcam_bridge/transform/decompose.py tests/test_decompose.py
git commit -m "feat: disguise euler convention (ZXY, heading negated) + R^T position formula"
```

---

## Task 3: fov.py 新增 hfov↔zoom 转换

**Files:**
- Modify: `src/vcam_bridge/transform/fov.py`
- Modify: `tests/test_fov.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_fov.py` 追加：

```python
from vcam_bridge.transform.fov import hfov_to_zoom, zoom_to_hfov


def test_hfov_to_zoom_fixture_values():
    B = 30.296; S = 35.0
    assert math.isclose(hfov_to_zoom(98.24, B, S), 0.5, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(60.02, B, S), 1.0, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(42.12, B, S), 1.5, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(32.22, B, S), 2.0, abs_tol=0.01)


def test_hfov_zoom_roundtrip():
    B = 30.296; S = 35.0
    for fov in [30, 45, 60, 75, 90, 120]:
        z = hfov_to_zoom(float(fov), B, S)
        back = zoom_to_hfov(z, B, S)
        assert math.isclose(back, fov, abs_tol=0.01)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_fov.py::test_hfov_to_zoom_fixture_values -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现 hfov_to_zoom 和 zoom_to_hfov**

在 `src/vcam_bridge/transform/fov.py` 追加：

```python
def hfov_to_zoom(h_fov_deg: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    target_focal = sensor_width_mm / (2 * math.tan(math.radians(h_fov_deg) / 2))
    return target_focal / baseline_focal_mm


def zoom_to_hfov(zoom: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    focal = baseline_focal_mm * zoom
    return math.degrees(2 * math.atan(sensor_width_mm / (2 * focal)))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_fov.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/fov.py tests/test_fov.py
git commit -m "feat: hfov<->zoom conversion for Designer virtual camera zoom scale"
```

---

## Task 4: codegen.py 放宽字段名验证 + models.py 更新

**Files:**
- Modify: `src/vcam_bridge/designer/codegen.py`
- Modify: `src/vcam_bridge/domain/models.py`
- Modify: `tests/test_codegen.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: 写字段名含空格的失败测试**

在 `tests/test_codegen.py` 追加：

```python
def test_validate_field_name_allows_spaces():
    assert validate_field_name("camera pivot.x") == "camera pivot.x"
    assert validate_field_name("distance from pivot") == "distance from pivot"
    assert validate_field_name("virtual camera zoom") == "virtual camera zoom"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_codegen.py::test_validate_field_name_allows_spaces -q`
Expected: FAIL（`ValueError: invalid field name: 'camera pivot.x'`）

- [ ] **Step 3: 修改 _FIELD_RE 允许空格**

在 `src/vcam_bridge/designer/codegen.py` 中修改：

```python
_FIELD_RE = re.compile(r"^[A-Za-z0-9_ ]+(\.[A-Za-z0-9_ ]+)*$")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_codegen.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 更新 Calibration 模型**

在 `src/vcam_bridge/domain/models.py` 中修改 `Calibration` 类：
- `forward_axis` 默认值从 `"+X"` 改为 `"+Z"`
- `euler_order` 默认值从 `"XYZ"` 改为 `"disguise_zxy"`
- 删除 `handedness: int = 1`
- 新增 `baseline_focal_mm: float = 30.296`
- 新增 `sensor_width_mm: float = 35.0`

- [ ] **Step 6: 更新 test_models.py**

在 `tests/test_models.py` 追加：

```python
from vcam_bridge.domain.models import Calibration

def test_calibration_defaults():
    cal = Calibration()
    assert cal.forward_axis == "+Z"
    assert cal.euler_order == "disguise_zxy"
    assert cal.baseline_focal_mm == 30.296
    assert cal.sensor_width_mm == 35.0
    assert not hasattr(cal, "handedness") or "handedness" not in cal.model_fields
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_models.py tests/test_codegen.py -q`
Expected: 全部 PASS

- [ ] **Step 8: Commit**

```bash
git add src/vcam_bridge/designer/codegen.py src/vcam_bridge/domain/models.py tests/test_codegen.py tests/test_models.py
git commit -m "feat: allow spaces in field names + calibration model with zoom/focal defaults"
```

---

## Task 5: convert.py 适配新公式 + FOV→zoom

**Files:**
- Modify: `src/vcam_bridge/cli/commands/convert.py`
- Modify: `tests/test_cli_convert.py`
- Modify: `tests/test_pipeline_e2e.py`
- Modify: `tests/test_live_simulation.py`
- Modify: `tests/test_cli_live.py`

- [ ] **Step 1: 修改 convert.py**

在 `src/vcam_bridge/cli/commands/convert.py` 中：

1. 修改 imports：加 `from vcam_bridge.transform.decompose import disguise_matrix_to_euler`，加 `from vcam_bridge.transform.fov import hfov_to_zoom`，删 `from vcam_bridge.transform.fov import map_fov`。

2. 修改 `_CANONICAL_FIELDS`：
```python
_CANONICAL_FIELDS = ("pivot.x", "pivot.y", "pivot.z", "rotation.x", "rotation.y", "rotation.z", "distance", "zoom")
```

3. 修改 `build_keyframes` 中的 Euler 分解和 FOV 映射：
   - 删 `effective_fov_axis = fov_axis or cal.fov_axis` 和 `fov = map_fov(...)` 相关行
   - 加 `zoom = hfov_to_zoom(fr.fov_h_deg, cal.baseline_focal_mm, cal.sensor_width_mm)`
   - keyframe dict 中 `"fov": fov` 改为 `"zoom": zoom`
   - keys_payload 中 `"fov": fov` 改为 `"zoom": zoom`
   - Euler 分解：在 pose = decompose_pivot_orbit 后，rotation 已经由 decompose 内部的 `disguise_matrix_to_euler` 处理了，无需额外改动

4. 修改默认 `field_map`：
```python
field_map = cal.field_map or {
    "pivot.x": "camera pivot.x", "pivot.y": "camera pivot.y", "pivot.z": "camera pivot.z",
    "rotation.x": "camera rotation.x", "rotation.y": "camera rotation.y",
    "rotation.z": "camera rotation.z", "distance": "distance from pivot",
    "zoom": "virtual camera zoom",
}
```

5. `convert_dry_run` 中 `"fov_axis": fov_axis or cal.fov_axis` 改为 `"fov_control": "zoom_scale"`。删 `fov_axis` 参数。

6. `convert_live` 签名和调用同步删 `fov_axis` 参数。

- [ ] **Step 2: 更新 test_cli_convert.py**

所有引用 `fov` 的断言改为 `zoom`：
- `test_convert_dry_run_builds_plan`：`kf0` 的 keys 检查 `"zoom"` 而非 `"fov"`
- `test_convert_dry_run_fov_horizontal_passthrough`：改为检查 `zoom` 值 — `hfov_to_zoom(60.0, 30.296, 35.0)` ≈ 0.867
- `test_convert_dry_run_inject_script_has_populated_keys`：`"fov" in pl["keys"][0]["values"]` 改为 `"zoom"`
- `test_convert_rejects_partial_field_map`：field_map 内容改为含空格的真实字段名（只有 `pivot.x` 一个 key，仍会触发 missing canonical keys 报错）
- 删 `fov_axis="horizontal"` 参数
- 删 `test_convert_dry_run_fov_horizontal_passthrough`（FOV 不再通过 `fov_axis` 控制），换为：

```python
def test_convert_dry_run_zoom_computed(sample_track_json):
    import math
    from vcam_bridge.transform.fov import hfov_to_zoom
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg, layer_uid="0xabc")
    kf = data["dry_run_plan"]["keyframes"][0]
    expected_zoom = hfov_to_zoom(60.0, cfg.calibration.baseline_focal_mm, cfg.calibration.sensor_width_mm)
    assert abs(kf["zoom"] - expected_zoom) < 0.001
```

- [ ] **Step 3: 更新 test_pipeline_e2e.py**

- `test_pipeline_identity_camera_at_origin`：`kf["fov"]` 改为 `kf["zoom"]`，断言值改为 `hfov_to_zoom(90.0, 30.296, 35.0)`
- `test_pipeline_fov_vertical_conversion`：整个测试删除（不再有 fov_axis 参数）
- `test_pipeline_known_translation`：pivot 手算改用 R.T @ forward_vector("+Z")
- 其他测试中 `fov_axis="horizontal"` 参数删除

- [ ] **Step 4: 更新 test_live_simulation.py**

- `test_build_keyframes_all_canonical_fields`：canonical keys 检查 `"zoom"` 替代 `"fov"`
- `test_timeout_bisect_then_succeed` 和 `test_double_timeout_cascading_bisect`：keys 的 values 中 `"fov"` 改为 `"zoom"`
- `test_convert_live_full_flow`：`chunk_size=5` 时 written 数是 10 frames × 8 fields = 80，保持不变

- [ ] **Step 5: 更新 test_cli_live.py**

- `test_convert_live_injects`：written=16 来自 2 frames × 8 fields，保持不变（field 名变了但数量没变）

- [ ] **Step 6: 运行全部测试**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_convert.py tests/test_pipeline_e2e.py tests/test_live_simulation.py tests/test_cli_live.py
git commit -m "feat: convert uses zoom scale instead of FOV + real Designer field names"
```

---

## Task 6: inject.py 新增 verify_keys（两级）

**Files:**
- Modify: `src/vcam_bridge/designer/inject.py`
- Create: `tests/test_verify.py`

- [ ] **Step 1: 写 Level 1 (persistence) 失败测试**

创建 `tests/test_verify.py`：

```python
import pytest
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import verify_keys_persistence
from vcam_bridge.domain.errors import VerifyToleranceError


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_verify_persistence_passes():
    ft = FakeTransport(execute_responses=[
        _ok('{"max_errors": {"pivot.x": 0.0001, "zoom": 0.001}, "total_keys": 8}'),
    ])
    c = DesignerClient(ft, "localhost")
    report = verify_keys_persistence(c, layer_uid="0x1",
        fields={"pivot.x": "camera pivot.x", "zoom": "virtual camera zoom"},
        keys=[{"t_sec": 0, "values": {"pivot.x": 1.0, "zoom": 1.0}}],
        start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05)
    assert report["ok"] is True


def test_verify_persistence_raises_on_tolerance():
    ft = FakeTransport(execute_responses=[
        _ok('{"max_errors": {"pivot.x": 0.5, "zoom": 0.001}, "total_keys": 8}'),
    ])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(VerifyToleranceError):
        verify_keys_persistence(c, layer_uid="0x1",
            fields={"pivot.x": "camera pivot.x", "zoom": "virtual camera zoom"},
            keys=[{"t_sec": 0, "values": {"pivot.x": 1.0, "zoom": 1.0}}],
            start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_verify.py -q`
Expected: FAIL（`ImportError: cannot import name 'verify_keys_persistence'`）

- [ ] **Step 3: 实现 verify_keys_persistence**

在 `src/vcam_bridge/designer/inject.py` 追加：

```python
from vcam_bridge.domain.errors import VerifyToleranceError

_TOL_GROUPS = {
    "pivot.x": "pos", "pivot.y": "pos", "pivot.z": "pos",
    "rotation.x": "rot", "rotation.y": "rot", "rotation.z": "rot",
    "distance": "zoom", "zoom": "zoom",
}

_VERIFY_BODY = '''
import json
local_state = state.localOrDirectorState()
track = local_state.track
target = None
for layer in track.layers:
    if layer.uid == int(payload["layer_uid"], 16):
        target = layer
        break
if target is None:
    result = {"error": "layer not found"}
else:
    fieldmap = payload["fields"]
    seqs = {}
    for key in fieldmap:
        fs = target.findSequence(fieldmap[key])
        if fs is not None:
            seqs[key] = fs
    max_errors = {}
    start_offset = payload["start_offset_sec"]
    total = 0
    for kf in payload["keys"]:
        beat = track.timeToBeat(start_offset + kf["t_sec"])
        vals = kf["values"]
        for key in vals:
            if key in seqs:
                actual = seqs[key].eval(beat, 0.0)
                err = abs(actual - vals[key])
                if key not in max_errors or err > max_errors[key]:
                    max_errors[key] = err
                total = total + 1
    result = {"max_errors": max_errors, "total_keys": total}
'''


def verify_keys_persistence(client: DesignerClient, *, layer_uid: str, fields: dict,
                            keys: list[dict], start_offset_sec: float,
                            tol_pos: float, tol_rot: float, tol_zoom: float) -> dict:
    import json as _json
    payload = {"layer_uid": layer_uid, "start_offset_sec": start_offset_sec,
               "fields": fields, "keys": keys}
    json_str = _json.dumps(payload)
    script = "import json\npayload = json.loads(" + repr(json_str) + ")\n" + _VERIFY_BODY + "\nreturn json.dumps(result)\n"
    res = client.execute(script).return_value or {}
    if "error" in res:
        raise PartialError("verify failed: %s" % res["error"])
    tols = {"pos": tol_pos, "rot": tol_rot, "zoom": tol_zoom}
    max_errors = res.get("max_errors", {})
    exceeded = {}
    for field, err in max_errors.items():
        group = _TOL_GROUPS.get(field, "zoom")
        if err > tols[group]:
            exceeded[field] = {"error": err, "tolerance": tols[group]}
    if exceeded:
        raise VerifyToleranceError("verify tolerance exceeded",
                                   details={"exceeded": exceeded, "max_errors": max_errors})
    return {"ok": True, "max_errors": max_errors, "total_keys": res.get("total_keys", 0)}
```

- [ ] **Step 4: 运行 Level 1 测试确认通过**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_verify.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 写 Level 2 (world pose) 失败测试**

在 `tests/test_verify.py` 追加：

```python
from vcam_bridge.designer.inject import verify_world_pose


def test_verify_world_pose_passes():
    ft = FakeTransport(
        json_responses={},
        execute_responses=[
            _ok('{"pos": [1.0, 0.0, -2.0]}'),
        ],
    )
    c = DesignerClient(ft, "localhost")
    report = verify_world_pose(c, vc_uid="0xabc",
        keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}}],
        start_offset_sec=0.0,
        expected_positions=[[1.0, 0.0, -2.0]],
        tol_pos=0.001)
    assert report["ok"] is True


def test_verify_world_pose_raises():
    ft = FakeTransport(
        json_responses={},
        execute_responses=[
            _ok('{"pos": [5.0, 5.0, 5.0]}'),
        ],
    )
    c = DesignerClient(ft, "localhost")
    with pytest.raises(VerifyToleranceError):
        verify_world_pose(c, vc_uid="0xabc",
            keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}}],
            start_offset_sec=0.0,
            expected_positions=[[1.0, 0.0, -2.0]],
            tol_pos=0.001)
```

- [ ] **Step 6: 实现 verify_world_pose**

在 `src/vcam_bridge/designer/inject.py` 追加：

```python
import numpy as np


def verify_world_pose(client: DesignerClient, *, vc_uid: str, keys: list[dict],
                      start_offset_sec: float, expected_positions: list,
                      tol_pos: float) -> dict:
    indices = [0]
    if len(keys) > 2:
        indices.append(len(keys) // 2)
    if len(keys) > 1:
        indices.append(len(keys) - 1)
    max_err = 0.0
    for idx in indices:
        if idx >= len(expected_positions):
            continue
        t_sec = start_offset_sec + keys[idx]["t_sec"]
        client._t.post_execute(client.host,
            "import json\nreturn json.dumps({'goto': True})", timeout_s=5)
        script = ("import json\nvc = None\nfor c in state.stage.cameras:\n"
                  "    if c.uid == int('%s', 16):\n        vc = c\n        break\n"
                  "w = vc.world\nt = w.getTranslation()\n"
                  "return json.dumps({'pos': [t.x, t.y, t.z]})" % vc_uid)
        res = client.execute(script).return_value or {}
        actual = np.array(res.get("pos", [0, 0, 0]))
        expected = np.array(expected_positions[idx])
        err = float(np.linalg.norm(actual - expected))
        if err > max_err:
            max_err = err
    if max_err > tol_pos:
        raise VerifyToleranceError("world pose tolerance exceeded",
                                   details={"max_pos_error": max_err, "tol_pos": tol_pos})
    return {"ok": True, "sampled": len(indices), "max_pos_error": max_err}
```

- [ ] **Step 7: 运行全部 verify 测试**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/test_verify.py -v`
Expected: 全部 PASS（4 passed）

- [ ] **Step 8: Commit**

```bash
git add src/vcam_bridge/designer/inject.py tests/test_verify.py
git commit -m "feat: two-level verify (keyframe persistence + VC world pose)"
```

---

## Task 7: CLI --verify flag + convert_live 接线

**Files:**
- Modify: `src/vcam_bridge/cli/main.py`
- Modify: `src/vcam_bridge/cli/commands/convert.py`

- [ ] **Step 1: 给 convert 子命令加 --verify 和 tolerance flags**

在 `src/vcam_bridge/cli/main.py` 的 `build_parser` 中，`p_conv` 部分追加：

```python
p_conv.add_argument("--verify", action="store_true", default=False)
p_conv.add_argument("--tol-pos", type=float, default=0.001)
p_conv.add_argument("--tol-rot", type=float, default=0.05)
p_conv.add_argument("--tol-zoom", type=float, default=0.05)
```

- [ ] **Step 2: 修改 convert_live 签名和 _dispatch 接线**

在 `convert.py` 的 `convert_live` 签名加：`verify=False, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05`。

在 `convert_live` 函数末尾（`return` 之前），注入后若 verify：

```python
verify_report = None
if verify:
    from vcam_bridge.designer.inject import verify_keys_persistence
    verify_report = verify_keys_persistence(
        client, layer_uid=layer_uid, fields=field_map, keys=keys,
        start_offset_sec=start_offset_sec,
        tol_pos=tol_pos, tol_rot=tol_rot, tol_zoom=tol_zoom)
```

返回 data 加 `"verify": verify_report`。

在 `main.py` 的 `_dispatch` 中 `convert_live` 调用加 `verify=args.verify, tol_pos=args.tol_pos, tol_rot=args.tol_rot, tol_zoom=args.tol_zoom`。

- [ ] **Step 3: 运行全部测试**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add src/vcam_bridge/cli/main.py src/vcam_bridge/cli/commands/convert.py
git commit -m "feat: --verify flag with tolerance params for live convert"
```

---

## Task 8: 最终全量测试 + 清理

**Files:**
- All test files

- [ ] **Step 1: 运行全量测试**

Run: `cd vcam-bridge && .venv/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -20`
Expected: 全部 PASS，0 failures

- [ ] **Step 2: 确认 convention.py 已删除**

Run: `test -f src/vcam_bridge/transform/convention.py && echo EXISTS || echo DELETED`
Expected: `DELETED`

- [ ] **Step 3: 确认没有残留的 convention import**

Run: `grep -r "from vcam_bridge.transform.convention" tests/ src/ || echo "No stale imports"`
Expected: `No stale imports`

- [ ] **Step 4: 确认没有残留的 "fov" 在 canonical fields**

Run: `grep -n "_CANONICAL_FIELDS" src/vcam_bridge/cli/commands/convert.py`
Expected: 含 `"zoom"` 不含 `"fov"`

- [ ] **Step 5: 验收 dry-run 输出含 zoom**

Run: `printf 'idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n0,0,0,0,0,0,0,0,60,2\n1,0.033,100,0,0,0,10,0,62,2.5\n' > /tmp/t.csv && .venv/bin/python -m vcam_bridge.cli.main convert --fbx /tmp/t.csv --target-uid 0xabc --dry-run --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); kf=d['data']['dry_run_plan']['keyframes'][0]; print('zoom' in kf, 'fov' not in kf)"`
Expected: `True True`

- [ ] **Step 6: Commit 清理**

```bash
git add -A
git status
git commit -m "chore: Phase B cleanup — all tests green, convention removed, zoom+disguise euler active"
```

---

## Self-Review

**1. Spec 覆盖**：
- §2.1 convention 删除 → Task 1 ✓
- §2.2 decompose 改写 → Task 2 ✓
- §2.3 fov zoom → Task 3 ✓
- §2.4 codegen 字段名 → Task 4 ✓
- §2.5 models → Task 4 ✓
- §2.6 convert 适配 → Task 5 ✓
- §2.7 verify 两级 → Task 6 ✓
- §2.8 CLI flags → Task 7 ✓
- §3 测试策略 → Tasks 1-7 各含测试更新 ✓
- §5 验收标准 → Task 8 Step 1/5 ✓

**2. 占位符扫描**：无 TBD/TODO；每个 code step 含完整代码。

**3. 类型一致性**：
- `disguise_euler_to_matrix/disguise_matrix_to_euler`（Task 2）在 Task 2/5 一致引用
- `hfov_to_zoom`（Task 3）在 Task 5 的 convert 一致调用
- `verify_keys_persistence/verify_world_pose`（Task 6）在 Task 7 的 convert_live 一致调用
- `_CANONICAL_FIELDS` 中 `"zoom"` 替代 `"fov"`（Task 5）与 field_map 默认值一致
- `Calibration.baseline_focal_mm/sensor_width_mm`（Task 4）在 Task 5 build_keyframes 一致使用

# Phase B：真机适配 — vcam-bridge 代码修正规格

> 状态：设计已确认（2026-06-04）；**v2 已吸收 Codex adversarial review 修订**。
> 前置：Phase A 真机采集已完成，fixture 数据在 `tests/fixtures/live/`。
> 本文定义从"spec 猜测模式"到"真机实测模式"的代码改动。

---

## 0. 背景

Plan 1/2 的代码基于 spec 猜测实现。Phase A 在 R33 Designer 真机上采集了 8 组 convention 样本和 FOV/zoom 映射数据，暴露了多处偏差。本 spec 定义将代码对齐到真机行为的全部改动。

**真机发现摘要**（证据在 `tests/fixtures/live/convention_discovery.json`）：

| 项 | Spec 猜测 | 真机实测 |
|---|----------|---------|
| moduleType 内部名 | `AnimateCameraControl` | `AnimateCamera` |
| 字段名 | 下划线分隔 `camera_pivot.x` | 空格分隔 `camera pivot.x` |
| forward 方向 | 未知（solver 运行时发现） | **+Z**（sample 0：pivot=(1,0,0) dist=2 → C=(1,0,-2)） |
| Euler 约定 | 标准 intrinsic（solver 36 种候选） | **intrinsic ZXY，heading(ry) 取反**（非标准，solver 无法解出） |
| position 公式 | `C = pivot - dist * (R @ forward)` | `C = pivot - dist * (R^T @ forward)` |
| FOV 控制 | `view angle` 直写水平 FOV | `view angle` 无效；用 `virtual camera zoom` 倍率控制 |
| VC FOV 参数 | — | baseline_focal=30.296mm, sensor_width=35.0mm |
| world 读取时机 | 同一 execute 内 | 必须分两次 execute，中间 gototime 触发渲染 |
| world.getRotation() 单位 | degrees | turns（1.0 = 360°） |

---

## 1. 改动范围

8 个文件修改，1 个文件删除，0 个新文件。不改架构，只改参数和公式。

```
删除:
  src/vcam_bridge/transform/convention.py
  tests/test_convention.py

修改:
  src/vcam_bridge/transform/decompose.py      — Euler 约定 + R^T 位置公式
  src/vcam_bridge/transform/fov.py             — 新增 hfov↔zoom 转换
  src/vcam_bridge/designer/codegen.py          — field_name 允许空格
  src/vcam_bridge/domain/models.py             — Calibration 加 baseline_focal/sensor_width
  src/vcam_bridge/cli/commands/convert.py      — 适配新公式 + FOV→zoom
  src/vcam_bridge/designer/inject.py           — 新增 verify_keys（两级）
  src/vcam_bridge/cli/main.py                  — 加 --verify + tolerance flags
  tests/ (多文件)                               — 适配改动 + 新增 verify 测试
```

---

## 2. 各模块规格

### 2.1 `transform/convention.py` → 删除

convention solver 遍历 36 种标准 Euler 组合，无法解出 Designer 的非标准约定（ZXY + heading 取反）。约定已通过真机确定，运行时发现不再需要。

- 删除 `src/vcam_bridge/transform/convention.py`
- 删除 `tests/test_convention.py`
- 删除 `tests/test_live_simulation.py` 中引用 `solve_convention` 的测试
- `manifest.py` 中 `probe` operation 保留（probe 仍可做 P1/P2 只读探测）

### 2.2 `transform/decompose.py` — 改写核心公式

**现有代码**：
```python
# decompose: pivot = C + d * (R @ forward)
# recompose: C = pivot - d * (R @ forward)
# euler: 标准 euler_to_matrix / matrix_to_euler
```

**改为**：
```python
# decompose: pivot = C + d * (R.T @ forward)
# recompose: C = pivot - d * (R.T @ forward)
# euler: disguise 专用 ZXY + heading 取反
```

新增两个函数：

- `disguise_euler_to_matrix(elev_deg, heading_deg, roll_deg) -> np.ndarray`
  - 实现：`Rotation.from_euler('ZXY', [roll, elev, -heading], degrees=True).as_matrix()`
  - 对应 Designer 的 rotation.x=elevation, rotation.y=heading, rotation.z=roll
  - heading 取反是真机实测确认的（rotation matrix 完美匹配，8 组 rot_err < 1e-7）

- `disguise_matrix_to_euler(R: np.ndarray) -> tuple[float, float, float]`
  - 逆操作：从旋转矩阵提取 (elevation, heading, roll)
  - `angles = Rotation.from_matrix(R).as_euler('ZXY', degrees=True)`
  - `as_euler('ZXY')` 返回 `[roll, elev, -heading]`（与 `from_euler` 的输入顺序一致）
  - 因此：`elevation = angles[1]`, `heading = -angles[2]`, `roll = angles[0]`
  - 返回 `(elevation, heading, roll)`
  - **（v2 修正：v1 写反了 heading 和 roll 的取值位置，已用真机 fixture roundtrip 验证正确性）**

`decompose_pivot_orbit` 和 `recompose` 签名不变，但内部使用 R.T 和 disguise euler 函数。

`forward_vector`、`_AXES` 常量不变。

保留旧的 `euler_to_matrix` / `matrix_to_euler`（scipy 包装），但 decompose/recompose 不再调用它们。

### 2.3 `transform/fov.py` — 新增 zoom scale 转换

新增：

- `hfov_to_zoom(h_fov_deg: float, baseline_focal_mm: float, sensor_width_mm: float) -> float`
  - `target_focal = sensor_width_mm / (2 * tan(radians(h_fov_deg) / 2))`
  - `zoom = target_focal / baseline_focal_mm`
  - UE 水平 FOV → Designer zoom scale
  - **（v2 修正：v1 fixture 的 formula 字段写成了 `baseline / target` 方向反了，已修正 fixture 和 spec）**

- `zoom_to_hfov(zoom: float, baseline_focal_mm: float, sensor_width_mm: float) -> float`
  - 逆操作：`focal = baseline_focal_mm * zoom`
  - `h_fov = degrees(2 * atan(sensor_width_mm / (2 * focal)))`
  - 用于 verify 时从 zoom 还原 FOV

数值验证（来自真机 fixture `fov_samples.json`）：

| hFOV (°) | zoom | focal (mm) |
|----------|------|-----------|
| 98.24 | 0.50 | 15.15 |
| 60.02 | 1.00 | 30.30 |
| 42.12 | 1.50 | 45.44 |
| 32.22 | 2.00 | 60.59 |

保留 `h_to_v`、`v_to_h`、`map_fov`（不删除，但 convert 不再调用 `map_fov`）。

### 2.4 `designer/codegen.py` — 放宽字段名验证

**现有**：`_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")`

**改为**：`_FIELD_RE = re.compile(r"^[A-Za-z0-9_ ]+(\.[A-Za-z0-9_ ]+)*$")`

允许空格，拒绝引号/换行/特殊字符不变。真实字段名如 `camera pivot.x`、`distance from pivot` 含空格。

### 2.5 `domain/models.py` — Calibration 模型扩展

```python
class Calibration(BaseModel):
    module_type: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    forward_axis: str = "+Z"                    # 从 "+X" 改为 "+Z"（真机确认）
    euler_order: str = "disguise_zxy"            # 语义变更：固定 Designer 约定
    fov_axis: str = "horizontal"                 # 保留
    linear_key_type: Any | None = None
    M_ue2dis: list[list[float]] | None = None
    aspect: float = 16.0 / 9.0
    legacy_vc: bool = False
    zoom_scale_neutral: float = 1.0
    baseline_focal_mm: float = 30.296            # 新增
    sensor_width_mm: float = 35.0                # 新增
```

删除 `handedness` 字段（已被 Euler 约定吸收）。

### 2.6 `cli/commands/convert.py` — 适配新公式 + FOV→zoom

**`_stage_pose_for_frame`**：decompose.py 的公式改动（R.T）已处理 position 计算，`_stage_pose_for_frame` 只需确保传给 decompose 的 R 是正确的旋转矩阵即可，此函数内部逻辑不变。

**`build_keyframes`**：
- Euler 分解用 `disguise_matrix_to_euler(R)`
- FOV 映射：不再调 `map_fov`，改为 `hfov_to_zoom(fr.fov_h_deg, cal.baseline_focal_mm, cal.sensor_width_mm)`
- keyframe 的 values 里 `fov` 键替换为 `zoom`，值为 zoom scale

**默认 `field_map`**（当 `cal.field_map` 为空时）：
```python
{
    "pivot.x": "camera pivot.x",
    "pivot.y": "camera pivot.y",
    "pivot.z": "camera pivot.z",
    "rotation.x": "camera rotation.x",
    "rotation.y": "camera rotation.y",
    "rotation.z": "camera rotation.z",
    "distance": "distance from pivot",
    "zoom": "virtual camera zoom",
}
```

`fov`/`view angle` 不再出现在 field_map 中，被 `zoom`/`virtual camera zoom` 取代。

**`_CANONICAL_FIELDS`**：从 `("pivot.x", ..., "fov")` 改为 `("pivot.x", ..., "zoom")`。

### 2.7 `designer/inject.py` — 新增两级 `verify_keys`

**（v2 变更：采纳 Codex F3 建议，verify 分两级）**

#### Level 1：keyframe 持久化验证（`verify_keys_persistence`）

```python
def verify_keys_persistence(client, *, layer_uid, fields, keys,
                            start_offset_sec, tol_pos, tol_rot, tol_zoom) -> dict:
```

生成 Py2.7 回读脚本：对每个 (field, beat) 调 `fseq.eval(beat, default)` 比对写入值。证明 keyframe 数据被正确写入了 sequence。

返回 `{"ok": True/False, "max_errors": {"pivot.x": 0.0001, ...}, "total_keys": N}`。超差抛 `VerifyToleranceError(exit_code=11)`。

tolerance 分组：pivot.x/y/z → `tol_pos`，rotation.x/y/z → `tol_rot`，distance + zoom → `tol_zoom`。

#### Level 2：VC world pose 验证（`verify_world_pose`）— 仅在 Level 1 通过后运行

```python
def verify_world_pose(client, *, vc_uid, keys, start_offset_sec,
                      expected_positions, tol_pos) -> dict:
```

流程：
1. 对每个抽样 beat（取 keys 的首/中/末 3 个），调 REST `transport/gototime` 跳到对应秒数
2. 在独立 execute 中读 `vc.world.getTranslation()` 得到实际 world position
3. 比对 expected_positions 的对应条目

返回 `{"ok": True/False, "sampled": N, "max_pos_error": float}`。超差抛 `VerifyToleranceError`。

**这级验证能发现 target VC 绑定失败、Euler/position 公式错误、coordinate system 未设 Global 等 Level 1 无法检测的问题。**

顶层入口 `verify_keys` 串联两级：先 persistence，再 world pose。

### 2.8 `cli/main.py` — 加 `--verify` + tolerance flags

convert 子命令新增参数：
- `--verify`（flag）
- `--tol-pos`（float，默认 0.001）
- `--tol-rot`（float，默认 0.05）
- `--tol-zoom`（float，默认 0.05）

live 路径：`convert_live(..., verify=args.verify, tol_pos=..., tol_rot=..., tol_zoom=...)`。

`convert_live` 签名加 `verify=False, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05`；注入完成后若 verify=True 则调 `verify_keys`（两级），report 放入返回 data 的 `verify` 字段。

---

## 3. 测试策略

### 3.1 删除

- `tests/test_convention.py`（convention.py 被删）
- `tests/test_live_simulation.py` 中 `test_synthetic_convention_solve`、`test_synthetic_umeyama_calibration`、6 个 `test_convention_solver_all_axes` 参数化测试

### 3.2 修改

| 测试文件 | 改动 |
|---------|------|
| `test_decompose.py` | 所有 decompose↔recompose 测试改用 `disguise_euler_to_matrix/matrix_to_euler` + R.T 公式 |
| `test_fov.py` | 新增 `hfov_to_zoom` / `zoom_to_hfov` roundtrip + 真机 fixture 数值验证 |
| `test_codegen.py` | `validate_field_name` 新增含空格的合法用例（`"camera pivot.x"`、`"distance from pivot"`） |
| `test_cli_convert.py` | dry-run 输出的 keys 含 `zoom` 而非 `fov`；默认 field_map 用真实字段名 |
| `test_models.py` | `Calibration` 默认 forward_axis="+Z"、有 baseline_focal_mm/sensor_width_mm |
| `test_pipeline_e2e.py` | 适配 `zoom` 替代 `fov` |
| `test_live_simulation.py` | 删除 convention 相关、适配 `zoom` 替代 `fov` |

### 3.3 新增

| 测试文件 | 内容 |
|---------|------|
| `test_verify.py` | Level 1：FakeTransport 测 `verify_keys_persistence` 通过/超差。Level 2：FakeTransport 测 `verify_world_pose` 通过/超差。CLI `--verify` 端到端。 |
| `test_decompose.py` 追加 | 用 `tests/fixtures/live/convention_samples.json` 的 8 组真机数据验证 disguise euler roundtrip + decompose 公式精度（含 heading+roll 同时非零的 samples） |
| `test_fov.py` 追加 | 用真机 fixture `fov_samples.json` 的 4 组 zoom_samples 做数值断言：`hfov_to_zoom(98.24, 30.296, 35.0) ≈ 0.5` 等 |

### 3.4 不动

- `test_register.py`、`test_rotation.py`、`test_ingest_intermediate.py`、`test_blender_fbx.py`
- `test_transport.py`、`test_client.py`、`test_targets.py`、`test_probe.py`
- `test_envelope.py`、`test_errors.py`、`test_config.py`、`test_render.py`
- `test_manifest.py`、`test_skill_manifest.py`、`test_cli_consistency.py`
- `integration/test_blender_extract_real.py`

---

## 4. 不做的事

- **不实现 `build_calibration` / `run_full_probe`**：probe 自动化属后续优化，当前手动采集 + config.yaml 已够用
- **不实现 probe 写 config.yaml**：手动编写即可
- **不改 Blender ingest 层**：FBX 提取不受约定改动影响
- **不改 transport/client 层**：HTTP 通信不受影响
- **不改 manifest**：operation 声明不变
- **不做 P6 M_ue2dis 标定**：default_M 作为初始值，精确标定属后续

---

## 5. 验收标准

1. `pytest tests/` 全部通过
2. `vcam convert --dry-run` 的 keyframes 含 `zoom` 字段（非 `fov`），pivot/rotation 值与真机 fixture 公式一致
3. `vcam convert --yes --verify` 能注入 + 两级回读验证
4. `validate_field_name("camera pivot.x")` 通过，`validate_field_name("bad\"name")` 拒绝
5. `disguise_euler_to_matrix → disguise_matrix_to_euler` roundtrip 对 heading+roll 同时非零的用例误差 < 1e-9

---

## 6. Codex Adversarial Review 修订记录（v2）

- **F1（采纳）Euler inverse 映射修正**：`as_euler('ZXY')` 返回 `[roll, elev, -heading]`，逆映射应为 `(angles[1], -angles[2], angles[0])`。v1 写成 `(angles[1], -angles[0], angles[2])` 会在 heading+roll 同时非零时交换两者。已用真机 fixture roundtrip 验证修正正确性。
- **F2（采纳）FOV formula 方向修正**：`zoom = target_focal / baseline_focal`（wide FOV → zoom < 1，narrow → zoom > 1）。v1 fixture 的 note 写成了 `baseline / target` 反了。已修正 `fov_samples.json` 和 `convention_discovery.json`。
- **F3（采纳）verify 升级为两级**：Level 1（keyframe 持久化）只能证明 sequence 写入正确；Level 2（VC world pose）通过 `gototime` + 独立 execute 读 `vc.world.getTranslation()` 验证 VC 实际输出。能检出 target 绑定失败、Euler 公式错误等 Level 1 盲区。
- **F4（确认）旧测试清理**：spec §3.1/3.2 已明确列出所有需要删除/迁移的测试，包括 `solve_convention` imports 和 `fov`→`zoom` 断言变更。

---

## 附录：真机 fixture 文件

| 文件 | 内容 | 用途 |
|------|------|------|
| `convention_discovery.json` | 完整的 Designer 约定参数 | 设计参考 |
| `convention_samples.json` | 8 组 (written, world) 对 | decompose 精度验证 |
| `fov_samples.json` | zoom→FOV 映射 + baseline 参数（v2 修正 formula 方向） | FOV 转换验证 |
| `probe_fields.json` | moduleType + 12 个字段名 | field_map 验证 |
| `key_type.json` | Linear key 类型（TBD） | P9 占位 |

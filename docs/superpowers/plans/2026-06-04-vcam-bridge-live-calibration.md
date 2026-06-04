# vcam-bridge 真机标定（Plan 3 / Live Handoff）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development / superpowers:executing-plans for the 💻 CODE tasks. 🖥️ OPERATOR tasks are a manual runbook run on the R33+ Designer hardware — they are NOT agent-executable.

**Goal:** 完成并验证 vcam-bridge 的真机标定闭环——补全 P3/P5/P7/P9 写状态探测、完整 `vcam probe`（产出 `config.yaml`）、`--verify`/P10 回读、UE5.7 golden——并固化为回归基线。

**核心策略（record → replay → validate）：** 因为这些代码的行为依赖真机回读的约定/字段名/枚举值，本计划用三段式：
1. 🖥️ **Phase A — 录制**：operator 在真机上跑现有只读 probe + 写已知 pose 读回 VC pose，把原始 `/execute` 响应**录成 fixtures**（`tests/fixtures/live/*.json`）。
2. 💻 **Phase B — 实现**：用 Phase A 的 fixtures 经 `FakeTransport` **回放**做离线 TDD，补全写状态探测、完整 probe 编排、`--verify`、golden。**这一步把真机依赖代码变成可单测代码。**
3. 🖥️ **Phase C — 真机验证**：跑补全后的 `vcam probe` → `config.yaml`，`vcam convert --verify` 端到端，跑 golden，冻结基线。

**前置：** 一台 R33+ Designer（新 VC 工作流，`enableLegacyVirtualCameraWorkflow` 期望 OFF）、一个绑定到目标 Virtual Camera 的 **scratch** AnimateCameraControl 层、本机 Blender、一个已知 UE5.7 Sequencer 导出的相机 FBX。

参照：spec `docs/superpowers/specs/2026-06-03-vcam-bridge-design.md` §5.7/§6（探测套件 + §6.0 探测安全）；已实现的 `transform/convention.py`(solve_convention)、`transform/register.py`(umeyama)、`designer/probe.py`、`designer/client.py`、`designer/inject.py`。

---

## 文件结构（本计划新增/修改）

```
src/vcam_bridge/designer/probe.py     # 修改：补 P0/P3/P4/P5/P7/P9 写状态脚本 + run_full_probe -> Calibration
src/vcam_bridge/designer/inject.py    # 修改：verify_keys()（P10 全 beat 回读 + VC pose 抽样）
src/vcam_bridge/cli/commands/probe.py # 修改：run_probe 调 run_full_probe，写 config.yaml
src/vcam_bridge/cli/commands/convert.py # 修改：convert_live 支持 verify=True
src/vcam_bridge/cli/main.py           # 修改：重新加 convert --verify（现在已实现）
tests/fixtures/live/                   # 新增：录制的真机响应（probe_fields/convention_samples/fov_samples/key_type）
tests/fixtures/golden/                 # 新增：golden FBX + expected 参数
tests/test_probe_full.py               # 新增：用 fixtures 回放单测完整 probe
tests/test_verify.py                   # 新增：P10 verify 通过/超容差用例
tests/integration/test_golden.py       # 新增：golden 端到端（Blender + 标定 config）
```

---

## Phase A — 🖥️ OPERATOR 录制（在 R33+ Designer 上手动运行）

> 目的：把真机回读录成 fixtures，供 Phase B 离线回放。**不写 production 层**——全部在 scratch 层（§6.0）。每步把 `--output json` 的**完整信封**存盘。

- [ ] **A1 — 连通 + 版本 + legacy flag（P0）**
  在能连到 Designer 的机器上：
  ```bash
  vcam probe --director <host:port> --probe-layer-uid <scratch-acc-uid> --output json | tee tests/fixtures/live/probe_fields.json
  ```
  另用 `/execute` 读 `enableLegacyVirtualCameraWorkflow`（experimental option）并记下：
  ```bash
  printf '%s' '{"script":"import json\nreturn json.dumps(bool(d3.experimentalOption(\"enableLegacyVirtualCameraWorkflow\")))"}' \
    | curl -s -X POST http://<host:port>/api/session/python/execute -H 'Content-Type: application/json' -d @- | tee tests/fixtures/live/legacy_flag.json
  ```
  **通过判据：** 版本 ≥ R33；`probe_fields.json` 的 `data.module_type` 非空、`data.field_names` 含 pivot/rotation/distance/FOV/coordinate-system/zoom-scale 对应项。记录这些 **decorated 名**——它们是 Phase B 写状态脚本的字段名来源（不再靠 KB label 猜）。

- [ ] **A2 — 录制 convention 样本（P4/P5：写已知 pose → 读 VC world pose）**
  用下方 operator 脚本（占位字段名换成 A1 记录的真名）向 scratch 层写 ≥6 个非退化 (pivot, rot, dist) 已知值，每次读回 VC world position + rotation_matrix。把每对 `{written, world}` 汇成数组存 `tests/fixtures/live/convention_samples.json`（schema 对齐 `transform/convention.solve_convention` 的输入：`[{"written":{"pivot","rotation","distance"},"world":{"position","rotation_matrix"}}]`）。
  > 录制脚本骨架（operator 按 A1 字段名填充并经 `/execute` 运行；务必先 snapshot scratch 层、结束 restore，见 §6.0）：
  > 对每个样本：`findSequence(<pivot.x名>).sequence.setFloat(t, vx)` …（pivot xyz / rotation xyz / distance）→ 触发求值 → 读 VC `worldPosition`/`worldRotation`（A 步确认读法，P4）→ `json.dumps({"written":..., "world":...})`。
  **通过判据：** ≥6 条非共线样本；VC world pose 可读（若不可读，记录降级方案：用 stage visualiser 数值人工读）。

- [ ] **A3 — 录制 FOV 样本（P7）**
  向 scratch 层写若干已知 `Field of view` 值，读回 VC 实际 frustum/FOV。存 `tests/fixtures/live/fov_samples.json`：`[{"written_fov":N,"world_fov_h":M,"world_fov_v":K}]`。同时确认驱动的是 **global FOV**（非 zoom scale），zoom scale 中性值。
  **通过判据：** 能判定 Designer `Field of view` 是水平还是垂直（先验：水平）。

- [ ] **A4 — 录制 key 类型（P9）**
  写一对 keyframe，读回其插值/类型枚举，确定 Linear 枚举值与"setFloat 后设 Linear"的确切 API（`keyseq.insert(i,t,key_type)` 或写后改 `key(i).type`）。存 `tests/fixtures/live/key_type.json`：`{"linear_enum":<value>, "set_api":"<notes>"}`。

- [ ] **A5 — 准备 golden**
  导出一个已知 UE5.7 Sequencer 相机 FBX（直线 dolly + pan + FOV 推拉，10–30 帧）→ `tests/fixtures/golden/golden.fbx`。**暂不**算 expected（Phase B 标定出 config 后再算并回填 `tests/fixtures/golden/expected.json`）。

---

## Phase B — 💻 CODE（离线 TDD，用 Phase A 的 fixtures 回放）

> 每个 task 走 TDD：先写用 fixture 的失败测试 → 实现 → 绿 → commit（commit 尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`）。

### Task B1: 完整 probe 编排 → Calibration（用 convention/fov/key fixtures 回放）

**Files:** Modify `src/vcam_bridge/designer/probe.py`; Test `tests/test_probe_full.py`

- [ ] **Step 1: 失败测试 `tests/test_probe_full.py`**
```python
import json
from pathlib import Path
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.probe import build_calibration

FIX = Path("tests/fixtures/live")


def test_build_calibration_from_recorded_samples():
    samples = json.loads((FIX / "convention_samples.json").read_text())
    fov = json.loads((FIX / "fov_samples.json").read_text())
    key = json.loads((FIX / "key_type.json").read_text())
    cal = build_calibration(convention_samples=samples, fov_samples=fov, key_type=key,
                            module_type="AnimateCameraControl",
                            field_names=json.loads((FIX / "probe_fields.json").read_text())["data"]["field_names"])
    assert cal.forward_axis in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")
    assert cal.euler_order
    assert cal.M_ue2dis is not None and len(cal.M_ue2dis) == 4
    assert cal.fov_axis in ("horizontal", "vertical")
```
> 注：Phase A 完成前，先放一份**合成的** `convention_samples.json` 等（用已知约定生成，见 §合成 fixture）让本测试能先跑通；真机录制就绪后替换为真数据，断言不变。

- [ ] **Step 2-4: 实现 `build_calibration` + run RED→GREEN**
在 `probe.py` 加（复用已实现的 `solve_convention` + `umeyama`）：
```python
import numpy as np
from vcam_bridge.transform.convention import solve_convention
from vcam_bridge.transform.register import umeyama
from vcam_bridge.transform.fov import h_to_v
from vcam_bridge.domain.models import Calibration


def build_calibration(*, convention_samples, fov_samples, key_type, module_type, field_names):
    conv = solve_convention(convention_samples)
    src = np.array([s["written"]["pivot"] for s in convention_samples], dtype=float)
    dst = np.array([s["world"]["position"] for s in convention_samples], dtype=float)
    M = umeyama(src, dst)
    # FOV axis: compare written vs read horizontal/vertical
    fov_axis = "horizontal"
    for f in fov_samples:
        if abs(f.get("world_fov_v", f["written_fov"]) - f["written_fov"]) < abs(f.get("world_fov_h", f["written_fov"]) - f["written_fov"]):
            fov_axis = "vertical"
            break
    return Calibration(module_type=module_type, forward_axis=conv["forward_axis"],
                       euler_order=conv["euler_order"], fov_axis=fov_axis,
                       linear_key_type=key_type.get("linear_enum"),
                       M_ue2dis=M.tolist())
```
Run: `uv run pytest tests/test_probe_full.py -q` → PASS.

- [ ] **Step 5: Commit** `feat: build_calibration from probe samples (convention+umeyama+fov+key)`

### Task B2: `config.yaml` 写出 + `vcam probe` 接线

**Files:** Modify `cli/commands/probe.py`, add a `Config`/`Calibration` YAML dump helper; Test extend `test_probe_full.py`

- [ ] **Step 1-4:** 实现 `run_full_probe(client, probe_layer_uid, vc_uid) -> Calibration`（跑 A 步的写状态脚本——字段名取自 P2/A1）+ `write_calibration(cal, path)`（pydantic `model_dump` → yaml）。`cli/commands/probe.py:run_probe` 改为：连真机 → run_full_probe → write `config.yaml` → 返回 `{"calibration_written": path, "convention": {...}}`。用 FakeTransport 回放 A 步录制的 `/execute` 响应做单测（断言写出的 yaml 能被 `load_config` 读回且 `M_ue2dis` 为 4x4）。
- [ ] **Step 5: Commit** `feat: vcam probe runs full P-series and writes config.yaml`

### Task B3: `--verify` / P10 回读

**Files:** Modify `designer/inject.py`(加 `verify_keys`)、`cli/commands/convert.py`(convert_live verify 分支)、`cli/main.py`(重加 `--verify`); Test `tests/test_verify.py`

- [ ] **Step 1: 失败测试 `tests/test_verify.py`**
```python
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import verify_keys
from vcam_bridge.domain.errors import VerifyToleranceError
import pytest


def _ok(rv):
    return {"status": {"code": 0}, "returnValue": rv, "d3Log": "", "pythonLog": ""}


def test_verify_passes_within_tolerance():
    # script returns max abs error per field; all within tol
    ft = FakeTransport(execute_responses=[_ok('{"max_pos_err": 0.0005, "max_rot_err": 0.01, "max_fov_err": 0.01}')])
    c = DesignerClient(ft, "localhost")
    report = verify_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=[{"t_sec": 0, "values": {"fov": 60.0}}],
                         start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_fov=0.05)
    assert report["ok"] is True


def test_verify_raises_over_tolerance():
    ft = FakeTransport(execute_responses=[_ok('{"max_pos_err": 0.5, "max_rot_err": 0.01, "max_fov_err": 0.01}')])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(VerifyToleranceError):
        verify_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=[{"t_sec": 0, "values": {"fov": 60.0}}],
                    start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_fov=0.05)
```
- [ ] **Step 2-4:** 实现 `verify_keys`：生成一段 Py2.7 回读脚本（对每个写入的 (field, beat) `fseq.eval(beat,default)` 比对期望值，算 max 误差；并抽样读 VC world pose 比对），`client.execute` 跑，超 `tol_*` 抛 `VerifyToleranceError`(exit 11)。`convert_live(..., verify=False)` 加：注入后若 verify 则调 `verify_keys` 并把 report 放进返回 data。`main.py` 重新加 `convert --verify`，live 分支把 `verify=args.verify` 传入。Run → GREEN。
- [ ] **Step 5: Commit** `feat: --verify P10 readback (all-beat field eval + VC pose) -> exit 11`

### Task B4: golden 端到端（Blender + 标定 config）

**Files:** Test `tests/integration/test_golden.py`

- [ ] **Step 1-4:** 实现 `tests/integration/test_golden.py`（`@pytest.mark.integration`）：用 `tests/fixtures/golden/golden.fbx` + Phase C 标定出的 `tests/fixtures/golden/calib.yaml` → `convert_dry_run(golden.fbx, config=load_config(calib.yaml), ...)` → 断言每帧 `keyframes` 的 pivot/rot/dist/fov ≈ `expected.json`（tol 由 spec）。Run（需本机 Blender）→ GREEN（expected.json 在 Phase C 回填后才有意义；在此之前 `pytest.skip("golden expected not yet recorded")` 占位）。
- [ ] **Step 5: Commit** `test: golden FBX -> ACC params regression (skipped until expected recorded)`

### 合成 fixture（让 Phase B 在真机录制前就能 TDD）
在写真机 fixtures 前，先用已知约定生成合成版放入 `tests/fixtures/live/`（用 `transform.rotation`/`decompose` 正向生成 convention_samples，fov_samples 用恒等，key_type 占位）。Phase A 录制就绪后**替换为真数据，B 系列断言不变**——这就是 record→replay 的价值：代码先成型并单测，真数据一到即验证。

---

## Phase C — 🖥️ OPERATOR 真机验证（在 R33+ Designer 上）

- [ ] **C1 — 真跑 probe 标定**：`vcam probe --director <host:port> --probe-layer-uid <scratch> --vc-uid <vc> --output json` → 写出真 `config.yaml`。通过判据：convention-lock `pos_error < 1mm`、`rot_error < 0.05°` 且最优候选与次优明显拉开；`M_ue2dis` scale ≈ 0.01。把真响应回填覆盖 `tests/fixtures/live/*`（替换合成版），重跑 Phase B 单测确认仍绿。

- [ ] **C2 — 端到端注入 + verify**：
  ```bash
  vcam convert --fbx tests/fixtures/golden/golden.fbx --target-uid <acc> --vc-uid <vc> \
    --director <host:port> --config config.yaml --dry-run --output json     # 预览 plan
  vcam convert --fbx ... --target-uid <acc> --vc-uid <vc> --director <host:port> \
    --config config.yaml --yes --verify --output json                       # 注入 + P10
  ```
  通过判据：`--verify` 返回 `data.verify.ok==true`（max 平移<1mm、角<0.05°、FOV<0.05°）；exit 0。超容差则 exit 11 + 误差报告。

- [ ] **C3 — 固化 golden 基线**：用 C1 的 config 离线算 golden 的 expected 参数 → `tests/fixtures/golden/expected.json`，去掉 B4 的 skip，`uv run pytest -m integration` 全绿。把 `config.yaml` + `tests/fixtures/` 作为该 stage 的回归基线提交。

---

## 风险 / 注记
- **写状态探测安全（§6.0）**：A2/A3/C1 全部在 scratch 层 + 写前 snapshot / `finally` restore；有既有 keyframe 的层默认拒绝（`--allow-destructive-probe`）。
- **字段名来源**：B 系列的写状态脚本字段名一律取自 A1 录制的 decorated 名（不靠 KB label 猜）；合成 fixture 仅用于让代码先成型。
- **legacy 分支**：若 A1 显示 `enableLegacyVirtualCameraWorkflow=ON`，字段集不同——按 A1 实测字段名走，convention/umeyama/verify 逻辑不变。
- **VC world pose 不可读**：A2 若读不到 VC world pose，降级为 stage visualiser 人工数值；B1 的 solve_convention 改用人工录入样本，逻辑不变。

---

## Self-Review
- **Spec 覆盖**：§5.7 P10→B3/C2 ✓；§6 P0–P9→A1/A2/A3/A4 + B1/B2 ✓；§6.0 安全→风险注记 + A/C 步骤 ✓；golden→A5/B4/C3 ✓。
- **占位符**：B 系列代码完整（复用已实现的 solve_convention/umeyama/fov）；真机依赖以 **录制 fixture + 合成占位** 显式处理，非 vague TODO。`expected.json`/真 fixtures 的"待录制"是有意的 record 步骤，已在 A5/C3 明确。
- **类型一致**：`build_calibration`/`run_full_probe` 产 `Calibration`(已存在模型)；`verify_keys` 用 `VerifyToleranceError`(exit 11, 已存在)；fixtures schema 对齐 `solve_convention` 输入与 `inject` 的 keys 形状。

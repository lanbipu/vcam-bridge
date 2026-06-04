# vcam-bridge CLI 修复实施计划 (v2 — 含 Codex adversarial review 采纳项)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 vcam-bridge 的"对话式全-CLI"成立——层和相机都能报名字（无需十六进制 uid）、macOS 全程可跑、注入正确性可信、**写真机前不静默破坏/误判**。

**Architecture:** 沿用已落地的 `--target-name`（层名→uid 现场解析）模式，对称补齐相机侧（`--camera-name`），把 `--curl` 提升为全局 transport 开关；并修复 Codex review 发现的两处 live-write 安全/正确性洞。改动只动组合根（`cli/`）与 designer 适配层，domain/transform 不碰。

**Tech Stack:** Python 3.11，argparse，pydantic v2，pytest + FakeTransport（不触网），Disguise Py2.7 `/execute` API（curl/requests 双 transport）。

**v2 变更**：纳入 Codex adversarial review 的 4 条采纳项 → 新增 Task 6（coord 非破坏化）、Task 7（aspect/vc-not-found fail-safe）；修订 Task 3（vc.list 向后兼容别名）；Task 9 标注 Codex 印证。

---

## 背景：本计划之前已完成的事（你另一 session，working tree 未提交）

- **ACC 枚举精确匹配**（`designer/targets.py`）：`_module_name()` 用 `_MODULE_RE` 提 `_blipValue(NAME)`，`list_acc_layers` 过滤 `== "AnimateCamera"` → 排除 Preset(`AnimateCamera2`)。过滤在 Python 端做，规避 Py2.7 脚本 C++ 异常穿透。
- **`--target-name`**（`cli/main.py:121-138`）：`resolve_layer_uid` 名→uid 消歧（0→`NotFoundError`，多→`ConfigError`），现场不缓存；解析在 `--curl` 时用 `CurlTransport`。
- **`--target-uid` 改 `default=None`**（运行时校验"uid/name 二选一"）。

## 实测约束（已在 lanPC Disguise 验证）

- macOS 下 `requests` 被本地网络策略拦死（`No route to host`）；`curl` 可用 → 所有连真机的命令必须能走 `--curl`。
- d3 `Camera` 无 `.name`；名 = `str(cam.path)` 末段去 `.apx`（`objects/camera/live cam 1.apx`→`live cam 1`），`description` 备选；虚拟判定用 `type(cam).__name__` 含 `Virtual`。
- d3 `Layer` 无 `.sequences`；字段枚举用 `layer.fields`（`str(fs)` 得装饰名）。
- `KeySequence.setFloat(beat,val)` 是 **replace-at-beat**（同 take 重跑 nKeys 不变，幂等）→ `--overwrite` 仅"换不同长度/起点 take"才需要，降级到批次 C。
- Py2.7 `/execute` 里 C++ 异常穿透 Python `try/except` → 脚本只读安全属性、过滤/派生放 Python 端。

## Codex review 采纳项（v2 新增/修订的依据）

1. **[high]** `_SET_TARGET_SCRIPT` 无条件 `stripToFirstKey()` 掉 `virtual camera coordinates` → 若该字段有多键动画会被静默抹平 → **Task 6**（坐标系=Global 是硬要求，故不删 strip，改"仅多键时 strip 且上报"）。
2. **[high]** `_read_camera_aspect` 吞所有异常回退 16:9，且坏 `--vc-uid` 被 `_SET_TARGET_SCRIPT` 的 `ok:True` 掩盖 → **Task 7**（vc-not-found 硬失败 + 暴露 `aspect_source`/`warnings`）。
3. **[medium]** solo 下 `verify.ok=True` 误导 → 已在 **Task 9**（`pose_verified` 标志）。
4. **[medium]** plan 把 `vc.list` 改名当兼容 → **Task 3 修订**（保留 `virtual_cameras` 废弃别名）。

---

## File Structure

| 文件 | 改动 |
|---|---|
| `src/vcam_bridge/cli/main.py` | `_transport(args)`；`--curl` 升全局；`--camera-name`；convert dispatch 相机名解析 |
| `src/vcam_bridge/designer/targets.py` | `_CAMERA_ENUM_SCRIPT`+`_camera_name`+`list_cameras`+`resolve_camera_uid`；废 `_VC_ENUM_SCRIPT`/`list_vcs` |
| `src/vcam_bridge/cli/commands/vc.py` | 改用 `list_cameras`，输出 `cameras`+`virtual_cameras`(别名) |
| `src/vcam_bridge/manifest.py` | `vc.list` 描述改"全部 stage 相机" |
| `src/vcam_bridge/designer/probe.py` | `_FIELD_DUMP` 用 `layer.fields` |
| `src/vcam_bridge/cli/commands/convert.py` | **Task6** coord 守卫；**Task7** vc-not-found 硬失败+aspect_source；**Task9** pose_verified；**Task10** fov_control 标签 |
| `src/vcam_bridge/designer/transport.py` | Protocol 加 `post_json` + 3 适配器 |
| `src/vcam_bridge/designer/inject.py` | `_gototime` 走 transport、不静默 |
| `src/vcam_bridge/designer/codegen.py` | `--overwrite` 首-chunk strip（批次 C，降级） |

---

# 批次 A — 补齐对话式全-CLI

## Task 1: `_transport(args)` 助手 + `--curl` 升全局

**Files:** Modify `src/vcam_bridge/cli/main.py`；Test `tests/test_cli_transport_select.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_transport_select.py
from argparse import Namespace
import vcam_bridge.cli.main as m
from vcam_bridge.designer.transport import CurlTransport, RequestsTransport

def test_transport_helper_picks_curl_when_flag_set():
    assert isinstance(m._transport(Namespace(curl=True)), CurlTransport)
    assert isinstance(m._transport(Namespace(curl=False)), RequestsTransport)
    assert isinstance(m._transport(Namespace()), RequestsTransport)
```

- [ ] **Step 2: 跑测试确认失败** — Run `pytest tests/test_cli_transport_select.py -v` → FAIL（`_transport` 不存在）
- [ ] **Step 3: 实现** — `_add_global` 加 `--curl`（走 suppress 双挂）：
```python
    parser.add_argument("--curl", action="store_true", default=d(False),
                        help="use curl subprocess instead of requests (macOS workaround)")
```
删 convert 子命令上原 `--curl`（避免重复）。加助手：
```python
def _transport(args):
    from vcam_bridge.designer.transport import CurlTransport, RequestsTransport
    return CurlTransport() if getattr(args, "curl", False) else RequestsTransport()
```
`_dispatch` 里 targets.list/vc.list/probe 三处 `RequestsTransport()` 与 convert 的 transport 构造、target-name 解析块统一改 `_transport(args)`。
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cli_transport_select.py -v && pytest -q` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/cli/main.py tests/test_cli_transport_select.py
git commit -m "feat: --curl 升全局 + _transport(args)；targets/vc/probe 可在 macOS 走 curl"
```

---

## Task 2: 相机枚举修复 + `resolve_camera_uid`

**Files:** Modify `src/vcam_bridge/designer/targets.py`；Test `tests/test_cameras.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cameras.py
import json, pytest
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.targets import list_cameras, resolve_camera_uid, _CAMERA_ENUM_SCRIPT
from vcam_bridge.domain.errors import NotFoundError, ConfigError

_ROWS = [
    ["0xaa1e1c34ac2ad525", "objects/camera/live cam 1.apx", "live cam 1", "Camera"],
    ["0x8590ade039a8af4", "objects/camera/live cam 2.apx", "live cam 2", "Camera"],
    ["0xd3ebbf1e5336711c", "objects/virtualcamera/virtual cam 1.apx", "virtual cam 1", "VirtualCamera"],
]
def _client(rows):
    ft = FakeTransport(execute_responses=[{"status": {"code": 0}, "returnValue": json.dumps(rows)}])
    return DesignerClient(ft, "h:80")

def test_list_cameras_includes_live_and_virtual_with_type():
    assert list_cameras(_client(_ROWS)) == [
        {"name": "live cam 1", "uid": "0xaa1e1c34ac2ad525", "type": "live"},
        {"name": "live cam 2", "uid": "0x8590ade039a8af4", "type": "live"},
        {"name": "virtual cam 1", "uid": "0xd3ebbf1e5336711c", "type": "virtual"}]

def test_enum_script_never_uses_broken_cam_name():
    assert "cam.name" not in _CAMERA_ENUM_SCRIPT
    assert "cam.path" in _CAMERA_ENUM_SCRIPT

def test_resolve_by_name_and_uid():
    cams = list_cameras(_client(_ROWS))
    assert resolve_camera_uid(cams, "live cam 1") == "0xaa1e1c34ac2ad525"
    assert resolve_camera_uid(cams, "0xAA1E1C34AC2AD525") == "0xaa1e1c34ac2ad525"

def test_resolve_unknown_and_ambiguous():
    cams = list_cameras(_client(_ROWS))
    with pytest.raises(NotFoundError):
        resolve_camera_uid(cams, "nope")
    dup = list_cameras(_client(_ROWS + [["0x999", "objects/camera/live cam 1.apx", "d", "Camera"]]))
    with pytest.raises(ConfigError):
        resolve_camera_uid(dup, "live cam 1")
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/test_cameras.py -v` → FAIL（`list_cameras` 不存在）
- [ ] **Step 3: 实现** — `targets.py` 删 `_VC_ENUM_SCRIPT`/`list_vcs`，加：
```python
_CAMERA_ENUM_SCRIPT = '''
import json
out = []
for cam in state.stage.cameras:
    out.append(["0x%x" % cam.uid, str(cam.path), str(getattr(cam, "description", "")), str(type(cam).__name__)])
return json.dumps(out)
'''

def _camera_name(path_str: str, description: str) -> str:
    base = path_str.rsplit("/", 1)[-1]
    if base.endswith(".apx"):
        base = base[:-4]
    return base or description

def list_cameras(client: DesignerClient) -> list[dict]:
    rows = client.execute(_CAMERA_ENUM_SCRIPT).return_value or []
    return [{"name": _camera_name(p, d), "uid": u,
             "type": "virtual" if "Virtual" in t else "live"} for u, p, d, t in rows]

def resolve_camera_uid(cameras: list[dict], selector: str) -> str:
    s = selector.strip()
    if s.lower().startswith("0x"):
        for cam in cameras:
            if cam["uid"].lower() == s.lower():
                return cam["uid"]
        raise NotFoundError(f"no camera with uid {s}", details={"available_uids": [c["uid"] for c in cameras]})
    matches = [cam for cam in cameras if cam["name"] == s]
    if len(matches) == 1:
        return matches[0]["uid"]
    if not matches:
        raise NotFoundError(f"no camera named {s!r}",
                            details={"available": [{"name": c["name"], "type": c["type"]} for c in cameras]})
    raise ConfigError(f"ambiguous camera name {s!r}: {len(matches)} matches; pass --vc-uid instead",
                      details={"matches": [{"name": c["name"], "uid": c["uid"]} for c in matches]})
```

- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cameras.py -v` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/designer/targets.py tests/test_cameras.py
git commit -m "feat: list_cameras 列全部相机+type，名取 path 末段；resolve_camera_uid 消歧；废除 cam.name 枚举"
```

---

## Task 3: `vc list` 改用 `list_cameras`（**保留 `virtual_cameras` 废弃别名 — Codex finding #4**）

**Files:** Modify `src/vcam_bridge/cli/commands/vc.py`、`src/vcam_bridge/manifest.py`；Test 追加 `tests/test_cameras.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cameras.py 追加
from vcam_bridge.cli.commands import vc as vc_cmd

def test_vc_list_emits_cameras_and_backcompat_alias():
    import json
    from vcam_bridge.designer.transport import FakeTransport
    ft = FakeTransport(execute_responses=[{"status": {"code": 0}, "returnValue": json.dumps([
        ["0xaa", "objects/camera/live cam 1.apx", "live cam 1", "Camera"],
        ["0xd3", "objects/virtualcamera/virtual cam 1.apx", "virtual cam 1", "VirtualCamera"]])}])
    op, data = vc_cmd.list_vcams(ft, host="h:80")
    assert op == "vc.list"
    assert data["cameras"] == [
        {"name": "live cam 1", "uid": "0xaa", "type": "live"},
        {"name": "virtual cam 1", "uid": "0xd3", "type": "virtual"}]
    # 向后兼容：旧 key 仍在，但只含虚拟子集（语义不变）
    assert data["virtual_cameras"] == [{"name": "virtual cam 1", "uid": "0xd3", "type": "virtual"}]
```

- [ ] **Step 2: 跑测试确认失败** — FAIL（旧返回 `{"virtual_cameras": list_vcs(...)}`）
- [ ] **Step 3: 实现** — `cli/commands/vc.py`：
```python
from vcam_bridge.designer.targets import list_cameras

def list_vcams(transport, *, host: str):
    client = DesignerClient(transport, host)
    client.resolve_routing()
    cams = list_cameras(client)
    return "vc.list", {
        "cameras": cams,                                                   # 新：全部相机
        "virtual_cameras": [c for c in cams if c["type"] == "virtual"],    # 废弃别名，保留一版
    }
```
`manifest.py`：`vc.list` 描述改 `"Enumerate stage cameras (live + virtual); 'virtual_cameras' 为废弃别名"`。同步 `test_manifest.py`/`test_cli_consistency.py` 旧断言。
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cameras.py -v && pytest -q` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/cli/commands/vc.py src/vcam_bridge/manifest.py tests/
git commit -m "feat: vc list 返回 cameras(全)+type；保留 virtual_cameras 废弃别名(向后兼容)"
```

---

## Task 4: `--camera-name`（convert 内现场解析，镜像 --target-name）

**Files:** Modify `src/vcam_bridge/cli/main.py`；Test `tests/test_cli_camera_name.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_camera_name.py
import pytest
import vcam_bridge.cli.main as m
from vcam_bridge.domain.errors import ConfigError

def test_camera_name_without_director_errors(tmp_path):
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--camera-name", "live cam 1", "--yes"])
    with pytest.raises(ConfigError):
        m._dispatch(args)

def test_camera_name_resolves_to_uid(monkeypatch, tmp_path):
    monkeypatch.setattr("vcam_bridge.designer.targets.list_cameras",
                        lambda c: [{"name": "live cam 1", "uid": "0xaa", "type": "live"}])
    monkeypatch.setattr("vcam_bridge.designer.client.DesignerClient.resolve_routing", lambda self: None)
    captured = {}
    monkeypatch.setattr("vcam_bridge.cli.commands.convert.convert_live",
                        lambda transport, **kw: (captured.update(kw), ("convert", {"written": 0}))[1])
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--camera-name", "live cam 1",
         "--director", "h:80", "--yes", "--curl"])
    m._dispatch(args)
    assert captured["vc_uid"] == "0xaa"
```

- [ ] **Step 2: 跑测试确认失败** — FAIL（`--camera-name` 不存在）
- [ ] **Step 3: 实现** — convert 子命令 `--vc-uid` 后加：
```python
    p_conv.add_argument("--camera-name", default=None,
                        help="目标相机名（替代 --vc-uid；经 --director 现场解析，含 live/virtual）")
```
`_dispatch` convert 分支，把 target-name 解析块替换为统一 client 复用 + 双解析：
```python
        from vcam_bridge.designer.client import DesignerClient
        from vcam_bridge.designer.targets import (list_acc_layers, resolve_layer_uid,
                                                  list_cameras, resolve_camera_uid)
        need_client = (not args.target_uid and args.target_name) or (not args.vc_uid and args.camera_name)
        _client = None
        if need_client:
            if not args.director:
                raise ConfigError("--target-name/--camera-name require --director to resolve names")
            _client = DesignerClient(_transport(args), args.director)
            _client.resolve_routing()
        layer_uid = args.target_uid
        if not layer_uid:
            if not args.target_name:
                raise ConfigError("one of --target-uid / --target-name is required")
            layer_uid = resolve_layer_uid(list_acc_layers(_client), args.target_name)
        vc_uid = args.vc_uid
        if not vc_uid and args.camera_name:
            vc_uid = resolve_camera_uid(list_cameras(_client), args.camera_name)
```
live 路径传 `vc_uid`（非 `args.vc_uid`），守卫改：
```python
        if not vc_uid:
            raise ConfigError("--vc-uid or --camera-name is required for live injection")
```
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cli_camera_name.py -v && pytest -q` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/cli/main.py tests/test_cli_camera_name.py
git commit -m "feat: --camera-name 现场解析相机名→uid（镜像 --target-name，复用 client，走 --curl）"
```
- [ ] **Step 6: 真机冒烟（手动）** — `vcam convert --fbx … --target-name "AnimateCameraControl 2" --camera-name "live cam 1" --director 192.168.10.20:80 --curl --yes --verify -o json` → `written`>0、`verify.ok`、全程零 hex。

---

## Task 5: `vcam probe` 字段枚举改 `layer.fields`

**Files:** Modify `src/vcam_bridge/designer/probe.py`；Test `tests/test_probe.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_probe.py 追加
from vcam_bridge.designer.probe import _FIELD_DUMP
def test_field_dump_uses_layer_fields_not_sequences():
    assert ".sequences" not in _FIELD_DUMP
    assert "target.fields" in _FIELD_DUMP
```
- [ ] **Step 2: 跑测试确认失败** — FAIL（当前含 `target.sequences`）
- [ ] **Step 3: 实现** — `_FIELD_DUMP` 循环体改 `for fs in target.fields:` → `out.append(str(fs))`。
- [ ] **Step 4: 跑测试 + 真机冒烟 + Commit**
```bash
.venv/bin/vcam probe --director 192.168.10.20:80 --curl --probe-layer-uid 0x514cd26872da7fde -o json
# field_names 含 camera pivot.x/.../view angle/virtual camera zoom/camera/virtual camera coordinates
git add src/vcam_bridge/designer/probe.py tests/test_probe.py
git commit -m "fix: probe 字段枚举用 layer.fields（d3 Layer 无 .sequences）"
```

---

# 批次 B — 安全 / 正确性（含 Codex review 采纳项）

## Task 6: coord 守卫 — `virtual camera coordinates` 仅多键时 strip 且上报（**Codex finding #1**）

> 坐标系=Global 是 1:1 复现 UE 的硬要求（axis-doc §6），**不删 strip**；但改为非破坏-by-default：单键直接覆盖（常态零损），多键才 strip 并在 note 上报抹掉了几个键，去掉静默数据丢失。

**Files:** Modify `src/vcam_bridge/cli/commands/convert.py`（`_SET_TARGET_SCRIPT` coord 块）；Test `tests/test_cli_convert.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_cli_convert.py 追加
from vcam_bridge.cli.commands.convert import _SET_TARGET_SCRIPT
def test_coord_strip_is_guarded_by_keycount():
    s = _SET_TARGET_SCRIPT
    assert "nKeys()" in s                      # 写前查键数
    assert "stripToFirstKey" in s
    assert "coord-keys-collapsed" in s         # 多键时上报，非静默
```
- [ ] **Step 2: 跑测试确认失败** — FAIL（当前无条件 strip，无 nKeys 守卫）
- [ ] **Step 3: 实现** — `_SET_TARGET_SCRIPT` 的 coord 块改：
```python
try:
    cs = layer.findSequence("virtual camera coordinates")
    if cs is not None:
        n_before = cs.sequence.nKeys()
        if n_before > 1:
            cs.sequence.stripToFirstKey()      # 仅多键(异常情形)才清，避免抹掉单键常态
        cs.disableSequencing = True
        cs.sequence.setFloat(layer.tStart, 0.0)   # 强制 Global=0（设计硬要求）
        note.append("coord-global-set")
        if n_before > 1:
            note.append("coord-keys-collapsed:%d" % n_before)
except Exception as e:
    note.append("coord-skipped:" + str(e))
```
（可选增强：`convert_live` 检测 setup.note 里有 `coord-keys-collapsed:` 时，往结果 `warnings` 追加一条，见 Task 7 的 warnings 通道。）
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cli_convert.py -v` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_convert.py
git commit -m "fix: coord=Global 仅多键时 strip 并上报 collapse 数（消除静默坐标动画丢失，Codex#1）"
```

---

## Task 7: vc-not-found 硬失败 + 暴露 `aspect_source`/`warnings`（**Codex finding #2**）

> 坏 `--vc-uid` 不能再被 `ok:True` 掩盖；aspect 读不到时不静默回退——暴露来源与告警，让 AI/用户能按数据分支。

**Files:** Modify `src/vcam_bridge/cli/commands/convert.py`（`convert_live`）；Test `tests/test_cli_live.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_cli_live.py 追加（沿用现有 convert_live FakeTransport 构造）
def test_convert_live_fails_when_camera_uid_not_found(...):
    # _SET_TARGET_SCRIPT 返回 ok:True 但 vc_found:False
    # 期望 convert_live 抛 ConfigError（不再静默注入到未绑定相机的层）
    import pytest
    from vcam_bridge.domain.errors import ConfigError
    with pytest.raises(ConfigError):
        convert_live(... vc_uid="0xdeadbeef" ...)

def test_convert_live_reports_aspect_source(...):
    # 正常路径：data['aspect_source'] in ('live','config-fallback')；回退时 warnings 非空
    op, data = convert_live(...)
    assert data["aspect_source"] in ("live", "config-fallback")
    assert "warnings" in data
```
- [ ] **Step 2: 跑测试确认失败** — FAIL（当前 vc_found:False 不报错；无 aspect_source/warnings）
- [ ] **Step 3: 实现** — `convert_live` 内，把 `setup` 检查与 aspect 读重排：
```python
    setup = client.execute(_SET_TARGET_SCRIPT % {"layer": layer_uid, "vc": vc_uid}).return_value or {}
    if not setup.get("ok"):
        raise PartialError("failed to set ACC camera target: %s" % setup.get("error", "unknown"), details=setup)
    if not setup.get("vc_found"):
        raise ConfigError("camera uid not found in stage: %s (check --vc-uid/--camera-name)" % vc_uid,
                          details={"vc_uid": vc_uid, "note": setup.get("note")})
    render_aspect = _read_camera_aspect(client, vc_uid)
    aspect_source = "live" if render_aspect else "config-fallback"
    warnings = []
    if render_aspect is None:
        warnings.append("render aspect not read from camera; FOV uses config aspect %.4f (wrong on non-16:9 output)"
                        % cal.aspect)
    if "coord-keys-collapsed" in " ".join(setup.get("note", [])):
        warnings.append("existing 'virtual camera coordinates' animation was collapsed to Global")
```
（`build_keyframes(..., aspect_override=render_aspect)` 保持原样。）返回 dict 追加 `"aspect_source": aspect_source, "warnings": warnings`。`ConfigError` 已 import；确认 `convert.py` 顶部 import 含 `ConfigError`（convert_live 现有 import 列表里加）。
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_cli_live.py -v` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_live.py
git commit -m "fix: convert_live 在相机 uid 找不到时硬失败 + 暴露 aspect_source/warnings（Codex#2）"
```

---

## Task 8: `_gototime` 走 transport、失败不静默（director 会话 world-pose）

**Files:** Modify `src/vcam_bridge/designer/transport.py`（Protocol+3 适配器加 `post_json`）、`src/vcam_bridge/designer/inject.py`；Test `tests/test_verify.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_verify.py 追加
def test_gototime_routes_through_transport():
    from vcam_bridge.designer.transport import FakeTransport
    from vcam_bridge.designer.client import DesignerClient
    from vcam_bridge.designer import inject
    ft = FakeTransport()
    inject._gototime(DesignerClient(ft, "h:80"), 2.5)
    assert ft.posted_json[-1] == ("h:80", "/api/session/transport/gototime", {"time": 2.5})
```
- [ ] **Step 2: 跑测试确认失败** — FAIL（`FakeTransport` 无 `posted_json`）
- [ ] **Step 3: 实现** — Protocol 加 `post_json(self, host, path, body, timeout_s=None) -> dict`；`RequestsTransport`/`CurlTransport` 实现（POST json，无 body 返 `{}`，失败抛 `ExternalError`）；`FakeTransport.__init__` 加 `self.posted_json=[]`、`post_json` 记录并返 `{}`。`inject.py` 删 `import requests as _requests`；`_gototime(client, t_sec)` 改 `client._t.post_json(client.host, "/api/session/transport/gototime", {"time": t_sec})`；`verify_world_pose` 内调用改 `_gototime(client, t_sec)`。失败现以 `ExternalError` 上抛（不再静默用陈旧读数）。
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/test_verify.py -v` → PASS
- [ ] **Step 5: Commit**
```bash
git add src/vcam_bridge/designer/transport.py src/vcam_bridge/designer/inject.py tests/test_verify.py
git commit -m "fix: gototime 走注入 transport（macOS curl 可用）且失败不静默"
```

---

## Task 9: solo verify 暴露 `pose_verified`（**Codex finding #3 独立印证**）

**Files:** Modify `src/vcam_bridge/cli/commands/convert.py`（verify 块）；Test `tests/test_cli_live.py`

- [ ] **Step 1: 写失败测试**
```python
# tests/test_cli_live.py solo verify 用例追加
    assert data["verify"]["pose_verified"] is False
    assert data["verify"]["level"] == "persistence-only"
```
- [ ] **Step 2: 跑测试确认失败** — FAIL（`KeyError: 'pose_verified'`）
- [ ] **Step 3: 实现** — solo 分支设 skip 后加 `verify_report["pose_verified"]=False; verify_report["level"]="persistence-only"`；非 solo 成功后加 `verify_report["pose_verified"]=True; verify_report["level"]="world-pose"`。
- [ ] **Step 4: 跑测试 + Commit**
```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_live.py
git commit -m "feat: verify 暴露 pose_verified/level，solo 明确仅 persistence-only（Codex#3）"
```

---

# 批次 C — 打磨

## Task 10: dry_run_plan `fov_control` 标签改真值

**Files:** Modify `src/vcam_bridge/cli/commands/convert.py:203`；Test `tests/test_cli_convert.py`

- [ ] **Step 1: 写失败测试** — `assert data["dry_run_plan"]["fov_control"] == "view_angle+zoom"`
- [ ] **Step 2: 跑测试确认失败** — FAIL（当前 `"zoom_scale"`）
- [ ] **Step 3: 实现** — `"fov_control": "zoom_scale",` → `"fov_control": "view_angle+zoom",`
- [ ] **Step 4: 跑测试 + Commit**
```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_convert.py
git commit -m "fix: dry_run_plan fov_control 标 view_angle+zoom（Live Camera 实为 view angle 驱动）"
```

---

## Task 11（可选/降级）: `--overwrite` 首-chunk 清键

> 已实测 `setFloat` replace-at-beat，同名同长 take 重跑天然幂等；`--overwrite` 仅"用更短/不同起点 take 覆盖更长旧动画"时才需要（否则旧帧 straggler 残留）。

**Files:** Modify `codegen.py`/`inject.py`/`convert.py`/`main.py`；Test `tests/test_inject.py`

- [ ] **Step 1-2: 测试** — `build_inject_script({...,"overwrite":True})` 含 `stripToFirstKey`、`overwrite:False` 不含。
- [ ] **Step 3: 实现** — INJECT_BODY 写循环前加 `if payload.get("overwrite"): for key in seqs: seqs[key].sequence.stripToFirstKey()`；`inject_keys` **仅首 chunk** 置 `overwrite=True`；`convert_live` 加 `overwrite=False` 参穿到 `inject_keys`；`main.py` 加 `--overwrite`。
- [ ] **Step 4: 测试 + Commit** — `git commit -m "feat: --overwrite 首-chunk stripToFirstKey（换不同长度 take 时避免 straggler）"`

---

## Self-Review

- **覆盖**：批次 A（transport/相机名/枚举/probe）解"发现阶段无法全 CLI"硬伤；批次 B（coord 守卫、vc-not-found/aspect、gototime、pose_verified）含 Codex 全部 4 条采纳项 + director 校验；批次 C 打磨。已完成项不重复建任务。
- **类型一致**：`list_cameras`/`resolve_camera_uid` 返回 `{name,uid,type}` 全程一致；`vc.list` envelope 含 `cameras`+`virtual_cameras`。
- **无占位**：每步给实际代码/命令/期望。`tests/test_cli_live.py`/`test_cli_convert.py` 以"沿用现有构造"标注（执行时套用同款 fixture）。
- **假绿测试对策**：Task 2/5/6 加脚本文本回归断言（`"cam.name" not in …`、`".sequences" not in …`、coord 守卫文本）；真机行为靠各 Task 的真机冒烟手动步覆盖。

## 风险（v2 已据 Codex 修订）

| 风险 | 缓解 |
|---|---|
| ~~vc.list 改名破坏下游~~ → **真 break（Codex#4）** | **Task 3 同时输出 `cameras`+`virtual_cameras`(废弃别名，仅虚拟子集)** → 旧消费者不破；别名延一版后再移除并在 CHANGELOG 标注 |
| coord 强制 Global 覆盖用户的 Relative 意图（Codex#1） | Task 6 单键零损；多键 strip 并 `coord-keys-collapsed` 上报 + warnings；如需更保守可改"冲突即 fail"（留作 reviewer 选项） |
| 坏 vc-uid/aspect 静默错 FOV（Codex#2） | Task 7 vc-not-found 硬失败 + `aspect_source`/`warnings` 暴露 |
| `cam.path` 末段去 `.apx` 对非 `.apx` 资源失效 | `_camera_name` 回退 `description`、再回退原 basename；真机冒烟核对 |
| `layer.fields` 在某些 d3 版本属性名不同 | Task 5 真机冒烟即时验证；失败回退 `findSequence` 候选探测 |
| `post_json` 改 Transport Protocol，FakeTransport 需同步 | Task 8 同 commit 改三适配器 + Fake |

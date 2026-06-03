# vcam-bridge 真机层（Plan 2）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 Plan 1 离线核心之上，实现 vcam-bridge 的真机层：Designer 连接（REST + solo/director 路由）、目标枚举、convention-lock、分块注入执行（超时回读续写）、P10 验证、P0–P9 探测编排、Blender 原生 FBX、Skill 包——**全部经依赖注入做到离线/本机可单测**（Designer 用 FakeTransport，FBX 用本机 Blender 真集成）。

**关键边界（执行者必读）：** 本计划只实现并**离线/本机单测**代码。需要 live R33+ Designer 的步骤（P0–P10 真机标定、端到端注入、UE5.7 golden、锁定 `config.yaml` 约定）**不在自动执行范围**，作为 §Live Handoff 交接，由 operator 在真机运行 `vcam probe` / `vcam convert --verify`。

**Architecture:** 沿用 Plan 1 分层。新增 `designer/transport.py`(Port: `Transport` 协议 + `RequestsTransport` 真实现 + `FakeTransport` 测试替身)、`designer/client.py`(DesignerClient：execute 解析/错误映射/行号-10/重试 + solo-director 路由)、`designer/targets.py`、`designer/inject.py`(分块+超时续写+验证)、`designer/probe.py`(P0–P9 编排)、`transform/convention.py`(convention-lock 求解)、`ingest/blender_fbx.py`+`blender_extract.py`。CLI 接入 `probe`/`targets list`/`vc list`/`convert`(live)。

**Tech Stack:** Plan 1 栈 + `requests`(真实 HTTP transport)。FBX 集成测试需本机 Blender（`/Applications/Blender.app/...`，已确认存在）。

参照 spec：`docs/superpowers/specs/2026-06-03-vcam-bridge-design.md`（v2）§5.1/5.2/5.4/5.5/5.7/6/7.6。

---

## 文件结构（本计划新增/修改）

```
src/vcam_bridge/
├── designer/
│   ├── transport.py     # 新增：Transport 协议 + RequestsTransport + FakeTransport
│   ├── client.py        # 新增：DesignerClient（execute/路由/错误/重试）
│   ├── targets.py       # 新增：枚举 tracks/ACC layers/VCs
│   ├── inject.py        # 新增：分块注入执行 + 超时续写 + 验证
│   └── probe.py         # 新增：P0–P9 编排（snapshot/restore/scratch）
├── transform/
│   └── convention.py    # 新增：convention-lock 求解（forward×euler×handed）
├── ingest/
│   ├── blender_fbx.py    # 新增：无头 Blender 子进程 wrapper（缓存/killpg/原子写）
│   └── blender_extract.py# 新增：bpy 提取（matrix_world+angle_x+fps+focus → CameraTrack）
└── cli/
    ├── main.py           # 修改：接 probe/targets/vc，convert live 路径
    └── commands/
        ├── targets.py    # 新增
        ├── vc.py         # 新增
        ├── probe.py      # 新增
        └── convert.py    # 修改：live 注入路径
.claude/skills/vcam-bridge/   # 新增：SKILL.md + reference/ + scripts/
tests/                        # 各模块对应单测 + Blender 集成测试
pyproject.toml                # 加 requests 依赖
```

---

## Task 1: 加 requests 依赖 + Transport 端口

**Files:**
- Modify: `pyproject.toml`
- Create: `src/vcam_bridge/designer/transport.py`
- Test: `tests/test_transport.py`

- [ ] **Step 1: pyproject 加 requests**

在 `[project] dependencies` 列表加一行 `"requests>=2.28",`（置于 `pyyaml` 之后）。然后 `uv pip install -e ".[dev]"` 重新同步。

- [ ] **Step 2: 写失败测试 `tests/test_transport.py`**

```python
from vcam_bridge.designer.transport import FakeTransport


def test_fake_transport_records_and_replies():
    ft = FakeTransport(
        execute_responses=[{"status": {"code": 0}, "returnValue": "\"ok\"", "d3Log": "", "pythonLog": ""}],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    resp = ft.post_execute("localhost", "print('x')")
    assert resp["returnValue"] == '"ok"'
    assert ft.executed[0]["script"] == "print('x')"
    assert ft.get_json("localhost", "/api/session/status/session")["isRunningSolo"] is True


def test_fake_transport_raises_when_exhausted():
    import pytest
    ft = FakeTransport(execute_responses=[])
    with pytest.raises(IndexError):
        ft.post_execute("localhost", "x")
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd vcam-bridge/.worktrees/vcam-bridge-live && uv run pytest tests/test_transport.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 4: 写 `src/vcam_bridge/designer/transport.py`**

```python
from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    """IO port: HTTP to a Designer Service/Session API. Adapters implement this."""

    def post_execute(self, host: str, script: str, module_name: str | None = None,
                     timeout_s: float | None = None) -> dict[str, Any]: ...

    def get_json(self, host: str, path: str, timeout_s: float | None = None) -> dict[str, Any]: ...


class RequestsTransport:
    """Real HTTP transport using a persistent requests.Session for connection reuse."""

    def __init__(self) -> None:
        import requests
        self._session = requests.Session()

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        body: dict[str, Any] = {"script": script}
        if module_name:
            body["moduleName"] = module_name
        r = self._session.post(f"http://{host}/api/session/python/execute", json=body, timeout=timeout_s)
        return r.json()

    def get_json(self, host, path, timeout_s=None):
        r = self._session.get(f"http://{host}{path}", timeout=timeout_s)
        return r.json()


class FakeTransport:
    """Test double. execute_responses are returned in order; json_responses keyed by path."""

    def __init__(self, execute_responses=None, json_responses=None):
        self._execute = list(execute_responses or [])
        self._json = dict(json_responses or {})
        self.executed: list[dict[str, Any]] = []
        self.idx = 0

    def post_execute(self, host, script, module_name=None, timeout_s=None):
        self.executed.append({"host": host, "script": script, "module_name": module_name})
        resp = self._execute[self.idx]   # IndexError when exhausted (test relies on this)
        self.idx += 1
        return resp

    def get_json(self, host, path, timeout_s=None):
        return self._json[path]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_transport.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/vcam_bridge/designer/transport.py tests/test_transport.py
git commit -m "feat: Transport port (requests + fake) for Designer HTTP"
```

---

## Task 2: DesignerClient（execute 解析 / solo-director 路由 / 错误映射 / 重试）

**Files:**
- Create: `src/vcam_bridge/designer/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: 写失败测试 `tests/test_client.py`**

```python
import pytest
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.domain.errors import ExternalError, DesignerTimeoutError


def _ok(rv="null"):
    return {"status": {"code": 0, "message": "", "details": []}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_execute_parses_return_value_json():
    ft = FakeTransport(execute_responses=[_ok('{"written": 3}')])
    c = DesignerClient(ft, "localhost")
    res = c.execute("...")
    assert res.return_value == {"written": 3}


def test_execute_null_returns_none():
    c = DesignerClient(FakeTransport(execute_responses=[_ok("null")]), "localhost")
    assert c.execute("...").return_value is None


def test_execute_error_maps_to_external_and_fixes_line_offset():
    err = {"status": {"code": 1, "message": "Error at line 12: NameError", "details": []},
           "d3Log": "", "pythonLog": "", "returnValue": "null"}
    c = DesignerClient(FakeTransport(execute_responses=[err]), "localhost")
    with pytest.raises(ExternalError) as ei:
        c.execute("...")
    assert "line 2" in ei.value.message   # 12 - 10 offset


def test_timeout_maps_to_designer_timeout():
    err = {"status": {"code": 1, "message": "TimeoutError: exceeded"}, "d3Log": "", "pythonLog": "", "returnValue": "null"}
    c = DesignerClient(FakeTransport(execute_responses=[err]), "localhost")
    with pytest.raises(DesignerTimeoutError):
        c.execute("...")


def test_resolve_routes_to_director_when_not_solo():
    ft = FakeTransport(json_responses={"/api/session/status/session":
                       {"isRunningSolo": False, "director": {"hostname": "10.0.0.9"}}})
    c = DesignerClient(ft, "localhost")
    c.resolve_routing()
    assert c.host == "10.0.0.9"


def test_resolve_stays_local_when_solo():
    ft = FakeTransport(json_responses={"/api/session/status/session": {"isRunningSolo": True}})
    c = DesignerClient(ft, "localhost:80")
    c.resolve_routing()
    assert c.host == "localhost:80"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_client.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 写 `src/vcam_bridge/designer/client.py`**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from vcam_bridge.designer.transport import Transport
from vcam_bridge.domain.errors import DesignerTimeoutError, ExternalError

_LINE_RE = re.compile(r"line (\d+)")


@dataclass
class ExecuteResult:
    return_value: Any
    d3_log: str
    python_log: str


class DesignerClient:
    """Wraps a Transport: solo/director routing + /execute call with parsing, error
    mapping, userScript line-offset correction, and simple retry on retryable errors."""

    def __init__(self, transport: Transport, host: str, *, timeout_s: float = 30.0, retries: int = 2):
        self._t = transport
        self.host = host
        self._timeout_s = timeout_s
        self._retries = retries

    def resolve_routing(self) -> None:
        st = self._t.get_json(self.host, "/api/session/status/session", self._timeout_s)
        if not st.get("isRunningSolo", True):
            self.host = st["director"]["hostname"]

    @staticmethod
    def _fix_line_offset(msg: str) -> str:
        # Designer wraps the script in def userScript(): so reported lines are +10.
        def repl(m: re.Match) -> str:
            return "line %d" % (int(m.group(1)) - 10)
        return _LINE_RE.sub(repl, msg)

    def execute(self, script: str, module_name: str | None = None) -> ExecuteResult:
        last_exc: Exception | None = None
        for _ in range(self._retries + 1):
            resp = self._t.post_execute(self.host, script, module_name, self._timeout_s)
            status = resp.get("status", {}) or {}
            code = status.get("code", 0)
            if code == 0:
                rv = resp.get("returnValue", "null")
                value = None if rv in (None, "null", "") else json.loads(rv)
                return ExecuteResult(value, resp.get("d3Log", ""), resp.get("pythonLog", ""))
            msg = self._fix_line_offset(status.get("message", "") or "")
            details = {"code": code, "details": status.get("details", []),
                       "d3Log": resp.get("d3Log", ""), "pythonLog": resp.get("pythonLog", "")}
            if "TimeoutError" in msg or "KeyboardInterrupt" in msg:
                raise DesignerTimeoutError(msg or "Designer python execution timed out", details=details)
            last_exc = ExternalError(msg or "Designer execute failed", details=details)
            break  # non-timeout execute errors are not retried (deterministic)
        raise last_exc  # type: ignore[misc]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_client.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/designer/client.py tests/test_client.py
git commit -m "feat: DesignerClient (execute parse, solo/director routing, error mapping)"
```

---

## Task 3: 目标枚举（tracks / ACC layers / VCs）

**Files:**
- Create: `src/vcam_bridge/designer/targets.py`
- Test: `tests/test_targets.py`

- [ ] **Step 1: 写失败测试 `tests/test_targets.py`**

```python
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_tracks, list_acc_layers, list_vcs


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_list_tracks_parses_rest():
    ft = FakeTransport(json_responses={"/api/session/transport/tracks":
        {"status": {"code": 0}, "result": [{"uid": "0x1", "name": "Main", "length": 100, "crossfade": ""}]}})
    c = DesignerClient(ft, "localhost")
    tracks = list_tracks(c)
    assert tracks == [{"uid": "0x1", "name": "Main"}]


def test_list_acc_layers_uses_execute():
    ft = FakeTransport(execute_responses=[_ok('[["My ACC", "0xabc"]]')])
    c = DesignerClient(ft, "localhost")
    layers = list_acc_layers(c)
    assert layers == [{"name": "My ACC", "uid": "0xabc"}]
    assert "moduleType" in ft.executed[0]["script"]   # enumerates via track.layers


def test_list_vcs_uses_execute():
    ft = FakeTransport(execute_responses=[_ok('[["VC1", "0xdef"]]')])
    c = DesignerClient(ft, "localhost")
    assert list_vcs(c) == [{"name": "VC1", "uid": "0xdef"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_targets.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `src/vcam_bridge/designer/targets.py`**

```python
from __future__ import annotations

from vcam_bridge.designer.client import DesignerClient

# ACC moduleType identifier is confirmed at runtime (P1); accept either historical/new name.
_ACC_ENUM_SCRIPT = '''
import json
local_state = state.localOrDirectorState()
out = []
for track in [local_state.track]:
    for layer in track.layers:
        mt = str(layer.moduleType())
        if "AnimateCamera" in mt:
            out.append([layer.name, hex(layer.uid)])
return json.dumps(out)
'''

_VC_ENUM_SCRIPT = '''
import json
out = []
for cam in state.stage.cameras:
    if getattr(cam, "isVirtual", False) or "Virtual" in str(type(cam).__name__):
        out.append([cam.name, hex(cam.uid)])
return json.dumps(out)
'''


def list_tracks(client: DesignerClient) -> list[dict]:
    resp = client._t.get_json(client.host, "/api/session/transport/tracks", client._timeout_s)
    return [{"uid": t["uid"], "name": t["name"]} for t in resp.get("result", [])]


def list_acc_layers(client: DesignerClient) -> list[dict]:
    rows = client.execute(_ACC_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u in rows]


def list_vcs(client: DesignerClient) -> list[dict]:
    rows = client.execute(_VC_ENUM_SCRIPT).return_value or []
    return [{"name": n, "uid": u} for n, u in rows]
```

> 注：`_VC_ENUM_SCRIPT` 里 VC 的精确识别属性（`isVirtual` / 类型名）由 P1/真机确认；当前用宽松判定，真机 probe 时校正。`list_tracks` 直接用 transport（REST tracks 端点），其余经 /execute。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_targets.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/designer/targets.py tests/test_targets.py
git commit -m "feat: enumerate tracks (REST) + ACC layers/VCs (execute)"
```

---

## Task 4: convention-lock 求解（transform/convention.py）

**Files:**
- Create: `src/vcam_bridge/transform/convention.py`
- Test: `tests/test_convention.py`

- [ ] **Step 1: 写失败测试 `tests/test_convention.py`**

```python
import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector
from vcam_bridge.transform.convention import solve_convention, CANDIDATES


def _world_from_params(pivot, rot, dist, forward_axis, euler_order):
    R = euler_to_matrix(rot, euler_order)
    f = R @ forward_vector(forward_axis)
    C = np.asarray(pivot) - dist * f
    return C, R


def test_solver_recovers_true_convention():
    true_fwd, true_order = "+X", "XYZ"
    rng = np.random.default_rng(3)
    samples = []
    for _ in range(8):
        pivot = rng.normal(size=3)
        rot = tuple(rng.uniform(-70, 70, size=3))
        dist = float(rng.uniform(0.3, 4.0))
        C, R = _world_from_params(pivot, rot, dist, true_fwd, true_order)
        samples.append({"written": {"pivot": tuple(pivot), "rotation": rot, "distance": dist},
                        "world": {"position": tuple(C), "rotation_matrix": R.tolist()}})
    best = solve_convention(samples)
    assert best["forward_axis"] == true_fwd
    assert best["euler_order"] == true_order
    assert best["pos_error"] < 1e-6


def test_candidates_cover_axes_and_orders():
    assert len(CANDIDATES) >= 6 * 6   # 6 forward axes x >=6 euler orders
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_convention.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `src/vcam_bridge/transform/convention.py`**

```python
from __future__ import annotations

import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector

_FORWARD = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
_ORDERS = ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"]
CANDIDATES = [{"forward_axis": fa, "euler_order": eo} for fa in _FORWARD for eo in _ORDERS]


def _predict_world(written: dict, forward_axis: str, euler_order: str):
    R = euler_to_matrix(written["rotation"], euler_order)
    f = R @ forward_vector(forward_axis)
    C = np.asarray(written["pivot"], dtype=float) - written["distance"] * f
    return C, R


def solve_convention(samples: list[dict]) -> dict:
    """samples: [{written:{pivot,rotation,distance}, world:{position, rotation_matrix}}].
    Returns the candidate {forward_axis, euler_order, pos_error, rot_error} that best
    reproduces the readback world poses. (handedness is absorbed by P6 Umeyama; this
    locks forward axis + euler order against measured VC world poses.)"""
    best = None
    for cand in CANDIDATES:
        pos_err = 0.0
        rot_err = 0.0
        for s in samples:
            C_pred, R_pred = _predict_world(s["written"], cand["forward_axis"], cand["euler_order"])
            C_obs = np.asarray(s["world"]["position"], dtype=float)
            R_obs = np.asarray(s["world"]["rotation_matrix"], dtype=float)
            pos_err += float(np.linalg.norm(C_pred - C_obs))
            rot_err += float(np.linalg.norm(R_pred - R_obs))
        score = pos_err + rot_err
        if best is None or score < best["_score"]:
            best = {**cand, "pos_error": pos_err / len(samples),
                    "rot_error": rot_err / len(samples), "_score": score}
    best.pop("_score")
    return best
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_convention.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/convention.py tests/test_convention.py
git commit -m "feat: convention-lock solver (forward axis x euler order vs readback)"
```

---

## Task 5: 分块注入执行（超时回读续写 + 验证）

**Files:**
- Create: `src/vcam_bridge/designer/inject.py`
- Test: `tests/test_inject.py`

- [ ] **Step 1: 写失败测试 `tests/test_inject.py`**

```python
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import chunk_keys, inject_keys


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def _keys(n):
    return [{"t_sec": i * 0.1, "values": {"fov": 60.0 + i}} for i in range(n)]


def test_chunk_keys_splits():
    chunks = chunk_keys(_keys(250), 100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_inject_writes_all_chunks():
    ft = FakeTransport(execute_responses=[_ok('{"ok": true, "written": 100}'),
                                          _ok('{"ok": true, "written": 100}'),
                                          _ok('{"ok": true, "written": 50}')])
    c = DesignerClient(ft, "localhost")
    fields = {"fov": "fieldOfView"}
    written = inject_keys(c, layer_uid="0x1", fields=fields, keys=_keys(250),
                          start_offset_sec=0.0, chunk_size=100)
    assert written == 250
    assert len(ft.executed) == 3


def test_inject_halves_chunk_on_timeout():
    from vcam_bridge.designer.transport import FakeTransport as FT
    # first call (50 keys) -> timeout; then two 25-key calls succeed
    timeout = {"status": {"code": 1, "message": "TimeoutError"}, "returnValue": "null", "d3Log": "", "pythonLog": ""}
    ft = FT(execute_responses=[timeout, _ok('{"ok": true, "written": 25}'), _ok('{"ok": true, "written": 25}')])
    c = DesignerClient(ft, "localhost", retries=0)
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=_keys(50),
                          start_offset_sec=0.0, chunk_size=50)
    assert written == 50
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_inject.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `src/vcam_bridge/designer/inject.py`**

```python
from __future__ import annotations

from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.codegen import build_inject_script
from vcam_bridge.domain.errors import DesignerTimeoutError, PartialError


def chunk_keys(keys: list[dict], size: int) -> list[list[dict]]:
    if size < 1:
        size = 1
    return [keys[i:i + size] for i in range(0, len(keys), size)]


def _write_chunk(client: DesignerClient, layer_uid, fields, chunk, start_offset_sec) -> int:
    payload = {"layer_uid": layer_uid, "start_offset_sec": start_offset_sec,
               "fields": fields, "keys": chunk}
    script = build_inject_script(payload)
    res = client.execute(script).return_value or {}
    if not res.get("ok"):
        raise PartialError("inject chunk failed: %s" % res.get("error", "unknown"),
                           details={"missing": res.get("missing")})
    return int(res.get("written", 0))


def inject_keys(client: DesignerClient, *, layer_uid: str, fields: dict, keys: list[dict],
                start_offset_sec: float, chunk_size: int, min_chunk: int = 8) -> int:
    """Inject keyframes in chunks (one /execute per chunk). On a chunk TimeoutError,
    halve that chunk and retry its halves (not a blind re-send), down to min_chunk."""
    total = 0
    pending = chunk_keys(keys, chunk_size)
    while pending:
        chunk = pending.pop(0)
        try:
            total += _write_chunk(client, layer_uid, fields, chunk, start_offset_sec)
        except DesignerTimeoutError:
            if len(chunk) <= min_chunk:
                raise
            mid = len(chunk) // 2
            pending.insert(0, chunk[mid:])
            pending.insert(0, chunk[:mid])
    return total
```

> 注：每个 chunk 的写入幂等（脚本 §5.4(c) 段内清理 + setFloat replace-at-beat）；超时把该 chunk 二分重投，而非盲发整批。端到端 P10 验证（读 `fseq.eval` 全 beat + VC world pose）作为 `--verify` 的独立步骤，在真机 §Live Handoff 运行。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_inject.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/designer/inject.py tests/test_inject.py
git commit -m "feat: chunked keyframe injection with timeout bisect-retry"
```

---

## Task 6: Blender FBX wrapper（子进程编排，单测 mock subprocess）

**Files:**
- Create: `src/vcam_bridge/ingest/blender_fbx.py`
- Test: `tests/test_blender_fbx.py`

- [ ] **Step 1: 写失败测试 `tests/test_blender_fbx.py`**

```python
import pytest
from vcam_bridge.ingest.blender_fbx import find_blender, _cache_key
from vcam_bridge.domain.errors import ExternalError


def test_find_blender_uses_env(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("BLENDER", str(fake))
    assert find_blender(blender_path=None) == str(fake)


def test_find_blender_raises_when_missing(monkeypatch):
    monkeypatch.delenv("BLENDER", raising=False)
    monkeypatch.setattr("shutil.which", lambda _x: None)
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(ExternalError):
        find_blender(blender_path="/nonexistent/blender")


def test_cache_key_changes_with_script(tmp_path):
    fbx = tmp_path / "a.fbx"; fbx.write_bytes(b"fbxbytes")
    k1 = _cache_key(str(fbx), camera="Cam", blender_ver="4.0")
    k2 = _cache_key(str(fbx), camera="Other", blender_ver="4.0")
    assert k1 != k2   # camera participates in the key
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_blender_fbx.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `src/vcam_bridge/ingest/blender_fbx.py`**

```python
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from vcam_bridge import __version__
from vcam_bridge.domain.errors import ExternalError, InvalidFbxError
from vcam_bridge.domain.models import CameraTrack

_SCRIPT = Path(__file__).with_name("blender_extract.py")
_LOG_CAP = 64 * 1024


def _candidate_paths(blender_path: str | None) -> list[str]:
    out = []
    if blender_path:
        out.append(blender_path)
    if os.environ.get("BLENDER"):
        out.append(os.environ["BLENDER"])
    if sys.platform == "darwin":
        out.append("/Applications/Blender.app/Contents/MacOS/Blender")
    which = shutil.which("blender")
    if which:
        out.append(which)
    return out


def find_blender(blender_path: str | None = None) -> str:
    for p in _candidate_paths(blender_path):
        if p and Path(p).exists():
            return p
    raise ExternalError("Blender not found; set --blender-path or $BLENDER, or install Blender",
                        details={"searched": _candidate_paths(blender_path)})


def blender_version(blender: str) -> str:
    try:
        out = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip().splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_dir(cache_dir: str | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "vcam_bridge" / "fbx"


def _cache_key(fbx_path: str, *, camera: str | None, blender_ver: str) -> dict:
    return {"fbx_sha": _sha(Path(fbx_path).read_bytes()), "script_sha": _sha(_SCRIPT.read_bytes()),
            "version": __version__, "blender_version": blender_ver, "camera": camera or ""}


def _run_blender(blender, script, inp, out, camera, timeout):
    cmd = [blender, "--background", "--factory-startup", "--python", script, "--", "--in", inp, "--out", out]
    if camera:
        cmd += ["--camera", camera]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        so, se = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            proc.kill()
        proc.communicate()
        raise ExternalError("Blender FBX conversion exceeded %ss" % timeout, details={"timeout": True})
    return proc.returncode, (so or "")[-_LOG_CAP:], (se or "")[-_LOG_CAP:]


def extract_fbx(fbx_path: str, *, camera: str | None = None, blender_path: str | None = None,
                cache_dir: str | None = None, timeout_s: float = 120.0, use_cache: bool = True) -> CameraTrack:
    fbx_path = str(Path(fbx_path).resolve())
    if not Path(fbx_path).exists():
        raise InvalidFbxError("FBX not found: %s" % fbx_path, details={"path": fbx_path})
    blender = find_blender(blender_path)
    key = _cache_key(fbx_path, camera=camera, blender_ver=blender_version(blender))
    digest = _sha(json.dumps(key, sort_keys=True).encode())
    cdir = _cache_dir(cache_dir)
    out_json = cdir / ("%s.track.json" % digest)
    if not (use_cache and out_json.exists()):
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = out_json.with_suffix(".tmp")
        rc, so, se = _run_blender(blender, str(_SCRIPT), fbx_path, str(tmp), camera or "", timeout_s)
        if rc != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise InvalidFbxError("Blender FBX extraction failed (rc=%s)" % rc,
                                  details={"stderr": se[-2000:], "stdout": so[-500:]})
        os.replace(tmp, out_json)
    data = json.loads(out_json.read_text(encoding="utf-8"))
    if not data.get("frames"):
        raise InvalidFbxError("FBX produced no frames", details={"path": fbx_path})
    return CameraTrack.model_validate(data)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_blender_fbx.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/ingest/blender_fbx.py tests/test_blender_fbx.py
git commit -m "feat: headless Blender FBX wrapper (find/cache/killpg/atomic)"
```

---

## Task 7: Blender 提取脚本 + 本机真集成测试

**Files:**
- Create: `src/vcam_bridge/ingest/blender_extract.py`
- Test: `tests/integration/test_blender_extract_real.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1: 写 `src/vcam_bridge/ingest/blender_extract.py`**

（在 Blender 内运行；vcam_bridge 进程绝不 import 它。输出 `CameraTrack` JSON：position + 4x4 T + 水平 FOV + fps + focus。）

```python
"""Runs INSIDE Blender: blender --background --factory-startup --python this.py -- --in ... --out ...
Emits a vcam.track/1 JSON: per-frame world matrix (T 4x4), horizontal FOV (angle_x), fps, focus."""
import argparse
import json
import sys

import bpy   # only available inside Blender


def _parse(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--camera", default="")
    return ap.parse_args(argv)


def _import(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)


def _pick_camera(name):
    cams = sorted([o for o in bpy.data.objects if o.type == "CAMERA"], key=lambda o: o.name)
    if not cams:
        raise SystemExit("ERR_NO_CAMERA")
    if name:
        for c in cams:
            if c.name == name:
                return c
        raise SystemExit("ERR_CAMERA_NOT_FOUND:%s|%s" % (name, [c.name for c in cams]))
    if len(cams) > 1:
        raise SystemExit("ERR_MULTI_CAMERA:%s" % [c.name for c in cams])
    return cams[0]


def _frame_range(cam, scene):
    ad = cam.animation_data
    if ad and ad.action:
        lo, hi = ad.action.frame_range
        return int(round(lo)), int(round(hi))
    return scene.frame_current, scene.frame_current


def main():
    args = _parse(list(sys.argv))
    _import(args.inp)
    cam = _pick_camera(args.camera)
    scene = bpy.context.scene
    fps = scene.render.fps / max(1.0, float(scene.render.fps_base))
    f0, f1 = _frame_range(cam, scene)
    import math
    frames = []
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        mw = cam.matrix_world
        T = [[mw[r][c] for c in range(4)] for r in range(4)]
        fov_h = math.degrees(cam.data.angle_x)
        focus = cam.data.dof.focus_distance if cam.data.dof else None
        frames.append({"idx": f - f0, "t_sec": (f - f0) / fps, "T": T,
                       "fov_h_deg": fov_h, "focus_m": focus})
    out = {"schema": "vcam.track/1", "fps": fps, "camera": cam.name, "frames": frames}
    with open(args.out, "w") as fh:
        json.dump(out, fh)
    print("OK_FRAMES=%d" % len(frames))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写真集成测试 `tests/integration/__init__.py`（空）与 `tests/integration/test_blender_extract_real.py`**

```python
import os
import shutil
import subprocess
import sys
import textwrap
import pytest

from vcam_bridge.ingest.blender_fbx import extract_fbx, find_blender


def _blender_or_skip():
    try:
        return find_blender(None)
    except Exception:
        pytest.skip("Blender not installed")


def _make_camera_fbx(blender: str, out_fbx: str):
    # Generate a 2-frame animated camera and export FBX, all inside Blender.
    script = textwrap.dedent('''
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cam_data = bpy.data.cameras.new("Cam")
        cam = bpy.data.objects.new("Cam", cam_data)
        bpy.context.collection.objects.link(cam)
        cam.location = (0, 0, 0)
        cam.keyframe_insert("location", frame=1)
        cam.location = (1, 0, 0)
        cam.keyframe_insert("location", frame=2)
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = 2
        import sys
        out = sys.argv[sys.argv.index("--") + 1]
        bpy.ops.export_scene.fbx(filepath=out, object_types={"CAMERA"}, bake_anim=True)
    ''')
    rc = subprocess.run([blender, "--background", "--factory-startup", "--python-expr", script,
                         "--", out_fbx], capture_output=True, text=True, timeout=120)
    assert rc.returncode == 0, rc.stderr[-2000:]
    assert os.path.exists(out_fbx)


@pytest.mark.integration
def test_blender_roundtrip_real(tmp_path):
    blender = _blender_or_skip()
    fbx = str(tmp_path / "cam.fbx")
    _make_camera_fbx(blender, fbx)
    track = extract_fbx(fbx, cache_dir=str(tmp_path / "cache"), use_cache=False)
    assert track.camera
    assert len(track.frames) >= 2
    assert track.frames[0].fov_h_deg > 0
    assert len(track.frames[0].T) == 4 and len(track.frames[0].T[0]) == 4
```

- [ ] **Step 3: 注册 integration marker（pyproject）**

在 `[tool.pytest.ini_options]` 加：
```toml
markers = ["integration: tests requiring Blender or live hardware"]
```

- [ ] **Step 4: 跑真集成测试（本机 Blender）**

Run: `uv run pytest tests/integration/test_blender_extract_real.py -q -m integration`
Expected: PASS（1 passed）—— 真用本机 Blender 生成相机 FBX 并提取。若环境无 Blender 则 skip。

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/ingest/blender_extract.py tests/integration/__init__.py tests/integration/test_blender_extract_real.py pyproject.toml
git commit -m "feat: Blender bpy FBX extract + real round-trip integration test"
```

---

## Task 8: P0–P9 探测编排（snapshot/restore/scratch；FakeTransport 单测）

**Files:**
- Create: `src/vcam_bridge/designer/probe.py`
- Test: `tests/test_probe.py`

- [ ] **Step 1: 写失败测试 `tests/test_probe.py`**

```python
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.probe import probe_field_set, ProbeReport


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_probe_field_set_parses_sequences():
    ft = FakeTransport(execute_responses=[_ok('["camera_pivot.x", "camera_pivot.y", "fieldOfView"]')])
    c = DesignerClient(ft, "localhost")
    fields = probe_field_set(c, layer_uid="0xabc")
    assert "fieldOfView" in fields
    assert "moduleType" not in ft.executed[0]["script"]  # this probe lists sequences


def test_probe_report_dataclass():
    r = ProbeReport(version="R33", legacy_vc=False, module_type="AnimateCameraControl",
                    field_names=["fieldOfView"], notes=[])
    assert r.legacy_vc is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_probe.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `src/vcam_bridge/designer/probe.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from vcam_bridge.designer.client import DesignerClient

_FIELD_DUMP = '''
import json
local_state = state.localOrDirectorState()
target = None
for layer in local_state.track.layers:
    if hex(layer.uid) == %r:
        target = layer
        break
if target is None:
    return json.dumps([])
out = []
for fs in target.sequences:
    out.append(str(fs))
return json.dumps(out)
'''

_MODULE_TYPE = '''
import json
local_state = state.localOrDirectorState()
for layer in local_state.track.layers:
    if hex(layer.uid) == %r:
        return json.dumps(str(layer.moduleType()))
return json.dumps(None)
'''


@dataclass
class ProbeReport:
    version: str
    legacy_vc: bool
    module_type: str | None
    field_names: list[str]
    notes: list[str] = field(default_factory=list)


def probe_module_type(client: DesignerClient, *, layer_uid: str) -> str | None:
    return client.execute(_MODULE_TYPE % layer_uid).return_value


def probe_field_set(client: DesignerClient, *, layer_uid: str) -> list[str]:
    """P2 — dump decorated FieldSequence names on the probe ACC layer."""
    return client.execute(_FIELD_DUMP % layer_uid).return_value or []
```

> 注：完整 P0/P3/P4/P5/P7/P9（写已知 pose、读 VC world、convention-lock、FOV 轴、key 类型）与 snapshot/restore + scratch 层创建/删除的脚本，由后续在真机迭代（其行为依赖真机字段名 P2 结果）。本任务落地 **P1（moduleType）+ P2（字段集）** 这两个最确定、无需写真机状态的只读探测，使 `vcam probe` 有可运行骨架；写真机状态的 P 步（P3/P5/P7/P9）在 §Live Handoff 真机阶段补全并标定。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_probe.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/designer/probe.py tests/test_probe.py
git commit -m "feat: probe P1 moduleType + P2 field-set dump (read-only)"
```

---

## Task 9: CLI 接入（targets/vc/probe 命令 + convert live 路径）

**Files:**
- Create: `src/vcam_bridge/cli/commands/targets.py`, `vc.py`, `probe.py`
- Modify: `src/vcam_bridge/cli/commands/convert.py`, `src/vcam_bridge/cli/main.py`
- Test: `tests/test_cli_live.py`

- [ ] **Step 1: 写失败测试 `tests/test_cli_live.py`**

```python
import json
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.cli.commands import targets as targets_cmd


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_targets_list_command_returns_layers():
    ft = FakeTransport(execute_responses=[_ok('[["My ACC", "0xabc"]]')])
    op, data = targets_cmd.list_targets(ft, host="localhost")
    assert op == "targets.list"
    assert data["layers"] == [{"name": "My ACC", "uid": "0xabc"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cli_live.py -q`
Expected: FAIL

- [ ] **Step 3: 写命令模块**

`src/vcam_bridge/cli/commands/targets.py`:
```python
from __future__ import annotations

from typing import Any
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_acc_layers


def list_targets(transport, *, host: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "targets.list", {"layers": list_acc_layers(client)}
```

`src/vcam_bridge/cli/commands/vc.py`:
```python
from __future__ import annotations

from typing import Any
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_vcs


def list_vcams(transport, *, host: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "vc.list", {"virtual_cameras": list_vcs(client)}
```

`src/vcam_bridge/cli/commands/probe.py`:
```python
from __future__ import annotations

from typing import Any
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.probe import probe_module_type, probe_field_set


def run_probe(transport, *, host: str, probe_layer_uid: str) -> tuple[str, Any]:
    client = DesignerClient(transport, host)
    client.resolve_routing()
    return "probe", {
        "module_type": probe_module_type(client, layer_uid=probe_layer_uid),
        "field_names": probe_field_set(client, layer_uid=probe_layer_uid),
    }
```

- [ ] **Step 4: 接入 `main.py`**

在 `build_parser()` 加子命令：`targets`(子命令 `list`)、`vc`(子命令 `list`)、`probe`(`--probe-layer-uid` 必填)。给 convert 加 `--vc-uid`、`--chunk-size`、`--verify`（已部分存在则补全）。在 `_dispatch` 加分支：构造 `RequestsTransport()` 注入对应命令模块（`targets.list_targets(transport, host=args.director)` 等）；`--director` 缺失时抛 `ConfigError`。`_op_id` 增加映射。convert 的 live 路径：`if not args.dry_run:` 改为构造 transport + DesignerClient + 调 `inject.inject_keys(...)`（用 §convert 算出的 keys/fields）。具体接线代码：

```python
    # in _dispatch, after meta/convert-dry-run handling:
    if args.command == "targets" and getattr(args, "subcommand", None) == "list":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import targets as targets_cmd
        return targets_cmd.list_targets(RequestsTransport(), host=args.director)
    if args.command == "vc" and getattr(args, "subcommand", None) == "list":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import vc as vc_cmd
        return vc_cmd.list_vcams(RequestsTransport(), host=args.director)
    if args.command == "probe":
        if not args.director:
            raise ConfigError("--director HOST:PORT is required")
        from vcam_bridge.designer.transport import RequestsTransport
        from vcam_bridge.cli.commands import probe as probe_cmd
        return probe_cmd.run_probe(RequestsTransport(), host=args.director,
                                   probe_layer_uid=args.probe_layer_uid)
```

并在 build_parser 中：
```python
    p_targets = sub.add_parser("targets", parents=[gp])
    p_targets.add_subparsers(dest="subcommand").add_parser("list", parents=[gp])
    p_vc = sub.add_parser("vc", parents=[gp])
    p_vc.add_subparsers(dest="subcommand").add_parser("list", parents=[gp])
    p_probe = sub.add_parser("probe", parents=[gp])
    p_probe.add_argument("--probe-layer-uid", required=True)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_cli_live.py -q`
Expected: PASS（1 passed）

- [ ] **Step 6: convert live 路径 + 全量测试**

修改 `convert.py`：抽出 `build_keyframes(track, config, ...) -> (field_map, keys, keyframes)` 供 dry-run 与 live 共用；新增 `convert_live(transport, host, fbx, config, layer_uid, vc_uid, ...)`：ingest（CSV/JSON 或 Blender 按扩展名）→ build_keyframes → `DesignerClient` → 设 Camera target+Global（execute 小脚本）→ `inject.inject_keys(...)` → 返回 `{"written": n}`。main 的 `convert` 非 dry-run 分支改为调 `convert_live`。补一个用 FakeTransport 的 `test_convert_live_injects`（断言 written 总数 + execute 调用次数）。

Run: `uv run pytest -q`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add src/vcam_bridge/cli tests/test_cli_live.py
git commit -m "feat: CLI targets/vc/probe commands + convert live injection path"
```

---

## Task 10: Skill 包 + manifest 一致性

**Files:**
- Create: `.claude/skills/vcam-bridge/SKILL.md`, `reference/contract-manifest.json`, `reference/errors.md`, `scripts/call_cli.py`
- Test: `tests/test_skill_manifest.py`

- [ ] **Step 1: 生成 `reference/contract-manifest.json`**

Run: `uv run vcam manifest --output json > .claude/skills/vcam-bridge/reference/contract-manifest.json`（先建目录）。

- [ ] **Step 2: 写 `SKILL.md`**

```markdown
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
```

- [ ] **Step 3: 写 `reference/errors.md`** — 列 exit code 表（从 spec §7.5 抄）+ `error.code` 语义。

- [ ] **Step 4: 写 `scripts/call_cli.py`** — 一个最小 fallback wrapper：`subprocess.run(["vcam", *args, "--output", "json", "--no-input"], ...)`，返回解析后的 envelope；非零退出抛出含 `error.code` 的异常。

- [ ] **Step 5: 写一致性测试 `tests/test_skill_manifest.py`**

```python
import json
from pathlib import Path
from vcam_bridge.manifest import build_manifest


def test_skill_manifest_matches_live():
    p = Path(".claude/skills/vcam-bridge/reference/contract-manifest.json")
    synced = json.loads(p.read_text())
    live = build_manifest()
    assert {o["operation_id"] for o in synced["operations"]} == {o["operation_id"] for o in live["operations"]}
    assert synced["contract_version"] == live["contract_version"]
```

- [ ] **Step 6: 跑测试 + 全量**

Run: `uv run pytest -q`
Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/vcam-bridge tests/test_skill_manifest.py
git commit -m "feat: Claude Code Skill package + manifest consistency test"
```

---

## Live Handoff（operator 在 R33+ Designer 上运行，不在自动执行范围）

这些步骤需 live Designer + 真实 UE5.7 FBX，由你在真机执行；工具已具备运行它们的命令骨架，但**实际约定/容差由真机标定**：

1. **连通 + P0**：`vcam probe --director <host:port> --probe-layer-uid <scratch ACC uid> --output json`。核对 `module_type`、字段集；记 `enableLegacyVirtualCameraWorkflow`。
2. **补全写真机的 P 步（P3/P5/P7/P9）**：在 scratch 层上写已知 (pivot,rot,dist,fov) → 读 VC world pose → 喂 `transform.convention.solve_convention` 锁 forward/euler；`register.umeyama` 解 `M_ue2dis`；P7 定 FOV 轴；P9 定 Linear key 类型。把结果写进 `config.yaml`（snapshot/restore 保护现场，破坏性闸门见 spec §6.0）。
3. **端到端 + P10**：`vcam convert --fbx <real.fbx> --target-uid <ACC uid> --vc-uid <VC uid> --dry-run` 看 plan → 去掉 `--dry-run` 注入 → `--verify` 全 beat 回读 + VC world pose 比对，超容差非零退出（exit 11）。
4. **Golden**：用一个已知 UE5.7 FBX（直线 dolly + pan + FOV 推拉）跑通，固化 tolerance + `config.yaml`，存为回归基线。

> 把第 2 步真机迭代出的写状态脚本回填到 `designer/probe.py`（补全 P3/P5/P7/P9），即完成 probe 的 live 闭环——届时再开一个小 plan 把它单测化（用真机录下的 readback 作 fixture）。

---

## Self-Review

**1. Spec 覆盖（Plan 2 范围，离线可实现部分）**：§5.1 连接层→T1/T2 ✓；§5.5 枚举→T3 ✓；P5 convention-lock→T4 ✓；§5.4(c)(d) 分块+超时续写→T5 ✓；§5.2 Blender→T6/T7 ✓（含真集成）；P1/P2 探测→T8 ✓（写真机的 P 步明确划入 Live Handoff）；CLI 接入→T9 ✓；§7.6 Skill→T10 ✓。§5.7 P10 端到端、§6.0 snapshot/restore 的真机写状态部分→Live Handoff（依赖真机字段名，诚实标注）。

**2. 占位符扫描**：无 TBD；每个 code step 含完整可运行代码。两处"由真机迭代补全"（VC 识别属性、写状态 P 步）是**有意的真机依赖**，已在 Live Handoff 明确，非占位符。

**3. 类型一致性**：`Transport`(T1) 被 client(T2)/targets(T3)/inject(T5 经 client) 一致使用；`DesignerClient.execute -> ExecuteResult`(T2) 被 targets/inject/probe 一致消费；`build_inject_script`(Plan 1) payload 形状（layer_uid/start_offset_sec/fields/keys）被 inject(T5) 一致构造；`CameraTrack`(Plan 1) 被 blender_extract(T7) 产出、extract_fbx(T6) 返回。`FakeTransport`(T1) 贯穿所有 designer 单测。

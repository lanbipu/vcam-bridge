# vcam-bridge 核心（离线管线）实现计划 — Plan 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 vcam-bridge 的**离线核心**：从 FBX 中间格式（CSV/JSON）读取相机轨迹 → UE→Disguise 坐标变换 → pivot-orbit 分解 → FOV 映射 → 生成安全的 Py2.7 注入脚本，并通过 `vcam convert --dry-run` 串起来，全程纯单元测试、不依赖真机 Designer 或 Blender。

**Architecture:** Contract-first 分层（对齐同生态项目 `tracksim`）：Core SDK（domain models/errors/envelope/manifest，pydantic + DI）→ ingest/transform 纯函数（numpy/scipy）→ designer/codegen（生成注入脚本，信任边界隔离）→ cli adapter（argparse + text/json/ndjson 信封）。本计划只做离线可测部分；真机注入/probe 在 Plan 2。

**Tech Stack:** Python 3.11+，pydantic v2，numpy，scipy（旋转/SVD），pyyaml，pytest；打包 hatchling + src 布局；uv 管环境。

参照 spec：`docs/superpowers/specs/2026-06-03-vcam-bridge-design.md`（v2）。

---

## 文件结构（本计划创建/修改）

```
vcam-bridge/
├── pyproject.toml                         # 包元数据 + [project.scripts] vcam + deps
├── src/vcam_bridge/
│   ├── __init__.py                        # __version__
│   ├── envelope.py                        # SCHEMA/CONTRACT 版本, EXIT_*, success/error_envelope
│   ├── manifest.py                        # 完整 Contract Manifest（operations + side_effects 等）
│   ├── config.py                          # Config 加载（YAML/默认）
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── errors.py                      # VcamError 基类 + 子类→exit_code
│   │   └── models.py                      # pydantic: Frame, CameraTrack, StagePose, ACCKeyframe, Calibration, Config
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── rotation.py                    # euler↔matrix（scipy 封装，固定约定入口）
│   │   ├── register.py                    # Umeyama 相似变换 + 默认基变换
│   │   ├── decompose.py                   # 自由相机 → pivot-orbit
│   │   └── fov.py                         # H↔V 换算
│   ├── ingest/
│   │   ├── __init__.py
│   │   └── intermediate.py                # CSV/JSON → CameraTrack
│   ├── designer/
│   │   ├── __init__.py
│   │   └── codegen.py                      # 生成 Py2.7 注入脚本（固定模板 + 单一 JSON payload）+ 校验
│   └── cli/
│       ├── __init__.py
│       ├── runtime.py                     # request_id / utc_now / 输出格式解析
│       ├── render.py                      # 信封渲染 text/json/ndjson
│       ├── main.py                        # argparse + 全局 flag + dispatch
│       └── commands/
│           ├── __init__.py
│           ├── meta.py                    # manifest/version/schema
│           └── convert.py                 # convert --dry-run 编排
└── tests/
    ├── __init__.py
    ├── conftest.py                        # 夹具：sample CameraTrack JSON/CSV
    ├── test_envelope.py
    ├── test_errors.py
    ├── test_models.py
    ├── test_config.py
    ├── test_manifest.py
    ├── test_rotation.py
    ├── test_register.py
    ├── test_decompose.py
    ├── test_fov.py
    ├── test_ingest_intermediate.py
    ├── test_codegen.py
    ├── test_render.py
    └── test_cli_convert.py
```

---

## Task 1: 脚手架（package + pyproject + pytest）

**Files:**
- Create: `vcam-bridge/pyproject.toml`
- Create: `vcam-bridge/src/vcam_bridge/__init__.py`
- Create: `vcam-bridge/tests/__init__.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "vcam-bridge"
version = "0.1.0"
description = "UE Sequencer FBX camera animation -> Disguise AnimateCameraControl keyframe injector"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2",
    "numpy>=1.24",
    "scipy>=1.10",
    "pyyaml>=6",
]

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
vcam = "vcam_bridge.cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/vcam_bridge"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: 写包入口 `src/vcam_bridge/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: 写 `tests/__init__.py`（空文件）**

```python
```

- [ ] **Step 4: 建环境并验证可导入**

Run:
```bash
cd vcam-bridge && uv venv && uv pip install -e ".[dev]" && uv run python -c "import vcam_bridge; print(vcam_bridge.__version__)"
```
Expected: 打印 `0.1.0`

- [ ] **Step 5: README 占位 + commit**

Create `vcam-bridge/README.md`:
```markdown
# vcam-bridge

UE Sequencer FBX camera animation → Disguise AnimateCameraControl keyframe injector.

See `docs/superpowers/specs/2026-06-03-vcam-bridge-design.md`.
```
```bash
git add pyproject.toml README.md src/vcam_bridge/__init__.py tests/__init__.py
git commit -m "chore: scaffold vcam-bridge package"
```

---

## Task 2: `envelope.py`（输出信封 + 退出码）

**Files:**
- Create: `src/vcam_bridge/envelope.py`
- Test: `tests/test_envelope.py`

- [ ] **Step 1: 写失败测试 `tests/test_envelope.py`**

```python
from vcam_bridge.envelope import (
    SCHEMA_VERSION, CONTRACT_VERSION, EXIT_OK, EXIT_USAGE,
    success_envelope, error_envelope,
)


def test_success_envelope_shape():
    env = success_envelope("convert", {"frames": 3},
                           request_id="r1", duration_ms=5, timestamp="2026-06-03T00:00:00Z")
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["status"] == "ok"
    assert env["operation_id"] == "convert"
    assert env["data"] == {"frames": 3}
    assert env["meta"]["request_id"] == "r1"


def test_error_envelope_shape():
    env = error_envelope("convert", code="INVALID_FBX", exit_code=13,
                         message="bad", retryable=False, details={"path": "x"},
                         request_id="r1", duration_ms=1, timestamp="2026-06-03T00:00:00Z")
    assert env["status"] == "error"
    assert env["error"]["code"] == "INVALID_FBX"
    assert env["error"]["exit_code"] == 13
    assert env["error"]["retryable"] is False


def test_exit_codes_present():
    assert EXIT_OK == 0
    assert EXIT_USAGE == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_envelope.py -q`
Expected: FAIL（`ModuleNotFoundError: vcam_bridge.envelope`）

- [ ] **Step 3: 写实现 `src/vcam_bridge/envelope.py`**

```python
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0"
CONTRACT_VERSION = "1.0"

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_AUTH = 4
EXIT_NOT_FOUND = 5
EXIT_CONFLICT = 6
EXIT_TIMEOUT = 7
EXIT_EXTERNAL = 8
EXIT_PARTIAL = 9
EXIT_PROBE_FAILED = 10
EXIT_VERIFY_TOLERANCE = 11
EXIT_CONVENTION_LOCK = 12
EXIT_INVALID_FBX = 13
EXIT_SIGINT = 130


def success_envelope(operation_id: str, data: Any, *, request_id: str,
                     duration_ms: int, timestamp: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "operation_id": operation_id,
        "data": data,
        "meta": {"request_id": request_id, "duration_ms": duration_ms, "timestamp": timestamp},
    }


def error_envelope(operation_id: str, *, code: str, exit_code: int, message: str,
                   retryable: bool, details: dict[str, Any], request_id: str,
                   duration_ms: int, timestamp: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "operation_id": operation_id,
        "error": {"code": code, "exit_code": exit_code, "message": message,
                  "retryable": retryable, "details": details},
        "meta": {"request_id": request_id, "duration_ms": duration_ms, "timestamp": timestamp},
    }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_envelope.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/envelope.py tests/test_envelope.py
git commit -m "feat: output envelope + exit codes"
```

---

## Task 3: `domain/errors.py`（错误层 → 退出码）

**Files:**
- Create: `src/vcam_bridge/domain/__init__.py`
- Create: `src/vcam_bridge/domain/errors.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: 写失败测试 `tests/test_errors.py`**

```python
import pytest
from vcam_bridge.domain.errors import (
    VcamError, ConfigError, InvalidFbxError, ConventionLockError, VerifyToleranceError,
)


def test_base_defaults():
    e = VcamError("boom")
    assert e.code == "INTERNAL"
    assert e.exit_code == 1
    assert e.message == "boom"
    assert e.details == {}


def test_subclass_codes():
    assert ConfigError("x").exit_code == 3
    assert InvalidFbxError("x").exit_code == 13
    assert ConventionLockError("x").exit_code == 12
    assert VerifyToleranceError("x").exit_code == 11


def test_details_carried():
    e = InvalidFbxError("bad", details={"path": "a.fbx"})
    assert e.details["path"] == "a.fbx"


def test_is_exception():
    with pytest.raises(VcamError):
        raise ConfigError("nope")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_errors.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/domain/__init__.py`（空）与 `errors.py`**

`src/vcam_bridge/domain/__init__.py`:
```python
```

`src/vcam_bridge/domain/errors.py`:
```python
from __future__ import annotations

from typing import Any


class VcamError(Exception):
    code: str = "INTERNAL"
    exit_code: int = 1
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details if details is not None else {}


class ConfigError(VcamError):
    code = "CONFIG_ERROR"; exit_code = 3; retryable = False


class AuthError(VcamError):
    code = "AUTH_ERROR"; exit_code = 4; retryable = False


class NotFoundError(VcamError):
    code = "NOT_FOUND"; exit_code = 5; retryable = False


class ConflictError(VcamError):
    code = "CONFLICT"; exit_code = 6; retryable = False


class DesignerTimeoutError(VcamError):
    code = "TIMEOUT"; exit_code = 7; retryable = True


class ExternalError(VcamError):
    code = "EXTERNAL_DEPENDENCY"; exit_code = 8; retryable = True


class PartialError(VcamError):
    code = "PARTIAL_FAILURE"; exit_code = 9; retryable = True


class ProbeFailedError(VcamError):
    code = "PROBE_FAILED"; exit_code = 10; retryable = False


class VerifyToleranceError(VcamError):
    code = "VERIFY_TOLERANCE_EXCEEDED"; exit_code = 11; retryable = False


class ConventionLockError(VcamError):
    code = "CONVENTION_LOCK_FAILED"; exit_code = 12; retryable = False


class InvalidFbxError(VcamError):
    code = "INVALID_FBX"; exit_code = 13; retryable = False
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_errors.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/domain/__init__.py src/vcam_bridge/domain/errors.py tests/test_errors.py
git commit -m "feat: domain error hierarchy mapped to exit codes"
```

---

## Task 4: `domain/models.py`（pydantic 数据模型）

**Files:**
- Create: `src/vcam_bridge/domain/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试 `tests/test_models.py`**

```python
import pytest
from pydantic import ValidationError
from vcam_bridge.domain.models import Frame, CameraTrack, StagePose, ACCKeyframe

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def test_frame_and_track():
    f = Frame(idx=0, t_sec=0.0, T=IDENTITY, fov_h_deg=60.0, focus_m=2.0)
    tr = CameraTrack(fps=30.0, camera="Cam", frames=[f])
    assert tr.schema_ == "vcam.track/1"
    assert tr.frames[0].fov_h_deg == 60.0


def test_T_must_be_4x4():
    with pytest.raises(ValidationError):
        Frame(idx=0, t_sec=0.0, T=[[1, 0], [0, 1]], fov_h_deg=60.0)


def test_stage_pose_and_keyframe():
    p = StagePose(pivot=(1, 2, 3), rotation=(10, 20, 30), distance=1.5, fov_deg=60)
    k = ACCKeyframe(idx=0, t_sec=0.0, pose=p)
    assert k.pose.distance == 1.5
    assert k.pose.rotation == (10, 20, 30)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_models.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/domain/models.py`**

```python
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class Frame(BaseModel):
    idx: int
    t_sec: float
    T: list[list[float]]            # 4x4 world transform (UE world space as ingested)
    fov_h_deg: float
    focus_m: float | None = None

    @field_validator("T")
    @classmethod
    def _check_4x4(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) != 4 or any(len(row) != 4 for row in v):
            raise ValueError("T must be a 4x4 matrix")
        return v


class CameraTrack(BaseModel):
    schema_: str = Field(default="vcam.track/1", alias="schema")
    fps: float
    camera: str
    frames: list[Frame]

    model_config = {"populate_by_name": True}


class StagePose(BaseModel):
    pivot: tuple[float, float, float]
    rotation: tuple[float, float, float]   # (elevation, heading, roll) degrees
    distance: float
    fov_deg: float
    zoom_scale: float | None = None


class ACCKeyframe(BaseModel):
    idx: int
    t_sec: float
    pose: StagePose


class Calibration(BaseModel):
    module_type: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    forward_axis: str = "+X"               # UE camera local forward (X-forward)
    euler_order: str = "XYZ"
    handedness: int = 1
    fov_axis: str = "horizontal"
    linear_key_type: Any | None = None
    M_ue2dis: list[list[float]] | None = None   # 4x4; None -> default base transform
    aspect: float = 16.0 / 9.0
    legacy_vc: bool = False
    zoom_scale_neutral: float = 1.0


class Tolerances(BaseModel):
    pos_m: float = 0.001
    rot_deg: float = 0.05
    fov_deg: float = 0.05


class Config(BaseModel):
    director: str | None = None
    calibration: Calibration = Field(default_factory=Calibration)
    tolerances: Tolerances = Field(default_factory=Tolerances)
    chunk_size: int = 200
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_models.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/domain/models.py tests/test_models.py
git commit -m "feat: pydantic domain models (CameraTrack, StagePose, Calibration, Config)"
```

---

## Task 5: `config.py`（配置加载）

**Files:**
- Create: `src/vcam_bridge/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
from vcam_bridge.config import load_config
from vcam_bridge.domain.models import Config


def test_load_default_when_none():
    cfg = load_config(None)
    assert isinstance(cfg, Config)
    assert cfg.chunk_size == 200
    assert cfg.calibration.euler_order == "XYZ"


def test_load_from_yaml(tmp_path):
    p = tmp_path / "vcam.yaml"
    p.write_text("chunk_size: 50\ndirector: 'host:80'\ncalibration:\n  euler_order: ZYX\n")
    cfg = load_config(str(p))
    assert cfg.chunk_size == 50
    assert cfg.director == "host:80"
    assert cfg.calibration.euler_order == "ZYX"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_config.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/config.py`**

```python
from __future__ import annotations

from pathlib import Path
import yaml

from vcam_bridge.domain.errors import ConfigError
from vcam_bridge.domain.models import Config


def load_config(path: str | None) -> Config:
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {path}", details={"path": path})
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in config: {exc}", details={"path": path}) from exc
    try:
        return Config.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid config schema: {exc}", details={"path": path}) from exc
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_config.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/config.py tests/test_config.py
git commit -m "feat: config loader (yaml + defaults)"
```

---

## Task 6: `manifest.py`（完整 Contract Manifest，spec §7.1 / F4）

**Files:**
- Create: `src/vcam_bridge/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: 写失败测试 `tests/test_manifest.py`**

```python
from vcam_bridge.manifest import build_manifest


def test_manifest_has_contract_version_and_ops():
    m = build_manifest()
    assert m["contract_version"] == "1.0"
    ids = {op["operation_id"] for op in m["operations"]}
    assert {"convert", "probe", "targets.list", "vc.list", "meta.manifest"} <= ids


def test_convert_declares_destructive_and_dry_run():
    m = build_manifest()
    convert = next(op for op in m["operations"] if op["operation_id"] == "convert")
    assert convert["side_effects"]["writes"] is True
    assert convert["side_effects"]["destructive"] is True
    assert convert["cli"]["supports_dry_run"] is True
    assert 11 in convert["exit_codes"]


def test_readonly_ops_not_destructive():
    m = build_manifest()
    for oid in ("targets.list", "vc.list", "meta.manifest"):
        op = next(o for o in m["operations"] if o["operation_id"] == oid)
        assert op["side_effects"]["writes"] is False
        assert op["side_effects"]["destructive"] is False
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_manifest.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/manifest.py`**

```python
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
        _op("vc.list", "Enumerate Virtual Cameras in the stage",
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_manifest.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/manifest.py tests/test_manifest.py
git commit -m "feat: full contract manifest with side_effects/dry-run/exit_codes"
```

---

## Task 7: `transform/rotation.py`（euler↔matrix）

**Files:**
- Create: `src/vcam_bridge/transform/__init__.py`
- Create: `src/vcam_bridge/transform/rotation.py`
- Test: `tests/test_rotation.py`

- [ ] **Step 1: 写失败测试 `tests/test_rotation.py`**

```python
import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix, matrix_to_euler


def test_roundtrip_xyz():
    ang = (12.0, -34.0, 56.0)
    R = euler_to_matrix(ang, "XYZ")
    back = matrix_to_euler(R, "XYZ")
    R2 = euler_to_matrix(back, "XYZ")
    assert np.allclose(R, R2, atol=1e-9)


def test_orthonormal():
    R = euler_to_matrix((10, 20, 30), "ZYX")
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_rotation.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `transform/__init__.py`（空）与 `rotation.py`**

`src/vcam_bridge/transform/__init__.py`:
```python
```

`src/vcam_bridge/transform/rotation.py`:
```python
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def euler_to_matrix(angles_deg: tuple[float, float, float], order: str) -> np.ndarray:
    """angles_deg are applied in the given intrinsic order (uppercase = intrinsic)."""
    return Rotation.from_euler(order, list(angles_deg), degrees=True).as_matrix()


def matrix_to_euler(R: np.ndarray, order: str) -> tuple[float, float, float]:
    e = Rotation.from_matrix(np.asarray(R, dtype=float)).as_euler(order, degrees=True)
    return (float(e[0]), float(e[1]), float(e[2]))
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_rotation.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/__init__.py src/vcam_bridge/transform/rotation.py tests/test_rotation.py
git commit -m "feat: euler<->matrix rotation utils (scipy)"
```

---

## Task 8: `transform/register.py`（Umeyama + 默认基变换）

**Files:**
- Create: `src/vcam_bridge/transform/register.py`
- Test: `tests/test_register.py`

- [ ] **Step 1: 写失败测试 `tests/test_register.py`**

```python
import numpy as np
from vcam_bridge.transform.register import umeyama, default_M, apply_M


def test_umeyama_recovers_known_similarity():
    rng = np.random.default_rng(0)
    src = rng.normal(size=(8, 3))
    s = 0.01
    R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)  # 90deg about z
    t = np.array([5.0, -2.0, 1.0])
    dst = (s * (R @ src.T)).T + t
    M = umeyama(src, dst)
    out = apply_M(M, src)
    assert np.allclose(out, dst, atol=1e-9)


def test_default_M_is_4x4_and_scales_cm_to_m():
    M = default_M()
    assert M.shape == (4, 4)
    out = apply_M(M, np.array([[100.0, 0.0, 0.0]]))   # 100 cm -> 1 m magnitude
    assert np.isclose(np.linalg.norm(out[0]), 1.0, atol=1e-9)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_register.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/transform/register.py`**

```python
from __future__ import annotations

import numpy as np


def umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Similarity transform (rotation + uniform scale + translation) mapping src->dst.
    src, dst: (N,3). Returns 4x4 homogeneous matrix. Kabsch/Umeyama with scale."""
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    n = src.shape[0]
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    sc = src - mu_s
    dc = dst - mu_d
    cov = (dc.T @ sc) / n
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[-1, -1] = -1.0
    R = U @ S @ Vt
    var_s = (sc ** 2).sum() / n
    scale = float(np.trace(np.diag(D) @ S) / var_s)
    t = mu_d - scale * (R @ mu_s)
    M = np.eye(4)
    M[:3, :3] = scale * R
    M[:3, 3] = t
    return M


def default_M() -> np.ndarray:
    """Fallback UE(LH, Z-up, cm) -> Disguise(Y-up, m) base transform.
    Starting point only; replaced by umeyama() result from P6 calibration."""
    scale = 0.01  # cm -> m
    # Z-up -> Y-up axis remap: (x, y, z)_ue -> (x, z, y)_dis
    A = np.array([[1, 0, 0],
                  [0, 0, 1],
                  [0, 1, 0]], dtype=float)
    M = np.eye(4)
    M[:3, :3] = scale * A
    return M


def apply_M(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=float)
    h = np.hstack([pts, np.ones((pts.shape[0], 1))])
    return (h @ np.asarray(M, dtype=float).T)[:, :3]
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_register.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/register.py tests/test_register.py
git commit -m "feat: umeyama similarity solver + default base transform"
```

---

## Task 9: `transform/decompose.py`（pivot-orbit 分解，含可逆性）

**Files:**
- Create: `src/vcam_bridge/transform/decompose.py`
- Test: `tests/test_decompose.py`

- [ ] **Step 1: 写失败测试 `tests/test_decompose.py`**

```python
import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector, decompose_pivot_orbit, recompose


def test_forward_vector_axes():
    assert np.allclose(forward_vector("+X"), [1, 0, 0])
    assert np.allclose(forward_vector("-Z"), [0, 0, -1])


def test_decompose_recompose_invertible():
    rng = np.random.default_rng(1)
    for _ in range(20):
        C = rng.normal(size=3)
        R = euler_to_matrix(tuple(rng.uniform(-80, 80, size=3)), "XYZ")
        d = float(rng.uniform(0.2, 5.0))
        pose = decompose_pivot_orbit(C, R, d, forward_axis="+X", euler_order="XYZ")
        C2, R2 = recompose(pose, forward_axis="+X", euler_order="XYZ")
        assert np.allclose(C2, C, atol=1e-6)
        assert np.allclose(R2, R, atol=1e-6)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_decompose.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/transform/decompose.py`**

```python
from __future__ import annotations

import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix, matrix_to_euler

_AXES = {"+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0],
         "-Y": [0, -1, 0], "+Z": [0, 0, 1], "-Z": [0, 0, -1]}


def forward_vector(axis: str) -> np.ndarray:
    if axis not in _AXES:
        raise ValueError(f"unknown forward axis: {axis}")
    return np.array(_AXES[axis], dtype=float)


def decompose_pivot_orbit(C: np.ndarray, R: np.ndarray, d: float, *,
                          forward_axis: str, euler_order: str) -> dict:
    """C: camera position (stage space, m). R: 3x3 world rotation. d: distance.
    Returns {pivot:(3,), rotation:(elev,head,roll) deg, distance:d}."""
    C = np.asarray(C, dtype=float)
    R = np.asarray(R, dtype=float)
    f = R @ forward_vector(forward_axis)
    pivot = C + d * f
    rot = matrix_to_euler(R, euler_order)
    return {"pivot": tuple(float(x) for x in pivot),
            "rotation": rot, "distance": float(d)}


def recompose(pose: dict, *, forward_axis: str, euler_order: str) -> tuple[np.ndarray, np.ndarray]:
    R = euler_to_matrix(pose["rotation"], euler_order)
    f = R @ forward_vector(forward_axis)
    pivot = np.asarray(pose["pivot"], dtype=float)
    C = pivot - pose["distance"] * f
    return C, R
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_decompose.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/decompose.py tests/test_decompose.py
git commit -m "feat: pivot-orbit decompose/recompose (invertible)"
```

---

## Task 10: `transform/fov.py`（H↔V 换算）

**Files:**
- Create: `src/vcam_bridge/transform/fov.py`
- Test: `tests/test_fov.py`

- [ ] **Step 1: 写失败测试 `tests/test_fov.py`**

```python
import math
from vcam_bridge.transform.fov import h_to_v, v_to_h, map_fov


def test_h_v_roundtrip():
    aspect = 16 / 9
    h = 90.0
    v = h_to_v(h, aspect)
    assert math.isclose(v_to_h(v, aspect), h, rel_tol=1e-9)
    assert v < h  # vertical FOV narrower for wide aspect


def test_map_fov_horizontal_passthrough():
    assert map_fov(75.0, fov_axis="horizontal", aspect=16 / 9) == 75.0


def test_map_fov_vertical_converts():
    out = map_fov(90.0, fov_axis="vertical", aspect=16 / 9)
    assert math.isclose(out, h_to_v(90.0, 16 / 9), rel_tol=1e-9)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_fov.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/transform/fov.py`**

```python
from __future__ import annotations

import math


def h_to_v(h_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(h_deg) / 2) / aspect))


def v_to_h(v_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(v_deg) / 2) * aspect))


def map_fov(h_fov_deg: float, *, fov_axis: str, aspect: float) -> float:
    """UE gives horizontal FOV. If the Disguise field is horizontal -> passthrough;
    if vertical -> convert. (Prior: Disguise VC field is 'Field of view (horizontal)'.)"""
    if fov_axis == "horizontal":
        return h_fov_deg
    if fov_axis == "vertical":
        return h_to_v(h_fov_deg, aspect)
    raise ValueError(f"unknown fov_axis: {fov_axis}")
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_fov.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/transform/fov.py tests/test_fov.py
git commit -m "feat: FOV horizontal<->vertical mapping"
```

---

## Task 11: `ingest/intermediate.py`（CSV/JSON → CameraTrack）

**Files:**
- Create: `src/vcam_bridge/ingest/__init__.py`
- Create: `src/vcam_bridge/ingest/intermediate.py`
- Create: `tests/conftest.py`
- Test: `tests/test_ingest_intermediate.py`

- [ ] **Step 1: 写夹具 `tests/conftest.py`**

```python
import json
import pytest


@pytest.fixture
def sample_track_json(tmp_path):
    data = {
        "fps": 30.0,
        "camera": "Cam",
        "frames": [
            {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0],
             "rotation_deg": [0, 0, 0], "fov_h_deg": 60.0, "focus_m": 2.0},
            {"idx": 1, "t_sec": 0.0333, "position": [100, 0, 0],
             "rotation_deg": [0, 10, 0], "fov_h_deg": 62.0, "focus_m": 2.5},
        ],
    }
    p = tmp_path / "track.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def sample_track_csv(tmp_path):
    p = tmp_path / "track.csv"
    p.write_text(
        "idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
        "0,0.0,0,0,0,0,0,0,60.0,2.0\n"
        "1,0.0333,100,0,0,0,10,0,62.0,2.5\n",
        encoding="utf-8",
    )
    return p
```

- [ ] **Step 2: 写失败测试 `tests/test_ingest_intermediate.py`**

```python
import numpy as np
import pytest
from vcam_bridge.ingest.intermediate import load_intermediate
from vcam_bridge.domain.errors import InvalidFbxError


def test_load_json(sample_track_json):
    tr = load_intermediate(str(sample_track_json), euler_order="XYZ")
    assert tr.fps == 30.0
    assert tr.camera == "Cam"
    assert len(tr.frames) == 2
    assert tr.frames[1].fov_h_deg == 62.0
    T = np.array(tr.frames[1].T)
    assert np.allclose(T[:3, 3], [100, 0, 0])   # translation preserved


def test_load_csv(sample_track_csv):
    tr = load_intermediate(str(sample_track_csv), euler_order="XYZ")
    assert len(tr.frames) == 2
    assert tr.frames[0].focus_m == 2.0


def test_missing_file_raises(tmp_path):
    with pytest.raises(InvalidFbxError):
        load_intermediate(str(tmp_path / "nope.json"), euler_order="XYZ")


def test_no_frames_raises(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text('{"fps": 30, "camera": "c", "frames": []}', encoding="utf-8")
    with pytest.raises(InvalidFbxError):
        load_intermediate(str(p), euler_order="XYZ")
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_ingest_intermediate.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 4: 写 `ingest/__init__.py`（空）与 `intermediate.py`**

`src/vcam_bridge/ingest/__init__.py`:
```python
```

`src/vcam_bridge/ingest/intermediate.py`:
```python
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from vcam_bridge.domain.errors import InvalidFbxError
from vcam_bridge.domain.models import CameraTrack, Frame
from vcam_bridge.transform.rotation import euler_to_matrix


def _frame_from_components(idx: int, t_sec: float, pos, rot_deg, fov_h_deg,
                           focus_m, euler_order: str) -> Frame:
    R = euler_to_matrix((float(rot_deg[0]), float(rot_deg[1]), float(rot_deg[2])), euler_order)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [float(pos[0]), float(pos[1]), float(pos[2])]
    return Frame(idx=int(idx), t_sec=float(t_sec), T=T.tolist(),
                 fov_h_deg=float(fov_h_deg),
                 focus_m=None if focus_m in (None, "") else float(focus_m))


def _load_json(path: Path, euler_order: str) -> CameraTrack:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = []
    for fr in data.get("frames", []):
        if "T" in fr:
            frames.append(Frame(idx=int(fr["idx"]), t_sec=float(fr["t_sec"]),
                                 T=fr["T"], fov_h_deg=float(fr["fov_h_deg"]),
                                 focus_m=fr.get("focus_m")))
        else:
            frames.append(_frame_from_components(
                fr["idx"], fr["t_sec"], fr["position"], fr["rotation_deg"],
                fr["fov_h_deg"], fr.get("focus_m"), euler_order))
    return CameraTrack(fps=float(data["fps"]), camera=str(data["camera"]), frames=frames)


def _load_csv(path: Path, euler_order: str) -> CameraTrack:
    frames = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            frames.append(_frame_from_components(
                row["idx"], row["t_sec"],
                (row["x"], row["y"], row["z"]),
                (row["rx"], row["ry"], row["rz"]),
                row["fov_h_deg"], row.get("focus_m"), euler_order))
    fps = 1.0 / (frames[1].t_sec - frames[0].t_sec) if len(frames) >= 2 and frames[1].t_sec > frames[0].t_sec else 30.0
    return CameraTrack(fps=round(fps), camera="Camera", frames=frames)


def load_intermediate(path: str, *, euler_order: str) -> CameraTrack:
    p = Path(path)
    if not p.exists():
        raise InvalidFbxError(f"intermediate file not found: {path}", details={"path": path})
    try:
        track = _load_csv(p, euler_order) if p.suffix.lower() == ".csv" else _load_json(p, euler_order)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidFbxError(f"failed to parse intermediate track: {exc}", details={"path": path}) from exc
    if not track.frames:
        raise InvalidFbxError("track has no frames", details={"path": path})
    return track
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_ingest_intermediate.py -q`
Expected: PASS（4 passed）

- [ ] **Step 6: Commit**

```bash
git add src/vcam_bridge/ingest/__init__.py src/vcam_bridge/ingest/intermediate.py tests/conftest.py tests/test_ingest_intermediate.py
git commit -m "feat: CSV/JSON intermediate FBX ingest -> CameraTrack"
```

---

## Task 12: `designer/codegen.py`（Py2.7 注入脚本生成 + F3 信任边界）

**Files:**
- Create: `src/vcam_bridge/designer/__init__.py`
- Create: `src/vcam_bridge/designer/codegen.py`
- Test: `tests/test_codegen.py`

- [ ] **Step 1: 写失败测试 `tests/test_codegen.py`**

```python
import ast
import json
import re
import pytest
from vcam_bridge.designer.codegen import (
    build_inject_script, validate_uid, validate_field_name, INJECT_BODY,
)


def _payload():
    return {
        "layer_uid": "0x1a2b",
        "fields": {"pivot.x": "camera_pivot.x", "fov": "fieldOfView"},
        "keys": [{"beat": 1.0, "values": {"pivot.x": 1.5, "fov": 60.0}}],
    }


def test_script_is_valid_python_and_embeds_payload_safely():
    script = build_inject_script(_payload())
    ast.parse(script)  # must be syntactically valid
    # the embedded payload must json-roundtrip exactly
    m = re.search(r"payload = json\.loads\((.*)\)\n", script)
    assert m
    embedded = ast.literal_eval(m.group(1))  # the python string literal
    assert json.loads(embedded) == _payload()


def test_injection_attempt_cannot_break_out():
    evil = dict(_payload())
    evil["fields"] = {"a\"b\n'); import os; os.system('x') #": "x"}
    script = build_inject_script(evil)
    ast.parse(script)                       # still valid python, no code escape
    m = re.search(r"payload = json\.loads\((.*)\)\n", script)
    assert json.loads(ast.literal_eval(m.group(1))) == evil


def test_body_has_no_forbidden_py3_constructs():
    tree = ast.parse(INJECT_BODY)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                                     ast.GeneratorExp, ast.NamedExpr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print"


def test_validate_uid():
    assert validate_uid("0x1a2b") == "0x1a2b"
    with pytest.raises(ValueError):
        validate_uid("0xZZ")
    with pytest.raises(ValueError):
        validate_uid("1a2b; drop")


def test_validate_field_name():
    assert validate_field_name("camera_pivot.x") == "camera_pivot.x"
    with pytest.raises(ValueError):
        validate_field_name('bad"name')
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_codegen.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `designer/__init__.py`（空）与 `codegen.py`**

`src/vcam_bridge/designer/__init__.py`:
```python
```

`src/vcam_bridge/designer/codegen.py`:
```python
from __future__ import annotations

import json
import re

_UID_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_FIELD_RE = re.compile(r"^[A-Za-z0-9_.]+$")

# Fixed Python 2.7 body. Reads only `payload`; no dynamic values are interpolated
# into code. Field names / uids are DATA passed to findSequence / uid lookup.
# Must stay Py2.7-safe: no comprehensions, no walrus, no print().
INJECT_BODY = '''
local_state = state.localOrDirectorState()
track = local_state.track
target = None
for l in track.layers:
    if hex(l.uid) == payload["layer_uid"]:
        target = l
        break
if target is None:
    result = {"ok": False, "error": "layer not found"}
else:
    fieldmap = payload["fields"]
    seqs = {}
    missing = []
    for key in fieldmap:
        fs = target.findSequence(fieldmap[key])
        if fs is None:
            missing.append(fieldmap[key])
        else:
            fs.disableSequencing = False
            seqs[key] = fs
    if missing:
        result = {"ok": False, "error": "missing fields", "missing": missing}
    else:
        written = 0
        for kf in payload["keys"]:
            beat = kf["beat"]
            vals = kf["values"]
            for key in vals:
                seqs[key].sequence.setFloat(beat, vals[key])
                written = written + 1
        result = {"ok": True, "written": written}
'''


def validate_uid(uid: str) -> str:
    if not _UID_RE.match(uid):
        raise ValueError(f"invalid uid (must be 0x-hex): {uid!r}")
    return uid


def validate_field_name(name: str) -> str:
    if not _FIELD_RE.match(name):
        raise ValueError(f"invalid field name: {name!r}")
    return name


def build_inject_script(payload: dict) -> str:
    """Generate a Py2.7 injection script. All dynamic data enters ONLY via a single
    json.loads of a safely-escaped string literal; nothing is concatenated as code."""
    validate_uid(payload["layer_uid"])
    for key, decorated in payload["fields"].items():
        validate_field_name(decorated)
    json_str = json.dumps(payload)
    header = "import json\npayload = json.loads(" + repr(json_str) + ")\n"
    return header + INJECT_BODY + "\nreturn json.dumps(result)\n"
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_codegen.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/designer/__init__.py src/vcam_bridge/designer/codegen.py tests/test_codegen.py
git commit -m "feat: Py2.7 inject codegen with JSON trust boundary + validators"
```

---

## Task 13: `cli/runtime.py` + `cli/render.py`（运行时 + 信封渲染）

**Files:**
- Create: `src/vcam_bridge/cli/__init__.py`
- Create: `src/vcam_bridge/cli/runtime.py`
- Create: `src/vcam_bridge/cli/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: 写失败测试 `tests/test_render.py`**

```python
import json
from vcam_bridge.cli import runtime, render
from vcam_bridge.envelope import success_envelope


def test_resolve_output_precedence():
    assert runtime.resolve_output("json", ai_agent_env=False, is_tty=True) == "json"
    assert runtime.resolve_output(None, ai_agent_env=True, is_tty=False) == "json"
    assert runtime.resolve_output(None, ai_agent_env=False, is_tty=True) == "text"
    assert runtime.resolve_output(None, ai_agent_env=False, is_tty=False) == "text"


def test_request_id_and_timestamp():
    rid = runtime.new_request_id()
    assert len(rid) >= 8
    ts = runtime.utc_now_iso()
    assert ts.endswith("Z")


def test_render_success_json_is_parseable():
    env = success_envelope("convert", {"n": 1}, request_id="r", duration_ms=1,
                           timestamp="2026-06-03T00:00:00Z")
    out = render.render_success(env, "json")
    assert json.loads(out)["data"]["n"] == 1


def test_render_success_text_is_human():
    env = success_envelope("convert", {"n": 1}, request_id="r", duration_ms=1,
                           timestamp="2026-06-03T00:00:00Z")
    out = render.render_success(env, "text")
    assert "convert" in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_render.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `cli/__init__.py`（空）、`runtime.py`、`render.py`**

`src/vcam_bridge/cli/__init__.py`:
```python
```

`src/vcam_bridge/cli/runtime.py`:
```python
from __future__ import annotations

import datetime
import uuid


def new_request_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_output(explicit: str | None, *, ai_agent_env: bool, is_tty: bool) -> str:
    if explicit:
        return explicit
    if ai_agent_env:
        return "json"
    return "text"
```

`src/vcam_bridge/cli/render.py`:
```python
from __future__ import annotations

import json
from typing import Any


def _text_success(env: dict[str, Any]) -> str:
    lines = [f"[ok] {env['operation_id']} ({env['meta']['duration_ms']}ms)"]
    data = env.get("data", {})
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(v, (dict, list)):
                lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _text_error(env: dict[str, Any]) -> str:
    err = env["error"]
    return f"[error] {env['operation_id']}: {err['code']} (exit {err['exit_code']}) - {err['message']}"


def render_success(env: dict[str, Any], fmt: str) -> str:
    if fmt in ("json", "ndjson"):
        return json.dumps(env, ensure_ascii=False)
    return _text_success(env)


def render_error(env: dict[str, Any], fmt: str) -> str:
    if fmt in ("json", "ndjson"):
        return json.dumps(env, ensure_ascii=False)
    return _text_error(env)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_render.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/cli/__init__.py src/vcam_bridge/cli/runtime.py src/vcam_bridge/cli/render.py tests/test_render.py
git commit -m "feat: cli runtime + envelope rendering (text/json)"
```

---

## Task 14: `cli/commands/meta.py`（manifest/version/schema）

**Files:**
- Create: `src/vcam_bridge/cli/commands/__init__.py`
- Create: `src/vcam_bridge/cli/commands/meta.py`
- Test: 扩展 `tests/test_manifest.py`（新增 meta 命令断言）

- [ ] **Step 1: 在 `tests/test_manifest.py` 末尾追加失败测试**

```python


def test_meta_commands_return_operation_and_data():
    from vcam_bridge.cli.commands import meta
    op, data = meta.manifest()
    assert op == "meta.manifest"
    assert data["contract_version"] == "1.0"
    op2, data2 = meta.version()
    assert op2 == "meta.version"
    assert "version" in data2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_manifest.py::test_meta_commands_return_operation_and_data -q`
Expected: FAIL（`ModuleNotFoundError: vcam_bridge.cli.commands`）

- [ ] **Step 3: 写 `cli/commands/__init__.py`（空）与 `meta.py`**

`src/vcam_bridge/cli/commands/__init__.py`:
```python
```

`src/vcam_bridge/cli/commands/meta.py`:
```python
from __future__ import annotations

from typing import Any
from vcam_bridge import __version__
from vcam_bridge.manifest import build_manifest


def manifest() -> tuple[str, Any]:
    return "meta.manifest", build_manifest()


def version() -> tuple[str, Any]:
    return "meta.version", {"name": "vcam-bridge", "version": __version__}


def schema() -> tuple[str, Any]:
    return "meta.schema", {"operations": [op["operation_id"] for op in build_manifest()["operations"]]}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_manifest.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/cli/commands/__init__.py src/vcam_bridge/cli/commands/meta.py tests/test_manifest.py
git commit -m "feat: meta commands (manifest/version/schema)"
```

---

## Task 15: `cli/commands/convert.py`（convert --dry-run 编排）

**Files:**
- Create: `src/vcam_bridge/cli/commands/convert.py`
- Test: `tests/test_cli_convert.py`（单元部分）

- [ ] **Step 1: 写失败测试 `tests/test_cli_convert.py`**

```python
from vcam_bridge.cli.commands.convert import convert_dry_run
from vcam_bridge.config import load_config


def test_convert_dry_run_builds_plan(sample_track_json):
    cfg = load_config(None)
    op, data = convert_dry_run(str(sample_track_json), config=cfg,
                               layer_uid="0xabc", fov_axis="horizontal")
    assert op == "convert"
    plan = data["dry_run_plan"]
    assert plan["frame_count"] == 2
    assert len(plan["keyframes"]) == 2
    kf0 = plan["keyframes"][0]
    assert set(kf0.keys()) >= {"idx", "t_sec", "pivot", "rotation", "distance", "fov"}
    # injection script generated and references the layer uid as data
    assert "0xabc" in data["inject_script"]
    assert "json.loads" in data["inject_script"]


def test_convert_dry_run_fov_horizontal_passthrough(sample_track_json):
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg,
                              layer_uid="0xabc", fov_axis="horizontal")
    assert data["dry_run_plan"]["keyframes"][0]["fov"] == 60.0
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_cli_convert.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写 `src/vcam_bridge/cli/commands/convert.py`**

```python
from __future__ import annotations

from typing import Any
import numpy as np

from vcam_bridge.config import load_config  # noqa: F401 (re-exported convenience)
from vcam_bridge.domain.models import Config
from vcam_bridge.ingest.intermediate import load_intermediate
from vcam_bridge.transform.register import default_M, apply_M
from vcam_bridge.transform.decompose import decompose_pivot_orbit
from vcam_bridge.transform.fov import map_fov
from vcam_bridge.designer.codegen import build_inject_script


def _stage_pose_for_frame(T_ue: np.ndarray, M: np.ndarray, cal) -> tuple[np.ndarray, np.ndarray]:
    """Apply M_ue2dis to the camera position and rotation. Returns (C_stage, R_stage)."""
    C_ue = T_ue[:3, 3]
    C_stage = apply_M(M, C_ue.reshape(1, 3))[0]
    # rotation part of M (drop scale) applied to camera basis
    Rm = M[:3, :3]
    scale = float(np.cbrt(np.linalg.det(Rm)))
    R_only = Rm / scale if scale != 0 else Rm
    R_stage = R_only @ T_ue[:3, :3]
    return C_stage, R_stage


def convert_dry_run(fbx_or_intermediate: str, *, config: Config,
                    layer_uid: str, fov_axis: str | None = None,
                    pivot_distance_const: float | None = None) -> tuple[str, Any]:
    cal = config.calibration
    fov_axis = fov_axis or cal.fov_axis
    track = load_intermediate(fbx_or_intermediate, euler_order=cal.euler_order)
    M = np.array(cal.M_ue2dis, dtype=float) if cal.M_ue2dis else default_M()

    keyframes = []
    keys_payload = []
    for fr in track.frames:
        T_ue = np.array(fr.T, dtype=float)
        C, R = _stage_pose_for_frame(T_ue, M, cal)
        d = pivot_distance_const if pivot_distance_const is not None else (fr.focus_m or 1.0)
        pose = decompose_pivot_orbit(C, R, d, forward_axis=cal.forward_axis,
                                     euler_order=cal.euler_order)
        fov = map_fov(fr.fov_h_deg, fov_axis=fov_axis, aspect=cal.aspect)
        keyframes.append({
            "idx": fr.idx, "t_sec": fr.t_sec,
            "pivot": pose["pivot"], "rotation": pose["rotation"],
            "distance": pose["distance"], "fov": fov,
        })
        # beat is resolved live at inject time (needs track.timeToBeat); use t_sec here
        keys_payload.append({"beat_from_t_sec": fr.t_sec,
                             "values": {"fov": fov, "distance": pose["distance"]}})

    field_map = cal.field_map or {"fov": "fieldOfView", "distance": "distance"}
    inject_payload = {"layer_uid": layer_uid, "fields": field_map, "keys": []}
    inject_script = build_inject_script(inject_payload)

    data = {
        "dry_run_plan": {
            "frame_count": len(track.frames),
            "fps": track.fps,
            "fov_axis": fov_axis,
            "keyframes": keyframes,
            "note": "beat values are resolved live via track.timeToBeat at inject time",
        },
        "inject_script": inject_script,
    }
    return "convert", data
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_cli_convert.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/vcam_bridge/cli/commands/convert.py tests/test_cli_convert.py
git commit -m "feat: convert --dry-run orchestration (ingest->transform->decompose->fov->codegen)"
```

---

## Task 16: `cli/main.py`（argparse + dispatch + 全局 flag）

**Files:**
- Create: `src/vcam_bridge/cli/main.py`
- Test: 扩展 `tests/test_cli_convert.py`（端到端 main()）

- [ ] **Step 1: 在 `tests/test_cli_convert.py` 末尾追加失败测试**

```python


def test_main_convert_dry_run_json(sample_track_json, capsys):
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(sample_track_json),
               "--target-uid", "0xabc", "--dry-run", "--output", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    import json
    env = json.loads(out)
    assert env["status"] == "ok"
    assert env["operation_id"] == "convert"
    assert env["data"]["dry_run_plan"]["frame_count"] == 2


def test_main_manifest_json(capsys):
    from vcam_bridge.cli.main import main
    rc = main(["manifest", "--output", "json"])
    assert rc == 0
    import json
    env = json.loads(capsys.readouterr().out)
    assert env["data"]["contract_version"] == "1.0"


def test_main_bad_args_exit_2(capsys):
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--output", "json"])   # missing required --fbx
    assert rc == 2
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd vcam-bridge && uv run pytest tests/test_cli_convert.py -k main -q`
Expected: FAIL（`ModuleNotFoundError: vcam_bridge.cli.main`）

- [ ] **Step 3: 写 `src/vcam_bridge/cli/main.py`**

```python
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from vcam_bridge.cli import render, runtime
from vcam_bridge.cli.commands import meta as meta_cmd
from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import VcamError
from vcam_bridge.envelope import EXIT_OK, EXIT_USAGE, error_envelope, success_envelope


def _add_global(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    def d(v: Any) -> Any:
        return argparse.SUPPRESS if suppress else v
    parser.add_argument("--output", "-o", choices=["text", "json", "ndjson", "stream-json"], default=d(None))
    parser.add_argument("--director", default=d(None))
    parser.add_argument("--config", default=d(None))
    parser.add_argument("--dry-run", action="store_true", default=d(False))
    parser.add_argument("--yes", "-y", action="store_true", default=d(False))
    parser.add_argument("--no-input", action="store_true", default=d(False))
    parser.add_argument("--no-color", action="store_true", default=d(False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vcam", description="UE FBX camera -> Disguise ACC injector")
    _add_global(parser)
    gp = argparse.ArgumentParser(add_help=False)
    _add_global(gp, suppress=True)
    sub = parser.add_subparsers(dest="command")

    p_conv = sub.add_parser("convert", parents=[gp])
    p_conv.add_argument("--fbx", required=True)
    p_conv.add_argument("--target-uid", required=True)
    p_conv.add_argument("--vc-uid", default=None)
    p_conv.add_argument("--pivot-distance", default=None)

    sub.add_parser("manifest", parents=[gp])
    sub.add_parser("version", parents=[gp])
    sub.add_parser("schema", parents=[gp])
    return parser


def _normalize_fmt(fmt: str) -> str:
    return "ndjson" if fmt == "stream-json" else fmt


def _dispatch(args: argparse.Namespace) -> tuple[str, Any]:
    if args.command == "manifest":
        return meta_cmd.manifest()
    if args.command == "version":
        return meta_cmd.version()
    if args.command == "schema":
        return meta_cmd.schema()
    if args.command == "convert":
        cfg = load_config(args.config)
        const = None
        if args.pivot_distance and args.pivot_distance.startswith("const="):
            const = float(args.pivot_distance.split("=", 1)[1])
        if not args.dry_run:
            from vcam_bridge.domain.errors import ConfigError
            raise ConfigError("live injection is implemented in Plan 2; use --dry-run")
        from vcam_bridge.cli.commands import convert as convert_cmd
        return convert_cmd.convert_dry_run(args.fbx, config=cfg, layer_uid=args.target_uid,
                                           pivot_distance_const=const)
    raise VcamError("no command given")


def _op_id(args: argparse.Namespace) -> str:
    return {"manifest": "meta.manifest", "version": "meta.version",
            "schema": "meta.schema", "convert": "convert"}.get(args.command, "INTERNAL")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ai_agent = os.environ.get("AI_AGENT") == "1"
    request_id = runtime.new_request_id()
    timestamp = runtime.utc_now_iso()
    started = time.monotonic()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    fmt = _normalize_fmt(runtime.resolve_output(args.output, ai_agent_env=ai_agent,
                                                is_tty=sys.stdout.isatty()))
    op_id = _op_id(args)
    try:
        op, data = _dispatch(args)
        env = success_envelope(op, data, request_id=request_id,
                               duration_ms=int((time.monotonic() - started) * 1000),
                               timestamp=timestamp)
        sys.stdout.write(render.render_success(env, fmt) + "\n")
        return EXIT_OK
    except VcamError as exc:
        env = error_envelope(op_id, code=exc.code, exit_code=exc.exit_code,
                             message=exc.message, retryable=exc.retryable, details=exc.details,
                             request_id=request_id,
                             duration_ms=int((time.monotonic() - started) * 1000),
                             timestamp=timestamp)
        sys.stdout.write(render.render_error(env, fmt) + "\n")
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd vcam-bridge && uv run pytest tests/test_cli_convert.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 端到端冒烟（CLI 真跑）**

Run:
```bash
cd vcam-bridge && printf 'idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n0,0,0,0,0,0,0,0,60,2\n1,0.033,100,0,0,0,10,0,62,2.5\n' > /tmp/t.csv && uv run vcam convert --fbx /tmp/t.csv --target-uid 0xabc --dry-run --output json | python -c "import sys,json;print(json.load(sys.stdin)['data']['dry_run_plan']['frame_count'])"
```
Expected: 打印 `2`

- [ ] **Step 6: Commit**

```bash
git add src/vcam_bridge/cli/main.py tests/test_cli_convert.py
git commit -m "feat: cli main (argparse + dispatch + envelope output)"
```

---

## Task 17: 全量测试 + manifest 一致性 + README 更新

**Files:**
- Test: `tests/test_cli_consistency.py`
- Modify: `vcam-bridge/README.md`

- [ ] **Step 1: 写一致性测试 `tests/test_cli_consistency.py`**

```python
from vcam_bridge.cli.main import build_parser
from vcam_bridge.manifest import build_manifest


def test_cli_subcommands_subset_of_manifest():
    parser = build_parser()
    sub_actions = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    cli_cmds = set(sub_actions[0].choices.keys())
    manifest_ops = {op["operation_id"] for op in build_manifest()["operations"]}
    # each implemented CLI command maps to a manifest operation_id
    mapping = {"convert": "convert", "manifest": "meta.manifest",
               "version": "meta.version", "schema": "meta.schema"}
    for cmd in cli_cmds:
        assert mapping[cmd] in manifest_ops
```

- [ ] **Step 2: 运行测试，确认失败（或通过——若已成立则跳到 Step 4）**

Run: `cd vcam-bridge && uv run pytest tests/test_cli_consistency.py -q`
Expected: PASS（映射已成立；此测试锁定 CLI↔manifest 不漂移）

- [ ] **Step 3: 全量测试 + 覆盖率**

Run: `cd vcam-bridge && uv run pytest -q`
Expected: 全部 PASS（约 30+ 测试）

- [ ] **Step 4: 更新 README 用法**

在 `vcam-bridge/README.md` 追加：
```markdown

## Usage (Plan 1 — offline dry-run)

```bash
uv venv && uv pip install -e ".[dev]"
uv run vcam convert --fbx track.csv --target-uid 0x1a2b --dry-run --output json
uv run vcam manifest --output json
```

`--dry-run` 算出 ACC pivot/rotation/distance/FOV 并生成 Py2.7 注入脚本，不触真机。
真机注入/probe（连接层、P0–P10、Blender 原生 FBX、Skill）见 Plan 2。
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli_consistency.py README.md
git commit -m "test: cli<->manifest consistency; docs: usage"
```

---

## Self-Review（写完后自查结果）

**1. Spec 覆盖（Plan 1 范围内）**：
- §3 架构分层 → Tasks 1-16 文件结构 ✓
- §4 数据模型 → Task 4 ✓
- §5.2 FBX ingest（CSV/JSON fallback 部分） → Task 11 ✓（Blender 原生 → Plan 2）
- §5.3 transform/decompose/fov → Tasks 7-10 ✓
- §5.4(a)(b) codegen 信任边界 + Py2.7-safe → Task 12 ✓（分块执行/超时续写属真机 → Plan 2）
- §7.1 完整 Contract Manifest（F4） → Task 6 ✓
- §7.4 输出契约 text/json → Tasks 13,16 ✓
- §7.5 退出码 → Task 2 ✓
- §9 单测（分解可逆/Umeyama/FOV/codegen 安全/manifest 一致性） → Tasks 7-12,17 ✓
- **明确不在 Plan 1**：§5.1 连接层、§5.5 枚举、§5.4(c)(d) 分块执行、§5.7 P10、§6 probe、§7.6 Skill → 全部 Plan 2。

**2. 占位符扫描**：无 TBD/TODO；每个 code step 含完整可运行代码。

**3. 类型一致性**：`CameraTrack/Frame/StagePose/Calibration/Config`（Task 4）在 Tasks 11/15 一致引用；`build_inject_script`/`validate_uid`/`validate_field_name`（Task 12）在 Task 15 一致；`success_envelope/error_envelope`（Task 2）在 Tasks 13/16 一致；`load_config`（Task 5）在 Tasks 15/16 一致；`decompose_pivot_orbit`/`map_fov`/`apply_M`/`default_M`（Tasks 8-10）在 Task 15 一致。

> 注：`convert` 的 dry-run keyframes 不含 `beat`（需真机 `track.timeToBeat`），已在 plan/note 中标明 beat 在 Plan 2 注入时解析；这与 spec §5.6 一致。

"""Layer 3 — Simulated real-machine tests using FakeTransport replay.
No Designer hardware needed; exercises the full live path with synthetic fixtures."""

import json
import math
import numpy as np
import pytest

from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import inject_keys, chunk_keys
from vcam_bridge.cli.commands.convert import convert_live, build_keyframes
from vcam_bridge.config import load_config
from vcam_bridge.domain.errors import DesignerTimeoutError, PartialError
from vcam_bridge.domain.models import Config, Calibration
from vcam_bridge.transform.convention import solve_convention
from vcam_bridge.transform.register import umeyama
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector, decompose_pivot_orbit


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def _solo():
    return {"/api/session/status/session": {"isRunningSolo": True}}


# ---------- 3.1 build_calibration from synthetic convention samples ----------

def _synth_convention_samples(fwd="+X", order="XYZ", n=8, seed=42):
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n):
        pivot = rng.normal(size=3) * 3
        rot = tuple(rng.uniform(-60, 60, size=3))
        dist = float(rng.uniform(0.5, 3.0))
        R = euler_to_matrix(rot, order)
        f = R @ forward_vector(fwd)
        C = np.asarray(pivot) - dist * f
        samples.append({
            "written": {"pivot": tuple(pivot), "rotation": rot, "distance": dist},
            "world": {"position": tuple(C), "rotation_matrix": R.tolist()},
        })
    return samples


def test_synthetic_convention_solve():
    """3.1 — solve_convention recovers the correct convention from synthetic samples."""
    samples = _synth_convention_samples("+X", "XYZ")
    result = solve_convention(samples)
    assert result["forward_axis"] == "+X"
    assert result["euler_order"] == "XYZ"
    assert result["pos_error"] < 1e-6
    assert result["rot_error"] < 1e-6


def test_synthetic_umeyama_calibration():
    """3.1 — Umeyama from UE positions → stage positions (identity mapping, same points)."""
    rng = np.random.default_rng(42)
    scale = 0.01
    R_true = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
    t_true = np.array([1.0, 2.0, 3.0])
    src = rng.normal(size=(10, 3)) * 100
    dst = (scale * (R_true @ src.T)).T + t_true
    M = umeyama(src, dst)
    from vcam_bridge.transform.register import apply_M
    out = apply_M(M, src)
    residuals = np.linalg.norm(out - dst, axis=1)
    assert residuals.max() < 1e-6


# ---------- 3.5 convert_live full flow ----------

def test_convert_live_full_flow(tmp_path):
    """3.5 — Full live path: resolve routing → set target → inject 2 chunks → return."""
    p = tmp_path / "t.csv"
    p.write_text("idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n" +
                 "\n".join(f"{i},{i/30.0},{i*10},0,0,0,{i},0,60,2" for i in range(10)))
    ft = FakeTransport(
        json_responses=_solo(),
        execute_responses=[
            _ok('{"ok": true, "note": ["camera-target-set"]}'),  # set target
            _ok('{"ok": true, "written": 40}'),  # chunk 1
            _ok('{"ok": true, "written": 40}'),  # chunk 2
        ],
    )
    op, data = convert_live(ft, host="localhost", fbx=str(p), config=load_config(None),
                            layer_uid="0xabc", vc_uid="0xdef", chunk_size=5)
    assert op == "convert"
    assert data["written"] == 80
    assert data["frames"] == 10
    assert data["target_setup"]["ok"] is True
    assert len(ft.executed) == 3  # set-target + 2 chunks


# ---------- 3.8 timeout bisect-retry → full write ----------

def test_timeout_bisect_then_succeed(tmp_path):
    """3.8 — chunk1 ok, chunk2 timeout → bisect into 2 sub-chunks → all keys written."""
    keys = [{"t_sec": i * 0.1, "values": {"fov": 60.0 + i}} for i in range(20)]
    timeout = {"status": {"code": 1, "message": "TimeoutError: script"}, "returnValue": "null",
               "d3Log": "", "pythonLog": ""}
    ft = FakeTransport(execute_responses=[
        _ok('{"ok": true, "written": 10}'),   # chunk 1 (keys 0-9) ok
        timeout,                                # chunk 2 (keys 10-19) timeout
        _ok('{"ok": true, "written": 5}'),     # sub-chunk 2a (keys 10-14) ok
        _ok('{"ok": true, "written": 5}'),     # sub-chunk 2b (keys 15-19) ok
    ])
    c = DesignerClient(ft, "localhost")
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=keys,
                          start_offset_sec=0.0, chunk_size=10)
    assert written == 20
    assert len(ft.executed) == 4


def test_double_timeout_cascading_bisect():
    """3.8 edge — two cascading timeouts, bisect down twice then succeed."""
    keys = [{"t_sec": i * 0.1, "values": {"fov": 60.0}} for i in range(16)]
    timeout = {"status": {"code": 1, "message": "TimeoutError"}, "returnValue": "null",
               "d3Log": "", "pythonLog": ""}
    ft = FakeTransport(execute_responses=[
        timeout,                                # 16 keys timeout
        timeout,                                # 8 keys timeout (first half)
        _ok('{"ok": true, "written": 4}'),     # 4 keys ok
        _ok('{"ok": true, "written": 4}'),     # 4 keys ok
        _ok('{"ok": true, "written": 8}'),     # 8 keys ok (second half)
    ])
    c = DesignerClient(ft, "localhost")
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=keys,
                          start_offset_sec=0.0, chunk_size=16, min_chunk=4)
    assert written == 16


# ---------- 3.5+3.6 convert_live with director routing ----------

def test_convert_live_director_routing(tmp_path):
    """3.5 — Non-solo session routes to director hostname."""
    p = tmp_path / "t.csv"
    p.write_text("idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
                 "0,0.0,0,0,0,0,0,0,60,1\n"
                 "1,0.033,100,0,0,0,0,0,60,1\n")
    ft = FakeTransport(
        json_responses={"/api/session/status/session":
                        {"isRunningSolo": False, "director": {"hostname": "10.0.0.1"}}},
        execute_responses=[
            _ok('{"ok": true, "note": []}'),
            _ok('{"ok": true, "written": 16}'),
        ],
    )
    op, data = convert_live(ft, host="localhost:80", fbx=str(p), config=load_config(None),
                            layer_uid="0xabc", vc_uid="0xdef", chunk_size=100)
    assert data["written"] == 16
    assert ft.executed[0]["host"] == "10.0.0.1:80"


# ---------- 3.1 convention solver edge: all 6 forward axes ----------

@pytest.mark.parametrize("fwd,order", [
    ("+X", "XYZ"), ("-X", "ZYX"), ("+Y", "YXZ"), ("-Y", "XZY"), ("+Z", "ZXY"), ("-Z", "YZX"),
])
def test_convention_solver_all_axes(fwd, order):
    """3.1 — Verify convention solver works for all 6 forward axes."""
    samples = _synth_convention_samples(fwd, order, n=10)
    result = solve_convention(samples)
    assert result["forward_axis"] == fwd
    assert result["euler_order"] == order
    assert result["pos_error"] < 1e-5


# ---------- 3.5 build_keyframes consistency ----------

def test_build_keyframes_all_canonical_fields(tmp_path):
    """3.5 — build_keyframes produces all 8 canonical field values per key."""
    p = tmp_path / "t.json"
    import json as _json
    p.write_text(_json.dumps({"fps": 30, "camera": "Cam", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 2.0}]}))
    from vcam_bridge.ingest.intermediate import load_intermediate
    track = load_intermediate(str(p), euler_order="XYZ")
    cfg = load_config(None)
    field_map, keys, keyframes = build_keyframes(track, cfg)
    assert len(keys) == 1
    vals = keys[0]["values"]
    for canon in ("pivot.x", "pivot.y", "pivot.z", "rotation.x", "rotation.y",
                  "rotation.z", "distance", "fov"):
        assert canon in vals, f"missing canonical key {canon}"
        assert isinstance(vals[canon], float), f"{canon} is not float"

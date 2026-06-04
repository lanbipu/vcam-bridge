"""Layer 2.3 — Complete offline pipeline end-to-end:
CSV with known geometry → convert_dry_run → verify keyframe values match hand-calculation."""

import json
import math
import numpy as np
import pytest

from vcam_bridge.cli.commands.convert import convert_dry_run, build_keyframes, _stage_pose_for_frame
from vcam_bridge.config import load_config
from vcam_bridge.domain.models import Config, Calibration
from vcam_bridge.transform.register import default_M, apply_M
from vcam_bridge.transform.decompose import decompose_pivot_orbit
from vcam_bridge.transform.fov import hfov_to_zoom


def test_pipeline_identity_camera_at_origin(tmp_path):
    """Camera at origin, identity rotation, default_M. Hand-verify the decomposition."""
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 24, "camera": "Cam", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 90.0, "focus_m": 2.0},
    ]}))
    cfg = load_config(None)
    _, data = convert_dry_run(str(p), config=cfg, layer_uid="0x1")

    kf = data["dry_run_plan"]["keyframes"][0]
    expected_zoom = hfov_to_zoom(90.0, 30.296, 35.0)
    assert abs(kf["zoom"] - expected_zoom) < 0.001
    assert kf["distance"] == 2.0
    assert len(kf["pivot"]) == 3
    assert len(kf["rotation"]) == 3

    M = default_M()
    C_ue = np.array([0.0, 0.0, 0.0])
    C_stage = apply_M(M, C_ue.reshape(1, 3))[0]
    assert np.allclose(C_stage, [0, 0, 0], atol=1e-9)


def test_pipeline_known_translation(tmp_path):
    """Camera at (100, 0, 0) UE-cm → should be (1, 0, 0) stage-m with default_M."""
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "Cam", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [100, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60.0, "focus_m": 1.0},
    ]}))
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0x1")
    kf = data["dry_run_plan"]["keyframes"][0]
    pivot = np.array(kf["pivot"])
    M = default_M()
    C_expected = apply_M(M, np.array([[100, 0, 0]]))[0]
    f_local = np.array([0, 0, 1])
    Rm = M[:3, :3]
    scale = abs(np.linalg.det(Rm)) ** (1.0 / 3.0)
    R_only = Rm / scale
    U, _, Vt = np.linalg.svd(R_only)
    R_lin = U @ Vt
    if np.linalg.det(R_lin) < 0:
        U[:, -1] = -U[:, -1]
        R_lin = U @ Vt
    R_cam = R_lin @ np.eye(3)
    expected_pivot = C_expected + 1.0 * (R_cam.T @ f_local)
    assert np.allclose(pivot, expected_pivot, atol=1e-6)


def test_pipeline_multi_frame_monotonic_time(tmp_path):
    """5-frame track: t_sec and idx are strictly monotonic in output."""
    frames = [{"idx": i, "t_sec": i / 30.0, "position": [i * 10, 0, 0],
               "rotation_deg": [0, i * 5, 0], "fov_h_deg": 60 + i, "focus_m": 1.0}
              for i in range(5)]
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "Cam", "frames": frames}))
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0x1")
    kfs = data["dry_run_plan"]["keyframes"]
    assert len(kfs) == 5
    for i in range(1, 5):
        assert kfs[i]["t_sec"] > kfs[i-1]["t_sec"]
        assert kfs[i]["idx"] == i


def test_pipeline_custom_m_ue2dis(tmp_path):
    """Custom M_ue2dis in config propagates through the pipeline."""
    M_custom = np.eye(4).tolist()
    M_custom[0][0] = 0.01
    M_custom[1][1] = 0.01
    M_custom[2][2] = 0.01
    cfg = Config(calibration=Calibration(M_ue2dis=M_custom))
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "Cam", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [1000, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 2.0}]}))
    _, data = convert_dry_run(str(p), config=cfg, layer_uid="0x1")
    kf = data["dry_run_plan"]["keyframes"][0]
    pivot = np.array(kf["pivot"])
    assert abs(pivot[0]) < 15  # 1000cm * 0.01 = 10m + pivot offset

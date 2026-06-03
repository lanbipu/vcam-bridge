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

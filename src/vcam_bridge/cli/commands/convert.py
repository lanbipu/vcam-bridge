from __future__ import annotations

from typing import Any
import numpy as np

from vcam_bridge.domain.models import Config
from vcam_bridge.ingest.intermediate import load_intermediate
from vcam_bridge.transform.register import default_M, apply_M
from vcam_bridge.transform.decompose import decompose_pivot_orbit
from vcam_bridge.transform.fov import map_fov
from vcam_bridge.designer.codegen import build_inject_script


def _stage_pose_for_frame(T_ue: np.ndarray, M: np.ndarray, cal) -> tuple[np.ndarray, np.ndarray]:
    """Apply M_ue2dis to the camera position and rotation. Returns (C_stage, R_stage).
    Extracts the nearest PROPER rotation via SVD so a reflection/handedness component
    in M never silently mirrors the orientation."""
    C_ue = T_ue[:3, 3]
    C_stage = apply_M(M, C_ue.reshape(1, 3))[0]
    Rm = M[:3, :3]
    det = np.linalg.det(Rm)
    scale = abs(det) ** (1.0 / 3.0)
    A = Rm / scale
    U, _, Vt = np.linalg.svd(A)
    R_lin = U @ Vt
    if np.linalg.det(R_lin) < 0:
        U[:, -1] = -U[:, -1]
        R_lin = U @ Vt
    R_stage = R_lin @ T_ue[:3, :3]
    return C_stage, R_stage


def convert_dry_run(fbx_or_intermediate: str, *, config: Config,
                    layer_uid: str, fov_axis: str | None = None,
                    pivot_distance_const: float | None = None) -> tuple[str, Any]:
    cal = config.calibration
    fov_axis = fov_axis or cal.fov_axis
    track = load_intermediate(fbx_or_intermediate, euler_order=cal.euler_order)
    M = np.array(cal.M_ue2dis, dtype=float) if cal.M_ue2dis else default_M()

    keyframes = []
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

    field_map = cal.field_map or {
        "pivot.x": "camera_pivot.x", "pivot.y": "camera_pivot.y", "pivot.z": "camera_pivot.z",
        "rotation.x": "camera_rotation.x", "rotation.y": "camera_rotation.y",
        "rotation.z": "camera_rotation.z", "distance": "distance", "fov": "fieldOfView",
    }
    keys = []
    for kf in keyframes:
        keys.append({
            "t_sec": kf["t_sec"],
            "values": {
                "pivot.x": kf["pivot"][0], "pivot.y": kf["pivot"][1], "pivot.z": kf["pivot"][2],
                "rotation.x": kf["rotation"][0], "rotation.y": kf["rotation"][1],
                "rotation.z": kf["rotation"][2], "distance": kf["distance"], "fov": kf["fov"],
            },
        })
    inject_payload = {"layer_uid": layer_uid, "start_offset_sec": 0.0,
                      "fields": field_map, "keys": keys}
    inject_script = build_inject_script(inject_payload)

    data = {
        "dry_run_plan": {
            "frame_count": len(track.frames),
            "fps": track.fps,
            "fov_axis": fov_axis,
            "keyframes": keyframes,
            "note": ("field map names and start_offset_sec are placeholders resolved live in "
                     "Plan 2 (P2 field map; --start-tc/--at-playhead); beats are computed "
                     "in-script via track.timeToBeat"),
        },
        "inject_script": inject_script,
    }
    return "convert", data

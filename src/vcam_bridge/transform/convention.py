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

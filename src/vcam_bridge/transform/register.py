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
    if var_s < 1e-15:
        raise ValueError("degenerate source points: zero variance")
    scale = float(np.trace(np.diag(D) @ S) / var_s)
    t = mu_d - scale * (R @ mu_s)
    M = np.eye(4)
    M[:3, :3] = scale * R
    M[:3, 3] = t
    return M


def default_M() -> np.ndarray:
    """Blender-extracted UE world (cm) -> Disguise stage (m). Verified against UE
    Sequencer ground truth: a UE camera Location maps to Disguise as
    (UE_Y, UE_Z, UE_X)/100 (right->right, up->up, forward->forward; no sign flip).
    Because the Blender FBX importer negates UE's Y (left- -> right-handed), from the
    Blender-extracted translation T this is (-T_y, T_z, T_x)/100 -- a reflection
    (det<0). That reflection is INTENTIONAL: it undoes Blender's Y-flip. The rotation
    path (convert._stage_pose_for_frame) derives its axis map P from this same linear
    block, so a calibrated config.calibration.M_ue2dis stays consistent across both."""
    scale = 0.01  # cm -> m
    # (T_x, T_y, T_z)_blender -> (-T_y, T_z, T_x)_dis
    A = np.array([[0, -1, 0],
                  [0,  0, 1],
                  [1,  0, 0]], dtype=float)
    M = np.eye(4)
    M[:3, :3] = scale * A
    return M


def apply_M(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=float)
    h = np.hstack([pts, np.ones((pts.shape[0], 1))])
    return (h @ np.asarray(M, dtype=float).T)[:, :3]

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
    """Fallback UE(Z-up, cm) -> Disguise(Y-up, m) base transform.
    A PROPER rotation (det=+1): +90deg about X maps Z-up -> Y-up. This does NOT
    resolve UE's left-handed -> right-handed handedness (that is determined empirically
    by P5/P6 Umeyama calibration); it is only a non-mirrored starting point for the
    offline dry-run preview, replaced by config.calibration.M_ue2dis after calibration."""
    scale = 0.01  # cm -> m
    # +90deg about X: (x, y, z)_ue -> (x, z, -y)_dis  (det = +1)
    A = np.array([[1, 0, 0],
                  [0, 0, 1],
                  [0, -1, 0]], dtype=float)
    M = np.eye(4)
    M[:3, :3] = scale * A
    return M


def apply_M(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=float)
    h = np.hstack([pts, np.ones((pts.shape[0], 1))])
    return (h @ np.asarray(M, dtype=float).T)[:, :3]

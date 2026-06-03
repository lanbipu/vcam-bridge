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

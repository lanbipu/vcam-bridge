from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

_AXES = {"+X": [1, 0, 0], "-X": [-1, 0, 0], "+Y": [0, 1, 0],
         "-Y": [0, -1, 0], "+Z": [0, 0, 1], "-Z": [0, 0, -1]}


def forward_vector(axis: str) -> np.ndarray:
    if axis not in _AXES:
        raise ValueError(f"unknown forward axis: {axis}")
    return np.array(_AXES[axis], dtype=float)


def disguise_euler_to_matrix(elev_deg: float, heading_deg: float, roll_deg: float) -> np.ndarray:
    return Rotation.from_euler('ZXY', [roll_deg, elev_deg, -heading_deg], degrees=True).as_matrix()


def disguise_matrix_to_euler(R: np.ndarray) -> tuple[float, float, float]:
    angles = Rotation.from_matrix(np.asarray(R, dtype=float)).as_euler('ZXY', degrees=True)
    return (float(angles[1]), float(-angles[2]), float(angles[0]))


def decompose_pivot_orbit(C, R, d, *, forward_axis, euler_order=None):
    C = np.asarray(C, dtype=float)
    R = np.asarray(R, dtype=float)
    f = R.T @ forward_vector(forward_axis)
    pivot = C + d * f
    rot = disguise_matrix_to_euler(R)
    return {"pivot": tuple(float(x) for x in pivot), "rotation": rot, "distance": float(d)}


def recompose(pose, *, forward_axis, euler_order=None):
    R = disguise_euler_to_matrix(*pose["rotation"])
    f = R.T @ forward_vector(forward_axis)
    pivot = np.asarray(pose["pivot"], dtype=float)
    C = pivot - pose["distance"] * f
    return C, R

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def euler_to_matrix(angles_deg: tuple[float, float, float], order: str) -> np.ndarray:
    """angles_deg are applied in the given intrinsic order (uppercase = intrinsic)."""
    return Rotation.from_euler(order, list(angles_deg), degrees=True).as_matrix()


def matrix_to_euler(R: np.ndarray, order: str) -> tuple[float, float, float]:
    e = Rotation.from_matrix(np.asarray(R, dtype=float)).as_euler(order, degrees=True)
    return (float(e[0]), float(e[1]), float(e[2]))

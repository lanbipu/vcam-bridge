import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix, matrix_to_euler


def test_roundtrip_xyz():
    ang = (12.0, -34.0, 56.0)
    R = euler_to_matrix(ang, "XYZ")
    back = matrix_to_euler(R, "XYZ")
    R2 = euler_to_matrix(back, "XYZ")
    assert np.allclose(R, R2, atol=1e-9)


def test_orthonormal():
    R = euler_to_matrix((10, 20, 30), "ZYX")
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)

import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector, decompose_pivot_orbit, recompose


def test_forward_vector_axes():
    assert np.allclose(forward_vector("+X"), [1, 0, 0])
    assert np.allclose(forward_vector("-Z"), [0, 0, -1])


def test_decompose_recompose_invertible():
    rng = np.random.default_rng(1)
    for _ in range(20):
        C = rng.normal(size=3)
        R = euler_to_matrix(tuple(rng.uniform(-80, 80, size=3)), "XYZ")
        d = float(rng.uniform(0.2, 5.0))
        pose = decompose_pivot_orbit(C, R, d, forward_axis="+X", euler_order="XYZ")
        C2, R2 = recompose(pose, forward_axis="+X", euler_order="XYZ")
        assert np.allclose(C2, C, atol=1e-6)
        assert np.allclose(R2, R, atol=1e-6)

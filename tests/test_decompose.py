import pytest
import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector, decompose_pivot_orbit, recompose


def test_forward_vector_axes():
    assert np.allclose(forward_vector("+X"), [1, 0, 0])
    assert np.allclose(forward_vector("-Z"), [0, 0, -1])


def test_forward_vector_all_six():
    for axis, expected in [("+X", [1,0,0]), ("-X", [-1,0,0]),
                           ("+Y", [0,1,0]), ("-Y", [0,-1,0]),
                           ("+Z", [0,0,1]), ("-Z", [0,0,-1])]:
        assert np.allclose(forward_vector(axis), expected)


def test_forward_vector_invalid():
    with pytest.raises(ValueError):
        forward_vector("W")


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


@pytest.mark.parametrize("fwd,order", [
    ("-Z", "YXZ"), ("+Y", "ZYX"), ("-X", "XZY"), ("+Z", "YZX"),
])
def test_decompose_recompose_various_conventions(fwd, order):
    rng = np.random.default_rng(7)
    for _ in range(5):
        C = rng.normal(size=3)
        R = euler_to_matrix(tuple(rng.uniform(-60, 60, size=3)), order)
        d = float(rng.uniform(0.5, 3.0))
        pose = decompose_pivot_orbit(C, R, d, forward_axis=fwd, euler_order=order)
        C2, R2 = recompose(pose, forward_axis=fwd, euler_order=order)
        assert np.allclose(C2, C, atol=1e-6), f"pos failed for {fwd}/{order}"
        assert np.allclose(R2, R, atol=1e-6), f"rot failed for {fwd}/{order}"


def test_decompose_steep_angles():
    R = euler_to_matrix((88.0, -85.0, 75.0), "XYZ")
    C = np.array([10.0, 20.0, 30.0])
    pose = decompose_pivot_orbit(C, R, 2.0, forward_axis="+X", euler_order="XYZ")
    C2, R2 = recompose(pose, forward_axis="+X", euler_order="XYZ")
    assert np.allclose(C2, C, atol=1e-5)
    assert np.allclose(R2, R, atol=1e-5)

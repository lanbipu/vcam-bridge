import numpy as np
from vcam_bridge.transform.register import umeyama, default_M, apply_M


def test_umeyama_recovers_known_similarity():
    rng = np.random.default_rng(0)
    src = rng.normal(size=(8, 3))
    s = 0.01
    R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)  # 90deg about z
    t = np.array([5.0, -2.0, 1.0])
    dst = (s * (R @ src.T)).T + t
    M = umeyama(src, dst)
    out = apply_M(M, src)
    assert np.allclose(out, dst, atol=1e-9)


def test_umeyama_degenerate_raises():
    import pytest
    pts = np.zeros((4, 3))
    with pytest.raises(ValueError):
        umeyama(pts, pts)


def test_default_M_is_4x4_and_scales_cm_to_m():
    M = default_M()
    assert M.shape == (4, 4)
    out = apply_M(M, np.array([[100.0, 0.0, 0.0]]))   # 100 cm -> 1 m magnitude
    assert np.isclose(np.linalg.norm(out[0]), 1.0, atol=1e-9)


def test_default_M_is_proper_rotation():
    M = default_M()
    Rm = M[:3, :3]
    assert np.linalg.det(Rm) > 0
    scale = abs(np.linalg.det(Rm)) ** (1.0 / 3.0)
    R = Rm / scale
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)


def test_umeyama_noisy_residual_bounded():
    rng = np.random.default_rng(42)
    src = rng.normal(size=(10, 3)) * 100
    s = 0.01
    R = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
    t = np.array([1.0, 2.0, 3.0])
    dst = (s * (R @ src.T)).T + t + rng.normal(scale=0.001, size=(10, 3))
    M = umeyama(src, dst)
    out = apply_M(M, src)
    residuals = np.linalg.norm(out - dst, axis=1)
    assert residuals.max() < 0.01


def test_apply_M_batch():
    M = default_M()
    pts = np.array([[100, 0, 0], [0, 200, 0], [0, 0, 300]], dtype=float)
    out = apply_M(M, pts)
    assert out.shape == (3, 3)
    for i in range(3):
        single = apply_M(M, pts[i:i+1, :])
        assert np.allclose(out[i], single[0])

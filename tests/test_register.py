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


def test_default_M_is_4x4_and_scales_cm_to_m():
    M = default_M()
    assert M.shape == (4, 4)
    out = apply_M(M, np.array([[100.0, 0.0, 0.0]]))   # 100 cm -> 1 m magnitude
    assert np.isclose(np.linalg.norm(out[0]), 1.0, atol=1e-9)

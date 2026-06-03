import numpy as np
from vcam_bridge.transform.rotation import euler_to_matrix
from vcam_bridge.transform.decompose import forward_vector
from vcam_bridge.transform.convention import solve_convention, CANDIDATES


def _world_from_params(pivot, rot, dist, forward_axis, euler_order):
    R = euler_to_matrix(rot, euler_order)
    f = R @ forward_vector(forward_axis)
    C = np.asarray(pivot) - dist * f
    return C, R


def test_solver_recovers_true_convention():
    true_fwd, true_order = "+X", "XYZ"
    rng = np.random.default_rng(3)
    samples = []
    for _ in range(8):
        pivot = rng.normal(size=3)
        rot = tuple(rng.uniform(-70, 70, size=3))
        dist = float(rng.uniform(0.3, 4.0))
        C, R = _world_from_params(pivot, rot, dist, true_fwd, true_order)
        samples.append({"written": {"pivot": tuple(pivot), "rotation": rot, "distance": dist},
                        "world": {"position": tuple(C), "rotation_matrix": R.tolist()}})
    best = solve_convention(samples)
    assert best["forward_axis"] == true_fwd
    assert best["euler_order"] == true_order
    assert best["pos_error"] < 1e-6


def test_candidates_cover_axes_and_orders():
    assert len(CANDIDATES) >= 6 * 6   # 6 forward axes x >=6 euler orders

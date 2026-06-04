import json
import pytest
import numpy as np
from pathlib import Path
from vcam_bridge.transform.decompose import (
    forward_vector, decompose_pivot_orbit, recompose,
    disguise_euler_to_matrix, disguise_matrix_to_euler,
)


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


def test_disguise_euler_roundtrip():
    cases = [(0, 0, 0), (10, 0, 0), (0, 20, 0), (0, 0, 5),
             (20, -10, 5), (-5, 45, -10), (30, -20, 15), (-25, 15, -5)]
    for elev, head, roll in cases:
        R = disguise_euler_to_matrix(elev, head, roll)
        e2, h2, r2 = disguise_matrix_to_euler(R)
        assert abs(e2 - elev) < 1e-9, f"elev {elev} -> {e2}"
        assert abs(h2 - head) < 1e-9, f"head {head} -> {h2}"
        assert abs(r2 - roll) < 1e-9, f"roll {roll} -> {r2}"


def test_disguise_euler_matches_real_machine_fixtures():
    samples = json.loads(Path("tests/fixtures/live/convention_samples.json").read_text())
    for i, s in enumerate(samples):
        R_expected = np.array(s["world"]["rotation_matrix"])
        rx, ry, rz = s["written"]["rotation"]
        R_built = disguise_euler_to_matrix(rx, ry, rz)
        assert np.allclose(R_built, R_expected, atol=1e-6), f"sample {i} rotation mismatch"


def test_decompose_recompose_invertible():
    rng = np.random.default_rng(1)
    for _ in range(20):
        C = rng.normal(size=3)
        elev, head, roll = rng.uniform(-60, 60, size=3)
        R = disguise_euler_to_matrix(float(elev), float(head), float(roll))
        d = float(rng.uniform(0.2, 5.0))
        pose = decompose_pivot_orbit(C, R, d, forward_axis="+Z", euler_order="disguise_zxy")
        C2, R2 = recompose(pose, forward_axis="+Z", euler_order="disguise_zxy")
        assert np.allclose(C2, C, atol=1e-6)
        assert np.allclose(R2, R, atol=1e-6)


def test_decompose_steep_angles():
    R = disguise_euler_to_matrix(55.0, -70.0, 25.0)
    C = np.array([10.0, 20.0, 30.0])
    pose = decompose_pivot_orbit(C, R, 2.0, forward_axis="+Z", euler_order="disguise_zxy")
    C2, R2 = recompose(pose, forward_axis="+Z", euler_order="disguise_zxy")
    assert np.allclose(C2, C, atol=1e-5)
    assert np.allclose(R2, R, atol=1e-5)


def test_decompose_position_matches_real_machine():
    samples = json.loads(Path("tests/fixtures/live/convention_samples.json").read_text())
    for i, s in enumerate(samples):
        rx, ry, rz = s["written"]["rotation"]
        R = disguise_euler_to_matrix(rx, ry, rz)
        pivot = np.array(s["written"]["pivot"], dtype=float)
        dist = s["written"]["distance"]
        C_actual = np.array(s["world"]["position"])
        f = R.T @ forward_vector("+Z")
        C_pred = pivot - dist * f
        assert np.allclose(C_pred, C_actual, atol=0.5), f"sample {i}: pred={C_pred} actual={C_actual}"

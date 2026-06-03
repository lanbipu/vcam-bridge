import math
from vcam_bridge.transform.fov import h_to_v, v_to_h, map_fov


def test_h_v_roundtrip():
    aspect = 16 / 9
    h = 90.0
    v = h_to_v(h, aspect)
    assert math.isclose(v_to_h(v, aspect), h, rel_tol=1e-9)
    assert v < h  # vertical FOV narrower for wide aspect


def test_map_fov_horizontal_passthrough():
    assert map_fov(75.0, fov_axis="horizontal", aspect=16 / 9) == 75.0


def test_map_fov_vertical_converts():
    out = map_fov(90.0, fov_axis="vertical", aspect=16 / 9)
    assert math.isclose(out, h_to_v(90.0, 16 / 9), rel_tol=1e-9)

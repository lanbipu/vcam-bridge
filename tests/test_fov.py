import math
import pytest
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


@pytest.mark.parametrize("aspect", [4/3, 16/9, 21/9, 1.0])
def test_roundtrip_various_aspects(aspect):
    h = 75.0
    v = h_to_v(h, aspect)
    assert math.isclose(v_to_h(v, aspect), h, rel_tol=1e-9)


def test_square_aspect_h_equals_v():
    h = 60.0
    v = h_to_v(h, 1.0)
    assert math.isclose(v, h, rel_tol=1e-9)


def test_map_fov_invalid_axis():
    with pytest.raises(ValueError, match="unknown fov_axis"):
        map_fov(60.0, fov_axis="diagonal", aspect=16/9)


def test_ultrawide_v_smaller_than_h():
    v = h_to_v(120.0, 21/9)
    assert v < 120.0

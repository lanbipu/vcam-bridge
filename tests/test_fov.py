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


from vcam_bridge.transform.fov import hfov_to_zoom, zoom_to_hfov


def test_hfov_to_zoom_fixture_values():
    B = 30.296; S = 35.0
    assert math.isclose(hfov_to_zoom(98.24, B, S), 0.5, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(60.02, B, S), 1.0, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(42.12, B, S), 1.5, abs_tol=0.01)
    assert math.isclose(hfov_to_zoom(32.22, B, S), 2.0, abs_tol=0.01)


def test_hfov_zoom_roundtrip():
    B = 30.296; S = 35.0
    for fov in [30, 45, 60, 75, 90, 120]:
        z = hfov_to_zoom(float(fov), B, S)
        back = zoom_to_hfov(z, B, S)
        assert math.isclose(back, fov, abs_tol=0.01)

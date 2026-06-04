from __future__ import annotations

import math


def h_to_v(h_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(h_deg) / 2) / aspect))


def v_to_h(v_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(v_deg) / 2) * aspect))


def map_fov(h_fov_deg: float, *, fov_axis: str, aspect: float) -> float:
    """UE gives horizontal FOV. If the Disguise field is horizontal -> passthrough;
    if vertical -> convert. (Prior: Disguise VC field is 'Field of view (horizontal)'.)"""
    if fov_axis == "horizontal":
        return h_fov_deg
    if fov_axis == "vertical":
        return h_to_v(h_fov_deg, aspect)
    raise ValueError(f"unknown fov_axis: {fov_axis}")


def hfov_to_zoom(h_fov_deg: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    target_focal = sensor_width_mm / (2 * math.tan(math.radians(h_fov_deg) / 2))
    return target_focal / baseline_focal_mm


def zoom_to_hfov(zoom: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    focal = baseline_focal_mm * zoom
    return math.degrees(2 * math.atan(sensor_width_mm / (2 * focal)))

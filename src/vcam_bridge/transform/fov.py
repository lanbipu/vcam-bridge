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


def fov_h_from_sensor(sensor_width_mm: float, focal_mm: float) -> float:
    """UE-convention horizontal FOV from filmback sensor width + focal length:
    FOV_h = 2*atan(SensorWidth / (2*FocalLength)). Robust to Blender's sensor_fit
    (always uses the horizontal/width dimension, as UE does). See
    docs/ue-disguise-axis-mapping.md."""
    if focal_mm <= 0.0 or sensor_width_mm <= 0.0:
        raise ValueError("sensor_width_mm and focal_mm must be > 0, got %s, %s"
                         % (sensor_width_mm, focal_mm))
    return math.degrees(2 * math.atan(sensor_width_mm / (2 * focal_mm)))


def hfov_to_zoom(h_fov_deg: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    if h_fov_deg <= 0.0 or h_fov_deg >= 180.0:
        raise ValueError("h_fov_deg must be in (0, 180), got %s" % h_fov_deg)
    target_focal = sensor_width_mm / (2 * math.tan(math.radians(h_fov_deg) / 2))
    return target_focal / baseline_focal_mm


def zoom_to_hfov(zoom: float, baseline_focal_mm: float, sensor_width_mm: float) -> float:
    focal = baseline_focal_mm * zoom
    return math.degrees(2 * math.atan(sensor_width_mm / (2 * focal)))

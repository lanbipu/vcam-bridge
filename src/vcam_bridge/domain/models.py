from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class Frame(BaseModel):
    idx: int
    t_sec: float
    T: list[list[float]]            # 4x4 world transform (Blender-extracted UE world)
    fov_h_deg: float               # horizontal FOV, = 2*atan(sensor_width/(2*focal))
    focus_m: float | None = None
    sensor_width_mm: float | None = None   # UE filmback width (lens data from FBX)
    focal_mm: float | None = None          # UE current focal length

    @field_validator("T")
    @classmethod
    def _check_4x4(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) != 4 or any(len(row) != 4 for row in v):
            raise ValueError("T must be a 4x4 matrix")
        return v


class CameraTrack(BaseModel):
    schema_: str = Field(default="vcam.track/1", alias="schema")
    fps: float
    camera: str
    frames: list[Frame]

    model_config = {"populate_by_name": True}


class StagePose(BaseModel):
    pivot: tuple[float, float, float]
    rotation: tuple[float, float, float]   # (elevation, heading, roll) degrees
    distance: float
    fov_deg: float
    zoom_scale: float | None = None


class ACCKeyframe(BaseModel):
    idx: int
    t_sec: float
    pose: StagePose


class Calibration(BaseModel):
    module_type: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    forward_axis: str = "+Z"
    euler_order: str = "disguise_zxy"
    fov_axis: str = "horizontal"
    linear_key_type: Any | None = None
    M_ue2dis: list[list[float]] | None = None   # 4x4; None -> default base transform
    aspect: float = 16.0 / 9.0
    legacy_vc: bool = False
    zoom_scale_neutral: float = 1.0
    baseline_focal_mm: float = 30.296
    sensor_width_mm: float = 35.0

    @field_validator("M_ue2dis")
    @classmethod
    def _check_M_4x4(cls, v):
        if v is None:
            return v
        if len(v) != 4 or any(len(row) != 4 for row in v):
            raise ValueError("M_ue2dis must be a 4x4 matrix")
        return v


class Tolerances(BaseModel):
    pos_m: float = 0.001
    rot_deg: float = 0.05
    fov_deg: float = 0.05


class Config(BaseModel):
    director: str | None = None
    calibration: Calibration = Field(default_factory=Calibration)
    tolerances: Tolerances = Field(default_factory=Tolerances)
    chunk_size: int = 200

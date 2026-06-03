from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from vcam_bridge.domain.errors import InvalidFbxError
from vcam_bridge.domain.models import CameraTrack, Frame
from vcam_bridge.transform.rotation import euler_to_matrix


def _frame_from_components(idx: int, t_sec: float, pos, rot_deg, fov_h_deg,
                           focus_m, euler_order: str) -> Frame:
    R = euler_to_matrix((float(rot_deg[0]), float(rot_deg[1]), float(rot_deg[2])), euler_order)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [float(pos[0]), float(pos[1]), float(pos[2])]
    return Frame(idx=int(idx), t_sec=float(t_sec), T=T.tolist(),
                 fov_h_deg=float(fov_h_deg),
                 focus_m=None if focus_m in (None, "") else float(focus_m))


def _load_json(path: Path, euler_order: str) -> CameraTrack:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = []
    for fr in data.get("frames", []):
        if "T" in fr:
            frames.append(Frame(idx=int(fr["idx"]), t_sec=float(fr["t_sec"]),
                                 T=fr["T"], fov_h_deg=float(fr["fov_h_deg"]),
                                 focus_m=fr.get("focus_m")))
        else:
            frames.append(_frame_from_components(
                fr["idx"], fr["t_sec"], fr["position"], fr["rotation_deg"],
                fr["fov_h_deg"], fr.get("focus_m"), euler_order))
    return CameraTrack(fps=float(data["fps"]), camera=str(data["camera"]), frames=frames)


def _load_csv(path: Path, euler_order: str) -> CameraTrack:
    frames = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            frames.append(_frame_from_components(
                row["idx"], row["t_sec"],
                (row["x"], row["y"], row["z"]),
                (row["rx"], row["ry"], row["rz"]),
                row["fov_h_deg"], row.get("focus_m"), euler_order))
    fps = 1.0 / (frames[1].t_sec - frames[0].t_sec) if len(frames) >= 2 and frames[1].t_sec > frames[0].t_sec else 30.0
    return CameraTrack(fps=float(fps), camera="Camera", frames=frames)


def load_intermediate(path: str, *, euler_order: str) -> CameraTrack:
    p = Path(path)
    if not p.exists():
        raise InvalidFbxError(f"intermediate file not found: {path}", details={"path": path})
    try:
        track = _load_csv(p, euler_order) if p.suffix.lower() == ".csv" else _load_json(p, euler_order)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidFbxError(f"failed to parse intermediate track: {exc}", details={"path": path}) from exc
    if not track.frames:
        raise InvalidFbxError("track has no frames", details={"path": path})
    return track

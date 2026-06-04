from __future__ import annotations

from typing import Any
import numpy as np

from vcam_bridge.domain.errors import ConfigError
from vcam_bridge.domain.models import Config
from vcam_bridge.transform.register import default_M, apply_M
from vcam_bridge.transform.decompose import decompose_pivot_orbit
from vcam_bridge.transform.fov import map_fov
from vcam_bridge.designer.codegen import build_inject_script

_CANONICAL_FIELDS = ("pivot.x", "pivot.y", "pivot.z", "rotation.x", "rotation.y", "rotation.z", "distance", "fov")

_SET_TARGET_SCRIPT = '''
import json
local_state = state.localOrDirectorState()
layer = None
for l in local_state.track.layers:
    if l.uid == int(%(layer)r, 16):
        layer = l
        break
if layer is None:
    return json.dumps({"ok": False, "error": "acc layer not found"})
vc = None
try:
    for cam in state.stage.cameras:
        if cam.uid == int(%(vc)r, 16):
            vc = cam
            break
except Exception:
    vc = None
note = []
if vc is None:
    note.append("vc-not-found-by-uid")
try:
    cam_seq = layer.findSequence("Camera")
    if cam_seq is not None and vc is not None:
        cam_seq.disableSequencing = True
        cam_seq.sequence.setResource(layer.tStart, vc)
        note.append("camera-target-set")
    elif cam_seq is None:
        note.append("camera-field-not-found")
except Exception as e:
    note.append("camera-target-skipped:" + str(e))
try:
    cs = layer.findSequence("coordinate system")
    if cs is not None:
        cs.disableSequencing = True
        cs.sequence.setFloat(layer.tStart, 0)
        note.append("coord-global-attempted")
except Exception as e:
    note.append("coord-skipped:" + str(e))
return json.dumps({"ok": True, "vc_found": vc is not None, "note": note})
'''


def _stage_pose_for_frame(T_ue: np.ndarray, M: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Apply M_ue2dis to the camera position and rotation. Returns (C_stage, R_stage).
    Extracts the nearest PROPER rotation via SVD so a reflection/handedness component
    in M never silently mirrors the orientation."""
    C_ue = T_ue[:3, 3]
    C_stage = apply_M(M, C_ue.reshape(1, 3))[0]
    Rm = M[:3, :3]
    det = np.linalg.det(Rm)
    scale = abs(det) ** (1.0 / 3.0)
    A = Rm / scale
    U, _, Vt = np.linalg.svd(A)
    R_lin = U @ Vt
    if np.linalg.det(R_lin) < 0:
        U[:, -1] = -U[:, -1]
        R_lin = U @ Vt
    R_stage = R_lin @ T_ue[:3, :3]
    return C_stage, R_stage


def _load_track(path: str, *, euler_order: str, blender_path: str | None = None):
    """Load a camera track from either an intermediate file (CSV/JSON) or FBX via Blender."""
    if path.lower().endswith(".fbx"):
        from vcam_bridge.ingest.blender_fbx import extract_fbx
        return extract_fbx(path, blender_path=blender_path)
    from vcam_bridge.ingest.intermediate import load_intermediate
    return load_intermediate(path, euler_order=euler_order)


def build_keyframes(track, config: Config, *, fov_axis: str | None = None,
                    pivot_distance_const: float | None = None) -> tuple[dict, list, list]:
    """Extract keyframe data from a track + config.

    Returns:
        (field_map, keys, keyframes)
        - field_map: canonical -> designer field name mapping
        - keys: list of {t_sec, values} dicts for inject_keys
        - keyframes: list of {idx, t_sec, pivot, rotation, distance, fov} for dry_run_plan
    """
    cal = config.calibration
    effective_fov_axis = fov_axis or cal.fov_axis
    M = np.array(cal.M_ue2dis, dtype=float) if cal.M_ue2dis else default_M()

    keyframes = []
    for fr in track.frames:
        T_ue = np.array(fr.T, dtype=float)
        C, R = _stage_pose_for_frame(T_ue, M)
        d = pivot_distance_const if pivot_distance_const is not None else (fr.focus_m if fr.focus_m is not None else 1.0)
        pose = decompose_pivot_orbit(C, R, d, forward_axis=cal.forward_axis,
                                     euler_order=cal.euler_order)
        fov = map_fov(fr.fov_h_deg, fov_axis=effective_fov_axis, aspect=cal.aspect)
        keyframes.append({
            "idx": fr.idx, "t_sec": fr.t_sec,
            "pivot": pose["pivot"], "rotation": pose["rotation"],
            "distance": pose["distance"], "fov": fov,
        })

    field_map = cal.field_map or {
        "pivot.x": "camera_pivot.x", "pivot.y": "camera_pivot.y", "pivot.z": "camera_pivot.z",
        "rotation.x": "camera_rotation.x", "rotation.y": "camera_rotation.y",
        "rotation.z": "camera_rotation.z", "distance": "distance", "fov": "fieldOfView",
    }

    keys = []
    for kf in keyframes:
        keys.append({
            "t_sec": kf["t_sec"],
            "values": {
                "pivot.x": kf["pivot"][0], "pivot.y": kf["pivot"][1], "pivot.z": kf["pivot"][2],
                "rotation.x": kf["rotation"][0], "rotation.y": kf["rotation"][1],
                "rotation.z": kf["rotation"][2], "distance": kf["distance"], "fov": kf["fov"],
            },
        })

    missing_fields = [k for k in _CANONICAL_FIELDS if k not in field_map]
    if missing_fields:
        raise ConfigError("calibration.field_map is missing required canonical keys",
                          details={"missing": missing_fields})

    return field_map, keys, keyframes


def convert_dry_run(fbx_or_intermediate: str, *, config: Config,
                    layer_uid: str, fov_axis: str | None = None,
                    pivot_distance_const: float | None = None) -> tuple[str, Any]:
    cal = config.calibration
    track = _load_track(fbx_or_intermediate, euler_order=cal.euler_order,
                        blender_path=getattr(config, "blender_path", None))
    field_map, keys, keyframes = build_keyframes(track, config, fov_axis=fov_axis,
                                                 pivot_distance_const=pivot_distance_const)

    inject_payload = {"layer_uid": layer_uid, "start_offset_sec": 0.0,
                      "fields": field_map, "keys": keys}
    inject_script = build_inject_script(inject_payload)

    data = {
        "dry_run_plan": {
            "frame_count": len(track.frames),
            "fps": track.fps,
            "fov_axis": fov_axis or cal.fov_axis,
            "keyframes": keyframes,
            "note": ("field map names and start_offset_sec are placeholders resolved live in "
                     "Plan 2 (P2 field map; --start-tc/--at-playhead); beats are computed "
                     "in-script via track.timeToBeat"),
        },
        "inject_script": inject_script,
    }
    return "convert", data


def convert_live(transport, *, host, fbx, config, layer_uid, vc_uid, fov_axis=None,
                 pivot_distance_const=None, start_offset_sec=0.0, chunk_size=None):
    from vcam_bridge.designer.client import DesignerClient
    from vcam_bridge.designer.inject import inject_keys
    from vcam_bridge.designer.codegen import validate_uid
    from vcam_bridge.domain.errors import ConfigError, PartialError
    for label, u in (("--target-uid", layer_uid), ("--vc-uid", vc_uid)):
        try:
            validate_uid(u)
        except ValueError as exc:
            raise ConfigError("%s must be a 0x-hex uid: %s" % (label, exc), details={"value": u}) from exc
    cal = config.calibration
    track = _load_track(fbx, euler_order=cal.euler_order, blender_path=getattr(config, "blender_path", None))
    field_map, keys, _ = build_keyframes(track, config, fov_axis=fov_axis, pivot_distance_const=pivot_distance_const)
    client = DesignerClient(transport, host)
    client.resolve_routing()
    setup = client.execute(_SET_TARGET_SCRIPT % {"layer": layer_uid, "vc": vc_uid}).return_value or {}
    if not setup.get("ok"):
        raise PartialError("failed to set ACC camera target: %s" % setup.get("error", "unknown"), details=setup)
    written = inject_keys(client, layer_uid=layer_uid, fields=field_map, keys=keys,
                          start_offset_sec=start_offset_sec, chunk_size=chunk_size or config.chunk_size)
    return "convert", {"written": written, "frames": len(keys), "layer_uid": layer_uid,
                       "vc_uid": vc_uid, "target_setup": setup}

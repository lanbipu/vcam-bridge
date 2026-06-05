from __future__ import annotations

from typing import Any
import numpy as np

from vcam_bridge.domain.errors import ConfigError
from vcam_bridge.domain.models import Config
from vcam_bridge.transform.register import default_M, apply_M
from vcam_bridge.transform.decompose import decompose_pivot_orbit
from vcam_bridge.transform.fov import hfov_to_zoom, h_to_v
from vcam_bridge.designer.codegen import build_inject_script

# "view_angle" drives a regular Live Camera's FOV (= vertical FOV); "zoom" drives a
# VirtualCamera. Both are injected so either camera type renders the right FOV.
_CANONICAL_FIELDS = ("pivot.x", "pivot.y", "pivot.z", "rotation.x", "rotation.y", "rotation.z",
                     "distance", "view_angle", "zoom")

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
    cam_seq = layer.findSequence("camera")
    if cam_seq is not None and vc is not None:
        cam_seq.disableSequencing = True
        cam_seq.sequence.setResource(layer.tStart, vc)
        note.append("camera-target-set")
    elif cam_seq is None:
        note.append("camera-field-not-found")
except Exception as e:
    note.append("camera-target-skipped:" + str(e))
try:
    cs = layer.findSequence("virtual camera coordinates")
    if cs is not None:
        n_before = cs.sequence.nKeys()
        if n_before > 1:
            cs.sequence.stripToFirstKey()   # 仅多键(异常情形)才清，避免抹掉单键常态
        cs.disableSequencing = True
        cs.sequence.setFloat(layer.tStart, 1.0)   # 强制 Global=1（实测 1=Global / 0=Relative：coord=1 时 VC.world==注入坐标；旧值 0.0=Relative 是 bug）
        note.append("coord-global-set")
        if n_before > 1:
            note.append("coord-keys-collapsed:%%d" %% n_before)
except Exception as e:
    note.append("coord-skipped:" + str(e))
return json.dumps({"ok": True, "vc_found": vc is not None, "note": note})
'''


_READ_ASPECT_SCRIPT = '''
import json
vc = None
for cam in state.stage.cameras:
    if cam.uid == int(%(vc)r, 16):
        vc = cam
        break
if vc is None:
    return json.dumps({"aspect": None})
return json.dumps({"aspect": float(vc.aspectRatio)})
'''


def _read_camera_aspect(client, vc_uid: str) -> float | None:
    """Read the target camera's actual render aspect (output resolution w/h) live, so the
    'view angle' (vertical FOV) -> horizontal FOV conversion is exact regardless of the
    camera's output resolution. Falls back to None (-> config aspect) on any failure."""
    try:
        res = client.execute(_READ_ASPECT_SCRIPT % {"vc": vc_uid}).return_value or {}
        a = res.get("aspect")
        return float(a) if a and float(a) > 0.0 else None
    except Exception:
        return None


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _stage_pose_for_frame(T_ue: np.ndarray, M: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map one Blender-extracted world matrix to a Disguise stage pose (C, R).

    Position: apply M (cm->m + axis map + undo Blender's Y-flip).
    Rotation: build the Disguise world rotation matrix from the camera's world look/up
    directions mapped through M's axis map P (= the linear block with the uniform scale
    divided out; P may be a REFLECTION -- correct, it undoes Blender's Y-flip). The
    Blender camera looks along its local -Z with up = local +Y. Disguise stores the
    world matrix so that camera look = R^T @ [0,0,1], i.e. look/up/right are its ROWS;
    verified against UE FRotator ground truth that disguise_matrix_to_euler then equals
    UE (Pitch, Yaw, Roll). See docs/ue-disguise-axis-mapping.md."""
    C_ue = T_ue[:3, 3]
    C_stage = apply_M(M, C_ue.reshape(1, 3))[0]
    Rm = M[:3, :3]
    scale = abs(np.linalg.det(Rm)) ** (1.0 / 3.0)
    P = Rm / scale
    R_cam = T_ue[:3, :3]
    look = _unit(P @ (-R_cam[:, 2]))
    up = _unit(P @ R_cam[:, 1])
    right = _unit(np.cross(up, look))
    up = _unit(np.cross(look, right))
    return C_stage, np.array([right, up, look])


def _load_track(path: str, *, euler_order: str, blender_path: str | None = None):
    """Load a camera track from either an intermediate file (CSV/JSON) or FBX via Blender."""
    if path.lower().endswith(".fbx"):
        from vcam_bridge.ingest.blender_fbx import extract_fbx
        return extract_fbx(path, blender_path=blender_path)
    from vcam_bridge.ingest.intermediate import load_intermediate
    return load_intermediate(path, euler_order=euler_order)


def build_keyframes(track, config: Config, *,
                    pivot_distance_const: float | str | None = None,
                    aspect_override: float | None = None) -> tuple[dict, list, list]:
    """Extract keyframe data from a track + config.

    Returns:
        (field_map, keys, keyframes)
        - field_map: canonical -> designer field name mapping
        - keys: list of {t_sec, values} dicts for inject_keys
        - keyframes: list of {idx, t_sec, pivot, rotation, distance, zoom} for dry_run_plan
    """
    cal = config.calibration
    M = np.array(cal.M_ue2dis, dtype=float) if cal.M_ue2dis else default_M()
    aspect = aspect_override if aspect_override is not None else cal.aspect   # live render aspect when known

    keyframes = []
    for fr in track.frames:
        T_ue = np.array(fr.T, dtype=float)
        C, R = _stage_pose_for_frame(T_ue, M)
        if pivot_distance_const == "focus":
            d = fr.focus_m if fr.focus_m is not None else 0.0
        elif pivot_distance_const is not None:
            d = float(pivot_distance_const)
        else:
            d = 0.0   # default: pivot == camera world position (clean offset)
        pose = decompose_pivot_orbit(C, R, d, forward_axis=cal.forward_axis,
                                     euler_order=cal.euler_order)
        zoom = hfov_to_zoom(fr.fov_h_deg, cal.baseline_focal_mm, cal.sensor_width_mm)
        view_angle = h_to_v(fr.fov_h_deg, aspect)   # vertical FOV: drives a Live Camera
        keyframes.append({
            "idx": fr.idx, "t_sec": fr.t_sec,
            "pivot": pose["pivot"], "rotation": pose["rotation"],
            "distance": pose["distance"], "view_angle": view_angle, "zoom": zoom,
        })

    field_map = cal.field_map or {
        "pivot.x": "camera pivot.x", "pivot.y": "camera pivot.y", "pivot.z": "camera pivot.z",
        "rotation.x": "camera rotation.x", "rotation.y": "camera rotation.y",
        "rotation.z": "camera rotation.z", "distance": "distance from pivot",
        "view_angle": "view angle", "zoom": "virtual camera zoom",
    }

    keys = []
    for kf in keyframes:
        keys.append({
            "t_sec": kf["t_sec"],
            "values": {
                "pivot.x": kf["pivot"][0], "pivot.y": kf["pivot"][1], "pivot.z": kf["pivot"][2],
                "rotation.x": kf["rotation"][0], "rotation.y": kf["rotation"][1],
                "rotation.z": kf["rotation"][2], "distance": kf["distance"],
                "view_angle": kf["view_angle"], "zoom": kf["zoom"],
            },
        })

    missing_fields = [k for k in _CANONICAL_FIELDS if k not in field_map]
    if missing_fields:
        raise ConfigError("calibration.field_map is missing required canonical keys",
                          details={"missing": missing_fields})

    return field_map, keys, keyframes


def convert_dry_run(fbx_or_intermediate: str, *, config: Config,
                    layer_uid: str, overwrite: bool = False,
                    pivot_distance_const: float | None = None) -> tuple[str, Any]:
    cal = config.calibration
    track = _load_track(fbx_or_intermediate, euler_order=cal.euler_order,
                        blender_path=getattr(config, "blender_path", None))
    field_map, keys, keyframes = build_keyframes(track, config,
                                                 pivot_distance_const=pivot_distance_const)

    # 预览须如实反映 live：--overwrite 时脚本里含 stripToFirstKey 分支
    inject_payload = {"layer_uid": layer_uid, "start_offset_sec": 0.0,
                      "fields": field_map, "keys": keys, "overwrite": overwrite}
    inject_script = build_inject_script(inject_payload)

    f0 = track.frames[0] if track.frames else None
    data = {
        "dry_run_plan": {
            "frame_count": len(track.frames),
            "fps": track.fps,
            "fov_control": "view_angle+zoom",
            "keyframes": keyframes,
            "aspect_source": "config-default",
            "sensor_width_mm": f0.sensor_width_mm if f0 else None,
            "focal_mm": f0.focal_mm if f0 else None,
            "note": ("field map names and start_offset_sec are placeholders resolved live in "
                     "Plan 2 (P2 field map; --start-tc/--at-playhead); beats are computed "
                     "in-script via track.timeToBeat"),
        },
        "inject_script": inject_script,
    }
    return "convert", data


def convert_live(transport, *, host, fbx, config, layer_uid, vc_uid,
                 pivot_distance_const=None, start_offset_sec=0.0, chunk_size=None,
                 overwrite=False, verify=False, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05,
                 client=None):
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
    if client is None:   # 直给 uid 路径自建并路由；name 解析路径复用 main 已路由的 client（免二次 resolve_routing）
        client = DesignerClient(transport, host)
        client.resolve_routing()
    render_aspect = _read_camera_aspect(client, vc_uid)   # exact view-angle conversion
    aspect_source = "live" if render_aspect is not None else "config-fallback"
    field_map, keys, keyframes = build_keyframes(track, config, pivot_distance_const=pivot_distance_const,
                                                 aspect_override=render_aspect)
    setup = client.execute(_SET_TARGET_SCRIPT % {"layer": layer_uid, "vc": vc_uid}).return_value or {}
    if not setup.get("ok"):
        raise PartialError("failed to set ACC camera target: %s" % setup.get("error", "unknown"), details=setup)
    if not setup.get("vc_found", True):   # 错/失效 --vc-uid：脚本 ok:True 但没绑相机，别静默成功
        raise PartialError("--vc-uid %s not found among stage cameras; ACC layer has no camera bound" % vc_uid,
                           details=setup)
    warnings = []
    if render_aspect is None:   # aspect 读不到→回退 config，非 16:9 输出会错 FOV，别静默（Codex#2）
        warnings.append("render aspect not read from camera; FOV uses config aspect %.4f (wrong on non-16:9 output)"
                        % cal.aspect)
    if any(str(n).startswith("coord-keys-collapsed") for n in setup.get("note", [])):
        warnings.append("existing 'virtual camera coordinates' animation was collapsed to Global")
    written = inject_keys(client, layer_uid=layer_uid, fields=field_map, keys=keys,
                          start_offset_sec=start_offset_sec, chunk_size=chunk_size or config.chunk_size,
                          overwrite=overwrite)
    # FOV is driven by the injected "view angle" (Live Camera) / "virtual camera zoom" (VC)
    # keyframes -- no separate lens edit needed. The camera focal-mm derives from the FOV.
    f0 = track.frames[0]
    verify_report = None
    if verify:
        from vcam_bridge.designer.inject import verify_keys_persistence, verify_world_pose
        from vcam_bridge.transform.decompose import recompose
        verify_report = verify_keys_persistence(
            client, layer_uid=layer_uid, fields=field_map, keys=keys,
            start_offset_sec=start_offset_sec,
            tol_pos=tol_pos, tol_rot=tol_rot, tol_zoom=tol_zoom)
        # World-pose verify needs the playhead to advance AND a render to refresh the
        # camera transform. In solo (no active render node) gototime does not re-render,
        # so the readback is stale and the check is meaningless -- skip it and tell the
        # user to confirm visually. Only run it when a director session is rendering.
        if client.is_solo:
            verify_report["world_pose"] = {
                "ok": None, "skipped": "solo",
                "note": "world-pose check skipped: solo session does not re-render on "
                        "gototime, so the readback would be stale. Confirm the camera "
                        "pose visually in the Designer GUI."}
            verify_report["pose_verified"] = False
            verify_report["level"] = "persistence-only"
        else:
            expected_positions = []
            for kf in keyframes:
                C, _ = recompose({"pivot": kf["pivot"], "rotation": kf["rotation"],
                                  "distance": kf["distance"]}, forward_axis=cal.forward_axis)
                expected_positions.append(C.tolist())
            wp = verify_world_pose(
                client, layer_uid=layer_uid, vc_uid=vc_uid, keys=keys, start_offset_sec=start_offset_sec,
                expected_positions=expected_positions, tol_pos=tol_pos)
            verify_report["world_pose"] = wp
            # world_pose 可能 degrade 成 skip（ok=None）或 0 采样：那都不算真验证过位姿
            _pose_ok = bool(wp.get("ok")) and wp.get("sampled", 0) > 0
            verify_report["pose_verified"] = _pose_ok
            verify_report["level"] = "world-pose" if _pose_ok else "persistence-only"
    return "convert", {"written": written, "frames": len(keys), "layer_uid": layer_uid,
                       "vc_uid": vc_uid, "target_setup": setup, "verify": verify_report,
                       "warnings": warnings, "aspect_source": aspect_source,
                       "fov_deg": f0.fov_h_deg, "render_aspect": render_aspect,
                       "sensor_width_mm": f0.sensor_width_mm, "focal_mm": f0.focal_mm}

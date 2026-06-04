"""Runs INSIDE Blender: blender --background --factory-startup --python this.py -- --in ... --out ...
Emits a vcam.track/1 JSON: per-frame world matrix (T 4x4), horizontal FOV (angle_x), fps, focus."""
import argparse
import json
import sys

import bpy   # only available inside Blender


def _parse(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--camera", default="")
    return ap.parse_args(argv)


def _import(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)


def _pick_camera(name):
    cams = sorted([o for o in bpy.data.objects if o.type == "CAMERA"], key=lambda o: o.name)
    if not cams:
        raise SystemExit("ERR_NO_CAMERA")
    if name:
        for c in cams:
            if c.name == name:
                return c
        raise SystemExit("ERR_CAMERA_NOT_FOUND:%s|%s" % (name, [c.name for c in cams]))
    if len(cams) > 1:
        raise SystemExit("ERR_MULTI_CAMERA:%s" % [c.name for c in cams])
    return cams[0]


def _frame_range(cam, scene):
    ad = cam.animation_data
    if ad and ad.action:
        lo, hi = ad.action.frame_range
        return int(round(lo)), int(round(hi))
    return scene.frame_current, scene.frame_current


def main():
    args = _parse(list(sys.argv))
    _import(args.inp)
    cam = _pick_camera(args.camera)
    scene = bpy.context.scene
    fps = scene.render.fps / max(1.0, float(scene.render.fps_base))
    f0, f1 = _frame_range(cam, scene)
    import math
    frames = []
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        mw = cam.matrix_world
        # Blender FBX import bakes the unit conversion (cm→m = 0.01 scale) into
        # matrix_world.  Decompose to get clean rotation + position in original
        # FBX units (cm) so downstream default_M handles cm→m correctly.
        loc, rot, scl = mw.decompose()
        s = scl[0]  # uniform scale from FBX unit conversion
        rm = rot.to_matrix()
        T = [[rm[r][c] for c in range(3)] + [loc[r] / s] for r in range(3)]
        T.append([0.0, 0.0, 0.0, 1.0])
        # UE-convention horizontal FOV from filmback width + focal (robust to Blender
        # sensor_fit, unlike cam.data.angle_x). Sensor/focal are the UE-exported lens
        # data the user asked to drive FOV from.
        sw = cam.data.sensor_width      # mm == UE Filmback Sensor Width
        focal = cam.data.lens           # mm == UE Current Focal Length
        fov_h = math.degrees(2 * math.atan(sw / (2 * focal)))
        focus = cam.data.dof.focus_distance if cam.data.dof else None
        frames.append({"idx": f - f0, "t_sec": (f - f0) / fps, "T": T,
                       "fov_h_deg": fov_h, "focus_m": focus,
                       "sensor_width_mm": sw, "focal_mm": focal})
    out = {"schema": "vcam.track/1", "fps": fps, "camera": cam.name, "frames": frames}
    with open(args.out, "w") as fh:
        json.dump(out, fh)
    print("OK_FRAMES=%d" % len(frames))


if __name__ == "__main__":
    main()

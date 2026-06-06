"""Runs in a SHORT-LIVED worker subprocess: python -m vcam_bridge.ingest.native_extract --in ... --out ...

Reads an FBX with ufbx (no Blender) and emits the SAME vcam.track/1 JSON as blender_extract.py:
per-frame world matrix (T 4x4), horizontal FOV, fps, lens (focal/sensor), focus.

Why a subprocess + os._exit:
  ufbx 0.0.5's Python binding segfaults (exit 139) during interpreter teardown when its
  native Scene objects are garbage-collected -- reproducible even on plain load, and NOT
  avoidable via .free().  We therefore run all ufbx work in a disposable process, write the
  result, flush+fsync the file, then os._exit(0) to skip the buggy teardown entirely.  The
  parent (native_fbx.py) reads the JSON; a crash here is isolated and cannot corrupt the CLI.
"""
import argparse
import gc
import json
import math
import os
import sys

import ufbx   # only imported inside the worker (optional [native] dependency)

# FBX camera local axes -> Blender camera local axes.  ufbx returns the raw FBX node
# rotation; Designer's downstream _stage_pose_for_frame assumes Blender's camera
# convention (look=-Z col, up=+Y col).  Right-multiplying R by C reconciles the two.
# Verified empirically: R_ufbx @ C matches Blender-extracted R to <1e-6 Frobenius across
# 324 frames of a real UE take.  det(C)=+1 (pure rotation, no reflection).
_C = ((0.0, 0.0, -1.0),
      (0.0, 1.0, 0.0),
      (1.0, 0.0, 0.0))


def _die(msg, code=1):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    os._exit(code)   # clean exit code even on error (normal exit risks the 139 teardown)


def _parse(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--camera", default="")
    return ap.parse_args(argv)


def _pick_camera(scene, name):
    nodes = sorted((n for n in scene.nodes if n.camera is not None), key=lambda n: n.name)
    if not nodes:
        _die("ERR_NO_CAMERA")
    if name:
        for n in nodes:
            if n.name == name:
                return n
        _die("ERR_CAMERA_NOT_FOUND:%s|%s" % (name, [n.name for n in nodes]))
    if len(nodes) > 1:
        _die("ERR_MULTI_CAMERA:%s" % [n.name for n in nodes])
    return nodes[0]


def _T_blender_equiv(m):
    """ufbx world Matrix (column-major, 3x4 affine) -> 4x4 list matching blender_extract.

    Translation is taken as-is (world position is convention-independent and matches Blender
    to micron level).  Rotation block is right-multiplied by _C to match Blender's camera axes.
    """
    R = [[m.c0.x, m.c1.x, m.c2.x],
         [m.c0.y, m.c1.y, m.c2.y],
         [m.c0.z, m.c1.z, m.c2.z]]
    t = (m.c3.x, m.c3.y, m.c3.z)
    RC = [[sum(R[r][k] * _C[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    return [RC[0] + [t[0]], RC[1] + [t[1]], RC[2] + [t[2]], [0.0, 0.0, 0.0, 1.0]]


def main():
    args = _parse(sys.argv[1:])
    gc.disable()                                  # never let cyclic GC touch ufbx natives mid-run

    # Everything ufbx runs inside this guard: any uncaught exception would otherwise unwind into
    # normal interpreter shutdown and trip the ufbx 0.0.5 teardown segfault (exit 139), losing the
    # error message AND the clean exit code.  Routing every failure through _die (os._exit) keeps a
    # malformed FBX a clean rc=1 + diagnostic instead of a confusing crash.  (_die's os._exit is a
    # process exit, not an exception, so _pick_camera's own _die paths still work through this try.)
    try:
        # Normalize any source axis system to right-handed Z-up, exactly like Blender's FBX
        # importer -- UE exports vary (some Z-up, some Y-up), and Blender always lands on Z-up.
        # Without this, a Y-up FBX would come out rotated 90deg vs the Blender path.  Units are
        # left as the file's own (no target_unit_meters), matching Blender's original-units output.
        scene = ufbx.load_file(args.inp, target_axes=ufbx.axes_right_handed_z_up)

        node = _pick_camera(scene, args.camera)
        cam_name = node.name
        fps = scene.settings.frames_per_second or 30.0
        unit_m = scene.settings.unit_meters or 1.0

        stacks = list(scene.anim_stacks)
        anim = stacks[0].anim if stacks else scene.anim

        # Real animated time range -- the FBX anim_stack often reports 0..0 for UE takes, so bake
        # to discover the true key range (cheap; used only for the range, sampling uses evaluate).
        # Snap the range to an INTEGER frame grid and sample at t=f/fps, exactly like Blender's
        # frame_set loop: Blender uses round(action.frame_range), not the raw take span (which can
        # start/end on fractional frames, e.g. -0.6 frame from UE tangent handles).  Anchoring to
        # f0/f1 here keeps frame count and per-frame eval times identical to the Blender path.
        baked = ufbx.bake_anim(scene, anim)
        f0 = int(round(baked.key_time_min * fps))
        f1 = int(round(baked.key_time_max * fps))
        nframes = max(1, f1 - f0 + 1)

        # Sensor (film aperture) width is static (UE animates focal length, not filmback) -- read
        # it ONCE from the BASE camera, where film_size_inch is genuine inches.  ufbx 0.0.5 returns
        # film_size_inch already in MM on EVALUATED cameras (a unit quirk), so never read aperture
        # from an evaluated camera.  Mirrors Blender, whose sensor_width isn't keyframed either.
        sw = node.camera.film_size_inch.x * 25.4       # inches -> mm

        frames = []
        keep = []                                  # hold evaluated scenes; do not let GC reclaim
        for i in range(nframes):
            f = f0 + i
            ev = ufbx.evaluate_scene(scene, anim, f / fps)   # integer-frame time, matches Blender
            keep.append(ev)
            en = ufbx.find_node(ev, cam_name)
            if en is None or en.camera is None:
                _die("ERR_CAMERA_EVAL:%s" % cam_name)        # name vanished on the evaluated scene
            focal = en.camera.focal_length_mm      # per-frame: animated zoom captured here (mm, safe on eval)
            fov_h = math.degrees(2 * math.atan(sw / (2 * focal)))
            # FBX raw focus distance in meters (scene units * unit_meters).  NOT matched to the
            # Blender reader: Blender's importer reports its own opaque post-import focus_distance
            # that is not a derivable function of the FBX value, so --pivot-distance focus is
            # rejected for --reader native upstream (convert._guard_focus_native).
            focus_m = en.camera.props.find_real("FocusDistance", 0.0) * unit_m
            frames.append({"idx": i, "t_sec": i / fps, "T": _T_blender_equiv(en.node_to_world),
                           "fov_h_deg": fov_h, "focus_m": focus_m,
                           "sensor_width_mm": sw, "focal_mm": focal})

        payload = {"schema": "vcam.track/1", "fps": fps, "camera": cam_name, "frames": frames}
        with open(args.out, "w") as fh:            # close() flushes before os._exit
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        sys.stdout.write("OK_FRAMES=%d\n" % len(frames))
        sys.stdout.flush()
    except Exception as exc:                       # never let it reach the segfaulting teardown
        _die("ERR_EXTRACT:%s" % exc)
    os._exit(0)                                    # bypass ufbx 0.0.5 teardown segfault


if __name__ == "__main__":
    main()

"""Frame-by-frame parity: --reader native (ufbx) must match --reader blender within the
project's own tolerances on a real UE-exported FBX.

This is the acceptance gate for the Blender-free reader. It needs both Blender and ufbx, so
it carries the `integration` marker and is skipped in the default unit run.

Point it at a reference FBX via $VCAM_PARITY_FBX (defaults to ~/Downloads/060503.fbx).
"""
import math
import os

import numpy as np
import pytest

from vcam_bridge.domain.models import Config
from vcam_bridge.cli.commands.convert import _load_track, build_keyframes

pytestmark = pytest.mark.integration

_FBX = os.environ.get("VCAM_PARITY_FBX", os.path.expanduser("~/Downloads/060503.fbx"))

# ufbx reads ASCII FBX, which Blender's importer flatly rejects ("ASCII FBX files are not
# supported"), so ASCII parity is checked native-ascii vs native-binary, not against Blender.
_FBX_BIN = os.environ.get("VCAM_PARITY_FBX_BIN",
                          os.path.expanduser("~/Downloads/take_10/test_take_10.fbx"))
_FBX_ASCII = os.environ.get("VCAM_PARITY_FBX_ASCII",
                            os.path.expanduser("~/Downloads/take_10/test_take_10_ascii.fbx"))

# Project tolerances (models.Tolerances / convert defaults).
TOL_POS_M = 1e-3          # 1 mm on Disguise-space position
TOL_POS_CM = TOL_POS_M * 100.0   # reader T is in UE centimeters
TOL_ROT_DEG = 0.05
TOL_FOV_DEG = 0.05


def _ang_diff(a, b):
    """Smallest absolute difference between two angles in degrees (handles ±180 wrap)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _rot_angle_deg(Ra, Rb):
    """Geodesic angle between two rotation matrices, in degrees."""
    c = (np.trace(Ra @ Rb.T) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


@pytest.fixture(scope="module")
def both():
    if not os.path.exists(_FBX):
        pytest.skip("reference FBX not found: %s (set $VCAM_PARITY_FBX)" % _FBX)
    cfg = Config()
    eo = cfg.calibration.euler_order
    bl = _load_track(_FBX, euler_order=eo, reader="blender")
    nv = _load_track(_FBX, euler_order=eo, reader="native")
    assert len(bl.frames) == len(nv.frames), "frame count mismatch: blender=%d native=%d" % (
        len(bl.frames), len(nv.frames))
    # fps: tolerant compare -- Blender derives render.fps/fps_base (e.g. 24/1.001) while ufbx
    # returns the file's stored rate, which can differ in the last digits for NTSC rates. A real
    # mismatch (24 vs 23.976, ~0.1%) still trips this; bit-level rounding noise does not.
    assert math.isclose(bl.fps, nv.fps, rel_tol=1e-4), "fps mismatch: %r vs %r" % (bl.fps, nv.fps)
    # camera name is NOT asserted equal: Blender's importer can collision-rename the object
    # (e.g. 'cam'->'cam.001'); the per-frame pose comparison below is the real parity check.
    kb = build_keyframes(nv, cfg)[2]
    ka = build_keyframes(bl, cfg)[2]
    return bl, nv, ka, kb


def test_reader_T_matrices_match(both):
    """Reader level: native Frame.T must equal Blender Frame.T (position cm, rotation deg)."""
    bl, nv, _, _ = both
    max_pos = max_rot = 0.0
    for fb, fn in zip(bl.frames, nv.frames):
        B, N = np.array(fb.T), np.array(fn.T)
        max_pos = max(max_pos, float(np.linalg.norm(B[:3, 3] - N[:3, 3])))
        max_rot = max(max_rot, _rot_angle_deg(B[:3, :3], N[:3, :3]))
    assert max_pos < TOL_POS_CM, "max position diff %.6g cm exceeds %.4g" % (max_pos, TOL_POS_CM)
    assert max_rot < TOL_ROT_DEG, "max rotation diff %.6g deg exceeds %.4g" % (max_rot, TOL_ROT_DEG)


def test_reader_fov_focal_match(both):
    """Reader level: per-frame FOV / focal / sensor must match Blender."""
    bl, nv, _, _ = both
    for fb, fn in zip(bl.frames, nv.frames):
        assert _ang_diff(fb.fov_h_deg, fn.fov_h_deg) < TOL_FOV_DEG
        assert abs((fb.focal_mm or 0) - (fn.focal_mm or 0)) < 1e-3
        assert abs((fb.sensor_width_mm or 0) - (fn.sensor_width_mm or 0)) < 1e-3


def test_keyframe_pose_parity(both):
    """End-to-end: pivot / rotation / distance / view_angle parity through build_keyframes."""
    bl, nv, ka, kb = both
    for a, b in zip(ka, kb):
        assert np.linalg.norm(np.array(a["pivot"]) - np.array(b["pivot"])) < TOL_POS_M
        for j in range(3):
            assert _ang_diff(a["rotation"][j], b["rotation"][j]) < TOL_ROT_DEG
        assert abs(a["distance"] - b["distance"]) < TOL_POS_M
        assert _ang_diff(a["view_angle"], b["view_angle"]) < TOL_FOV_DEG


def test_native_ascii_matches_binary():
    """ufbx reads ASCII FBX (Blender cannot); the ASCII parse must match the binary parse."""
    from vcam_bridge.ingest.native_fbx import extract_fbx_native
    for p in (_FBX_BIN, _FBX_ASCII):
        if not os.path.exists(p):
            pytest.skip("ascii/binary pair not found: %s" % p)
    bn = extract_fbx_native(_FBX_BIN, use_cache=False)        # bypass shared cache: test fresh output
    asc = extract_fbx_native(_FBX_ASCII, use_cache=False)
    assert len(bn.frames) == len(asc.frames)
    for fb, fa in zip(bn.frames, asc.frames):
        B, A = np.array(fb.T), np.array(fa.T)
        assert np.linalg.norm(B[:3, 3] - A[:3, 3]) < 1e-3
        assert _rot_angle_deg(B[:3, :3], A[:3, :3]) < TOL_ROT_DEG
        assert _ang_diff(fb.fov_h_deg, fa.fov_h_deg) < TOL_FOV_DEG

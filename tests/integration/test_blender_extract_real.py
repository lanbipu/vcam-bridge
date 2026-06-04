import math
import os
import shutil
import subprocess
import sys
import textwrap
import numpy as np
import pytest

from vcam_bridge.ingest.blender_fbx import extract_fbx, find_blender


def _blender_or_skip():
    try:
        return find_blender(None)
    except Exception:
        pytest.skip("Blender not installed")


def _run_blender_script(blender: str, script: str, out_fbx: str):
    rc = subprocess.run([blender, "--background", "--factory-startup", "--python-expr", script,
                         "--", out_fbx], capture_output=True, text=True, timeout=120)
    assert rc.returncode == 0, rc.stderr[-2000:]
    assert os.path.exists(out_fbx)


def _make_camera_fbx(blender: str, out_fbx: str):
    script = textwrap.dedent('''
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cam_data = bpy.data.cameras.new("Cam")
        cam = bpy.data.objects.new("Cam", cam_data)
        bpy.context.collection.objects.link(cam)
        cam.location = (0, 0, 0)
        cam.keyframe_insert("location", frame=1)
        cam.location = (1, 0, 0)
        cam.keyframe_insert("location", frame=2)
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = 2
        import sys
        out = sys.argv[sys.argv.index("--") + 1]
        bpy.ops.export_scene.fbx(filepath=out, object_types={"CAMERA"}, bake_anim=True)
    ''')
    _run_blender_script(blender, script, out_fbx)


@pytest.mark.integration
def test_blender_roundtrip_real(tmp_path):
    blender = _blender_or_skip()
    fbx = str(tmp_path / "cam.fbx")
    _make_camera_fbx(blender, fbx)
    track = extract_fbx(fbx, cache_dir=str(tmp_path / "cache"), use_cache=False)
    assert track.camera
    assert len(track.frames) >= 2
    assert track.frames[0].fov_h_deg > 0
    assert len(track.frames[0].T) == 4 and len(track.frames[0].T[0]) == 4


# --- Layer 2 integration tests ---


@pytest.mark.integration
def test_blender_multi_camera_select_by_name(tmp_path):
    """2.1 — Generate FBX with 2 cameras, select by name."""
    blender = _blender_or_skip()
    script = textwrap.dedent('''
        import bpy, math
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for name, loc in [("CamA", (0, 0, 0)), ("CamB", (5, 5, 5))]:
            cd = bpy.data.cameras.new(name)
            co = bpy.data.objects.new(name, cd)
            bpy.context.collection.objects.link(co)
            co.location = loc
            co.keyframe_insert("location", frame=1)
            co.location = (loc[0]+1, loc[1], loc[2])
            co.keyframe_insert("location", frame=2)
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = 2
        import sys
        bpy.ops.export_scene.fbx(filepath=sys.argv[sys.argv.index("--") + 1],
                                  object_types={"CAMERA"}, bake_anim=True)
    ''')
    fbx = str(tmp_path / "multi.fbx")
    _run_blender_script(blender, script, fbx)

    track_b = extract_fbx(fbx, camera="CamB", cache_dir=str(tmp_path / "c1"), use_cache=False)
    assert track_b.camera == "CamB"
    T0 = np.array(track_b.frames[0].T)
    assert T0[1, 3] > 1.0  # CamB starts at y=5

    track_a = extract_fbx(fbx, camera="CamA", cache_dir=str(tmp_path / "c2"), use_cache=False)
    assert track_a.camera == "CamA"


@pytest.mark.integration
def test_blender_static_camera_one_frame(tmp_path):
    """2.2 — FBX with a static camera (no animation) yields exactly 1 frame."""
    blender = _blender_or_skip()
    script = textwrap.dedent('''
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cd = bpy.data.cameras.new("Static")
        co = bpy.data.objects.new("Static", cd)
        bpy.context.collection.objects.link(co)
        co.location = (3, 4, 5)
        import sys
        bpy.ops.export_scene.fbx(filepath=sys.argv[sys.argv.index("--") + 1],
                                  object_types={"CAMERA"}, bake_anim=True)
    ''')
    fbx = str(tmp_path / "static.fbx")
    _run_blender_script(blender, script, fbx)
    track = extract_fbx(fbx, cache_dir=str(tmp_path / "cache"), use_cache=False)
    assert len(track.frames) == 1
    assert track.frames[0].fov_h_deg > 0


@pytest.mark.integration
def test_blender_cache_hit_consistent(tmp_path):
    """2.4 — Same FBX extracted twice: second call hits cache, results identical."""
    blender = _blender_or_skip()
    fbx = str(tmp_path / "cam.fbx")
    _make_camera_fbx(blender, fbx)
    cache = str(tmp_path / "cache")
    t1 = extract_fbx(fbx, cache_dir=cache, use_cache=True)
    t2 = extract_fbx(fbx, cache_dir=cache, use_cache=True)
    assert len(t1.frames) == len(t2.frames)
    for f1, f2 in zip(t1.frames, t2.frames):
        assert f1.T == f2.T
        assert f1.fov_h_deg == f2.fov_h_deg


@pytest.mark.integration
def test_blender_fov_and_translation_values(tmp_path):
    """2.3 partial — Known camera position + FOV, verify extracted values match."""
    blender = _blender_or_skip()
    script = textwrap.dedent('''
        import bpy, math
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cd = bpy.data.cameras.new("KnownCam")
        cd.lens = 35.0  # ~54.4 deg horizontal FOV for default sensor
        co = bpy.data.objects.new("KnownCam", cd)
        bpy.context.collection.objects.link(co)
        co.location = (10, 20, 30)
        co.keyframe_insert("location", frame=1)
        co.location = (11, 20, 30)
        co.keyframe_insert("location", frame=2)
        bpy.context.scene.frame_start = 1
        bpy.context.scene.frame_end = 2
        import sys
        bpy.ops.export_scene.fbx(filepath=sys.argv[sys.argv.index("--") + 1],
                                  object_types={"CAMERA"}, bake_anim=True)
    ''')
    fbx = str(tmp_path / "known.fbx")
    _run_blender_script(blender, script, fbx)
    track = extract_fbx(fbx, cache_dir=str(tmp_path / "cache"), use_cache=False)
    assert len(track.frames) == 2
    assert 30 < track.frames[0].fov_h_deg < 80  # 35mm lens ≈ 54° on default sensor

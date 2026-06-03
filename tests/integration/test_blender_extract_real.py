import os
import shutil
import subprocess
import sys
import textwrap
import pytest

from vcam_bridge.ingest.blender_fbx import extract_fbx, find_blender


def _blender_or_skip():
    try:
        return find_blender(None)
    except Exception:
        pytest.skip("Blender not installed")


def _make_camera_fbx(blender: str, out_fbx: str):
    # Generate a 2-frame animated camera and export FBX, all inside Blender.
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
    rc = subprocess.run([blender, "--background", "--factory-startup", "--python-expr", script,
                         "--", out_fbx], capture_output=True, text=True, timeout=120)
    assert rc.returncode == 0, rc.stderr[-2000:]
    assert os.path.exists(out_fbx)


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

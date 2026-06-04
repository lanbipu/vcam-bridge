from vcam_bridge.cli.commands.convert import convert_dry_run
from vcam_bridge.config import load_config


def test_convert_dry_run_builds_plan(sample_track_json):
    cfg = load_config(None)
    op, data = convert_dry_run(str(sample_track_json), config=cfg,
                               layer_uid="0xabc")
    assert op == "convert"
    plan = data["dry_run_plan"]
    assert plan["frame_count"] == 2
    assert len(plan["keyframes"]) == 2
    kf0 = plan["keyframes"][0]
    assert set(kf0.keys()) >= {"idx", "t_sec", "pivot", "rotation", "distance", "zoom"}
    # injection script generated and references the layer uid as data
    assert "0xabc" in data["inject_script"]
    assert "json.loads" in data["inject_script"]


def test_convert_dry_run_zoom_computed(sample_track_json):
    import math
    from vcam_bridge.transform.fov import hfov_to_zoom
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg, layer_uid="0xabc")
    kf = data["dry_run_plan"]["keyframes"][0]
    expected_zoom = hfov_to_zoom(60.0, cfg.calibration.baseline_focal_mm, cfg.calibration.sensor_width_mm)
    assert abs(kf["zoom"] - expected_zoom) < 0.001


def test_main_convert_dry_run_json(sample_track_json, capsys):
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(sample_track_json),
               "--target-uid", "0xabc", "--dry-run", "--output", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    import json
    env = json.loads(out)
    assert env["status"] == "ok"
    assert env["operation_id"] == "convert"
    assert env["data"]["dry_run_plan"]["frame_count"] == 2


def test_main_manifest_json(capsys):
    from vcam_bridge.cli.main import main
    rc = main(["manifest", "--output", "json"])
    assert rc == 0
    import json
    env = json.loads(capsys.readouterr().out)
    assert env["data"]["contract_version"] == "1.0"


def test_main_bad_args_exit_2(capsys):
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--output", "json"])   # missing required --fbx
    assert rc == 2


def test_main_convert_missing_fbx_error_envelope(tmp_path, capsys):
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(tmp_path / "nope.json"),
               "--target-uid", "0xabc", "--dry-run", "--output", "json"])
    assert rc == 13
    import json
    env = json.loads(capsys.readouterr().out)
    assert env["status"] == "error"
    assert env["error"]["code"] == "INVALID_FBX"
    assert env["error"]["exit_code"] == 13


# Real Blender-extracted matrices from a UE 5.7.4 CineCamera (Sequencer FBX export,
# Force Front XAxis OFF, Bake Transforms). Ground truth read from UE Sequencer:
#   frame 0   : Location (-1000, -150, 350) cm, FRotator(Pitch=0,    Yaw=0,   Roll=0)
#   frame end : Location (-2500,  1250, 520) cm, FRotator(Pitch=-4.8, Yaw=-26, Roll=5)
_FIX_T0 = [[-0.0, 0.0, -1.0, -1000.000022352], [-1.0, -0.0, 0.0, 150.000003353],
           [0.0, 1.0, -0.0, 350.000007823], [0, 0, 0, 1]]
_FIX_T1 = [[0.430148214, 0.113129623, -0.895641685, -2500.00028871],
           [-0.898570776, -0.041792274, -0.43683365, -1250.000144355],
           [-0.086849891, 0.992700756, 0.083678216, 520.000040978], [0, 0, 0, 1]]


def test_fbx_frame_matches_ue_sequencer_ground_truth():
    """End-to-end: Blender-extracted UE camera matrices -> Disguise ACC pivot/rotation
    must equal the UE Sequencer values. pivot = (UE_Y, UE_Z, UE_X)/100 and
    rotation = (Pitch, Yaw, Roll) (distance 0 -> pivot is the exact camera position).
    See docs/ue-disguise-axis-mapping.md."""
    import numpy as np
    from vcam_bridge.domain.models import CameraTrack
    from vcam_bridge.cli.commands.convert import build_keyframes
    from vcam_bridge.config import load_config
    track = CameraTrack(fps=30.0, camera="Cam", frames=[
        {"idx": 0, "t_sec": 0.0, "T": _FIX_T0, "fov_h_deg": 37.8493},
        {"idx": 1, "t_sec": 5.0, "T": _FIX_T1, "fov_h_deg": 37.8493}])
    _, _, kfs = build_keyframes(track, load_config(None))
    assert np.allclose(kfs[0]["pivot"], [-1.5, 3.5, -10.0], atol=1e-4)
    assert np.allclose(kfs[0]["rotation"], [0.0, 0.0, 0.0], atol=2e-3)
    assert kfs[0]["distance"] == 0.0
    assert np.allclose(kfs[1]["pivot"], [12.5, 5.2, -25.0], atol=1e-4)
    assert np.allclose(kfs[1]["rotation"], [-4.8, -26.0, 5.0], atol=2e-3)
    # FOV -> ACC "view angle" (vertical FOV) drives a Live Camera; clean 35mm focal
    from vcam_bridge.transform.fov import h_to_v
    assert np.isclose(kfs[0]["view_angle"], h_to_v(37.8493, 16.0 / 9.0), atol=1e-6)


def test_build_keyframes_aspect_override_changes_view_angle():
    """The live render aspect (read off the camera) overrides config aspect for view angle,
    so the vertical-FOV -> horizontal-FOV conversion is exact at any output resolution."""
    import numpy as np
    from vcam_bridge.domain.models import CameraTrack
    from vcam_bridge.cli.commands.convert import build_keyframes
    from vcam_bridge.config import load_config
    from vcam_bridge.transform.fov import h_to_v
    track = CameraTrack(fps=30.0, camera="Cam", frames=[
        {"idx": 0, "t_sec": 0.0, "T": _FIX_T0, "fov_h_deg": 37.8493}])
    _, _, kf_cfg = build_keyframes(track, load_config(None))                        # config 16/9
    _, _, kf_ovr = build_keyframes(track, load_config(None), aspect_override=1.6)   # 16:10
    assert np.isclose(kf_cfg[0]["view_angle"], h_to_v(37.8493, 16.0 / 9.0), atol=1e-9)
    assert np.isclose(kf_ovr[0]["view_angle"], h_to_v(37.8493, 1.6), atol=1e-9)
    assert kf_cfg[0]["view_angle"] != kf_ovr[0]["view_angle"]


def test_convert_dry_run_inject_script_has_populated_keys(sample_track_json):
    import re, ast, json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg,
                              layer_uid="0xabc")
    m = re.search(r"payload = json\.loads\((.*)\)\n", data["inject_script"])
    pl = json.loads(ast.literal_eval(m.group(1)))
    assert len(pl["keys"]) == 2
    assert "zoom" in pl["keys"][0]["values"]
    assert "pivot.x" in pl["keys"][0]["values"]
    assert "timeToBeat" in data["inject_script"]


def test_main_pivot_distance_invalid(sample_track_json, capsys):
    import json
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(sample_track_json), "--target-uid", "0xabc",
               "--dry-run", "--pivot-distance", "const=", "--output", "json"])
    assert rc == 3
    env = json.loads(capsys.readouterr().out)
    assert env["status"] == "error"
    assert env["error"]["code"] == "CONFIG_ERROR"


def test_convert_rejects_partial_field_map(sample_track_json):
    import pytest
    from vcam_bridge.domain.models import Config, Calibration
    from vcam_bridge.domain.errors import ConfigError
    from vcam_bridge.cli.commands.convert import convert_dry_run
    cfg = Config(calibration=Calibration(field_map={"pivot.x": "camera pivot.x"}))
    with pytest.raises(ConfigError):
        convert_dry_run(str(sample_track_json), config=cfg, layer_uid="0xabc")


def test_default_distance_ignores_frame_focus_m(tmp_path):
    """Behaviour change: the default (no --pivot-distance) is always 0 and ignores the
    frame's focus_m -- focus_m is only used in explicit "focus" mode."""
    import json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "c", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 5.0}]}))   # focus_m present but must be ignored
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0xabc")
    assert data["dry_run_plan"]["keyframes"][0]["distance"] == 0.0


def test_distance_defaults_to_zero(tmp_path):
    """Default (no --pivot-distance) -> distance 0 so pivot == camera world position."""
    import json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "c", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 2.0}]}))
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0xabc")
    assert data["dry_run_plan"]["keyframes"][0]["distance"] == 0.0


def test_pivot_distance_focus_uses_frame_focus_value(tmp_path):
    """--pivot-distance focus -> distance = frame focus_m."""
    import json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "c", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 2.0}]}))
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0xabc",
                              pivot_distance_const="focus")
    assert data["dry_run_plan"]["keyframes"][0]["distance"] == 2.0


def test_pivot_distance_const_overrides_focus(sample_track_json):
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    _, data = convert_dry_run(str(sample_track_json), config=load_config(None),
                              layer_uid="0xabc", pivot_distance_const=5.0)
    for kf in data["dry_run_plan"]["keyframes"]:
        assert kf["distance"] == 5.0


def test_stage_pose_determinant_always_positive():
    import numpy as np
    from vcam_bridge.cli.commands.convert import _stage_pose_for_frame
    from vcam_bridge.transform.register import default_M
    M = default_M()
    M[:3, :3] *= -1
    T = np.eye(4)
    _, R = _stage_pose_for_frame(T, M)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)


def test_main_config_not_found_exit_3(tmp_path, capsys):
    import json
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", "x.json", "--target-uid", "0x1", "--dry-run",
               "--config", str(tmp_path / "nope.yaml"), "--output", "json"])
    assert rc == 3
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["code"] == "CONFIG_ERROR"


def test_main_convert_live_without_yes_exit_6(sample_track_json, capsys):
    import json
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(sample_track_json), "--target-uid", "0xabc",
               "--director", "host:80", "--vc-uid", "0xdef", "--output", "json"])
    assert rc == 6
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["code"] == "CONFLICT"


def test_main_convert_live_without_vc_exit_3(sample_track_json, capsys):
    import json
    from vcam_bridge.cli.main import main
    rc = main(["convert", "--fbx", str(sample_track_json), "--target-uid", "0xabc",
               "--director", "host:80", "--yes", "--output", "json"])
    assert rc == 3


def test_main_pivot_distance_focus_uses_frame_focus(sample_track_json):
    from vcam_bridge.cli.commands.convert import convert_dry_run
    from vcam_bridge.config import load_config
    _, data = convert_dry_run(str(sample_track_json), config=load_config(None),
                              layer_uid="0xabc", pivot_distance_const="focus")
    assert data["dry_run_plan"]["keyframes"][0]["distance"] == 2.0
    assert data["dry_run_plan"]["keyframes"][1]["distance"] == 2.5


def test_main_generic_exception_exit_1(capsys, monkeypatch):
    import json
    from vcam_bridge.cli import main as main_mod
    original_dispatch = main_mod._dispatch
    def explode(args):
        raise RuntimeError("unexpected boom")
    monkeypatch.setattr(main_mod, "_dispatch", explode)
    rc = main_mod.main(["manifest", "--output", "json"])
    assert rc == 1
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["code"] == "INTERNAL"
    monkeypatch.setattr(main_mod, "_dispatch", original_dispatch)

from vcam_bridge.cli.commands.convert import convert_dry_run
from vcam_bridge.config import load_config


def test_convert_dry_run_builds_plan(sample_track_json):
    cfg = load_config(None)
    op, data = convert_dry_run(str(sample_track_json), config=cfg,
                               layer_uid="0xabc", fov_axis="horizontal")
    assert op == "convert"
    plan = data["dry_run_plan"]
    assert plan["frame_count"] == 2
    assert len(plan["keyframes"]) == 2
    kf0 = plan["keyframes"][0]
    assert set(kf0.keys()) >= {"idx", "t_sec", "pivot", "rotation", "distance", "fov"}
    # injection script generated and references the layer uid as data
    assert "0xabc" in data["inject_script"]
    assert "json.loads" in data["inject_script"]


def test_convert_dry_run_fov_horizontal_passthrough(sample_track_json):
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg,
                              layer_uid="0xabc", fov_axis="horizontal")
    assert data["dry_run_plan"]["keyframes"][0]["fov"] == 60.0


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


def test_stage_pose_default_transform_not_mirrored():
    import numpy as np
    from vcam_bridge.cli.commands.convert import _stage_pose_for_frame
    from vcam_bridge.transform.register import default_M
    T = np.eye(4)
    T[:3, 3] = [100.0, 0.0, 0.0]   # UE camera at +100cm X
    C, R = _stage_pose_for_frame(T, default_M())
    assert C[0] > 0                                   # +X stays +X (not mirrored)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)   # proper rotation


def test_convert_dry_run_inject_script_has_populated_keys(sample_track_json):
    import re, ast, json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    cfg = load_config(None)
    _, data = convert_dry_run(str(sample_track_json), config=cfg,
                              layer_uid="0xabc", fov_axis="horizontal")
    m = re.search(r"payload = json\.loads\((.*)\)\n", data["inject_script"])
    pl = json.loads(ast.literal_eval(m.group(1)))
    assert len(pl["keys"]) == 2
    assert "fov" in pl["keys"][0]["values"]
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
    cfg = Config(calibration=Calibration(field_map={"pivot.x": "camera_pivot.x"}))
    with pytest.raises(ConfigError):
        convert_dry_run(str(sample_track_json), config=cfg, layer_uid="0xabc")


def test_focus_m_zero_is_used_not_defaulted(tmp_path):
    import json
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"fps": 30, "camera": "c", "frames": [
        {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0], "rotation_deg": [0, 0, 0],
         "fov_h_deg": 60, "focus_m": 0.0}]}))
    _, data = convert_dry_run(str(p), config=load_config(None), layer_uid="0xabc")
    assert data["dry_run_plan"]["keyframes"][0]["distance"] == 0.0

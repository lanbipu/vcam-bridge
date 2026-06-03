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

def test_dry_run_fov_control_label(sample_track_csv):
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    op, data = convert_dry_run(str(sample_track_csv), config=load_config(None), layer_uid="0x1")
    # Live Camera 实由 view angle 驱动，旧的 "zoom_scale" 标签误导
    assert data["dry_run_plan"]["fov_control"] == "view_angle+zoom"

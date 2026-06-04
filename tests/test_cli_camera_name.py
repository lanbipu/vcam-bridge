import pytest

import vcam_bridge.cli.main as m
from vcam_bridge.domain.errors import ConfigError


def test_camera_name_without_director_errors(tmp_path):
    fbx = tmp_path / "t.csv"
    fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--camera-name", "live cam 1", "--yes"])
    with pytest.raises(ConfigError):
        m._dispatch(args)


def test_camera_name_resolves_to_uid(monkeypatch, tmp_path):
    monkeypatch.setattr("vcam_bridge.designer.targets.list_cameras",
                        lambda c: [{"name": "live cam 1", "uid": "0xaa", "type": "live"}])
    monkeypatch.setattr("vcam_bridge.designer.client.DesignerClient.resolve_routing", lambda self: None)
    captured = {}

    def fake_live(transport, **kw):
        captured.update(kw)
        return "convert", {"written": 0}

    monkeypatch.setattr("vcam_bridge.cli.commands.convert.convert_live", fake_live)
    fbx = tmp_path / "t.csv"
    fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--camera-name", "live cam 1",
         "--director", "h:80", "--yes", "--curl"])
    m._dispatch(args)
    assert captured["vc_uid"] == "0xaa"
    assert captured["layer_uid"] == "0x1"


def test_target_uid_and_name_mutually_exclusive(tmp_path):
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--target-name", "Foo",
         "--director", "h:80", "--yes"])
    with pytest.raises(ConfigError, match="mutually exclusive"):
        m._dispatch(args)


def test_vc_uid_and_camera_name_mutually_exclusive(tmp_path):
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--vc-uid", "0x2",
         "--camera-name", "Bar", "--director", "h:80", "--yes"])
    with pytest.raises(ConfigError, match="mutually exclusive"):
        m._dispatch(args)


def test_dry_run_with_camera_name_does_not_require_director(tmp_path, monkeypatch):
    # --camera-name 在 dry-run 不被消费 → 不该逼连 director（review #2 修复）
    monkeypatch.setattr("vcam_bridge.cli.commands.convert.convert_dry_run",
                        lambda fbx, **kw: ("convert", {"dry_run_plan": {}}))
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--camera-name", "live cam 1", "--dry-run"])
    op, data = m._dispatch(args)
    assert op == "convert"

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

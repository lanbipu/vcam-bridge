import json
import math
import pytest

from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.cli.commands import targets as targets_cmd


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_targets_list_command_returns_layers():
    ft = FakeTransport(
        execute_responses=[_ok('[["My ACC", "0xabc"]]')],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    op, data = targets_cmd.list_targets(ft, host="localhost")
    assert op == "targets.list"
    assert data["layers"] == [{"name": "My ACC", "uid": "0xabc"}]


def test_convert_live_injects(sample_track_csv):
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_live
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_ok('{"ok": true, "note": []}'),         # set-target
                           _ok('{"ok": true, "written": 16}')],     # one chunk (2 frames x 8 fields)
    )
    op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                            config=load_config(None), layer_uid="0xabc", vc_uid="0xdef", chunk_size=100)
    assert op == "convert"
    assert data["written"] == 16
    assert data["vc_uid"] == "0xdef"
    assert len(ft.executed) == 2   # 1 set-target + 1 chunk


def test_convert_live_invalid_uid():
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_live
    from vcam_bridge.domain.errors import ConfigError
    ft = FakeTransport(json_responses={}, execute_responses=[])
    with pytest.raises(ConfigError, match="0x-hex"):
        convert_live(ft, host="localhost", fbx="x.csv", config=load_config(None),
                     layer_uid="not-hex", vc_uid="0xdef")


def test_convert_live_set_target_fail(sample_track_csv):
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_live
    from vcam_bridge.domain.errors import PartialError
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_ok('{"ok": false, "error": "acc layer not found"}')],
    )
    with pytest.raises(PartialError, match="camera target"):
        convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                     config=load_config(None), layer_uid="0xabc", vc_uid="0xdef")


def test_vc_list_command():
    from vcam_bridge.cli.commands import vc as vc_cmd
    ft = FakeTransport(
        execute_responses=[_ok('[["VC1", "0x99"]]')],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    op, data = vc_cmd.list_vcams(ft, host="localhost")
    assert op == "vc.list"
    assert data["virtual_cameras"] == [{"name": "VC1", "uid": "0x99"}]


def test_probe_command():
    from vcam_bridge.cli.commands import probe as probe_cmd
    ft = FakeTransport(
        execute_responses=[
            _ok('"AnimateCameraControl"'),
            _ok('["camera_pivot.x", "fieldOfView"]'),
        ],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    op, data = probe_cmd.run_probe(ft, host="localhost", probe_layer_uid="0xabc")
    assert op == "probe"
    assert data["module_type"] == "AnimateCameraControl"
    assert "fieldOfView" in data["field_names"]

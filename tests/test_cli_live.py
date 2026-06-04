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

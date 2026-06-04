import pytest

from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_tracks, list_acc_layers, list_vcs, resolve_layer_uid
from vcam_bridge.domain.errors import ConfigError, NotFoundError


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_list_tracks_parses_rest():
    ft = FakeTransport(json_responses={"/api/session/transport/tracks":
        {"status": {"code": 0}, "result": [{"uid": "0x1", "name": "Main", "length": 100, "crossfade": ""}]}})
    c = DesignerClient(ft, "localhost")
    tracks = list_tracks(c)
    assert tracks == [{"uid": "0x1", "name": "Main"}]


def test_list_acc_layers_filters_exact_module():
    # moduleType 是 _blipValue(...) 对象字符串；精确取括号内 module 名 == AnimateCamera，
    # 排除 AnimateCamera2（Preset，子串也含 "AnimateCamera"）和其它 module。
    rv = ('[["Ctrl", "0xa", "<_blipValue(AnimateCamera) instance at 0x1>"], '
          '["Preset", "0xb", "<_blipValue(AnimateCamera2) instance at 0x2>"], '
          '["Vid", "0xc", "<_blipValue(VariableVideoModule) instance at 0x3>"]]')
    ft = FakeTransport(execute_responses=[_ok(rv)])
    c = DesignerClient(ft, "localhost")
    assert list_acc_layers(c) == [{"name": "Ctrl", "uid": "0xa"}]   # 仅精确 AnimateCamera
    assert "moduleType" in ft.executed[0]["script"]


def test_list_vcs_uses_execute():
    ft = FakeTransport(execute_responses=[_ok('[["VC1", "0xdef"]]')])
    c = DesignerClient(ft, "localhost")
    assert list_vcs(c) == [{"name": "VC1", "uid": "0xdef"}]


_LAYERS = [{"name": "AnimateCameraControl", "uid": "0x42be"},
           {"name": "AnimateCameraControl 2", "uid": "0x514c"}]


def test_resolve_by_name_single_match():
    assert resolve_layer_uid(_LAYERS, "AnimateCameraControl 2") == "0x514c"


def test_resolve_by_uid_passthrough_case_insensitive():
    assert resolve_layer_uid(_LAYERS, "0x42BE") == "0x42be"


def test_resolve_name_not_found_raises():
    with pytest.raises(NotFoundError):
        resolve_layer_uid(_LAYERS, "NoSuchLayer")


def test_resolve_name_ambiguous_raises():
    dup = [{"name": "ACC", "uid": "0x1"}, {"name": "ACC", "uid": "0x2"}]
    with pytest.raises(ConfigError):
        resolve_layer_uid(dup, "ACC")

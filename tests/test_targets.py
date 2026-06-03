from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_tracks, list_acc_layers, list_vcs


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_list_tracks_parses_rest():
    ft = FakeTransport(json_responses={"/api/session/transport/tracks":
        {"status": {"code": 0}, "result": [{"uid": "0x1", "name": "Main", "length": 100, "crossfade": ""}]}})
    c = DesignerClient(ft, "localhost")
    tracks = list_tracks(c)
    assert tracks == [{"uid": "0x1", "name": "Main"}]


def test_list_acc_layers_uses_execute():
    ft = FakeTransport(execute_responses=[_ok('[["My ACC", "0xabc"]]')])
    c = DesignerClient(ft, "localhost")
    layers = list_acc_layers(c)
    assert layers == [{"name": "My ACC", "uid": "0xabc"}]
    assert "moduleType" in ft.executed[0]["script"]   # enumerates via track.layers


def test_list_vcs_uses_execute():
    ft = FakeTransport(execute_responses=[_ok('[["VC1", "0xdef"]]')])
    c = DesignerClient(ft, "localhost")
    assert list_vcs(c) == [{"name": "VC1", "uid": "0xdef"}]

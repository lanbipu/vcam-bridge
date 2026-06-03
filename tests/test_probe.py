from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.probe import probe_field_set, ProbeReport


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_probe_field_set_parses_sequences():
    ft = FakeTransport(execute_responses=[_ok('["camera_pivot.x", "camera_pivot.y", "fieldOfView"]')])
    c = DesignerClient(ft, "localhost")
    fields = probe_field_set(c, layer_uid="0xabc")
    assert "fieldOfView" in fields
    assert "moduleType" not in ft.executed[0]["script"]  # this probe lists sequences


def test_probe_report_dataclass():
    r = ProbeReport(version="R33", legacy_vc=False, module_type="AnimateCameraControl",
                    field_names=["fieldOfView"], notes=[])
    assert r.legacy_vc is False

import pytest
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.domain.errors import ExternalError, DesignerTimeoutError


def _ok(rv="null"):
    return {"status": {"code": 0, "message": "", "details": []}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_execute_parses_return_value_json():
    ft = FakeTransport(execute_responses=[_ok('{"written": 3}')])
    c = DesignerClient(ft, "localhost")
    res = c.execute("...")
    assert res.return_value == {"written": 3}


def test_execute_null_returns_none():
    c = DesignerClient(FakeTransport(execute_responses=[_ok("null")]), "localhost")
    assert c.execute("...").return_value is None


def test_execute_error_maps_to_external_and_fixes_line_offset():
    err = {"status": {"code": 1, "message": "Error at line 12: NameError", "details": []},
           "d3Log": "", "pythonLog": "", "returnValue": "null"}
    c = DesignerClient(FakeTransport(execute_responses=[err]), "localhost")
    with pytest.raises(ExternalError) as ei:
        c.execute("...")
    assert "line 2" in ei.value.message   # 12 - 10 offset


def test_timeout_maps_to_designer_timeout():
    err = {"status": {"code": 1, "message": "TimeoutError: exceeded"}, "d3Log": "", "pythonLog": "", "returnValue": "null"}
    c = DesignerClient(FakeTransport(execute_responses=[err]), "localhost")
    with pytest.raises(DesignerTimeoutError):
        c.execute("...")


def test_resolve_routes_to_director_when_not_solo():
    ft = FakeTransport(json_responses={"/api/session/status/session":
                       {"isRunningSolo": False, "director": {"hostname": "10.0.0.9"}}})
    c = DesignerClient(ft, "localhost")
    c.resolve_routing()
    assert c.host == "10.0.0.9"


def test_resolve_stays_local_when_solo():
    ft = FakeTransport(json_responses={"/api/session/status/session": {"isRunningSolo": True}})
    c = DesignerClient(ft, "localhost:80")
    c.resolve_routing()
    assert c.host == "localhost:80"


def test_resolve_preserves_port_when_director_has_none():
    ft = FakeTransport(json_responses={"/api/session/status/session":
        {"isRunningSolo": False, "director": {"hostname": "10.0.0.9"}}})
    c = DesignerClient(ft, "localhost:8080")
    c.resolve_routing()
    assert c.host == "10.0.0.9:8080"


def test_resolve_idempotent():
    ft = FakeTransport(json_responses={"/api/session/status/session": {"isRunningSolo": True}})
    c = DesignerClient(ft, "myhost:80")
    c.resolve_routing()
    c.resolve_routing()
    assert c.host == "myhost:80"


def test_execute_empty_return_value():
    c = DesignerClient(FakeTransport(execute_responses=[_ok("")]), "localhost")
    assert c.execute("...").return_value is None


def test_execute_none_return_value():
    resp = {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": None}
    c = DesignerClient(FakeTransport(execute_responses=[resp]), "localhost")
    assert c.execute("...").return_value is None


def test_keyboard_interrupt_maps_to_timeout():
    err = {"status": {"code": 1, "message": "KeyboardInterrupt in script"}, "d3Log": "", "pythonLog": "", "returnValue": "null"}
    c = DesignerClient(FakeTransport(execute_responses=[err]), "localhost")
    with pytest.raises(DesignerTimeoutError):
        c.execute("...")


def test_line_offset_clamps_to_1():
    assert DesignerClient._fix_line_offset("Error at line 5: x") == "Error at line 1: x"


def test_execute_logs_captured():
    resp = {"status": {"code": 0}, "d3Log": "d3 stuff", "pythonLog": "py stuff", "returnValue": '"ok"'}
    c = DesignerClient(FakeTransport(execute_responses=[resp]), "localhost")
    res = c.execute("...")
    assert res.d3_log == "d3 stuff"
    assert res.python_log == "py stuff"

from vcam_bridge.designer.transport import FakeTransport


def test_fake_transport_records_and_replies():
    ft = FakeTransport(
        execute_responses=[{"status": {"code": 0}, "returnValue": "\"ok\"", "d3Log": "", "pythonLog": ""}],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    resp = ft.post_execute("localhost", "print('x')")
    assert resp["returnValue"] == '"ok"'
    assert ft.executed[0]["script"] == "print('x')"
    assert ft.get_json("localhost", "/api/session/status/session")["isRunningSolo"] is True


def test_fake_transport_raises_when_exhausted():
    import pytest
    ft = FakeTransport(execute_responses=[])
    with pytest.raises(IndexError):
        ft.post_execute("localhost", "x")

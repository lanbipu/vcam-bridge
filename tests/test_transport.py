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


def test_requests_transport_maps_connection_error(monkeypatch):
    import requests, pytest
    from vcam_bridge.designer.transport import RequestsTransport
    from vcam_bridge.domain.errors import ExternalError
    t = RequestsTransport()
    def boom(*a, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(t._session, "post", boom)
    with pytest.raises(ExternalError):
        t.post_execute("localhost", "x")

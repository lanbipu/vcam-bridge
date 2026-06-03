from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import chunk_keys, inject_keys


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def _keys(n):
    return [{"t_sec": i * 0.1, "values": {"fov": 60.0 + i}} for i in range(n)]


def test_chunk_keys_splits():
    chunks = chunk_keys(_keys(250), 100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_inject_writes_all_chunks():
    ft = FakeTransport(execute_responses=[_ok('{"ok": true, "written": 100}'),
                                          _ok('{"ok": true, "written": 100}'),
                                          _ok('{"ok": true, "written": 50}')])
    c = DesignerClient(ft, "localhost")
    fields = {"fov": "fieldOfView"}
    written = inject_keys(c, layer_uid="0x1", fields=fields, keys=_keys(250),
                          start_offset_sec=0.0, chunk_size=100)
    assert written == 250
    assert len(ft.executed) == 3


def test_inject_halves_chunk_on_timeout():
    from vcam_bridge.designer.transport import FakeTransport as FT
    # first call (50 keys) -> timeout; then two 25-key calls succeed
    timeout = {"status": {"code": 1, "message": "TimeoutError"}, "returnValue": "null", "d3Log": "", "pythonLog": ""}
    ft = FT(execute_responses=[timeout, _ok('{"ok": true, "written": 25}'), _ok('{"ok": true, "written": 25}')])
    c = DesignerClient(ft, "localhost", retries=0)
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=_keys(50),
                          start_offset_sec=0.0, chunk_size=50)
    assert written == 50

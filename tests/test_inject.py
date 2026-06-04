import pytest
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.inject import chunk_keys, inject_keys
from vcam_bridge.domain.errors import DesignerTimeoutError, PartialError


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def _keys(n):
    return [{"t_sec": i * 0.1, "values": {"fov": 60.0 + i}} for i in range(n)]


def test_chunk_keys_splits():
    chunks = chunk_keys(_keys(250), 100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_chunk_keys_single():
    chunks = chunk_keys(_keys(3), 100)
    assert len(chunks) == 1
    assert len(chunks[0]) == 3


def test_chunk_keys_exact():
    chunks = chunk_keys(_keys(100), 100)
    assert len(chunks) == 1


def test_chunk_keys_size_zero_clamps():
    chunks = chunk_keys(_keys(5), 0)
    assert len(chunks) == 5


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
    timeout = {"status": {"code": 1, "message": "TimeoutError"}, "returnValue": "null", "d3Log": "", "pythonLog": ""}
    ft = FakeTransport(execute_responses=[timeout, _ok('{"ok": true, "written": 25}'), _ok('{"ok": true, "written": 25}')])
    c = DesignerClient(ft, "localhost")
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=_keys(50),
                          start_offset_sec=0.0, chunk_size=50)
    assert written == 50


def test_inject_min_chunk_timeout_raises():
    timeout = {"status": {"code": 1, "message": "TimeoutError"}, "returnValue": "null", "d3Log": "", "pythonLog": ""}
    ft = FakeTransport(execute_responses=[timeout])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(DesignerTimeoutError):
        inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=_keys(5),
                    start_offset_sec=0.0, chunk_size=5, min_chunk=8)


def test_inject_partial_error():
    ft = FakeTransport(execute_responses=[_ok('{"ok": false, "error": "missing fields", "missing": ["x"]}')])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(PartialError, match="inject chunk failed"):
        inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=_keys(10),
                    start_offset_sec=0.0, chunk_size=100)


def test_inject_empty_keys_returns_zero():
    ft = FakeTransport(execute_responses=[])
    c = DesignerClient(ft, "localhost")
    written = inject_keys(c, layer_uid="0x1", fields={"fov": "fieldOfView"}, keys=[],
                          start_offset_sec=0.0, chunk_size=100)
    assert written == 0
    assert len(ft.executed) == 0

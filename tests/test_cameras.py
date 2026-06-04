import json

import pytest

from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.designer.targets import list_cameras, resolve_camera_uid, _CAMERA_ENUM_SCRIPT
from vcam_bridge.cli.commands import vc as vc_cmd
from vcam_bridge.domain.errors import ConfigError, NotFoundError


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


_ROWS = json.dumps([
    ["0xaa1e1c34ac2ad525", "objects/camera/live cam 1.apx", "live cam 1", "Camera"],
    ["0x8590ade039a8af4", "objects/camera/live cam 2.apx", "live cam 2", "Camera"],
    ["0xd3ebbf1e5336711c", "objects/virtualcamera/virtual cam 1.apx", "virtual cam 1", "VirtualCamera"],
])


def _client(rows=_ROWS):
    ft = FakeTransport(execute_responses=[_ok(rows)])
    return DesignerClient(ft, "localhost"), ft


def test_list_cameras_includes_live_and_virtual_with_type():
    c, _ = _client()
    assert list_cameras(c) == [
        {"name": "live cam 1", "uid": "0xaa1e1c34ac2ad525", "type": "live"},
        {"name": "live cam 2", "uid": "0x8590ade039a8af4", "type": "live"},
        {"name": "virtual cam 1", "uid": "0xd3ebbf1e5336711c", "type": "virtual"}]


def test_enum_script_never_uses_broken_cam_name():
    # d3 Camera 无 .name；脚本只读 uid/path/description/type，绝不能引用 cam.name
    assert "cam.name" not in _CAMERA_ENUM_SCRIPT
    assert "cam.path" in _CAMERA_ENUM_SCRIPT


def test_resolve_camera_by_name_and_uid():
    cams = list_cameras(_client()[0])
    assert resolve_camera_uid(cams, "live cam 1") == "0xaa1e1c34ac2ad525"
    assert resolve_camera_uid(cams, "0xAA1E1C34AC2AD525") == "0xaa1e1c34ac2ad525"


def test_resolve_camera_unknown_and_ambiguous():
    cams = list_cameras(_client()[0])
    with pytest.raises(NotFoundError):
        resolve_camera_uid(cams, "nope")
    dup = list_cameras(_client(json.dumps([
        ["0xaa", "objects/camera/live cam 1.apx", "live cam 1", "Camera"],
        ["0x999", "objects/camera/live cam 1.apx", "dup", "Camera"]]))[0])
    with pytest.raises(ConfigError):
        resolve_camera_uid(dup, "live cam 1")


def test_vc_list_emits_cameras_and_backcompat_alias():
    ft = FakeTransport(execute_responses=[_ok(_ROWS)],
                       json_responses={"/api/session/status/session": {"isRunningSolo": True}})
    op, data = vc_cmd.list_vcams(ft, host="localhost")
    assert op == "vc.list"
    assert data["cameras"][0] == {"name": "live cam 1", "uid": "0xaa1e1c34ac2ad525", "type": "live"}
    # 向后兼容：旧 key 保留，含虚拟子集（语义不变）
    assert data["virtual_cameras"] == [{"name": "virtual cam 1", "uid": "0xd3ebbf1e5336711c", "type": "virtual"}]

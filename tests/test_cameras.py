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
    {"uid": "0xaa1e1c34ac2ad525", "path": "objects/camera/live cam 1.apx", "desc": "live cam 1", "cls": "Camera",
     "focal_mm": 22.7, "sensor_mm": [35.0, 19.687]},
    {"uid": "0x8590ade039a8af4", "path": "objects/camera/live cam 2.apx", "desc": "live cam 2", "cls": "Camera",
     "focal_mm": 15.75, "sensor_mm": [24.0, 13.5]},
    {"uid": "0xd3ebbf1e5336711c", "path": "objects/virtualcamera/virtual cam 1.apx", "desc": "virtual cam 1", "cls": "VirtualCamera",
     "focal_mm": 22.97, "zoom_scale": 1.0, "sensor_mm": [35.0, 19.687], "parent_uid": "0xaa1e1c34ac2ad525"},
])


def _client(rows=_ROWS):
    ft = FakeTransport(execute_responses=[_ok(rows)])
    return DesignerClient(ft, "localhost"), ft


def test_list_cameras_includes_live_and_virtual_with_type():
    c, _ = _client()
    cams = list_cameras(c)
    assert len(cams) == 3
    assert cams[0]["name"] == "live cam 1"
    assert cams[0]["uid"] == "0xaa1e1c34ac2ad525"
    assert cams[0]["type"] == "live"
    assert cams[0]["focal_mm"] == 22.7
    assert cams[2]["name"] == "virtual cam 1"
    assert cams[2]["type"] == "virtual"
    assert cams[2]["zoom_scale"] == 1.0
    assert cams[2]["parent_uid"] == "0xaa1e1c34ac2ad525"


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
        {"uid": "0xaa", "path": "objects/camera/live cam 1.apx", "desc": "live cam 1", "cls": "Camera"},
        {"uid": "0x999", "path": "objects/camera/live cam 1.apx", "desc": "dup", "cls": "Camera"}]))[0])
    with pytest.raises(ConfigError):
        resolve_camera_uid(dup, "live cam 1")


def test_vc_list_emits_cameras_and_backcompat_alias():
    ft = FakeTransport(execute_responses=[_ok(_ROWS)],
                       json_responses={"/api/session/status/session": {"isRunningSolo": True}})
    op, data = vc_cmd.list_vcams(ft, host="localhost")
    assert op == "vc.list"
    assert data["cameras"][0]["name"] == "live cam 1"
    assert data["cameras"][0]["uid"] == "0xaa1e1c34ac2ad525"
    assert data["cameras"][0]["type"] == "live"
    assert len(data["virtual_cameras"]) == 1
    assert data["virtual_cameras"][0]["name"] == "virtual cam 1"
    assert data["virtual_cameras"][0]["uid"] == "0xd3ebbf1e5336711c"

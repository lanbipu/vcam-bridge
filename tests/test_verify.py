import pytest
import numpy as np
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient
from vcam_bridge.domain.errors import VerifyToleranceError


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_verify_persistence_passes():
    from vcam_bridge.designer.inject import verify_keys_persistence
    ft = FakeTransport(execute_responses=[
        _ok('{"max_errors": {"pivot.x": 0.0001, "zoom": 0.001}, "total_keys": 8}'),
    ])
    c = DesignerClient(ft, "localhost")
    report = verify_keys_persistence(c, layer_uid="0x1",
        fields={"pivot.x": "camera pivot.x", "zoom": "virtual camera zoom"},
        keys=[{"t_sec": 0, "values": {"pivot.x": 1.0, "zoom": 1.0}}],
        start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05)
    assert report["ok"] is True
    assert report["total_keys"] == 8


def test_verify_persistence_raises_on_tolerance():
    from vcam_bridge.designer.inject import verify_keys_persistence
    ft = FakeTransport(execute_responses=[
        _ok('{"max_errors": {"pivot.x": 0.5, "zoom": 0.001}, "total_keys": 8}'),
    ])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(VerifyToleranceError):
        verify_keys_persistence(c, layer_uid="0x1",
            fields={"pivot.x": "camera pivot.x", "zoom": "virtual camera zoom"},
            keys=[{"t_sec": 0, "values": {"pivot.x": 1.0, "zoom": 1.0}}],
            start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05)


def test_verify_world_pose_passes():
    from vcam_bridge.designer.inject import verify_world_pose
    ft = FakeTransport(
        execute_responses=[
            _ok('{"goto_secs": [0.0]}'),          # beat-corrected gototime seconds
            _ok('{"pos": [1.0, 0.0, -2.0]}'),
        ],
    )
    c = DesignerClient(ft, "localhost")
    report = verify_world_pose(c, layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}}],
        start_offset_sec=0.0,
        expected_positions=[[1.0, 0.0, -2.0]],
        tol_pos=0.001)
    assert report["ok"] is True
    assert report["sampled"] == 1
    # gototime 用 beatToTime(tStart + timeToBeat(...)) 修正，不再是裸秒（修 tStart 漏算 bug）
    assert "beatToTime" in ft.executed[0]["script"] and "tStart" in ft.executed[0]["script"]


def test_verify_world_pose_raises():
    from vcam_bridge.designer.inject import verify_world_pose
    ft = FakeTransport(
        execute_responses=[
            _ok('{"goto_secs": [0.0]}'),
            _ok('{"pos": [5.0, 5.0, 5.0]}'),
        ],
    )
    c = DesignerClient(ft, "localhost")
    with pytest.raises(VerifyToleranceError):
        verify_world_pose(c, layer_uid="0xL", vc_uid="0xabc",
            keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}}],
            start_offset_sec=0.0,
            expected_positions=[[1.0, 0.0, -2.0]],
            tol_pos=0.001)


def test_verify_world_pose_empty_keys():
    from vcam_bridge.designer.inject import verify_world_pose
    ft = FakeTransport(execute_responses=[])
    c = DesignerClient(ft, "localhost")
    report = verify_world_pose(c, layer_uid="0xL", vc_uid="0xabc", keys=[], start_offset_sec=0.0,
                               expected_positions=[], tol_pos=0.001)
    assert report["sampled"] == 0


def test_verify_persistence_null_return_raises():
    from vcam_bridge.designer.inject import verify_keys_persistence
    from vcam_bridge.domain.errors import PartialError
    ft = FakeTransport(execute_responses=[_ok("null")])
    c = DesignerClient(ft, "localhost")
    with pytest.raises(PartialError, match="returned null"):
        verify_keys_persistence(c, layer_uid="0x1",
            fields={"pivot.x": "camera pivot.x"},
            keys=[{"t_sec": 0, "values": {"pivot.x": 1.0}}],
            start_offset_sec=0.0, tol_pos=0.001, tol_rot=0.05, tol_zoom=0.05)

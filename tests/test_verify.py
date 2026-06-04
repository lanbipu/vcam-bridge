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


# ---- verify_world_pose: degrade 路径 + beat-corrected vs 裸秒 + 多-key（max-effort review 修复）----

def _err(msg="boom", code=500):
    # 非零 status → DesignerClient.execute 抛 ExternalError（模拟 C++ 异常穿透 → 500）
    return {"status": {"code": code, "message": msg, "details": []},
            "d3Log": "", "pythonLog": "", "returnValue": "null"}


def test_world_pose_uses_beat_corrected_time(monkeypatch):
    # 公式守护：goto_secs=[5.0] 而 t_sec=0.0 → 传给 gototime 的必须是 5.0（beat-corrected），不是裸秒 0.0
    from vcam_bridge.designer import inject
    calls = []
    monkeypatch.setattr(inject, "_gototime", lambda client, t: calls.append(t))
    ft = FakeTransport(execute_responses=[_ok('{"goto_secs": [5.0]}'), _ok('{"pos": [1.0, 2.0, 3.0]}')])
    c = DesignerClient(ft, "localhost")
    out = inject.verify_world_pose(c, layer_uid="0xL", vc_uid="0xabc", keys=[{"t_sec": 0.0}],
        start_offset_sec=0.0, expected_positions=[[1.0, 2.0, 3.0]], tol_pos=0.001)
    assert out["ok"] is True
    assert calls == [5.0]


def test_world_pose_degrades_on_goto_app_error(monkeypatch):
    from vcam_bridge.designer import inject
    monkeypatch.setattr(inject, "_gototime", lambda client, t: None)
    ft = FakeTransport(execute_responses=[_ok('{"error": "layer not found"}')])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0}], start_offset_sec=0.0, expected_positions=[[0, 0, 0]], tol_pos=0.001)
    assert out["ok"] is None and out["skipped"]


def test_world_pose_degrades_on_goto_external_error(monkeypatch):
    # C++ 异常 → 500 → ExternalError：inject 已成功，绝不炸 convert（exit 8），degrade 成 skip
    from vcam_bridge.designer import inject
    monkeypatch.setattr(inject, "_gototime", lambda client, t: None)
    ft = FakeTransport(execute_responses=[_err("AttributeError: beatToTime")])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0}], start_offset_sec=0.0, expected_positions=[[0, 0, 0]], tol_pos=0.001)
    assert out["ok"] is None and out["skipped"]


def test_world_pose_degrades_on_missing_goto_secs(monkeypatch):
    # 无 goto_secs → 绝不退回裸秒去 seek（那会重新引入 tStart 漏算 bug），degrade
    from vcam_bridge.designer import inject
    calls = []
    monkeypatch.setattr(inject, "_gototime", lambda client, t: calls.append(t))
    ft = FakeTransport(execute_responses=[_ok('{}')])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0}], start_offset_sec=0.0, expected_positions=[[0, 0, 0]], tol_pos=0.001)
    assert out["ok"] is None and out["skipped"]
    assert calls == []


def test_world_pose_degrades_on_short_goto_secs(monkeypatch):
    # 2 采样但 goto_secs 只 1 个 → 长度不符 → degrade（不 IndexError）
    from vcam_bridge.designer import inject
    monkeypatch.setattr(inject, "_gototime", lambda client, t: None)
    ft = FakeTransport(execute_responses=[_ok('{"goto_secs": [5.0]}')])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0}, {"t_sec": 1.0}], start_offset_sec=0.0,
        expected_positions=[[0, 0, 0], [0, 0, 0]], tol_pos=0.001)
    assert out["ok"] is None and out["skipped"]


def test_world_pose_degrades_on_readback_error(monkeypatch):
    from vcam_bridge.designer import inject
    monkeypatch.setattr(inject, "_gototime", lambda client, t: None)
    ft = FakeTransport(execute_responses=[_ok('{"goto_secs": [0.0]}'), _ok('{"error": "vc not found"}')])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=[{"t_sec": 0.0}], start_offset_sec=0.0, expected_positions=[[0, 0, 0]], tol_pos=0.001)
    assert out["ok"] is None and out["skipped"]


def test_world_pose_samples_multiple_indices(monkeypatch):
    # len(keys)=5 → indices=[0,2,4]（多-index 采样路径）
    from vcam_bridge.designer import inject
    calls = []
    monkeypatch.setattr(inject, "_gototime", lambda client, t: calls.append(t))
    keys = [{"t_sec": i * 0.1} for i in range(5)]
    ft = FakeTransport(execute_responses=[_ok('{"goto_secs": [0.0, 0.2, 0.4]}'),
        _ok('{"pos": [0, 0, 0]}'), _ok('{"pos": [0, 0, 0]}'), _ok('{"pos": [0, 0, 0]}')])
    out = inject.verify_world_pose(DesignerClient(ft, "localhost"), layer_uid="0xL", vc_uid="0xabc",
        keys=keys, start_offset_sec=0.0, expected_positions=[[0, 0, 0]] * 5, tol_pos=0.001)
    assert out["ok"] is True
    assert out["sampled"] == 3
    assert calls == [0.0, 0.2, 0.4]

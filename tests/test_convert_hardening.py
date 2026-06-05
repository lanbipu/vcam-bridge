"""convert.py 加固测试：Codex adversarial review 采纳项 #1(coord 守卫)/#2(aspect)/#3(pose_verified)。"""
from vcam_bridge.config import load_config
from vcam_bridge.cli.commands.convert import convert_live, _SET_TARGET_SCRIPT
from vcam_bridge.designer.transport import FakeTransport


import json


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


_VC_OPTICS = _ok(json.dumps({"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True, "lens_source": 0}))


def test_coord_strip_guarded_by_keycount():
    # Codex#1：coord=Global 是硬要求不能删 strip，但只在多键时 strip 且上报，消除静默丢失
    s = _SET_TARGET_SCRIPT
    assert "nKeys()" in s
    assert "stripToFirstKey" in s
    assert "coord-keys-collapsed" in s


def test_coord_set_to_global_is_1():
    # 实测 1=Global / 0=Relative（coord=1 时 VC.world==注入坐标）；旧代码 setFloat 0.0=Relative 是 bug
    s = _SET_TARGET_SCRIPT
    assert "setFloat(layer.tStart, 1.0)" in s
    assert "setFloat(layer.tStart, 0.0)" not in s


def test_convert_live_reports_aspect_source_live(sample_track_csv):
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_VC_OPTICS,
                           _ok('{"aspect": 1.7777777778}'),
                           _ok('{"ok": true, "vc_found": true, "note": []}'),
                           _ok('{"ok": true, "written": 18}')])
    op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                            config=load_config(None), layer_uid="0xabc", vc_uid="0xdef", chunk_size=100)
    assert data["aspect_source"] == "live"
    assert data["warnings"] == []


def test_convert_live_warns_on_aspect_fallback(sample_track_csv):
    # Codex#2：aspect 读不到时不静默 → aspect_source=config-fallback + warning
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_VC_OPTICS,
                           _ok('{"aspect": null}'),
                           _ok('{"ok": true, "vc_found": true, "note": []}'),
                           _ok('{"ok": true, "written": 18}')])
    op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                            config=load_config(None), layer_uid="0xabc", vc_uid="0xdef", chunk_size=100)
    assert data["aspect_source"] == "config-fallback"
    assert data["warnings"]


def test_solo_verify_marks_pose_unverified(sample_track_csv):
    # Codex#3：solo 下 verify.ok 只证 persistence，明确标 pose_verified=False
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_VC_OPTICS,
                           _ok('{"aspect": 1.7777777778}'),
                           _ok('{"ok": true, "vc_found": true, "note": []}'),
                           _ok('{"ok": true, "written": 18}'),
                           _ok('{"max_errors": {}, "total_keys": 18}')])
    op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                            config=load_config(None), layer_uid="0xabc", vc_uid="0xdef",
                            chunk_size=100, verify=True)
    assert data["verify"]["pose_verified"] is False
    assert data["verify"]["level"] == "persistence-only"

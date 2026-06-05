import json

import vcam_bridge.cli.main as m
from vcam_bridge.designer.codegen import INJECT_BODY, build_inject_script
from vcam_bridge.designer.inject import inject_keys
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


_VC_OPTICS = _ok(json.dumps({"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True}))


def test_inject_body_has_guarded_overwrite_strip():
    assert "stripToFirstKey" in INJECT_BODY
    assert 'payload.get("overwrite")' in INJECT_BODY


def test_build_inject_script_embeds_overwrite_flag():
    base = {"layer_uid": "0x1", "start_offset_sec": 0.0, "fields": {"pivot.x": "camera pivot.x"},
            "keys": [{"t_sec": 0.0, "values": {"pivot.x": 1.0}}]}
    assert '"overwrite": true' in build_inject_script({**base, "overwrite": True})
    assert '"overwrite": false' in build_inject_script({**base, "overwrite": False})


def test_overwrite_strips_only_on_first_chunk():
    # 分块写：strip 只能在第一块跑，否则第二块会清掉第一块刚写的键
    ft = FakeTransport(execute_responses=[_ok('{"ok": true, "written": 2}'),
                                          _ok('{"ok": true, "written": 1}')])
    inject_keys(DesignerClient(ft, "h:80"), layer_uid="0x1", fields={"pivot.x": "camera pivot.x"},
                keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}},
                      {"t_sec": 0.1, "values": {"pivot.x": 2.0}},
                      {"t_sec": 0.2, "values": {"pivot.x": 3.0}}],
                start_offset_sec=0.0, chunk_size=2, overwrite=True)
    assert '"overwrite": true' in ft.executed[0]["script"]
    assert '"overwrite": false' in ft.executed[1]["script"]


def test_overwrite_default_false_keeps_behavior_stable():
    ft = FakeTransport(execute_responses=[_ok('{"ok": true, "written": 1}')])
    inject_keys(DesignerClient(ft, "h:80"), layer_uid="0x1", fields={"pivot.x": "camera pivot.x"},
                keys=[{"t_sec": 0.0, "values": {"pivot.x": 1.0}}], start_offset_sec=0.0, chunk_size=200)
    assert '"overwrite": false' in ft.executed[0]["script"]


def test_dry_run_overwrite_shows_strip_in_preview(sample_track_csv):
    # 预览须如实反映 live：--overwrite 时 inject_script 含 stripToFirstKey 分支（review#2 finding[0]）
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_dry_run
    _, on = convert_dry_run(str(sample_track_csv), config=load_config(None), layer_uid="0x1", overwrite=True)
    _, off = convert_dry_run(str(sample_track_csv), config=load_config(None), layer_uid="0x1")
    assert '"overwrite": true' in on["inject_script"]
    assert '"overwrite": false' in off["inject_script"]


def test_convert_live_reuses_passed_client_no_reroute(sample_track_csv, monkeypatch):
    # name 解析路径传入已路由 client → convert_live 不再二次 resolve_routing（review#2 finding[3]）
    from vcam_bridge.config import load_config
    from vcam_bridge.cli.commands.convert import convert_live
    from vcam_bridge.designer.client import DesignerClient
    ft = FakeTransport(
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
        execute_responses=[_VC_OPTICS,
                           _ok('{"aspect": 1.7777777778}'),
                           _ok('{"ok": true, "vc_found": true, "note": []}'),
                           _ok('{"ok": true, "written": 18}')])
    pre = DesignerClient(ft, "localhost")
    calls = []
    monkeypatch.setattr(DesignerClient, "resolve_routing", lambda self: calls.append(1))
    convert_live(ft, client=pre, host="localhost", fbx=str(sample_track_csv),
                 config=load_config(None), layer_uid="0xabc", vc_uid="0xdef", chunk_size=100)
    assert calls == []


def test_overwrite_flag_threads_to_convert_live(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("vcam_bridge.cli.commands.convert.convert_live",
                        lambda transport, **kw: (captured.update(kw), ("convert", {"written": 0}))[1])
    monkeypatch.setattr("vcam_bridge.designer.client.DesignerClient.resolve_routing", lambda self: None)
    fbx = tmp_path / "t.csv"; fbx.write_text("x")
    args = m.build_parser().parse_args(
        ["convert", "--fbx", str(fbx), "--target-uid", "0x1", "--vc-uid", "0x2",
         "--director", "h:80", "--yes", "--overwrite", "--curl"])
    m._dispatch(args)
    assert captured["overwrite"] is True

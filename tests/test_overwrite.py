import vcam_bridge.cli.main as m
from vcam_bridge.designer.codegen import INJECT_BODY, build_inject_script
from vcam_bridge.designer.inject import inject_keys
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.designer.client import DesignerClient


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


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

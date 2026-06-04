def test_gototime_routes_through_transport():
    # Codex/B：gototime 必须走注入的 transport（macOS 下 requests 被拦，curl 才通），不再硬编码 requests
    from vcam_bridge.designer.transport import FakeTransport
    from vcam_bridge.designer.client import DesignerClient
    from vcam_bridge.designer import inject
    ft = FakeTransport()
    c = DesignerClient(ft, "h:80")
    inject._gototime(c, 2.5)
    # host/path/body 正确，且必须线程 client._timeout_s（否则 requests timeout=None 无限阻塞）
    assert ft.posted_json[-1] == ("h:80", "/api/session/transport/gototime", {"time": 2.5}, c._timeout_s)
    assert c._timeout_s == 30.0


def test_inject_module_has_no_hardcoded_requests():
    import vcam_bridge.designer.inject as inj
    assert not hasattr(inj, "_requests")

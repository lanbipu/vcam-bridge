def test_gototime_routes_through_transport():
    # Codex/B：gototime 必须走注入的 transport（macOS 下 requests 被拦，curl 才通），不再硬编码 requests
    from vcam_bridge.designer.transport import FakeTransport
    from vcam_bridge.designer.client import DesignerClient
    from vcam_bridge.designer import inject
    ft = FakeTransport()
    inject._gototime(DesignerClient(ft, "h:80"), 2.5)
    assert ft.posted_json[-1] == ("h:80", "/api/session/transport/gototime", {"time": 2.5})


def test_inject_module_has_no_hardcoded_requests():
    import vcam_bridge.designer.inject as inj
    assert not hasattr(inj, "_requests")

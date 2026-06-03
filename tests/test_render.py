import json
from vcam_bridge.cli import runtime, render
from vcam_bridge.envelope import success_envelope


def test_resolve_output_precedence():
    assert runtime.resolve_output("json", ai_agent_env=False, is_tty=True) == "json"
    assert runtime.resolve_output(None, ai_agent_env=True, is_tty=False) == "json"
    assert runtime.resolve_output(None, ai_agent_env=False, is_tty=True) == "text"
    assert runtime.resolve_output(None, ai_agent_env=False, is_tty=False) == "text"


def test_request_id_and_timestamp():
    rid = runtime.new_request_id()
    assert len(rid) >= 8
    ts = runtime.utc_now_iso()
    assert ts.endswith("Z")


def test_render_success_json_is_parseable():
    env = success_envelope("convert", {"n": 1}, request_id="r", duration_ms=1,
                           timestamp="2026-06-03T00:00:00Z")
    out = render.render_success(env, "json")
    assert json.loads(out)["data"]["n"] == 1


def test_render_success_text_is_human():
    env = success_envelope("convert", {"n": 1}, request_id="r", duration_ms=1,
                           timestamp="2026-06-03T00:00:00Z")
    out = render.render_success(env, "text")
    assert "convert" in out

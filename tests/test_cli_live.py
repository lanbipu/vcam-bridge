import json
import math
import pytest

from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.cli.commands import targets as targets_cmd


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


def test_targets_list_command_returns_layers():
    ft = FakeTransport(
        execute_responses=[_ok('[["My ACC", "0xabc"]]')],
        json_responses={"/api/session/status/session": {"isRunningSolo": True}},
    )
    op, data = targets_cmd.list_targets(ft, host="localhost")
    assert op == "targets.list"
    assert data["layers"] == [{"name": "My ACC", "uid": "0xabc"}]


def test_convert_live_injects(sample_track_csv):
    """FakeTransport-based test for convert_live; uses sample_track_csv fixture."""
    from math import ceil
    from vcam_bridge.cli.commands.convert import convert_live, build_keyframes
    from vcam_bridge.config import load_config
    from vcam_bridge.ingest.intermediate import load_intermediate

    chunk_size = 1  # 1 key per chunk so we can count precisely

    cfg = load_config(None)
    cal = cfg.calibration

    # How many frames are in the track?
    track = load_intermediate(str(sample_track_csv), euler_order=cal.euler_order)
    n_frames = len(track.frames)
    n_chunks = ceil(n_frames / chunk_size)

    # json_responses: resolve_routing (solo → stay on localhost)
    json_responses = {"/api/session/status/session": {"isRunningSolo": True}}

    # execute_responses:
    #   1 for set-target script
    #   n_chunks for inject chunks (each returns written=chunk_size or remainder)
    def chunk_written(i):
        start = i * chunk_size
        end = min(start + chunk_size, n_frames)
        return end - start

    execute_responses = (
        [_ok('{"ok": true, "note": "ok"}')]  # set-target script
        + [_ok('{"ok": true, "written": %d}' % chunk_written(i)) for i in range(n_chunks)]
    )

    ft = FakeTransport(execute_responses=execute_responses, json_responses=json_responses)

    op, data = convert_live(
        ft,
        host="localhost",
        fbx=str(sample_track_csv),
        config=cfg,
        layer_uid="0xabc",
        vc_uid="0xdef",
        chunk_size=chunk_size,
    )
    assert op == "convert"
    assert data["written"] == n_frames
    assert data["frames"] == n_frames
    assert data["vc_uid"] == "0xdef"
    assert data["layer_uid"] == "0xabc"

    # 1 set-target execute + n_chunks inject executes
    assert len(ft.executed) == 1 + n_chunks

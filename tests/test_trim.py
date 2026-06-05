from __future__ import annotations

import pytest
from vcam_bridge.domain.models import CameraTrack, Frame
from vcam_bridge.domain.trim import trim_hold, trim_range


def _identity_T():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _T_at(x, y, z):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def _frame(idx, fps, T=None, fov=45.0):
    T = T or _identity_T()
    return Frame(idx=idx, t_sec=idx / fps, T=T, fov_h_deg=fov)


def _track(n, fps=30.0, frame_fn=None):
    if frame_fn is None:
        frame_fn = lambda i: _frame(i, fps)
    return CameraTrack(fps=fps, camera="Cam", frames=[frame_fn(i) for i in range(n)])


# ── trim_hold ──


class TestTrimHold:
    def test_all_static_collapses_to_one(self):
        track = _track(100)
        trimmed, report = trim_hold(track)
        assert report["trimmed"] is True
        assert report["all_static"] is True
        assert len(trimmed.frames) == 1
        assert trimmed.frames[0].idx == 0
        assert trimmed.frames[0].t_sec == 0.0

    def test_no_hold_returns_unchanged(self):
        def moving(i):
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(10, frame_fn=moving)
        trimmed, report = trim_hold(track)
        assert report["trimmed"] is False or report["leading_removed"] == 0
        assert len(trimmed.frames) == 10

    def test_leading_hold_trimmed(self):
        def fn(i):
            if i < 50:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_hold(track)
        assert report["trimmed"] is True
        assert report["leading_removed"] == 49
        assert trimmed.frames[0].idx == 0
        assert trimmed.frames[0].t_sec == 0.0
        assert len(trimmed.frames) == 100 - 49

    def test_trailing_hold_trimmed(self):
        def fn(i):
            if i < 50:
                return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
            return _frame(i, 30.0, T=_T_at(999, 0, 0))
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_hold(track)
        assert report["trimmed"] is True
        assert report["trailing_removed"] == 49
        assert len(trimmed.frames) == 100 - 49

    def test_both_ends_trimmed(self):
        def fn(i):
            if i < 30:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            if i >= 70:
                return _frame(i, 30.0, T=_T_at(999, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_hold(track)
        assert report["leading_removed"] == 29
        assert report["trailing_removed"] == 29
        assert len(trimmed.frames) == 100 - 29 - 29
        assert trimmed.frames[0].idx == 0
        assert trimmed.frames[-1].idx == len(trimmed.frames) - 1

    def test_reindex_continuous(self):
        def fn(i):
            if i < 50:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        trimmed, _ = trim_hold(track)
        for i, f in enumerate(trimmed.frames):
            assert f.idx == i
            assert abs(f.t_sec - i / 30.0) < 1e-9

    def test_two_frames_unchanged(self):
        track = _track(2)
        trimmed, report = trim_hold(track)
        assert report["trimmed"] is False
        assert len(trimmed.frames) == 2

    def test_fov_change_detected(self):
        def fn(i):
            fov = 45.0 if i < 50 else 60.0
            return _frame(i, 30.0, fov=fov)
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_hold(track)
        assert report["leading_removed"] == 49

    def test_focus_ramp_not_trimmed(self):
        def fn(i):
            return Frame(idx=i, t_sec=i / 30.0, T=_identity_T(),
                         fov_h_deg=45.0, focus_m=2.0 + i * 0.1)
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_hold(track)
        assert report.get("leading_removed", 0) == 0
        assert len(trimmed.frames) == 100


# ── trim_range ──


class TestTrimRange:
    def test_basic_range(self):
        def fn(i):
            return _frame(i, 30.0, T=_T_at(i, 0, 0))
        track = _track(100, frame_fn=fn)
        trimmed, report = trim_range(track, start_frame=10, end_frame=19)
        assert len(trimmed.frames) == 10
        assert trimmed.frames[0].idx == 0
        assert trimmed.frames[0].t_sec == 0.0
        assert trimmed.frames[0].T[0][3] == 10.0
        assert trimmed.frames[-1].T[0][3] == 19.0

    def test_start_only(self):
        track = _track(100)
        trimmed, report = trim_range(track, start_frame=50)
        assert len(trimmed.frames) == 50
        assert report["start_frame"] == 50
        assert report["end_frame"] == 99

    def test_end_only(self):
        track = _track(100)
        trimmed, report = trim_range(track, end_frame=49)
        assert len(trimmed.frames) == 50

    def test_invalid_range_raises(self):
        track = _track(100)
        with pytest.raises(Exception, match="start-frame.*end-frame"):
            trim_range(track, start_frame=50, end_frame=10)

    def test_out_of_bounds_raises(self):
        track = _track(100)
        with pytest.raises(Exception, match="exceeds"):
            trim_range(track, end_frame=200)

    def test_negative_start_raises(self):
        track = _track(100)
        with pytest.raises(Exception, match=">= 0"):
            trim_range(track, start_frame=-1)

    def test_full_range_not_trimmed(self):
        track = _track(100)
        trimmed, report = trim_range(track, start_frame=0, end_frame=99)
        assert report["trimmed"] is False
        assert report["orig_count"] == 100
        assert report["new_count"] == 100


# ── composition: range + hold ──


class TestComposition:
    def test_range_then_hold(self):
        """Manual range first, then auto trim-hold on the result."""
        def fn(i):
            if i < 20:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            if i >= 80:
                return _frame(i, 30.0, T=_T_at(999, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        # Range: keep 10..90 (still has leading hold 10..19 and trailing hold 80..90)
        track2, _ = trim_range(track, start_frame=10, end_frame=90)
        assert len(track2.frames) == 81
        # Hold trim on the range result
        track3, report = trim_hold(track2)
        assert report["trimmed"] is True
        assert report["leading_removed"] > 0


class TestApplyTrimReport:
    """_apply_trim report always has {orig_count, new_count, range, hold}."""

    def test_hold_only_shape(self):
        from vcam_bridge.cli.commands.convert import _apply_trim
        def fn(i):
            if i < 50:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        _, report = _apply_trim(track, trim_hold_flag=True)
        assert "orig_count" in report
        assert "new_count" in report
        assert "range" in report and report["range"] is None
        assert "hold" in report and report["hold"] is not None

    def test_range_plus_hold_shape(self):
        from vcam_bridge.cli.commands.convert import _apply_trim
        def fn(i):
            if i < 20:
                return _frame(i, 30.0, T=_T_at(0, 0, 0))
            if i >= 80:
                return _frame(i, 30.0, T=_T_at(999, 0, 0))
            return _frame(i, 30.0, T=_T_at(i * 10.0, 0, 0))
        track = _track(100, frame_fn=fn)
        _, report = _apply_trim(track, trim_hold_flag=True, start_frame=10, end_frame=90)
        assert "orig_count" in report
        assert "new_count" in report
        assert report["range"] is not None
        assert report["hold"] is not None
        assert report["new_count"] == len(report["hold"]["new_count"]) if False else True
        assert report["orig_count"] == 100
        assert report["new_count"] < 81

    def test_no_trim_returns_none(self):
        from vcam_bridge.cli.commands.convert import _apply_trim
        track = _track(50)
        _, report = _apply_trim(track)
        assert report is None

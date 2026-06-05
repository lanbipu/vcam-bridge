"""Tests for VC auto-calibration: convert_live auto-reads baseline_focal_mm
and sensor_width_mm from the target VirtualCamera, eliminating manual --config."""
from __future__ import annotations

import json
import math
import pytest
import yaml

from vcam_bridge.domain.models import Config, Calibration
from vcam_bridge.designer.transport import FakeTransport
from vcam_bridge.cli.commands.convert import build_keyframes, convert_live

try:
    from vcam_bridge.cli.commands.convert import _read_vc_optics
except ImportError:
    def _read_vc_optics(client, vc_uid):
        raise NotImplementedError("_read_vc_optics not yet implemented")

try:
    from vcam_bridge.cli.commands.convert import _resolve_calibration
except ImportError:
    def _resolve_calibration(cfg, vc_optics):
        raise NotImplementedError("_resolve_calibration not yet implemented")

try:
    from vcam_bridge.cli.commands.convert import _ensure_lens_source_local
except ImportError:
    def _ensure_lens_source_local(client, vc_uid, vc_optics):
        raise NotImplementedError("_ensure_lens_source_local not yet implemented")


def _ok(rv):
    return {"status": {"code": 0}, "d3Log": "", "pythonLog": "", "returnValue": rv}


# ---------------------------------------------------------------------------
# 1. _read_vc_optics reads focal / zoomScale / sensor from VC
# ---------------------------------------------------------------------------

class TestReadVcOptics:
    def test_returns_optics_for_virtual_camera(self):
        ft = FakeTransport(execute_responses=[
            _ok(json.dumps({
                "focal_mm": 22.96875, "zoom_scale": 1.0,
                "sensor_w_mm": 35.0, "is_virtual": True, "lens_source": 0,
            }))])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        optics = _read_vc_optics(client, "0xd3ebbf1e5336711c")
        assert optics is not None
        assert optics["focal_mm"] == pytest.approx(22.96875)
        assert optics["zoom_scale"] == pytest.approx(1.0)
        assert optics["sensor_w_mm"] == pytest.approx(35.0)
        assert optics["is_virtual"] is True
        assert optics["lens_source"] == 0

    def test_returns_none_on_execute_failure(self):
        ft = FakeTransport(execute_responses=[
            {"status": {"code": 5000, "message": "script error"}, "returnValue": None}])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        assert _read_vc_optics(client, "0xbad") is None

    def test_returns_optics_for_live_camera(self):
        ft = FakeTransport(execute_responses=[
            _ok(json.dumps({
                "focal_mm": 22.7, "zoom_scale": None,
                "sensor_w_mm": 35.0, "is_virtual": False, "lens_source": None,
            }))])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        optics = _read_vc_optics(client, "0xe985481cf36d9ee")
        assert optics is not None
        assert optics["is_virtual"] is False
        assert optics["zoom_scale"] is None
        assert optics["lens_source"] is None


# ---------------------------------------------------------------------------
# 2. baseline derivation: baseline = focal_mm / zoom_scale
# ---------------------------------------------------------------------------

class TestBaselineDerivation:
    def test_zoom_scale_1_baseline_equals_focal(self):
        optics = {"focal_mm": 22.96875, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True}
        baseline = optics["focal_mm"] / optics["zoom_scale"]
        assert baseline == pytest.approx(22.96875)

    def test_zoom_scale_non_1_divides(self):
        optics = {"focal_mm": 45.9375, "zoom_scale": 2.0, "sensor_w_mm": 35.0, "is_virtual": True}
        baseline = optics["focal_mm"] / optics["zoom_scale"]
        assert baseline == pytest.approx(22.96875)


# ---------------------------------------------------------------------------
# 3. build_keyframes accepts baseline_override / sensor_override
# ---------------------------------------------------------------------------

class TestBuildKeyframesOverrides:
    @pytest.fixture()
    def two_frame_track(self, sample_track_csv):
        from vcam_bridge.cli.commands.convert import _load_track
        return _load_track(str(sample_track_csv), euler_order="disguise_zxy")

    def test_baseline_override_changes_zoom(self, two_frame_track):
        cfg = Config()
        _, _, kf_default = build_keyframes(two_frame_track, cfg)
        _, _, kf_custom = build_keyframes(two_frame_track, cfg,
                                          baseline_override=22.96875)
        assert kf_default[0]["zoom"] != pytest.approx(kf_custom[0]["zoom"])

    def test_sensor_override_changes_zoom(self, two_frame_track):
        cfg = Config()
        _, _, kf_default = build_keyframes(two_frame_track, cfg)
        _, _, kf_custom = build_keyframes(two_frame_track, cfg,
                                          sensor_override=24.0)
        assert kf_default[0]["zoom"] != pytest.approx(kf_custom[0]["zoom"])

    def test_both_overrides_applied(self, two_frame_track):
        cfg = Config()
        _, _, kf_custom = build_keyframes(two_frame_track, cfg,
                                          baseline_override=22.96875,
                                          sensor_override=35.0)
        from vcam_bridge.transform.fov import hfov_to_zoom
        expected_zoom = hfov_to_zoom(two_frame_track.frames[0].fov_h_deg,
                                     22.96875, 35.0)
        assert kf_custom[0]["zoom"] == pytest.approx(expected_zoom)


# ---------------------------------------------------------------------------
# 4. Priority: explicit config > VC auto > built-in default
# ---------------------------------------------------------------------------

class TestCalibrationPriority:
    def test_explicit_config_beats_auto(self, sample_track_csv):
        """YAML writes baseline_focal_mm -> model_fields_set has it -> config wins."""
        raw = yaml.safe_load("calibration:\n  baseline_focal_mm: 99.0\n  sensor_width_mm: 24.0")
        cfg = Config.model_validate(raw)
        assert "baseline_focal_mm" in cfg.calibration.model_fields_set
        assert "sensor_width_mm" in cfg.calibration.model_fields_set

        vc_optics = {"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True}
        result = _resolve_calibration(cfg, vc_optics)
        assert result["baseline"] == pytest.approx(99.0)
        assert result["sensor"] == pytest.approx(24.0)
        assert result["baseline_source"] == "config"
        assert result["sensor_source"] == "config"

    def test_vc_auto_beats_default(self, sample_track_csv):
        """No explicit config -> VC auto-read wins over built-in defaults."""
        cfg = Config()
        vc_optics = {"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True}
        result = _resolve_calibration(cfg, vc_optics)
        assert result["baseline"] == pytest.approx(22.97)
        assert result["sensor"] == pytest.approx(35.0)
        assert result["baseline_source"] == "vc-auto"
        assert result["sensor_source"] == "vc-auto"

    def test_default_when_no_optics(self, sample_track_csv):
        """No config, no VC optics -> built-in defaults."""
        cfg = Config()
        result = _resolve_calibration(cfg, None)
        assert result["baseline"] == pytest.approx(cfg.calibration.baseline_focal_mm)
        assert result["sensor"] == pytest.approx(cfg.calibration.sensor_width_mm)
        assert result["baseline_source"] == "default"
        assert result["sensor_source"] == "default"

    def test_live_camera_uses_default(self, sample_track_csv):
        """Live camera (no zoomScale) -> don't auto-calibrate baseline."""
        cfg = Config()
        vc_optics = {"focal_mm": 22.7, "zoom_scale": None, "sensor_w_mm": 35.0, "is_virtual": False}
        result = _resolve_calibration(cfg, vc_optics)
        assert result["baseline"] == pytest.approx(cfg.calibration.baseline_focal_mm)
        assert result["baseline_source"] == "default"

    def test_vc_optics_read_failed_falls_back(self, sample_track_csv):
        """VC optics returned None (execute failed) -> fall back to config/default."""
        cfg = Config()
        result = _resolve_calibration(cfg, None)
        assert result["baseline_source"] == "default"

    def test_mixed_config_only_sensor_explicit(self, sample_track_csv):
        """P2 fix: config only sets sensor_width_mm, not baseline -> baseline_source=vc-auto."""
        raw = yaml.safe_load("calibration:\n  sensor_width_mm: 24.0")
        cfg = Config.model_validate(raw)
        vc_optics = {"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 35.0, "is_virtual": True}
        result = _resolve_calibration(cfg, vc_optics)
        assert result["baseline"] == pytest.approx(22.97)
        assert result["baseline_source"] == "vc-auto"
        assert result["sensor"] == pytest.approx(24.0)
        assert result["sensor_source"] == "config"

    def test_mixed_config_only_baseline_explicit(self, sample_track_csv):
        """Config only sets baseline, not sensor -> sensor_source=vc-auto."""
        raw = yaml.safe_load("calibration:\n  baseline_focal_mm: 99.0")
        cfg = Config.model_validate(raw)
        vc_optics = {"focal_mm": 22.97, "zoom_scale": 1.0, "sensor_w_mm": 32.0, "is_virtual": True}
        result = _resolve_calibration(cfg, vc_optics)
        assert result["baseline"] == pytest.approx(99.0)
        assert result["baseline_source"] == "config"
        assert result["sensor"] == pytest.approx(32.0)
        assert result["sensor_source"] == "vc-auto"


# ---------------------------------------------------------------------------
# 5. _ensure_lens_source_local: force VC lens source to Local
# ---------------------------------------------------------------------------

class TestEnsureLensSourceLocal:
    def test_already_local_returns_none(self):
        optics = {"is_virtual": True, "lens_source": 0}
        assert _ensure_lens_source_local(None, "0xabc", optics) is None

    def test_none_optics_returns_none(self):
        assert _ensure_lens_source_local(None, "0xabc", None) is None

    def test_live_camera_returns_none(self):
        optics = {"is_virtual": False, "lens_source": None}
        assert _ensure_lens_source_local(None, "0xabc", optics) is None

    def test_follow_parent_zoom_triggers_change(self):
        ft = FakeTransport(execute_responses=[_ok('{"ok": true}')])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        optics = {"is_virtual": True, "lens_source": 1}
        result = _ensure_lens_source_local(client, "0xabc", optics)
        assert result is not None
        assert result["changed"] is True
        assert result["from"] == 1
        assert result["from_name"] == "Zoom from parent"
        assert result["to"] == 0

    def test_follow_all_intrinsics_triggers_change(self):
        ft = FakeTransport(execute_responses=[_ok('{"ok": true}')])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        optics = {"is_virtual": True, "lens_source": 2}
        result = _ensure_lens_source_local(client, "0xabc", optics)
        assert result is not None
        assert result["changed"] is True
        assert result["from"] == 2
        assert result["from_name"] == "Intrinsics from parent"

    def test_set_fails_reports_error(self):
        ft = FakeTransport(execute_responses=[
            _ok('{"ok": false, "error": "permission denied"}')])
        from vcam_bridge.designer.client import DesignerClient
        client = DesignerClient(ft, "localhost")
        optics = {"is_virtual": True, "lens_source": 1}
        result = _ensure_lens_source_local(client, "0xabc", optics)
        assert result is not None
        assert result["changed"] is False
        assert "permission denied" in result["error"]


# ---------------------------------------------------------------------------
# 6. convert_live integration: auto-calibration end-to-end
# ---------------------------------------------------------------------------

class TestConvertLiveAutoCal:
    def test_convert_live_outputs_calibration_block(self, sample_track_csv):
        ft = FakeTransport(
            json_responses={"/api/session/status/session": {"isRunningSolo": True}},
            execute_responses=[
                # _read_vc_optics (lens_source=0 -> already Local, no set call)
                _ok(json.dumps({"focal_mm": 22.96875, "zoom_scale": 1.0,
                                "sensor_w_mm": 35.0, "is_virtual": True, "lens_source": 0})),
                # _read_camera_aspect
                _ok('{"aspect": 1.7777777778}'),
                # _SET_TARGET_SCRIPT
                _ok('{"ok": true, "note": []}'),
                # inject chunk
                _ok('{"ok": true, "written": 18}'),
            ],
        )
        from vcam_bridge.config import load_config
        op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                                config=load_config(None), layer_uid="0xabc",
                                vc_uid="0xdef", chunk_size=100)
        assert "calibration" in data
        cal = data["calibration"]
        assert cal["baseline_focal_mm"] == pytest.approx(22.96875)
        assert cal["baseline_source"] == "vc-auto"
        assert cal["sensor_source"] == "vc-auto"
        assert cal["vc_optics"]["focal_mm"] == pytest.approx(22.96875)
        assert cal["lens_source_change"] is None

    def test_convert_live_warns_on_optics_failure(self, sample_track_csv):
        ft = FakeTransport(
            json_responses={"/api/session/status/session": {"isRunningSolo": True}},
            execute_responses=[
                # _read_vc_optics fails
                {"status": {"code": 5000, "message": "err"}, "returnValue": None},
                # _read_camera_aspect
                _ok('{"aspect": 1.7777777778}'),
                # _SET_TARGET_SCRIPT
                _ok('{"ok": true, "note": []}'),
                # inject chunk
                _ok('{"ok": true, "written": 18}'),
            ],
        )
        from vcam_bridge.config import load_config
        op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                                config=load_config(None), layer_uid="0xabc",
                                vc_uid="0xdef", chunk_size=100)
        assert data["calibration"]["baseline_source"] == "default"
        assert any("baseline" in w.lower() or "optics" in w.lower()
                    for w in data["warnings"])

    def test_convert_live_changes_lens_source_to_local(self, sample_track_csv):
        ft = FakeTransport(
            json_responses={"/api/session/status/session": {"isRunningSolo": True}},
            execute_responses=[
                # _read_vc_optics (lens_source=1 -> Zoom from parent)
                _ok(json.dumps({"focal_mm": 22.96875, "zoom_scale": 1.0,
                                "sensor_w_mm": 35.0, "is_virtual": True, "lens_source": 1})),
                # _ensure_lens_source_local -> _SET_LENS_SOURCE_SCRIPT
                _ok('{"ok": true}'),
                # _read_camera_aspect
                _ok('{"aspect": 1.7777777778}'),
                # _SET_TARGET_SCRIPT
                _ok('{"ok": true, "note": []}'),
                # inject chunk
                _ok('{"ok": true, "written": 18}'),
            ],
        )
        from vcam_bridge.config import load_config
        op, data = convert_live(ft, host="localhost", fbx=str(sample_track_csv),
                                config=load_config(None), layer_uid="0xabc",
                                vc_uid="0xdef", chunk_size=100)
        change = data["calibration"]["lens_source_change"]
        assert change is not None
        assert change["changed"] is True
        assert change["from"] == 1
        assert change["to"] == 0
        assert any("lens source" in w.lower() for w in data["warnings"])


# ---------------------------------------------------------------------------
# 7. P2 fix: dry-run notes that zoom will be auto-calibrated live
# ---------------------------------------------------------------------------

class TestDryRunAutocalNote:
    def test_dryrun_notes_zoom_uses_defaults(self, sample_track_csv):
        from vcam_bridge.cli.commands.convert import convert_dry_run
        from vcam_bridge.config import load_config
        op, data = convert_dry_run(str(sample_track_csv), config=load_config(None),
                                   layer_uid="0xabc")
        plan = data["dry_run_plan"]
        assert plan["baseline_source"] == "config-default"
        assert "auto-calibrat" in plan["note"].lower()



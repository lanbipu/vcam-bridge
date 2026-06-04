import json
import numpy as np
import pytest
from vcam_bridge.ingest.intermediate import load_intermediate
from vcam_bridge.domain.errors import InvalidFbxError


def test_load_json(sample_track_json):
    tr = load_intermediate(str(sample_track_json), euler_order="XYZ")
    assert tr.fps == 30.0
    assert tr.camera == "Cam"
    assert len(tr.frames) == 2
    assert tr.frames[1].fov_h_deg == 62.0
    T = np.array(tr.frames[1].T)
    assert np.allclose(T[:3, 3], [100, 0, 0])   # translation preserved


def test_load_csv(sample_track_csv):
    tr = load_intermediate(str(sample_track_csv), euler_order="XYZ")
    assert len(tr.frames) == 2
    assert tr.frames[0].focus_m == 2.0


def test_missing_file_raises(tmp_path):
    with pytest.raises(InvalidFbxError):
        load_intermediate(str(tmp_path / "nope.json"), euler_order="XYZ")


def test_no_frames_raises(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text('{"fps": 30, "camera": "c", "frames": []}', encoding="utf-8")
    with pytest.raises(InvalidFbxError):
        load_intermediate(str(p), euler_order="XYZ")


def test_load_json_with_4x4_T(tmp_path):
    T = [[1, 0, 0, 5], [0, 1, 0, 10], [0, 0, 1, 15], [0, 0, 0, 1]]
    data = {"fps": 24.0, "camera": "Cam", "frames": [
        {"idx": 0, "t_sec": 0.0, "T": T, "fov_h_deg": 70.0, "focus_m": 1.0}]}
    p = tmp_path / "t4x4.json"
    p.write_text(json.dumps(data))
    tr = load_intermediate(str(p), euler_order="XYZ")
    assert tr.frames[0].T == T
    assert tr.frames[0].fov_h_deg == 70.0


def test_csv_fps_inferred_from_timestamps(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
                 "0,0.0,0,0,0,0,0,0,60,1\n"
                 "1,0.04,0,0,0,0,0,0,60,1\n")
    tr = load_intermediate(str(p), euler_order="XYZ")
    assert abs(tr.fps - 25.0) < 0.1


def test_csv_single_frame_defaults_30fps(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
                 "0,0.0,0,0,0,0,0,0,60,1\n")
    tr = load_intermediate(str(p), euler_order="XYZ")
    assert tr.fps == 30.0


def test_malformed_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json!!!")
    with pytest.raises(InvalidFbxError, match="failed to parse"):
        load_intermediate(str(p), euler_order="XYZ")


def test_json_missing_required_key(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"fps": 30, "camera": "c", "frames": [{"idx": 0}]}')
    with pytest.raises(InvalidFbxError):
        load_intermediate(str(p), euler_order="XYZ")


def test_focus_m_empty_string_becomes_none(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
                 "0,0.0,0,0,0,0,0,0,60,\n"
                 "1,0.033,0,0,0,0,0,0,60,\n")
    tr = load_intermediate(str(p), euler_order="XYZ")
    assert tr.frames[0].focus_m is None

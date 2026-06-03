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

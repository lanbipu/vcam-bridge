import json
import pytest


@pytest.fixture
def sample_track_json(tmp_path):
    data = {
        "fps": 30.0,
        "camera": "Cam",
        "frames": [
            {"idx": 0, "t_sec": 0.0, "position": [0, 0, 0],
             "rotation_deg": [0, 0, 0], "fov_h_deg": 60.0, "focus_m": 2.0},
            {"idx": 1, "t_sec": 0.0333, "position": [100, 0, 0],
             "rotation_deg": [0, 10, 0], "fov_h_deg": 62.0, "focus_m": 2.5},
        ],
    }
    p = tmp_path / "track.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def sample_track_csv(tmp_path):
    p = tmp_path / "track.csv"
    p.write_text(
        "idx,t_sec,x,y,z,rx,ry,rz,fov_h_deg,focus_m\n"
        "0,0.0,0,0,0,0,0,0,60.0,2.0\n"
        "1,0.0333,100,0,0,0,10,0,62.0,2.5\n",
        encoding="utf-8",
    )
    return p

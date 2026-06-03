import pytest
from pydantic import ValidationError
from vcam_bridge.domain.models import Frame, CameraTrack, StagePose, ACCKeyframe

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def test_frame_and_track():
    f = Frame(idx=0, t_sec=0.0, T=IDENTITY, fov_h_deg=60.0, focus_m=2.0)
    tr = CameraTrack(fps=30.0, camera="Cam", frames=[f])
    assert tr.schema_ == "vcam.track/1"
    assert tr.frames[0].fov_h_deg == 60.0


def test_T_must_be_4x4():
    with pytest.raises(ValidationError):
        Frame(idx=0, t_sec=0.0, T=[[1, 0], [0, 1]], fov_h_deg=60.0)


def test_stage_pose_and_keyframe():
    p = StagePose(pivot=(1, 2, 3), rotation=(10, 20, 30), distance=1.5, fov_deg=60)
    k = ACCKeyframe(idx=0, t_sec=0.0, pose=p)
    assert k.pose.distance == 1.5
    assert k.pose.rotation == (10, 20, 30)

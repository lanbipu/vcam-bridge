from __future__ import annotations

from vcam_bridge.domain.models import CameraTrack, Frame

# Static-hold detection thresholds (raw Blender-extracted coordinates)
_POS_TOL = 0.5      # cm — position in UE centimeters
_ROT_TOL = 1e-4     # direction cosine element
_FOV_TOL = 0.01     # degrees
_FOCUS_TOL = 0.01   # metres


def _frames_equal(a: Frame, b: Frame) -> bool:
    for r in range(3):
        if abs(a.T[r][3] - b.T[r][3]) > _POS_TOL:
            return False
        for c in range(3):
            if abs(a.T[r][c] - b.T[r][c]) > _ROT_TOL:
                return False
    if abs(a.fov_h_deg - b.fov_h_deg) > _FOV_TOL:
        return False
    a_focus = a.focus_m if a.focus_m is not None else 0.0
    b_focus = b.focus_m if b.focus_m is not None else 0.0
    if abs(a_focus - b_focus) > _FOCUS_TOL:
        return False
    return True


def _reindex(frames: list[Frame], fps: float) -> list[Frame]:
    return [f.model_copy(update={"idx": i, "t_sec": i / fps})
            for i, f in enumerate(frames)]


def trim_hold(track: CameraTrack) -> tuple[CameraTrack, dict]:
    """Remove leading/trailing static hold frames, keeping one anchor at each boundary."""
    frames = track.frames
    if len(frames) <= 2:
        return track, {"trimmed": False, "reason": "too_few_frames"}

    first_diff = len(frames)
    for i in range(1, len(frames)):
        if not _frames_equal(frames[0], frames[i]):
            first_diff = i
            break

    if first_diff == len(frames):
        new_frames = _reindex(frames[:1], track.fps)
        return (
            CameraTrack(fps=track.fps, camera=track.camera, frames=new_frames),
            {"trimmed": True, "orig_count": len(frames), "new_count": 1,
             "leading_removed": len(frames) - 1, "trailing_removed": 0,
             "all_static": True},
        )

    last_diff = 0
    for i in range(len(frames) - 2, -1, -1):
        if not _frames_equal(frames[-1], frames[i]):
            last_diff = i
            break

    start = max(0, first_diff - 1)
    end = min(len(frames) - 1, last_diff + 1)

    sliced = frames[start:end + 1]
    new_frames = _reindex(sliced, track.fps)
    leading = start
    trailing = len(frames) - 1 - end
    return (
        CameraTrack(fps=track.fps, camera=track.camera, frames=new_frames),
        {"trimmed": leading > 0 or trailing > 0,
         "orig_count": len(frames), "new_count": len(new_frames),
         "leading_removed": leading, "trailing_removed": trailing,
         "leading_hold_sec": round(leading / track.fps, 3),
         "trailing_hold_sec": round(trailing / track.fps, 3)},
    )


def decimate(track: CameraTrack, factor: int) -> tuple[CameraTrack, dict]:
    """Keep every Nth frame, always preserving first and last.

    Unlike trim/range, the original t_sec values are preserved so that
    keyframes land at their correct time positions on the Designer timeline;
    Designer interpolates between the surviving keyframes.
    """
    from vcam_bridge.domain.errors import ConfigError
    if factor < 1:
        raise ConfigError("--decimate must be >= 1", details={"value": factor})
    frames = track.frames
    if factor <= 1 or len(frames) <= 2:
        return track, {"decimated": False, "factor": factor}

    selected = list(range(0, len(frames), factor))
    if selected[-1] != len(frames) - 1:
        selected.append(len(frames) - 1)

    new_frames = [frames[i].model_copy(update={"idx": j})
                  for j, i in enumerate(selected)]
    return (
        CameraTrack(fps=track.fps, camera=track.camera, frames=new_frames),
        {"decimated": True, "factor": factor,
         "orig_count": len(frames), "new_count": len(new_frames)},
    )


def trim_range(track: CameraTrack, *, start_frame: int | None = None,
               end_frame: int | None = None) -> tuple[CameraTrack, dict]:
    """Keep only frames in [start_frame, end_frame] (inclusive), re-index from 0."""
    from vcam_bridge.domain.errors import ConfigError

    frames = track.frames
    s = start_frame if start_frame is not None else 0
    e = end_frame if end_frame is not None else len(frames) - 1

    if s < 0:
        raise ConfigError("--start-frame must be >= 0", details={"value": s})
    if e >= len(frames):
        raise ConfigError("--end-frame %d exceeds track length %d" % (e, len(frames)),
                          details={"value": e, "max": len(frames) - 1})
    if s > e:
        raise ConfigError("--start-frame %d > --end-frame %d" % (s, e),
                          details={"start": s, "end": e})

    sliced = frames[s:e + 1]
    new_frames = _reindex(sliced, track.fps)
    actually_trimmed = s > 0 or e < len(frames) - 1
    return (
        CameraTrack(fps=track.fps, camera=track.camera, frames=new_frames),
        {"trimmed": actually_trimmed, "orig_count": len(frames), "new_count": len(new_frames),
         "start_frame": s, "end_frame": e},
    )

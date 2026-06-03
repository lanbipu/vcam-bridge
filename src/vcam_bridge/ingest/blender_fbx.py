from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from vcam_bridge import __version__
from vcam_bridge.domain.errors import ExternalError, InvalidFbxError
from vcam_bridge.domain.models import CameraTrack

_SCRIPT = Path(__file__).with_name("blender_extract.py")
_LOG_CAP = 64 * 1024


def _candidate_paths(blender_path: str | None) -> list[str]:
    out = []
    if blender_path:
        out.append(blender_path)
    if os.environ.get("BLENDER"):
        out.append(os.environ["BLENDER"])
    if sys.platform == "darwin":
        out.append("/Applications/Blender.app/Contents/MacOS/Blender")
    which = shutil.which("blender")
    if which:
        out.append(which)
    return out


def find_blender(blender_path: str | None = None) -> str:
    for p in _candidate_paths(blender_path):
        if p and Path(p).exists():
            return p
    raise ExternalError("Blender not found; set --blender-path or $BLENDER, or install Blender",
                        details={"searched": _candidate_paths(blender_path)})


def blender_version(blender: str) -> str:
    try:
        out = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip().splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_dir(cache_dir: str | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "vcam_bridge" / "fbx"


def _cache_key(fbx_path: str, *, camera: str | None, blender_ver: str) -> dict:
    return {"fbx_sha": _sha(Path(fbx_path).read_bytes()), "script_sha": _sha(_SCRIPT.read_bytes()),
            "version": __version__, "blender_version": blender_ver, "camera": camera or ""}


def _run_blender(blender, script, inp, out, camera, timeout):
    cmd = [blender, "--background", "--factory-startup", "--python", script, "--", "--in", inp, "--out", out]
    if camera:
        cmd += ["--camera", camera]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        so, se = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            proc.kill()
        proc.communicate()
        raise ExternalError("Blender FBX conversion exceeded %ss" % timeout, details={"timeout": True})
    return proc.returncode, (so or "")[-_LOG_CAP:], (se or "")[-_LOG_CAP:]


def extract_fbx(fbx_path: str, *, camera: str | None = None, blender_path: str | None = None,
                cache_dir: str | None = None, timeout_s: float = 120.0, use_cache: bool = True) -> CameraTrack:
    fbx_path = str(Path(fbx_path).resolve())
    if not Path(fbx_path).exists():
        raise InvalidFbxError("FBX not found: %s" % fbx_path, details={"path": fbx_path})
    blender = find_blender(blender_path)
    key = _cache_key(fbx_path, camera=camera, blender_ver=blender_version(blender))
    digest = _sha(json.dumps(key, sort_keys=True).encode())
    cdir = _cache_dir(cache_dir)
    out_json = cdir / ("%s.track.json" % digest)
    if not (use_cache and out_json.exists()):
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = out_json.with_suffix(".tmp")
        rc, so, se = _run_blender(blender, str(_SCRIPT), fbx_path, str(tmp), camera or "", timeout_s)
        if rc != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise InvalidFbxError("Blender FBX extraction failed (rc=%s)" % rc,
                                  details={"stderr": se[-2000:], "stdout": so[-500:]})
        os.replace(tmp, out_json)
    data = json.loads(out_json.read_text(encoding="utf-8"))
    if not data.get("frames"):
        raise InvalidFbxError("FBX produced no frames", details={"path": fbx_path})
    return CameraTrack.model_validate(data)

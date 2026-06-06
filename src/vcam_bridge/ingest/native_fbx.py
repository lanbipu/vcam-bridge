"""Blender-free FBX reader: spawns a short-lived ufbx worker subprocess and returns a
CameraTrack identical in schema to blender_fbx.extract_fbx.

Mirrors blender_fbx.py's cache/atomic-write/timeout scaffolding so the two readers behave
the same to callers; only the extraction backend differs.  Kept as a separate module so the
existing Blender path stays untouched during the trial period.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from vcam_bridge import __version__
from vcam_bridge.domain.errors import ExternalError, InvalidFbxError
from vcam_bridge.domain.models import CameraTrack

_WORKER = "vcam_bridge.ingest.native_extract"
_SCRIPT = Path(__file__).with_name("native_extract.py")
_LOG_CAP = 64 * 1024


def _ufbx_version() -> str:
    """Read ufbx's version from dist metadata WITHOUT importing the C extension (whose
    teardown segfaults).  Doubles as an availability check (ufbx is a core dependency, so this
    should only fire on a broken/partial install)."""
    try:
        return metadata.version("ufbx")
    except metadata.PackageNotFoundError as exc:
        raise ExternalError(
            "native FBX reader requires ufbx (a core dependency); reinstall the package: "
            "pip install -e . (or use --reader blender)",
            details={"missing": "ufbx"}) from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cache_dir(cache_dir: str | None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "vcam_bridge" / "fbx"


def _cache_key(fbx_path: str, *, camera: str | None, ufbx_ver: str) -> dict:
    return {"fbx_sha": _sha(Path(fbx_path).read_bytes()), "script_sha": _sha(_SCRIPT.read_bytes()),
            "version": __version__, "ufbx_version": ufbx_ver, "camera": camera or "",
            "reader": "native"}   # 'reader' key keeps native/blender cache entries distinct


def _run_worker(inp, out, camera, timeout):
    cmd = [sys.executable, "-m", _WORKER, "--in", inp, "--out", out]
    if camera:
        cmd += ["--camera", camera]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        so, se = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        proc.communicate()
        raise ExternalError("native FBX extraction exceeded %ss" % timeout, details={"timeout": True})
    return proc.returncode, (so or "")[-_LOG_CAP:], (se or "")[-_LOG_CAP:]


def extract_fbx_native(fbx_path: str, *, camera: str | None = None,
                       cache_dir: str | None = None, timeout_s: float = 120.0,
                       use_cache: bool = True) -> CameraTrack:
    fbx_path = str(Path(fbx_path).resolve())
    if not Path(fbx_path).exists():
        raise InvalidFbxError("FBX not found: %s" % fbx_path, details={"path": fbx_path})
    ufbx_ver = _ufbx_version()
    key = _cache_key(fbx_path, camera=camera, ufbx_ver=ufbx_ver)
    digest = _sha(json.dumps(key, sort_keys=True).encode())
    cdir = _cache_dir(cache_dir)
    out_json = cdir / ("%s.track.json" % digest)
    if not (use_cache and out_json.exists()):
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = out_json.with_suffix(".tmp")
        rc, so, se = _run_worker(fbx_path, str(tmp), camera or "", timeout_s)
        if rc != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise InvalidFbxError("native FBX extraction failed (rc=%s)" % rc,
                                  details={"stderr": se[-2000:], "stdout": so[-500:]})
        os.replace(tmp, out_json)
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise InvalidFbxError("corrupt native cache file: %s" % out_json,
                              details={"cache": str(out_json), "error": str(exc)}) from exc
    if not data.get("frames"):
        raise InvalidFbxError("FBX produced no frames", details={"path": fbx_path})
    return CameraTrack.model_validate(data)

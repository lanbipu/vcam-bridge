import pytest
from vcam_bridge.ingest.blender_fbx import find_blender, _cache_key
from vcam_bridge.domain.errors import ExternalError


def test_find_blender_uses_env(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("BLENDER", str(fake))
    assert find_blender(blender_path=None) == str(fake)


def test_find_blender_raises_when_missing(monkeypatch):
    monkeypatch.delenv("BLENDER", raising=False)
    monkeypatch.setattr("shutil.which", lambda _x: None)
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(ExternalError):
        find_blender(blender_path="/nonexistent/blender")


def test_cache_key_changes_with_camera(tmp_path):
    fbx = tmp_path / "a.fbx"; fbx.write_bytes(b"fbxbytes")
    k1 = _cache_key(str(fbx), camera="Cam", blender_ver="4.0")
    k2 = _cache_key(str(fbx), camera="Other", blender_ver="4.0")
    assert k1 != k2   # camera participates in the key

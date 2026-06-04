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


def test_cache_key_changes_with_blender_version(tmp_path):
    fbx = tmp_path / "a.fbx"; fbx.write_bytes(b"fbxbytes")
    k1 = _cache_key(str(fbx), camera="Cam", blender_ver="4.0")
    k2 = _cache_key(str(fbx), camera="Cam", blender_ver="4.1")
    assert k1 != k2


def test_cache_key_no_camera_uses_empty(tmp_path):
    fbx = tmp_path / "a.fbx"; fbx.write_bytes(b"fbxbytes")
    k1 = _cache_key(str(fbx), camera=None, blender_ver="4.0")
    assert k1["camera"] == ""


def test_find_blender_explicit_path(tmp_path):
    fake = tmp_path / "myblender"
    fake.write_text("#!/bin/sh\n")
    assert find_blender(blender_path=str(fake)) == str(fake)


def test_extract_fbx_file_not_found(tmp_path):
    from vcam_bridge.ingest.blender_fbx import extract_fbx
    from vcam_bridge.domain.errors import InvalidFbxError
    with pytest.raises(InvalidFbxError, match="not found"):
        extract_fbx(str(tmp_path / "nope.fbx"))

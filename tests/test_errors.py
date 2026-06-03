import pytest
from vcam_bridge.domain.errors import (
    VcamError, ConfigError, InvalidFbxError, ConventionLockError, VerifyToleranceError,
)


def test_base_defaults():
    e = VcamError("boom")
    assert e.code == "INTERNAL"
    assert e.exit_code == 1
    assert e.message == "boom"
    assert e.details == {}


def test_subclass_codes():
    assert ConfigError("x").exit_code == 3
    assert InvalidFbxError("x").exit_code == 13
    assert ConventionLockError("x").exit_code == 12
    assert VerifyToleranceError("x").exit_code == 11


def test_details_carried():
    e = InvalidFbxError("bad", details={"path": "a.fbx"})
    assert e.details["path"] == "a.fbx"


def test_is_exception():
    with pytest.raises(VcamError):
        raise ConfigError("nope")

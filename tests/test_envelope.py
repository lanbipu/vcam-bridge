from vcam_bridge.envelope import (
    SCHEMA_VERSION, CONTRACT_VERSION, EXIT_OK, EXIT_USAGE,
    success_envelope, error_envelope,
)


def test_success_envelope_shape():
    env = success_envelope("convert", {"frames": 3},
                           request_id="r1", duration_ms=5, timestamp="2026-06-03T00:00:00Z")
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["status"] == "ok"
    assert env["operation_id"] == "convert"
    assert env["data"] == {"frames": 3}
    assert env["meta"]["request_id"] == "r1"


def test_error_envelope_shape():
    env = error_envelope("convert", code="INVALID_FBX", exit_code=13,
                         message="bad", retryable=False, details={"path": "x"},
                         request_id="r1", duration_ms=1, timestamp="2026-06-03T00:00:00Z")
    assert env["status"] == "error"
    assert env["error"]["code"] == "INVALID_FBX"
    assert env["error"]["exit_code"] == 13
    assert env["error"]["retryable"] is False


def test_exit_codes_present():
    assert EXIT_OK == 0
    assert EXIT_USAGE == 2

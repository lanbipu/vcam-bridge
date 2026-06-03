from __future__ import annotations

from typing import Any


class VcamError(Exception):
    code: str = "INTERNAL"
    exit_code: int = 1
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details if details is not None else {}


class ConfigError(VcamError):
    code = "CONFIG_ERROR"; exit_code = 3; retryable = False


class AuthError(VcamError):
    code = "AUTH_ERROR"; exit_code = 4; retryable = False


class NotFoundError(VcamError):
    code = "NOT_FOUND"; exit_code = 5; retryable = False


class ConflictError(VcamError):
    code = "CONFLICT"; exit_code = 6; retryable = False


class DesignerTimeoutError(VcamError):
    code = "TIMEOUT"; exit_code = 7; retryable = True


class ExternalError(VcamError):
    code = "EXTERNAL_DEPENDENCY"; exit_code = 8; retryable = True


class PartialError(VcamError):
    code = "PARTIAL_FAILURE"; exit_code = 9; retryable = True


class ProbeFailedError(VcamError):
    code = "PROBE_FAILED"; exit_code = 10; retryable = False


class VerifyToleranceError(VcamError):
    code = "VERIFY_TOLERANCE_EXCEEDED"; exit_code = 11; retryable = False


class ConventionLockError(VcamError):
    code = "CONVENTION_LOCK_FAILED"; exit_code = 12; retryable = False


class InvalidFbxError(VcamError):
    code = "INVALID_FBX"; exit_code = 13; retryable = False

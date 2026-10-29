"""Domain errors. The API layer maps them to HTTP status codes; MCP maps them to tool errors."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class VersionConflict(Conflict):
    code = "version_conflict"


class InvalidTransition(Conflict):
    code = "invalid_transition"


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"

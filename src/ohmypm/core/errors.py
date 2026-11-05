"""Error types shared by every interface (CLI, MCP, HTTP).

Each error carries a stable machine-readable ``code``; interfaces map it to an
exit code, an MCP error payload or an HTTP status respectively.
"""

from __future__ import annotations

from typing import Any


class OhmypmError(Exception):
    code = "error"
    exit_code = 1
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ProjectNotRegisteredError(OhmypmError):
    """No registered project contains the given path."""

    code = "project_not_registered"
    exit_code = 3
    http_status = 404


class NotFoundError(OhmypmError):
    code = "not_found"
    exit_code = 4
    http_status = 404


class ValidationError(OhmypmError):
    code = "validation_error"
    exit_code = 5
    http_status = 422


class ConflictError(OhmypmError):
    code = "conflict"
    exit_code = 6
    http_status = 409


class AmbiguousReferenceError(ValidationError):
    code = "ambiguous_reference"

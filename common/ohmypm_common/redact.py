"""Best-effort secret redaction for logs and event payloads.

Applied by the runner before events leave the host, and by the backend before persisting
runner-supplied text. It is a safety net, not a guarantee: agents should not print secrets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    # Provider API keys
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    # ohmypm tokens
    re.compile(r"\bomr_[A-Za-z0-9_\-]{16,}"),
    # Authorization headers
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{16,}"),
    # key=value / "key": "value" secrets
    re.compile(
        r"(?i)((?:api[_-]?key|secret|password|passwd|token|access[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
        r"[^\s\"',;]{6,}"
    ),
    # Private key blocks
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


class Redactor:
    def __init__(self, extra_secrets: Iterable[str] = ()) -> None:
        self._literals = sorted({s for s in extra_secrets if s and len(s) >= 8}, key=len, reverse=True)

    def text(self, value: str) -> str:
        for literal in self._literals:
            value = value.replace(literal, REDACTED)
        for pattern in _PATTERNS:
            if pattern.groups:
                value = pattern.sub(lambda m: m.group(1) + REDACTED, value)
            else:
                value = pattern.sub(REDACTED, value)
        return value

    def value(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {k: self.value(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        return obj


_default = Redactor()


def redact(value: Any) -> Any:
    return _default.value(value)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + f"… [truncated {len(text) - limit + 20} chars]"

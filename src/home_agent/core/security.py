from __future__ import annotations

"""Secret redaction and bounded text helpers."""

import re
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"(?i)(PVEAPIToken=[^=\s]+)=([^\s\"']+)"),
    re.compile(r"(?i)\b(token[_ -]?secret|password|passwd|authorization|api[_ -]?key)\b(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]+)"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
)


def redact_secrets(value: Any) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = SECRET_PATTERNS[0].sub(r"\1=[REDACTED]", text)
    text = SECRET_PATTERNS[1].sub(r"\1\2[REDACTED]", text)
    text = SECRET_PATTERNS[2].sub(r"\1 [REDACTED]", text)
    return SECRET_PATTERNS[3].sub("[REDACTED PRIVATE KEY]", text)


def bounded_redacted(value: Any, limit: int) -> str:
    text = redact_secrets(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated {len(text) - limit} characters]"

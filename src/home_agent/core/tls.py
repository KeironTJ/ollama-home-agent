from __future__ import annotations

import ssl
from pathlib import Path


def verified_ssl_context(
    ca_file: Path | None,
    insecure: bool,
) -> bool | ssl.SSLContext:
    if insecure:
        return False
    if ca_file:
        context = ssl.create_default_context(cafile=str(ca_file))
        strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict:
            context.verify_flags &= ~strict
        return context
    return True

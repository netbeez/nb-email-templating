"""Container healthcheck: HTTP or HTTPS to localhost depending on TLS file paths."""
from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request

PORT = os.environ.get("UVICORN_PORT", "8025")
CERT = os.environ.get("SSL_CERTFILE", "")
KEY = os.environ.get("SSL_KEYFILE", "")
use_tls = bool(CERT and KEY and os.path.isfile(CERT) and os.path.isfile(KEY))
url = f"https://127.0.0.1:{PORT}/health" if use_tls else f"http://127.0.0.1:{PORT}/health"


def main() -> int:
    try:
        if use_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            urllib.request.urlopen(url, timeout=5, context=ctx)
        else:
            urllib.request.urlopen(url, timeout=5)
    except (urllib.error.URLError, OSError):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

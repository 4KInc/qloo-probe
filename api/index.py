"""Vercel entry point.

Cloud Run was the original target, but this organisation's policy forbids
granting allUsers, so a Cloud Run service here can never be publicly
reachable and the rules require a demo with no login. Vercel hosts the same
code instead.

Vercel's Python runtime expects a BaseHTTPRequestHandler subclass named
`handler`, which is exactly what app/server.py already defines, so this is a
re-export rather than a port.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.server import Handler  # noqa: E402


class handler(Handler):
    """Each invocation is a fresh process, so the in-memory budget guard
    resets between requests. The quota floor still applies because it is read
    from the response headers, and the recorded presets still serve without
    touching the API at all."""
    pass

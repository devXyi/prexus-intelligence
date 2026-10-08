"""
core/security.py — engine authentication (fail-closed).

The engine is a *service*, not a public API: only the Go gateway (which owns
users, RBAC and LLM keys) may call it, using the shared ENGINE_SECRET.

v1 problems fixed here:
  • `_verify` returned True when ENGINE_SECRET was empty → an unset env var
    silently turned authentication OFF on a public URL.
  • Secret compared with `!=` (timing side channel).
  • Several routes (/analyze, /chat, /sources, /risk/health) had no auth at all.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("meteorium.security")
MIN_SECRET_LEN = 16


def _secret() -> str:
    """ENGINE_SECRET, or the contents of ENGINE_SECRET_FILE (Docker/K8s secrets are files:
    env vars show up in `docker inspect`, crash dumps and child processes)."""
    f = os.environ.get("ENGINE_SECRET_FILE", "")
    if f:
        try:
            with open(f, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            logger.error("ENGINE_SECRET_FILE is set but unreadable")
            return ""
    return os.environ.get("ENGINE_SECRET", "")


def _is_placeholder(v: str) -> bool:
    l = v.lower()
    return "change-this" in l or "change-in-production" in l or "changeme" in l


def insecure_allowed() -> bool:
    """Explicit local-dev escape hatch. Never set in production."""
    return os.environ.get("ENGINE_ALLOW_INSECURE", "") == "1"


def assert_auth_configured() -> None:
    """Call at startup: refuse to boot without a usable secret."""
    s = _secret()
    if len(s) >= MIN_SECRET_LEN and not _is_placeholder(s):
        return
    if insecure_allowed():
        logger.warning("ENGINE_ALLOW_INSECURE=1 — engine authentication is DISABLED (development only)")
        return
    raise RuntimeError(
        f"ENGINE_SECRET is missing or shorter than {MIN_SECRET_LEN} characters. "
        "Set it (e.g. `openssl rand -hex 32`) on BOTH the gateway and the engine, "
        "or set ENGINE_ALLOW_INSECURE=1 for local development."
    )


def require_engine_auth(authorization: Optional[str] = Header(None)) -> bool:
    s = _secret()
    if not s:
        if insecure_allowed():
            return True
        raise HTTPException(503, "engine authentication not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    presented = authorization[7:].encode("utf-8")
    if not hmac.compare_digest(presented, s.encode("utf-8")):
        raise HTTPException(401, "Invalid token")
    return True

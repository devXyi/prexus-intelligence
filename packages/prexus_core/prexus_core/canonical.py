"""Canonical JSON — must stay byte-identical to airgap/control-plane/lib/canonical.mjs.

Rules: keys sorted and ASCII-only; no whitespace; integers only (float formatting differs
between languages: JS `1` vs Python `1.0`) so decimals travel as strings.
"""
from __future__ import annotations

import json
from typing import Any

MAX_SAFE_INT = 2**53 - 1


def canonical(value: Any) -> str:
    def walk(v: Any) -> str:
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, int):
            if abs(v) > MAX_SAFE_INT:
                raise TypeError("integer outside the safe range")
            return str(v)
        if isinstance(v, float):
            raise TypeError("canonical JSON forbids floats; encode decimals as strings")
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, (list, tuple)):
            return "[" + ",".join(walk(x) for x in v) + "]"
        if isinstance(v, dict):
            parts = []
            for k in sorted(v):
                if not isinstance(k, str) or not all(0x20 <= ord(c) <= 0x7E for c in k):
                    raise TypeError("canonical JSON keys must be ASCII strings")
                parts.append(json.dumps(k, ensure_ascii=False) + ":" + walk(v[k]))
            return "{" + ",".join(parts) + "}"
        raise TypeError(f"cannot canonicalise {type(v).__name__}")

    return walk(value)

"""Append-only, hash-chained, Ed25519-anchored audit ledger (spec: docs/LEDGER_SPEC.md).

Same on-disk format as the air-gap control plane (airgap/control-plane/lib/ledger.mjs):
NDJSON, one canonical-JSON event per line, `hash = sha256(canonical(event minus hash))`,
signed head anchor in anchors/head.json. Either implementation verifies the other's files.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .canonical import canonical

GENESIS = "GENESIS"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def key_id_of_public(pub) -> str:
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:16]


class Signer:
    def __init__(self, private_key: Ed25519PrivateKey):
        self._key = private_key
        self.public_key = private_key.public_key()
        self.public_pem = self.public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.key_id = key_id_of_public(self.public_key)

    @classmethod
    def generate(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Signer":
        return cls(serialization.load_pem_private_key(Path(path).read_bytes(), password=None))

    def save(self, path: str | os.PathLike) -> None:
        pem = self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)

    def sign(self, text: str) -> str:
        return base64.b64encode(self._key.sign(text.encode("utf-8"))).decode()


def head_message(h: Dict[str, Any]) -> str:
    return canonical({"sequence": h["sequence"], "head_hash": h["head_hash"], "signed_at": h["signed_at"], "key_id": h["key_id"]})


def verify_signed_head(head: Dict[str, Any], public_pem: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(public_pem.encode())
        pub.verify(base64.b64decode(head["signature"]), head_message(head).encode("utf-8"))
        return True
    except Exception:
        return False


def verify_event_chain(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    previous, seq = GENESIS, 0
    for ev in events:
        seq += 1
        unsigned = {k: v for k, v in ev.items() if k != "hash"}
        def bad(reason, s=ev.get("seq", seq)):
            return {"valid": False, "checked_events": len(events), "failed_seq": s, "reason": reason}
        if ev.get("v") != 2:
            return bad("unsupported event version")
        if ev.get("seq") != seq:
            return bad("sequence gap or reorder")
        if ev.get("previous_hash") != previous:
            return bad("previous_hash mismatch (event removed or reordered)")
        if ev.get("hash") != _sha256(canonical(unsigned)):
            return bad("event content does not match its hash (modified)")
        previous = ev["hash"]
    return {"valid": True, "checked_events": len(events), "head_hash": previous, "head_sequence": seq}


def _now() -> str:
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class LedgerIntegrityError(RuntimeError):
    pass


class Ledger:
    def __init__(self, directory: str | os.PathLike, signer: Optional[Signer] = None):
        self.dir = Path(directory)
        self.file = self.dir / "ledger.ndjson"
        self.signer = signer
        self.events: List[Dict[str, Any]] = []
        self.head_hash, self.seq = GENESIS, 0
        self.valid, self.failure = True, None
        self._lock = threading.Lock()
        self._fh = None
        self._open()

    # ── open / recover ───────────────────────────────────────────────────────
    def _open(self) -> None:
        (self.dir / "anchors").mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = self.file.read_bytes() if self.file.exists() else b""
        discarded = 0
        if raw and not raw.endswith(b"\n"):                       # crash mid-append: drop torn tail
            keep = raw.rfind(b"\n") + 1
            discarded = len(raw) - keep
            raw = raw[:keep]
            self.file.write_bytes(raw)
        try:
            self.events = [json.loads(l) for l in raw.decode("utf-8").split("\n") if l]
            v = verify_event_chain(self.events)
            if not v["valid"]:
                self.valid, self.failure = False, v
        except ValueError as e:
            self.valid, self.failure = False, {"valid": False, "reason": f"ledger is not valid JSON lines: {e}"}
        if self.valid and self.signer:
            self._check_anchor()
        if self.valid and self.events:
            self.seq, self.head_hash = self.events[-1]["seq"], self.events[-1]["hash"]
        self._fh = open(self.file, "ab")
        os.chmod(self.file, 0o600)
        if self.valid and discarded:
            self.append("system", "ledger.recovered", "ledger", {"discarded_bytes": discarded})

    def _check_anchor(self) -> None:
        p = self.dir / "anchors" / "head.json"
        if not p.exists():
            return
        try:
            a = json.loads(p.read_text())
        except ValueError:
            self.valid, self.failure = False, {"valid": False, "reason": "signed anchor is unreadable"}
            return
        if not verify_signed_head(a, self.signer.public_pem):
            self.valid, self.failure = False, {"valid": False, "reason": "signed anchor is invalid (tampered, or signed by a different key)"}
        elif a["sequence"] > len(self.events):
            self.valid, self.failure = False, {"valid": False, "reason": f"ledger has {len(self.events)} events but its signed anchor attests {a['sequence']} (truncated or replaced)"}
        elif a["sequence"] > 0 and self.events[a["sequence"] - 1]["hash"] != a["head_hash"]:
            self.valid, self.failure = False, {"valid": False, "reason": "ledger diverges from its signed anchor (history rewritten)"}

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    # ── write ────────────────────────────────────────────────────────────────
    def append(self, actor: str, action: str, resource: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            if not self.valid:
                raise LedgerIntegrityError("ledger integrity failure — refusing to write")
            ev = {"v": 2, "seq": self.seq + 1, "id": str(uuid.uuid4()), "at": _now(), "actor": actor,
                  "action": action, "resource": resource, "metadata": metadata or {}, "previous_hash": self.head_hash}
            ev["hash"] = _sha256(canonical(ev))
            self._fh.write((canonical(ev) + "\n").encode("utf-8"))
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self.events.append(ev)
            self.seq, self.head_hash = ev["seq"], ev["hash"]
            self._write_anchor()
            return ev

    def signed_head(self) -> Dict[str, Any]:
        base = {"sequence": self.seq, "head_hash": self.head_hash}
        if not self.signer:
            return {**base, "signed": False}
        h = {**base, "signed_at": _now(), "key_id": self.signer.key_id}
        return {**h, "alg": "Ed25519", "signature": self.signer.sign(head_message(h)), "public_key": self.signer.public_pem, "signed": True}

    def _write_anchor(self) -> None:
        if not self.signer:
            return
        p = self.dir / "anchors" / "head.json"
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.signed_head(), indent=2) + "\n")
        os.replace(tmp, p)

    # ── read ─────────────────────────────────────────────────────────────────
    def verify(self) -> Dict[str, Any]:
        if not self.valid:
            return self.failure
        try:
            events = [json.loads(l) for l in self.file.read_text("utf-8").split("\n") if l]
        except ValueError as e:
            return {"valid": False, "reason": str(e)}
        v = verify_event_chain(events)
        if v["valid"] and (v["head_hash"] != self.head_hash or v["head_sequence"] != self.seq):
            return {"valid": False, "checked_events": len(events), "reason": "on-disk ledger diverges from the running process (replaced or truncated)"}
        return v

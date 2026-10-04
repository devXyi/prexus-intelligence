"""Signed offline import bundles — same format as airgap/control-plane/lib/bundle.mjs.

  bundle/ manifest.json   canonical-JSON manifest (format "prexus-bundle/1")
          manifest.sig    base64 Ed25519 signature over canonical(manifest)
          files/**        payload; every file's sha256 + size is pinned in the manifest
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization

from .canonical import canonical
from .ledger import Signer, key_id_of_public

FORMAT = "prexus-bundle/1"
CLASSES = ("internal", "restricted")
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class BundleError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def key_id_of(pem: str) -> str:
    return key_id_of_public(serialization.load_pem_public_key(pem.encode()))


def load_trusted_keys(directory: str | Path) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for f in sorted(Path(directory).glob("*.pem")):
        pem = f.read_text()
        if "BEGIN PUBLIC KEY" not in pem:      # never treat a private key (or junk) as a trust anchor
            continue
        keys[key_id_of(pem)] = pem
    return keys


def safe_bundle_file(root: Path, rel: str) -> Path:
    """Return a canonical descendant of root; reject traversal and symlink escapes."""
    base = os.path.realpath(str(root))
    candidate = os.path.realpath(os.path.join(base, rel))
    if candidate == base or not candidate.startswith(base + os.sep):
        raise BundleError(f"unsafe file path: {rel!r}", 403)
    return Path(candidate)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_bundle(out_root: str | Path, name: str, version: int, files: Dict[str, bytes], signer: Signer, *,
                 classification: str = "restricted", file_meta: Optional[Dict[str, Dict[str, Any]]] = None,
                 created_at: Optional[str] = None) -> Path:
    if not _NAME.match(name):
        raise BundleError("invalid bundle name")
    root = Path(out_root) / f"{name}-v{version}"
    entries = []
    for rel, content in sorted(files.items()):
        if rel.startswith("/") or ".." in rel.split("/") or "\\" in rel or "\0" in rel:
            raise BundleError(f"unsafe file path: {rel!r}")
        p = safe_bundle_file(root / "files", rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        e = {"path": rel, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content), "classification": classification}
        e.update((file_meta or {}).get(rel, {}))
        entries.append(e)
    manifest = {"format": FORMAT, "name": name, "version": version, "signer_key_id": signer.key_id, "files": entries,
                "created_at": created_at or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "manifest.sig").write_text(signer.sign(canonical(manifest)))
    return root


def verify_manifest(manifest: Dict[str, Any], signature_b64: str, trusted: Dict[str, str],
                    last_versions: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BundleError("unsupported bundle format")
    if not _NAME.match(str(manifest.get("name", ""))):
        raise BundleError("invalid bundle name")
    ver = manifest.get("version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        raise BundleError("bundle version must be a positive integer")
    pem = trusted.get(manifest.get("signer_key_id"))
    if not pem:
        raise BundleError("bundle is signed by an untrusted key", 403)
    try:
        serialization.load_pem_public_key(pem.encode()).verify(base64.b64decode(signature_b64.strip()), canonical(manifest).encode("utf-8"))
    except Exception:
        raise BundleError("bundle signature is invalid", 403)
    last = (last_versions or {}).get(manifest["name"])
    if last is not None and ver <= last:
        raise BundleError(f"rollback/replay refused: {manifest['name']} v{ver} <= accepted v{last}", 409)
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 5000:
        raise BundleError("manifest.files must be a non-empty list")
    seen = set()
    for f in files:
        p = f.get("path")
        if not isinstance(p, str) or not p or p.startswith("/") or ".." in p.split("/") or "\\" in p or "\0" in p:
            raise BundleError(f"unsafe file path in manifest: {p!r}")
        if p in seen:
            raise BundleError(f"duplicate file path: {p}")
        seen.add(p)
        if not re.fullmatch(r"[a-f0-9]{64}", str(f.get("sha256", ""))):
            raise BundleError(f"bad sha256 for {p}")
        if not isinstance(f.get("size"), int) or f["size"] < 0:
            raise BundleError(f"bad size for {p}")
        if f.get("classification") not in CLASSES:
            raise BundleError(f"bad classification for {p}")
    return manifest


def verify_bundle_dir(root: str | Path, rel: str, trusted: Dict[str, str],
                      last_versions: Optional[Dict[str, int]] = None) -> tuple[Dict[str, Any], Path]:
    root_r = Path(root).resolve()
    try:
        d = (root_r / rel).resolve(strict=True)
    except FileNotFoundError:
        raise BundleError("bundle path not found", 404)
    if d != root_r and root_r not in d.parents:
        raise BundleError("bundle path escapes the import root", 403)
    manifest = json.loads((d / "manifest.json").read_text())
    verify_manifest(manifest, (d / "manifest.sig").read_text(), trusted, last_versions)
    problems = []
    files_root = (d / "files").resolve()
    for f in manifest["files"]:
        try:
            p = safe_bundle_file(files_root, f["path"])
        except BundleError:
            problems.append(f"{f['path']}: outside bundle"); continue
        if not p.exists():
            problems.append(f"{f['path']}: missing"); continue
        if p.stat().st_size != f["size"]:
            problems.append(f"{f['path']}: size {p.stat().st_size} != {f['size']}"); continue
        if _sha256_file(p) != f["sha256"]:
            problems.append(f"{f['path']}: sha256 mismatch")
    if problems:
        raise BundleError("bundle content verification failed: " + "; ".join(problems), 422)
    return manifest, d

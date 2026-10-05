"""Signed offline import bundles.

Security invariant: every filesystem path derived from caller/manifest input must be
resolved and proven to remain inside its trusted root before filesystem access.
"""
from __future__ import annotations

import base64
import hashlib
import json
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
        if "BEGIN PUBLIC KEY" not in pem:
            continue
        keys[key_id_of(pem)] = pem
    return keys


def resolve_trusted_path(root: str | Path, requested: str, *, strict: bool = False) -> Path:
    """Resolve a path and enforce that it stays beneath the trusted root."""
    if not isinstance(requested, str) or not requested or "\x00" in requested:
        raise BundleError("invalid bundle path", 400)

    root_r = Path(root).resolve()
    if not root_r.is_dir():
        raise BundleError("bundle root is not a directory", 500)

    candidate = (root_r / requested).resolve(strict=strict)
    if candidate != root_r and root_r not in candidate.parents:
        raise BundleError("bundle path escapes the trusted root", 403)
    return candidate


def _validate_relative_file_path(rel: str, *, field: str = "file path") -> None:
    if (
        not isinstance(rel, str)
        or not rel
        or rel.startswith("/")
        or rel.startswith("\\")
        or Path(rel).is_absolute()
        or ".." in Path(rel).parts
        or "\\" in rel
        or "\x00" in rel
    ):
        raise BundleError(f"unsafe {field}: {rel!r}")


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_bundle(
    out_root: str | Path,
    name: str,
    version: int,
    files: Dict[str, bytes],
    signer: Signer,
    *,
    classification: str = "restricted",
    file_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    created_at: Optional[str] = None,
) -> Path:
    if not _NAME.match(name):
        raise BundleError("invalid bundle name")
    root = resolve_trusted_path(out_root, f"{name}-v{version}")
    entries = []
    for rel, content in sorted(files.items()):
        _validate_relative_file_path(rel)
        p = resolve_trusted_path(root / "files", rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        e = {
            "path": rel,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "classification": classification,
        }
        e.update((file_meta or {}).get(rel, {}))
        entries.append(e)

    manifest = {
        "format": FORMAT,
        "name": name,
        "version": version,
        "signer_key_id": signer.key_id,
        "files": entries,
        "created_at": created_at
        or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "manifest.sig").write_text(signer.sign(canonical(manifest)))
    return root


def verify_manifest(
    manifest: Dict[str, Any],
    signature_b64: str,
    trusted: Dict[str, str],
    last_versions: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
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
        serialization.load_pem_public_key(pem.encode()).verify(
            base64.b64decode(signature_b64.strip()),
            canonical(manifest).encode("utf-8"),
        )
    except Exception:
        raise BundleError("bundle signature is invalid", 403)
    last = (last_versions or {}).get(manifest["name"])
    if last is not None and ver <= last:
        raise BundleError(
            f"rollback/replay refused: {manifest['name']} v{ver} <= accepted v{last}",
            409,
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 5000:
        raise BundleError("manifest.files must be a non-empty list")
    seen = set()
    for f in files:
        p = f.get("path")
        _validate_relative_file_path(p, field="file path in manifest")
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


def verify_bundle_dir(
    root: str | Path,
    rel: str,
    trusted: Dict[str, str],
    last_versions: Optional[Dict[str, int]] = None,
) -> tuple[Dict[str, Any], Path]:
    root_r = Path(root).resolve()
    try:
        d = resolve_trusted_path(root_r, rel, strict=True)
    except FileNotFoundError:
        raise BundleError("bundle path not found", 404)

    if d == root_r:
        raise BundleError("bundle path must identify a bundle directory", 400)
    if not d.is_dir():
        raise BundleError("bundle path is not a directory", 404)

    manifest_path = resolve_trusted_path(d, "manifest.json", strict=True)
    signature_path = resolve_trusted_path(d, "manifest.sig", strict=True)
    manifest = json.loads(manifest_path.read_text())
    verify_manifest(manifest, signature_path.read_text(), trusted, last_versions)

    problems = []
    files_root = resolve_trusted_path(d, "files", strict=False)
    if not files_root.is_dir():
        raise BundleError("bundle files directory is missing", 422)

    for f in manifest["files"]:
        try:
            p = resolve_trusted_path(files_root, f["path"], strict=True)
        except FileNotFoundError:
            problems.append(f"{f['path']}: missing")
            continue

        if p == files_root or files_root not in p.parents:
            problems.append(f"{f['path']}: outside bundle")
            continue
        if p.stat().st_size != f["size"]:
            problems.append(f"{f['path']}: size {p.stat().st_size} != {f['size']}")
            continue
        if _sha256_file(p) != f["sha256"]:
            problems.append(f"{f['path']}: sha256 mismatch")

    if problems:
        raise BundleError(
            "bundle content verification failed: " + "; ".join(problems),
            422,
        )
    return manifest, d

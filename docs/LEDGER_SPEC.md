# Audit ledger & signed bundle specification (v2)

One spec, two implementations — `airgap/control-plane/lib/{ledger,canonical,bundle}.mjs` (Node) and
`packages/prexus_core/prexus_core/{ledger,canonical,bundle}.py` (Python). Each verifies the other's
output; `packages/prexus_core/tests/test_crosslang.py` proves it (300 random structures hash identically).

## Canonical JSON
Keys sorted, ASCII-only keys, no whitespace, UTF-8 strings (`ensure_ascii=False` / `JSON.stringify`),
**integers only** (|n| ≤ 2^53−1). Decimals travel as strings: `1` vs `1.0` differs between languages.

## Ledger file (`ledger.ndjson`, one canonical-JSON event per line)
```
{ v:2, seq:N, id:<uuid>, at:<ISO-8601 UTC>, actor, action, resource, metadata:{…}, previous_hash, hash }
hash = sha256( canonical(event without "hash") )         previous_hash(seq 1) = "GENESIS"
```
Appends are serialised, written, `fsync`ed, then acknowledged. A torn final line (crash mid-write) is
discarded on open and recorded as `ledger.recovered`.

## Signed head (`anchors/head.json`, rewritten atomically after every append)
```
{ sequence, head_hash, signed_at, key_id, alg:"Ed25519", signature, public_key }
signature = Ed25519( canonical({sequence, head_hash, signed_at, key_id}) )     key_id = sha256(SPKI-DER)[:16]
```
Detects what a bare hash chain cannot: **truncation**, **replacement by a different valid chain**, and
history rewritten with the same length. Export the head to operator media regularly; verify offline:
```
node airgap/control-plane/tools/verify-ledger.mjs ledger.ndjson --anchor head.json --pubkey ledger.pub.pem
```
Exit 0 = valid; 1 = tampered/truncated/rewritten.

## Bundle (`prexus-bundle/1`)
```
<name>-v<version>/ manifest.json   manifest.sig (base64 Ed25519 over canonical(manifest))   files/**
manifest = { format, name, version:int, created_at, signer_key_id,
             files:[{ path, sha256, size, classification: internal|restricted, … connector/source/license }] }
```
Verifier checks: trusted `signer_key_id` (PUBLIC-key PEMs only; private keys in the trust dir are ignored),
signature, **monotonic version per name** (rollback/replay → 409), safe relative paths, no symlink or `..`
escape from the import root, then every file's size and SHA-256.

## What the ledger does *not* give you
Non-repudiation of *who* — that comes from per-operator credentials (control plane) / token→subject
mapping (Raksha). A compromised signing key can re-sign a forged chain: keep the key offline or in an HSM
and compare exported heads. Metadata must not contain secrets; the code never writes tokens.

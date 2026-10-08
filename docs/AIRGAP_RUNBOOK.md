# Air-gap runbook

## Model: a closed loop with one verified door
Inside the enclave nothing initiates outbound connections. Everything that enters is a **signed bundle**
(sneakernet); everything that leaves is an explicit, logged export. Three tiers — decide the tier first:
T1 isolated on-prem with controlled media · T2 classified, one-way data diode · T3 cross-domain (out of scope).

## What exists and is tested (sandbox, no Docker)
| Capability | Where | Evidence |
|---|---|---|
| Per-operator auth (hashed 256-bit tokens, roles `operator`/`auditor`, brute-force throttle) | `control-plane/lib/auth.mjs` | `security.test.mjs` |
| Tamper-evident ledger + signed head + offline verifier | `lib/ledger.mjs`, `tools/verify-ledger.mjs` | `ledger.test.mjs` (modify/delete/reorder/truncate/replace/torn-write/200 concurrent appends) |
| Signed bundle import with rollback + path-escape defence | `lib/bundle.mjs`, node `bundle-import` | `bundle.test.mjs`, cross-language tests |
| Real engine as a node (`meteorium-engine`), **internal URLs only** | `server.mjs`, `lib/netpolicy.mjs` | engine-node tests (receipt = input/output SHA-256) |
| Egress self-test; `air_gapped_verified` is measured, not asserted | `lib/egress.mjs` | probe tests |
| Whole suite passes with **no network** (netns with only `lo`) | `airgap/tools/netns-test.sh` | 30/30 inside the namespace |
| Gateway LLM → local model switch | Go `OPENAI_BASE_URL`/`OPENAI_MODEL` | `ai_gateway_test.go` |

## What is NOT done / not verified
Docker path (compose, Dockerfiles) — no daemon here: YAML validated, topology asserted, `nginx -t` passes, but never `up`'d.
Gateway + Postgres + a local LLM server are not in the compose stack yet. No HA, backup/restore, SSO/PKI,
HSM, multi-tenant isolation, third-party pen-test. Base images are tag-pinned, not digest-pinned.

## Procedures
**1. Operator onboarding** (connected, offline workstation): `node tools/mint-operator.mjs alice operator` →
hand `token` to Alice once; add `registry_entry` to `secrets/operators.json`. Auditors get role `auditor`.
**2. Build factory (connected side)**: reproducible builds; `docker save`; SBOM + vuln scan; sign with the
offline bundle key (`python -m raksha.builder … --key bundle.key.pem` or `prexus_core.bundle.build_bundle`).
**3. Import (enclave)**: copy the bundle dir to `./import/`; run node `bundle-import.register-bundle {"path":"<dir>"}`
(control plane) or `POST /v1/ingest/bundle` (Raksha, admin). Refusals are audited.
**4. Daily**: `GET /health` (`air_gapped_verified` must be true) and export `anchors/head.json` to media.
**5. Audit**: on a separate machine run `verify-ledger.mjs` with the exported head and public key.
**6. Local LLM**: serve an open-weight model behind an OpenAI-compatible endpoint (vLLM/Ollama/NIM), set
`OPENAI_BASE_URL` on the gateway. Pick weights by licence and provenance (some buyers will exclude certain origins).

## Residual risks
The ingress proxy is the only container on a non-internal network: if compromised it could attempt egress —
add a host firewall rule dropping forwarded traffic from the `ingress` subnet except to the enclave.
Clock drift breaks token and certificate checks: use a local time source. Operator tokens are bearer secrets:
prefer mTLS/OIDC for production (not implemented).

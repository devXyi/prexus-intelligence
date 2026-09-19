# Prexus air-gap control-plane foundation

This is a runnable, deliberately small vertical slice for a sovereign deployment. It is not a claim that Prexus is Foundry-equivalent or that the Meteorium score is calibrated climate intelligence.

## What is implemented

- An authenticated operator console served by the control plane.
- A fixed registry of Meteorium intake, offline-simulation, and audit-verification nodes.
- A controlled-action API: no tenant-supplied shell command is ever executed.
- A persisted, hash-chained audit ledger.
- Offline-only data registration: artifacts must be supplied by an operator with a SHA-256 digest.
- A Compose deployment with no external network, loopback-only access, a read-only root filesystem, dropped Linux capabilities, and a persistent state volume.

The end-to-end path is `register-dataset → offline-simulate → verify-ledger`. The simulation is explicitly marked `demonstration-only`; its deterministic result is test data, not a risk model.

## Run and verify locally

Node 20+ is sufficient; there are no third-party runtime dependencies.

```bash
cd airgap/control-plane
PREXUS_OPERATOR_TOKEN=replace-with-a-high-entropy-secret npm test
PREXUS_OPERATOR_TOKEN=replace-with-a-high-entropy-secret npm start
```

Open `http://127.0.0.1:8787`, enter the token, register a dataset, run the offline simulation, then run ledger verification. The test performs the same sequence over HTTP, including an unauthorized request check and a subsequent run lookup.

## Offline container delivery

Build the image on an approved build host, transfer it using your organization’s signed-media process, then load it inside the disconnected environment. Docker is needed only for the container path; it is not installed in this development workspace, so that path has not been executed here.

```bash
PREXUS_OPERATOR_TOKEN=replace-with-a-high-entropy-secret docker compose -f docker-compose.airgap.yml up --build
```

The `internal` Docker network prevents service egress at runtime. It does not by itself make the host air-gapped: the host, image-import process, operating system patching, hardware security controls, identity provider, backups, and ingress gateway must also be within the approved disconnected boundary.

## Not yet implemented

- A calibrated Meteorium model and validated local climate-data package.
- Multi-tenant database isolation, SSO/PKI, key management, backup/restore, HA, and signed release verification.
- An ontology, data lineage graph, governed workflows, and object/action model comparable to Palantir Foundry.
- Migration of the legacy Go/Python/Rust services away from Supabase, hosted LLMs, Render, and public data APIs.

Those are release gates, not details to obscure with a dashboard. The next build increment should replace the in-process JSON state with a locally operated PostgreSQL schema, introduce mTLS/OIDC, and wrap a validated offline Meteorium model behind the `meteorium-score` node.

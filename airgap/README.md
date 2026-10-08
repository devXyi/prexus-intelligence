# Air-gap control plane (v2)
Closed-loop operator console: per-operator authentication, a signed hash-chained audit ledger, signed-bundle import, an
engine node restricted to internal addresses, and an egress self-test. Not a Palantir-Foundry equivalent: no ontology,
lineage graph, SSO/PKI, HA or key management yet. Details: `/docs/AIRGAP_RUNBOOK.md`, `/docs/LEDGER_SPEC.md`.
`cd control-plane && node --test` · `./tools/netns-test.sh` (same suite, no network) · `tools/mint-operator.mjs`, `tools/verify-ledger.mjs`, `tools/verify-bundle.mjs`.
The `meteorium-score` node is a deterministic **demonstration**; `meteorium-engine` calls the real engine and its output says whether it is calibrated.

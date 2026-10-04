"""prexus_core — one implementation of the platform's trust primitives.

* canonical  — canonical JSON (bit-identical with airgap/control-plane/lib/canonical.mjs)
* ledger     — append-only hash-chained, Ed25519-anchored audit ledger (docs/LEDGER_SPEC.md)
* bundle     — signed offline import bundles (docs/AIRGAP_RUNBOOK.md)
* abac       — attribute-based access control (clearance, compartments, TLP, purpose)
"""
__version__ = "0.1.0"

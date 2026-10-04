# Raksha v0 — threat & disruption intelligence

**Scope assumed:** multi-domain (cyber + geo-events + physical hazards → infrastructure disruption), per the
module definition. If Shoghi's first need is pure cyber threat intel or pure ISR/geospatial fusion, the
connectors change, the rest does not.

## Built (modules/raksha, 31 tests) — everything runs offline against synthetic fixtures
* **Canonical model** — STIX 2.1 via the `stix2` library; custom SDOs `x-prexus-event`, `x-prexus-asset`;
  deterministic UUIDv5 ids (re-ingest never duplicates); TLP markings; Admiralty source reliability (A–F) and
  credibility (1–6) mapped to STIX `confidence`; H3 cells for geo indexing.
* **Store** — SQLite, STIX versioning (changed content ⇒ new `modified`, never an in-place edit), provenance table,
  rollback-protected bundle registry, stable cursor pagination.
* **Connectors** — CISA KEV (JSON), FIRST EPSS (CSV, applied as enrichment versions), GDELT 2.0 events (61-column TSV;
  column map from the published codebook — verify against a live sample), NASA FIRMS VIIRS (CSV, low-confidence dropped).
* **Pipeline** — connected side: `python -m raksha.builder` validates each feed and emits a signed bundle (no network code
  by design); enclave side: signature → rollback → file hashes → parse → store → ledger.
* **Access control** — `prexus_core.abac`: default-deny, deny-overrides, reasons for every denial (clearance 0–5,
  compartments, TLP incl. AMBER+STRICT/RED recipients, purpose limitation, export rules incl. licence and
  classification-vs-network, no-write-down). Every query is ledgered (`returned`/`denied` counts).
  **Scores are computed only from data the caller may read** (no inference leak); a caller cannot even confirm that a
  hidden asset exists (404).
* **TAXII 2.1 (read-only)** — discovery, api-root, collections, objects (filters, pagination, `X-TAXII-Date-Added-*`),
  manifest, single object. Served objects are validated as STIX in tests. OpenCTI/MISP interop not tested here.
* **Scoring (transparent v0)** — per asset, per component (unrest, violence, thermal, cyber):
  Gamma–Poisson rate with an empirical-Bayes regional prior, `P(≥1 event in τ) = 1 − (β/(β+τ))^α`, 90 % credible interval,
  evidence ids; cyber = noisy-OR of EPSS over KEV CVEs matching the asset's technologies **assuming unpatched** (upper bound);
  combined = noisy-OR. Always `calibrated:false`.
* **Cascade engine** — independent-cascade Monte Carlo on the dependency graph, checked against exact enumeration on
  chain/diamond graphs; edge-criticality what-if with common random numbers. Edge probabilities are operator priors.
* **Back-test harness** — rolling-origin Brier, ECE, reliability bins, skill vs climatology; flags a regime shift.

## Not built / honest limits
No live feeds were fetched (sandbox had no route to them); fixtures are synthetic and labelled. No Hawkes/contagion model,
no entity resolution beyond deterministic ids, no local-LLM extraction, no analyst UI, no Postgres/PostGIS adapter
(SQLite only), no ACLED (needs a licence), no personal-data handling — Raksha is purpose-limited to assets, organisations
and infrastructure and must not be pointed at individuals. Scores are NOT calibrated: run `raksha.backtest` on your own
history before anyone quotes a probability.

## Next 30 days
W1 requirements + threat model with the design partner; first real KEV/EPSS/GDELT/FIRMS packages through the builder.
W2 back-test on real history, tune priors; ACLED licence decision. W3 Postgres/PostGIS adapter, entity resolution,
analyst screen (map + evidence panel). W4 Hawkes contagion, Meteorium hazard feed → cascade, red-team pass, air-gap drill.

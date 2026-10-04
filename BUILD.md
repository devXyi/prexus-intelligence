# Build & run (v2 — replaces the stale layout in the previous BUILD.md)

```
backend/backend/apps/api-gateway   Go gateway (module root: backend/backend, go 1.22)
data-engine/python                  FastAPI engine (layer0-6, core/, catmodel/)    data-engine/rust   Rust core (PyO3, maturin)
packages/prexus_core                shared trust primitives (ledger, bundle, ABAC)
modules/raksha                      Raksha v0                                      airgap/control-plane  Node control plane
frontend/ index.html app/           static site + UI                              docs/                 specs, runbook, audit log
```

## Test everything
```
cd backend/backend && go vet ./... && go test ./... -race          # needs the whole repo (frontend↔route contract test)
cd data-engine/rust && cargo test                                   # 23 tests (portfolio MC module is compiled again)
cd data-engine/rust && pip install maturin && maturin build --release && pip install target/wheels/*.whl
cd data-engine/python && pip install -r requirements.txt pytest && python -m pytest tests
pip install ./packages/prexus_core ./modules/raksha pytest && python -m pytest packages/prexus_core modules/raksha
cd airgap/control-plane && node --test && cd .. && sudo ./tools/netns-test.sh      # second run has no network at all
```

## Run locally
```
export ENGINE_SECRET=$(openssl rand -hex 32) JWT_SECRET=$(openssl rand -hex 32) ENV=development
# engine (refuses to start without ENGINE_SECRET; ENGINE_ALLOW_INSECURE=1 only for throwaway dev)
cd data-engine/python && uvicorn layer6.api:app --port 8001
# gateway (needs Postgres: DATABASE_URL=postgres://… )
cd backend/backend && DATA_ENGINE_URL=http://localhost:8001 go run ./apps/api-gateway
```
Environment reference: `.env.example`. Deploy: `render.yaml` (paid plans; engine is a private service). Air-gap: `docs/AIRGAP_RUNBOOK.md`.

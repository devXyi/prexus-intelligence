# Go gateway audit ledger

The API gateway can write authenticated-route audit events using the v2 event format and Ed25519-signed head described in LEDGER_SPEC.md. The ledger is append-only at the application layer; each event is canonicalized, SHA-256 hash-chained, flushed, and fsync'd before the handler is invoked. The signed head is atomically replaced and its parent directory synced after each append.

## Required production configuration

Set both environment variables:

- AUDIT_LEDGER_DIR: persistent, private directory for ledger.ndjson and anchors/head.json.
- AUDIT_LEDGER_PRIVATE_KEY: filesystem path to an Ed25519 PKCS#8 PEM private key. Keep this key outside the repository and outside the ledger directory.

Generate a key in a controlled environment:

~~~sh
openssl genpkey -algorithm ED25519 -out prexus-audit-ed25519.pem
chmod 600 prexus-audit-ed25519.pem
~~~

Provision the private key through the deployment's secret-file mechanism and mount the ledger directory on durable storage. Do not commit the key, put it in ordinary environment-variable values, or copy it into an exported audit bundle. The gateway refuses to start in ENV=production if either setting is missing or the key cannot be parsed.

## Event behavior

- Middleware is applied after authentication on the protected API route group.
- It writes http.request.started before the route handler runs; if that append fails, the request is rejected with HTTP 503 before the handler executes.
- After the handler, it writes http.request.completed with status and duration. It does not record request bodies, query strings, bearer tokens, or provider payloads.
- If completion recording fails after the response has already been produced, the start event remains durable and the error is logged. The ledger then refuses subsequent appends, causing later protected requests to fail closed.
- Health, registration, and login routes are not covered by this middleware in the current iteration.

## Operational constraints and limits

- This implementation uses a local file and an in-process mutex. Run **one gateway writer per ledger directory**. Do not share the same ledger directory between independent replicas or network filesystems without a distributed locking and append protocol.
- Use durable mounted storage; an ephemeral container filesystem is not a durable audit archive.
- Back up/export anchors/head.json and the public key to independently controlled media on a regular schedule. Verify an exported copy offline using the verifier described in LEDGER_SPEC.md.
- A signing key stored on the same host can be compromised with that host. This is tamper evidence, not hardware-backed key custody, remote attestation, or a compliance certification.
- The gateway ledger is not yet transactionally coupled to PostgreSQL business mutations. A successful audit event records the request lifecycle, not proof that every downstream side effect committed atomically.

## Local validation

From the repository's Go module directory:

~~~sh
cd backend/backend
go test ./auditledger ./apps/api-gateway
go test -race ./auditledger ./apps/api-gateway
~~~

The CI workflow additionally runs the repository's existing Go vet, race, PostgreSQL integration, and vulnerability checks.

import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createApp } from "./server.mjs";

async function start(stateDir) {
  const app = await createApp({ stateDir, operatorToken: "test-operator-token" });
  await new Promise((resolve) => app.server.listen(0, "127.0.0.1", resolve));
  const { port } = app.server.address();
  return { ...app, baseUrl: `http://127.0.0.1:${port}` };
}

function request(baseUrl, path, options = {}) {
  return fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { authorization: "Bearer test-operator-token", "x-operator-id": "test-suite", ...(options.headers || {}) },
  });
}

test("air-gap node lifecycle is authorized, auditable, and persistent", async (t) => {
  const stateDir = await mkdtemp(join(tmpdir(), "prexus-control-plane-"));
  const first = await start(stateDir);
  t.after(() => first.server.close());

  const rejected = await fetch(`${first.baseUrl}/v1/nodes`);
  assert.equal(rejected.status, 401);

  const nodes = await request(first.baseUrl, "/v1/nodes");
  assert.equal(nodes.status, 200);
  assert.equal((await nodes.json()).nodes.length, 3);

  const ingestion = await request(first.baseUrl, "/v1/nodes/meteorium-ingest/runs", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ command: "register-dataset", input: { dataset: { id: "fixture-1", sha256: "a".repeat(64), classification: "restricted" } } }),
  });
  assert.equal(ingestion.status, 201);

  const simulation = await request(first.baseUrl, "/v1/nodes/meteorium-score/runs", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ command: "offline-simulate", input: { asset: { id: "asset-1", value_usd: 5000000 }, scenario: "baseline" } }),
  });
  assert.equal(simulation.status, 201);
  const simulationRun = (await simulation.json()).run;
  assert.equal(simulationRun.output.data_mode, "offline-input-only");
  assert.equal(simulationRun.output.model_status, "demonstration-only");

  const ledger = await request(first.baseUrl, "/v1/nodes/audit-ledger/runs", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ command: "verify-ledger", input: {} }),
  });
  assert.equal(ledger.status, 201);
  assert.equal((await ledger.json()).run.output.valid, true);

  const detail = await request(first.baseUrl, `/v1/runs/${simulationRun.id}`);
  assert.equal(detail.status, 200);
  assert.equal((await detail.json()).run.id, simulationRun.id);
});

import assert from "node:assert/strict";
import test from "node:test";
import { call, run, start, tmp } from "./testkit.mjs";
import { createApp } from "./server.mjs";

test("air-gap node lifecycle is authorized, auditable, and persistent", async (t) => {
  const app = await start();
  t.after(() => app.close());
  assert.equal((await call(app, "/v1/nodes", { as: null })).status, 401);
  const nodes = await call(app, "/v1/nodes");
  assert.equal(nodes.status, 200);
  const body = await nodes.json();
  assert.equal(body.nodes.length, 5);
  assert.deepEqual(body.principal, { id: "alice", role: "operator" });

  const ing = await run(app, "meteorium-ingest", "register-dataset", { dataset: { id: "fixture-1", sha256: "a".repeat(64), classification: "restricted" } });
  assert.equal(ing.status, 201);
  const sim = await run(app, "meteorium-score", "offline-simulate", { asset: { id: "asset-1", value_usd: 5000000 }, scenario: "baseline" });
  assert.equal(sim.status, 201);
  const simRun = (await sim.json()).run;
  assert.equal(simRun.output.model_status, "demonstration-only");
  const led = await run(app, "audit-ledger", "verify-ledger", {});
  assert.equal((await led.json()).run.output.valid, true);
  assert.equal((await (await call(app, `/v1/runs/${simRun.id}`)).json()).run.id, simRun.id);
});

test("state and ledger persist across restarts", async () => {
  const a = await start();
  await run(a, "meteorium-ingest", "register-dataset", { dataset: { id: "d1", sha256: "b".repeat(64), classification: "internal" } });
  const seq = a.ledger.seq;
  await a.close();
  const b = await start({ stateDir: a.stateDir });
  assert.equal(b.store.state.datasets.length, 1);
  assert.ok(b.ledger.seq > seq, "restart appends a controlplane.start event");
  assert.equal((await b.ledger.verify()).valid, true);
  await b.close();
});

test("production refuses weak configuration", async () => {
  const dir = await tmp();
  await assert.rejects(createApp({ stateDir: dir, production: true, operatorToken: "x".repeat(40) }), /shared operator token/);
  await assert.rejects(createApp({ stateDir: dir, production: true, operatorToken: "x".repeat(40), allowSharedToken: true }), /LEDGER_KEY/);
  await assert.rejects(createApp({ stateDir: dir }), /PREXUS_OPERATORS_FILE/);
});

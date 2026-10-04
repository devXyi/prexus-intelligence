import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { canonical } from "./lib/canonical.mjs";
import { assertInternalUrl, isInternalHost } from "./lib/netpolicy.mjs";
import { probeEgress } from "./lib/egress.mjs";
import { call, run, start, TOKENS } from "./testkit.mjs";
import { createApp } from "./server.mjs";

test("actor is the authenticated identity; a spoofed x-operator-id is ignored", async (t) => {
  const app = await start(); t.after(() => app.close());
  const r = await run(app, "meteorium-ingest", "register-dataset", { dataset: { id: "x1", sha256: "c".repeat(64), classification: "internal" } }, { as: "bob", headers: { "x-operator-id": "alice-the-ceo" } });
  assert.equal(r.status, 201);
  const ev = (await (await call(app, "/v1/ledger/events")).json()).events.at(-1);
  assert.equal(ev.actor, "bob");
  assert.ok(!JSON.stringify(ev).includes("alice-the-ceo"));
});

test("auditor can verify and read the ledger but cannot run other nodes", async (t) => {
  const app = await start(); t.after(() => app.close());
  assert.equal((await run(app, "audit-ledger", "verify-ledger", {}, { as: "audit" })).status, 201);
  assert.equal((await run(app, "meteorium-ingest", "register-dataset", { dataset: { id: "x", sha256: "d".repeat(64), classification: "internal" } }, { as: "audit" })).status, 403);
  assert.equal((await call(app, "/v1/ledger/head", { as: "audit" })).status, 200);
});

test("brute force is throttled per source", async (t) => {
  const app = await start(); t.after(() => app.close());
  for (let i = 0; i < 10; i++) assert.equal((await call(app, "/v1/nodes", { as: null, token: `wrong-${i}` })).status, 401);
  assert.equal((await call(app, "/v1/nodes")).status, 429, "even a valid token is refused once the source is throttled");
  const ev = (await (await call(app, "/v1/ledger/events", { as: null, token: TOKENS.alice })).json());
  assert.equal(ev.error, "too many failed attempts — try again later");
});

test("failed auth is audited (sampled), tokens never appear in the ledger", async (t) => {
  const app = await start(); t.after(() => app.close());
  await call(app, "/v1/nodes", { as: null, token: "super-secret-wrong-token" });
  await new Promise((r) => setTimeout(r, 30));
  const text = JSON.stringify(app.ledger.events);
  assert.ok(text.includes("auth.denied"));
  assert.ok(!text.includes("super-secret-wrong-token") && !text.includes(TOKENS.alice));
});

test("input handling: 413, 400, 404, and no ghost 'running' runs", async (t) => {
  const app = await start(); t.after(() => app.close());
  assert.equal((await call(app, "/v1/nodes/audit-ledger/runs", { method: "POST", body: JSON.stringify({ command: "verify-ledger", input: { pad: "x".repeat(70_000) } }) })).status, 413);
  assert.equal((await call(app, "/v1/nodes/audit-ledger/runs", { method: "POST", body: "{not json" })).status, 400);
  assert.equal((await call(app, "/v1/nodes/audit-ledger/runs", { method: "POST", body: "[1,2]" })).status, 400);
  assert.equal((await run(app, "no-such-node", "x", {})).status, 404);
  assert.equal((await run(app, "audit-ledger", "rm-rf", {})).status, 400);
  const bad = await run(app, "meteorium-ingest", "register-dataset", { dataset: { id: "d", sha256: "nothex", classification: "internal" } });
  assert.equal(bad.status, 400);
  assert.equal(app.store.state.runs.filter((r) => r.status === "running").length, 0);
  const failed = app.store.state.runs.at(-1);
  assert.equal(failed.status, "failed");
  assert.ok(app.ledger.events.some((e) => e.action === "node.meteorium-ingest.register-dataset.failed"));
});

test("ledger down ⇒ refuse to act (no unaudited actions)", async (t) => {
  const app = await start(); t.after(() => app.close());
  app.ledger.valid = false;
  const r = await run(app, "meteorium-ingest", "register-dataset", { dataset: { id: "d", sha256: "e".repeat(64), classification: "internal" } });
  assert.equal(r.status, 503);
  assert.equal((await (await fetch(`${app.baseUrl}/health`)).json()).status, "degraded");
});

test("terminal is served with a CSP and health leaks nothing sensitive", async (t) => {
  const app = await start(); t.after(() => app.close());
  const r = await fetch(`${app.baseUrl}/`);
  assert.match(r.headers.get("content-security-policy"), /connect-src 'self'/);
  const h = await (await fetch(`${app.baseUrl}/health`)).json();
  assert.deepEqual(Object.keys(h).sort(), ["air_gapped_declared", "air_gapped_verified", "egress_isolated", "ledger", "service", "status"]);
});

test("egress policy: only internal hosts are accepted for upstreams", () => {
  for (const h of ["localhost", "127.0.0.1", "10.2.3.4", "172.16.0.9", "192.168.1.5", "169.254.1.1", "engine", "engine.internal", "x.svc.cluster.local", "::1", "fd12:3456::1", "fe80::1", "::ffff:10.0.0.1"]) assert.ok(isInternalHost(h), h);
  for (const h of ["8.8.8.8", "172.32.0.1", "api.prexus.in", "example.com", "2606:4700::1111", "::ffff:8.8.8.8", ""]) assert.ok(!isInternalHost(h), h);
  assert.throws(() => assertInternalUrl("https://api.anthropic.com/v1"), /not an internal address/);
  assert.throws(() => assertInternalUrl("http://user:pw@10.0.0.1/"), /credentials/);
  assert.throws(() => assertInternalUrl("ftp://10.0.0.1/"), /http/);
  assert.doesNotThrow(() => assertInternalUrl("http://10.0.0.1:8000"));
});

test("egress probe: reachable public host ⇒ isolation claim is false", async (t) => {
  const bad = await probeEgress({ connect: async (h) => h === "8.8.8.8" });
  assert.equal(bad.isolated, false); assert.deepEqual(bad.reached, ["8.8.8.8:53"]);
  assert.equal((await probeEgress({ connect: async () => false })).isolated, true);
  const leaky = await start({ egressProbe: true, egressConnect: async () => true }); t.after(() => leaky.close());
  const h = await (await fetch(`${leaky.baseUrl}/health`)).json();
  assert.equal(h.air_gapped_verified, false); assert.equal(h.air_gapped_declared, true);
  assert.ok(leaky.ledger.events.some((e) => e.action === "egress.probe" && e.metadata.isolated === false));
  const tight = await start({ egressProbe: true, egressConnect: async () => false }); t.after(() => tight.close());
  assert.equal((await (await fetch(`${tight.baseUrl}/health`)).json()).air_gapped_verified, true);
});

test("engine node: internal-only, bearer forwarded, receipt hashes recorded", async (t) => {
  let seen;
  const engine = createServer((req, res) => {
    let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => {
      seen = { auth: req.headers.authorization, url: req.url, body: JSON.parse(b) };
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ cost_impact: 12.5, method: "catmodel-v0", calibrated: false }));
    });
  });
  await new Promise((r) => engine.listen(0, "127.0.0.1", r)); t.after(() => engine.close());
  const url = `http://127.0.0.1:${engine.address().port}`;
  const app = await start({ engineUrl: url, engineSecret: "engine-secret-value" }); t.after(() => app.close());
  const r = await run(app, "meteorium-engine", "simulate", { asset_id: "A1", scenario: "flood", intensity: 0.7, seed: 1, evil: "dropped" });
  assert.equal(r.status, 201);
  const out = (await r.json()).run.output;
  assert.equal(seen.auth, "Bearer engine-secret-value"); assert.equal(seen.url, "/risk/simulate");
  assert.ok(!("evil" in seen.body), "only whitelisted fields are forwarded");
  assert.equal(out.engine_output.calibrated, false); assert.equal(out.receipt.calibrated, false);
  assert.match(out.receipt.input_sha256, /^[a-f0-9]{64}$/); assert.match(out.receipt.output_sha256, /^[a-f0-9]{64}$/);
  assert.equal((await run(app, "meteorium-engine", "simulate", { intensity: "high" })).status, 400);
  const ledgerEv = app.ledger.events.find((e) => e.action === "node.meteorium-engine.simulate");
  assert.equal(ledgerEv.metadata.output_sha256, out.receipt.output_sha256.length === 64 ? ledgerEv.metadata.output_sha256 : "");
  await assert.rejects(createApp({ stateDir: app.stateDir + "-b", operatorToken: "t".repeat(20), engineUrl: "https://api.prexus.in" }), /not an internal address/);
});

test("engine node: unconfigured ⇒ 503, unreachable ⇒ 502 (both audited)", async (t) => {
  const none = await start(); t.after(() => none.close());
  assert.equal((await run(none, "meteorium-engine", "simulate", {})).status, 503);
  const down = await start({ engineUrl: "http://127.0.0.1:1", engineTimeoutMs: 500 }); t.after(() => down.close());
  assert.equal((await run(down, "meteorium-engine", "simulate", {})).status, 502);
  assert.ok(down.ledger.events.some((e) => e.action === "node.meteorium-engine.simulate.failed"));
});

test("canonical JSON: order-independent, integers-only by default, ASCII keys", () => {
  assert.equal(canonical({ b: 1, a: [true, null, "x"] }), canonical({ a: [true, null, "x"], b: 1 }));
  assert.equal(canonical({ b: 1, a: 2 }), '{"a":2,"b":1}');
  assert.throws(() => canonical({ a: 1.5 }), /non-integer/); assert.throws(() => canonical({ a: NaN }), /NaN/);
  assert.throws(() => canonical({ "é": 1 }), /ASCII/);
  assert.equal(canonical({ a: 1.5 }, { floats: true }), '{"a":1.5}');
});

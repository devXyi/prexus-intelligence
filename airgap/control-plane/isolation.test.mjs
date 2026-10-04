// Runs only inside a network namespace with no route out (see ../tools/netns-test.sh).
// Passing here is evidence — not a claim — that the control plane works with zero egress.
import assert from "node:assert/strict";
import net from "node:net";
import test from "node:test";
import { probeEgress } from "./lib/egress.mjs";
import { call, run, start } from "./testkit.mjs";

const inNetns = process.env.PREXUS_EXPECT_NETNS === "1";

test("no route to the outside world (real sockets, no stubs)", { skip: !inNetns && "set PREXUS_EXPECT_NETNS=1 (see tools/netns-test.sh)" }, async () => {
  const err = await new Promise((resolve) => { const s = net.connect({ host: "93.184.216.34", port: 80 }); s.once("error", resolve); s.once("connect", () => resolve(null)); s.setTimeout(2000, () => resolve(new Error("timeout"))); });
  assert.ok(err && /ENETUNREACH|EHOSTUNREACH|timeout/.test(err.code || err.message), `expected unreachable, got ${err && (err.code || err.message)}`);
  const p = await probeEgress({ timeoutMs: 800 });
  assert.equal(p.isolated, true, `leaked: ${p.reached}`);
});

test("full operator workflow works with zero egress", { skip: !inNetns && "netns only" }, async (t) => {
  const app = await start({ egressProbe: true }); t.after(() => app.close());
  const h = await (await fetch(`${app.baseUrl}/health`)).json();
  assert.equal(h.air_gapped_verified, true);
  assert.equal((await run(app, "meteorium-score", "offline-simulate", { asset: { id: "a", value_usd: 1e6 } })).status, 201);
  assert.equal((await run(app, "audit-ledger", "verify-ledger", {})).status, 201);
  assert.equal((await call(app, "/v1/ledger/head")).status, 200);
});

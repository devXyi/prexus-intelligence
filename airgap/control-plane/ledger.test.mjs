import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { appendFile, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { Ledger, Signer, parseNdjson, verifyEventChain, verifySignedHead } from "./lib/ledger.mjs";
import { tmp } from "./testkit.mjs";

async function fresh(n = 5) {
  const dir = await tmp("prexus-ledger-");
  const signer = await Signer.load({ autogen: true, stateDir: dir });
  const l = await new Ledger({ dir, signer }).open();
  for (let i = 1; i <= n; i++) await l.append({ actor: "alice", action: `act.${i}`, resource: `r${i}`, metadata: { i } });
  return { dir, signer, l };
}
const lines = async (dir) => (await readFile(join(dir, "ledger.ndjson"), "utf8")).split("\n").filter(Boolean);
const reopen = async (dir, signer) => new Ledger({ dir, signer }).open();

test("chain verifies and survives restart", async () => {
  const { dir, signer, l } = await fresh(5);
  assert.equal((await l.verify()).valid, true);
  await l.close();
  const r = await reopen(dir, signer);
  assert.equal(r.valid, true); assert.equal(r.seq, 5);
  await r.append({ actor: "a", action: "more", resource: "x" });
  assert.equal((await r.verify()).head_sequence, 6);
  await r.close();
});

test("tampering is detected: modified content, deleted middle, reordered", async () => {
  for (const [name, mutate, expect] of [
    ["modified", (ls) => { const e = JSON.parse(ls[2]); e.actor = "mallory"; ls[2] = JSON.stringify(e); return ls; }, /modified|hash/],
    ["deleted", (ls) => { ls.splice(2, 1); return ls; }, /sequence|previous_hash/],
    ["reordered", (ls) => { [ls[1], ls[2]] = [ls[2], ls[1]]; return ls; }, /sequence|previous_hash/],
  ]) {
    const { dir, signer, l } = await fresh(5);
    await l.close();
    await writeFile(join(dir, "ledger.ndjson"), mutate(await lines(dir)).join("\n") + "\n");
    const r = await reopen(dir, signer);
    assert.equal(r.valid, false, name);
    assert.match(r.failure.reason, expect, name);
    await assert.rejects(r.append({ actor: "a", action: "x", resource: "y" }), /integrity/);
    await r.close();
  }
});

test("tampering while running is caught by verify() (re-reads disk)", async () => {
  const { dir, l } = await fresh(4);
  const ls = await lines(dir); const e = JSON.parse(ls[1]); e.resource = "forged"; ls[1] = JSON.stringify(e);
  await writeFile(join(dir, "ledger.ndjson"), ls.join("\n") + "\n");
  const v = await l.verify();
  assert.equal(v.valid, false); await l.close();
});

test("truncation is caught by the signed anchor; so is replacement with a shorter valid chain", async () => {
  const { dir, signer, l } = await fresh(6);
  await l.close();
  await writeFile(join(dir, "ledger.ndjson"), (await lines(dir)).slice(0, 3).join("\n") + "\n");   // still a valid chain
  assert.equal(verifyEventChain(parseNdjson(await readFile(join(dir, "ledger.ndjson"), "utf8"))).valid, true);
  const r = await reopen(dir, signer);
  assert.equal(r.valid, false);
  assert.match(r.failure.reason, /truncated or replaced/);
  await r.close();
});

test("rewritten history that keeps the length is caught by the anchor", async () => {
  const { dir, signer, l } = await fresh(4); await l.close();
  // Rebuild a self-consistent but different chain of the same length.
  const forged = await (async () => { const d2 = await tmp(); const s2 = await Signer.load({ autogen: true, stateDir: d2 }); const f = await new Ledger({ dir: d2, signer: s2 }).open(); for (let i = 1; i <= 4; i++) await f.append({ actor: "mallory", action: `x${i}`, resource: "r" }); await f.close(); return d2; })();
  await writeFile(join(dir, "ledger.ndjson"), await readFile(join(forged, "ledger.ndjson")));
  const r = await reopen(dir, signer);
  assert.equal(r.valid, false); assert.match(r.failure.reason, /diverges from its signed anchor/); await r.close();
});

test("torn write (crash mid-append) is recovered and recorded", async () => {
  const { dir, signer, l } = await fresh(3); await l.close();
  await appendFile(join(dir, "ledger.ndjson"), '{"v":2,"seq":4,"id":"half');
  const r = await reopen(dir, signer);
  assert.equal(r.valid, true);
  assert.equal(r.events.at(-1).action, "ledger.recovered"); assert.ok(r.events.at(-1).metadata.discarded_bytes > 0);
  assert.equal((await r.verify()).valid, true); await r.close();
});

test("200 concurrent appends: nothing lost, order strict (v1 lost events under concurrency)", async () => {
  const { l } = await fresh(0);
  await Promise.all(Array.from({ length: 200 }, (_, i) => l.append({ actor: "a", action: "c", resource: String(i) })));
  assert.equal(l.seq, 200);
  const v = await l.verify();
  assert.equal(v.valid, true); assert.equal(v.checked_events, 200);
  assert.deepEqual(l.events.map((e) => e.seq), Array.from({ length: 200 }, (_, i) => i + 1));
  await l.close();
});

test("signed head verifies and rejects edits or a foreign key", async () => {
  const { signer, l } = await fresh(2);
  const head = l.signedHead();
  assert.equal(verifySignedHead(head, signer.publicKeyPem), true);
  assert.equal(verifySignedHead({ ...head, sequence: head.sequence + 1 }, signer.publicKeyPem), false);
  const other = await Signer.load({ autogen: true, stateDir: await tmp() });
  assert.equal(verifySignedHead(head, other.publicKeyPem), false); await l.close();
});

test("offline CLI verifier: valid / tampered / anchor mismatch", async () => {
  const { dir, signer, l } = await fresh(5); await l.close();
  const cli = (...a) => spawnSync("node", ["tools/verify-ledger.mjs", ...a], { encoding: "utf8" });
  const pub = join(dir, "pub.pem"); await writeFile(pub, signer.publicKeyPem);
  const ok = cli(join(dir, "ledger.ndjson"), "--anchor", join(dir, "anchors", "head.json"), "--pubkey", pub);
  assert.equal(ok.status, 0, ok.stdout); assert.equal(JSON.parse(ok.stdout).valid, true);
  const ls = await lines(dir); const e = JSON.parse(ls[0]); e.actor = "x"; ls[0] = JSON.stringify(e);
  await writeFile(join(dir, "bad.ndjson"), ls.join("\n") + "\n");
  assert.equal(cli(join(dir, "bad.ndjson")).status, 1);
  await writeFile(join(dir, "short.ndjson"), (await lines(dir)).slice(0, 2).join("\n") + "\n");
  const short = cli(join(dir, "short.ndjson"), "--anchor", join(dir, "anchors", "head.json"), "--pubkey", pub);
  assert.equal(short.status, 1); assert.match(short.stdout, /truncated or replaced/);
});

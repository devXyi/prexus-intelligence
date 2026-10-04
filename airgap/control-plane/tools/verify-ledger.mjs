#!/usr/bin/env node
// Offline ledger verifier — run it on a DIFFERENT machine from the operator media.
//   node tools/verify-ledger.mjs ledger.ndjson [--anchor head.json --pubkey key.pem]
// Exit 0 = chain valid (and consistent with the anchor if given); 1 = invalid; 2 = usage.
import { readFile } from "node:fs/promises";
import { parseNdjson, verifyEventChain, verifySignedHead } from "../lib/ledger.mjs";

const args = process.argv.slice(2);
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
const file = args.find((a) => !a.startsWith("--") && a !== opt("--anchor") && a !== opt("--pubkey"));
if (!file) { console.error("usage: verify-ledger.mjs <ledger.ndjson> [--anchor head.json --pubkey key.pem]"); process.exit(2); }
const fail = (m) => { console.log(JSON.stringify({ valid: false, reason: m })); process.exit(1); };
let events;
try { events = parseNdjson(await readFile(file, "utf8")); } catch (e) { fail(e.message); }
const v = verifyEventChain(events);
if (!v.valid) fail(`${v.reason} (event seq ${v.failed_seq})`);
if (opt("--anchor")) {
  if (!opt("--pubkey")) { console.error("--anchor requires --pubkey"); process.exit(2); }
  const anchor = JSON.parse(await readFile(opt("--anchor"), "utf8"));
  if (!verifySignedHead(anchor, await readFile(opt("--pubkey"), "utf8"))) fail("anchor signature invalid");
  if (anchor.sequence > events.length) fail(`ledger has ${events.length} events, anchor attests ${anchor.sequence} (truncated or replaced)`);
  if (anchor.sequence > 0 && events[anchor.sequence - 1].hash !== anchor.head_hash) fail("ledger diverges from anchor (history rewritten)");
  v.anchored_at_sequence = anchor.sequence;
}
console.log(JSON.stringify(v));

// Append-only, hash-chained, Ed25519-anchored audit ledger (spec: docs/LEDGER_SPEC.md).
//
// v1 kept the whole ledger inside one JSON file that was rewritten on every request, hashed
// with insertion-order JSON.stringify, and had no defence against wholesale replacement.
// v2: NDJSON append + fsync, canonical-JSON hashing, monotone sequence numbers, torn-write
// recovery, tamper detection re-read from disk, and a signed head that can be exported to
// operator media so replacing the whole log is detectable too.
import { createHash, createPrivateKey, createPublicKey, generateKeyPairSync, randomUUID, sign as edSign, verify as edVerify } from "node:crypto";
import { chmod, mkdir, open, readFile, rename, truncate, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { canonical } from "./canonical.mjs";
import { Mutex } from "./mutex.mjs";

export const GENESIS = "GENESIS";
const sha256 = (s) => createHash("sha256").update(s, "utf8").digest("hex");

export class Signer {
  constructor(privateKey) {
    this.privateKey = privateKey;
    this.publicKey = createPublicKey(privateKey);
    this.publicKeyPem = this.publicKey.export({ type: "spki", format: "pem" });
    this.keyId = createHash("sha256").update(this.publicKey.export({ type: "spki", format: "der" })).digest("hex").slice(0, 16);
  }
  static async load({ keyFile, autogen, stateDir }) {
    if (keyFile) return new Signer(createPrivateKey(await readFile(keyFile, "utf8")));
    if (!autogen) throw new Error("ledger signing key required: set PREXUS_LEDGER_KEY_FILE (production forbids auto-generation)");
    const file = join(stateDir, "ledger-signing-key.pem");
    try {
      return new Signer(createPrivateKey(await readFile(file, "utf8")));
    } catch (e) {
      if (e.code !== "ENOENT") throw e;
    }
    const { privateKey } = generateKeyPairSync("ed25519");
    await writeFile(file, privateKey.export({ type: "pkcs8", format: "pem" }), { mode: 0o600 });
    return new Signer(privateKey);
  }
  sign(text) { return edSign(null, Buffer.from(text, "utf8"), this.privateKey).toString("base64"); }
}

const headMessage = (h) => canonical({ sequence: h.sequence, head_hash: h.head_hash, signed_at: h.signed_at, key_id: h.key_id });

export function verifySignedHead(head, publicKeyPem) {
  try {
    return edVerify(null, Buffer.from(headMessage(head), "utf8"), createPublicKey(publicKeyPem), Buffer.from(head.signature, "base64"));
  } catch { return false; }
}

/** Pure chain verification (also used by tools/verify-ledger.mjs). */
export function verifyEventChain(events) {
  let previous = GENESIS;
  let seq = 0;
  for (const event of events) {
    const { hash, ...unsigned } = event;
    seq += 1;
    if (event.v !== 2) return { valid: false, checked_events: events.length, failed_seq: event.seq ?? seq, reason: "unsupported event version" };
    if (event.seq !== seq) return { valid: false, checked_events: events.length, failed_seq: event.seq ?? seq, reason: "sequence gap or reorder" };
    if (event.previous_hash !== previous) return { valid: false, checked_events: events.length, failed_seq: event.seq, reason: "previous_hash mismatch (event removed or reordered)" };
    if (hash !== sha256(canonical(unsigned))) return { valid: false, checked_events: events.length, failed_seq: event.seq, reason: "event content does not match its hash (modified)" };
    previous = hash;
  }
  return { valid: true, checked_events: events.length, head_hash: previous, head_sequence: seq };
}

export function parseNdjson(text) {
  return text.split("\n").filter((l) => l.length).map((l, i) => {
    try { return JSON.parse(l); } catch { throw Object.assign(new Error(`ledger line ${i + 1} is not valid JSON`), { line: i + 1 }); }
  });
}

export class Ledger {
  constructor({ dir, signer = null }) {
    this.dir = dir; this.file = join(dir, "ledger.ndjson"); this.signer = signer;
    this.events = []; this.headHash = GENESIS; this.seq = 0;
    this.valid = true; this.failure = null; this.fh = null; this.lock = new Mutex();
  }

  async open() {
    await mkdir(join(this.dir, "anchors"), { recursive: true, mode: 0o700 });
    let text = "";
    try { text = await readFile(this.file, "utf8"); } catch (e) { if (e.code !== "ENOENT") throw e; }
    let discarded = 0;
    if (text && !text.endsWith("\n")) {            // crash mid-append: drop the torn tail, keep the chain
      const keep = text.lastIndexOf("\n") + 1;
      discarded = Buffer.byteLength(text.slice(keep));
      text = text.slice(0, keep);
      await truncate(this.file, Buffer.byteLength(text));
    }
    try {
      this.events = parseNdjson(text);
      const v = verifyEventChain(this.events);
      if (!v.valid) { this.valid = false; this.failure = v; }
    } catch (e) {
      this.valid = false; this.failure = { valid: false, reason: e.message, failed_line: e.line };
    }
    if (this.valid && this.signer) await this.#checkAnchor();
    if (this.valid && this.events.length) { const last = this.events.at(-1); this.seq = last.seq; this.headHash = last.hash; }
    this.fh = await open(this.file, "a", 0o600);
    if (this.valid && discarded) {
      await this.append({ actor: "system", action: "ledger.recovered", resource: "ledger", metadata: { discarded_bytes: discarded } });
    }
    return this;
  }

  /** A signed head written after every append: shorter/replaced logs no longer match it. */
  async #checkAnchor() {
    let anchor;
    try { anchor = JSON.parse(await readFile(join(this.dir, "anchors", "head.json"), "utf8")); }
    catch (e) {
      if (e.code === "ENOENT") return;
      this.valid = false; this.failure = { valid: false, reason: "signed anchor is unreadable" }; return;
    }
    if (!verifySignedHead(anchor, this.signer.publicKeyPem)) {
      this.valid = false; this.failure = { valid: false, reason: "signed anchor is invalid (tampered, or signed by a different key)" };
    } else if (anchor.sequence > this.events.length) {
      this.valid = false; this.failure = { valid: false, reason: `ledger has ${this.events.length} events but its signed anchor attests ${anchor.sequence} (truncated or replaced)` };
    } else if (anchor.sequence > 0 && this.events[anchor.sequence - 1].hash !== anchor.head_hash) {
      this.valid = false; this.failure = { valid: false, reason: "ledger diverges from its signed anchor (history rewritten)" };
    }
  }

  async close() { if (this.fh) { await this.fh.close(); this.fh = null; } }

  append({ actor, action, resource, metadata }) {
    return this.lock.run(async () => {
      if (!this.valid) throw Object.assign(new Error("ledger integrity failure — refusing to write"), { status: 503 });
      const event = {
        v: 2, seq: this.seq + 1, id: randomUUID(), at: new Date().toISOString(),
        actor, action, resource, metadata: metadata ?? {}, previous_hash: this.headHash,
      };
      event.hash = sha256(canonical(event));
      await this.fh.write(`${canonical(event)}\n`);
      await this.fh.sync();                        // durable before we acknowledge
      this.events.push(event); this.seq = event.seq; this.headHash = event.hash;
      await this.#writeAnchor();
      return event;
    });
  }

  head() { return { sequence: this.seq, head_hash: this.headHash }; }

  signedHead() {
    if (!this.signer) return { ...this.head(), signed: false };
    const h = { sequence: this.seq, head_hash: this.headHash, signed_at: new Date().toISOString(), key_id: this.signer.keyId };
    return { ...h, alg: "Ed25519", signature: this.signer.sign(headMessage(h)), public_key: this.signer.publicKeyPem, signed: true };
  }

  async #writeAnchor() {
    if (!this.signer) return;
    const file = join(this.dir, "anchors", "head.json");
    const tmp = `${file}.${process.pid}.tmp`;
    await writeFile(tmp, `${JSON.stringify(this.signedHead(), null, 2)}\n`, { mode: 0o600 });
    await rename(tmp, file);
  }

  /** Re-reads the file from disk, so tampering after startup is detected too. */
  async verify() {
    if (!this.valid) return this.failure;
    let events;
    try { events = parseNdjson(await readFile(this.file, "utf8")); }
    catch (e) { return { valid: false, reason: e.message }; }
    const v = verifyEventChain(events);
    if (v.valid && (v.head_hash !== this.headHash || v.head_sequence !== this.seq)) {
      return { valid: false, checked_events: events.length, reason: "on-disk ledger diverges from the running process (replaced or truncated)" };
    }
    return v;
  }

  page(after = 0, limit = 100) {
    const n = Math.min(Math.max(Number(limit) || 100, 1), 500);
    return this.events.filter((e) => e.seq > after).slice(0, n);
  }
}

export async function ensureFileMode(file) { try { await chmod(file, 0o600); } catch { /* best effort */ } }

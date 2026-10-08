import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { readFile } from "node:fs/promises";

export const ROLES = Object.freeze({ operator: "operator", auditor: "auditor" });
const ID_RE = /^[a-z0-9][a-z0-9._-]{1,63}$/;

export const hashToken = (token) => createHash("sha256").update(String(token), "utf8").digest("hex");
export const mintToken = () => `prx_${randomBytes(32).toString("base64url")}`;

export class OperatorRegistry {
  /** entries: [{ id, role, token_sha256 }] — tokens are stored only as SHA-256 (they are 256-bit random). */
  constructor(entries) {
    const seen = new Set();
    this.entries = entries.map((e) => {
      if (!ID_RE.test(e.id || "")) throw new Error(`invalid operator id: ${JSON.stringify(e.id)}`);
      if (!Object.values(ROLES).includes(e.role)) throw new Error(`operator ${e.id}: role must be operator|auditor`);
      if (!/^[a-f0-9]{64}$/.test(e.token_sha256 || "")) throw new Error(`operator ${e.id}: token_sha256 must be 64 hex chars`);
      if (seen.has(e.id)) throw new Error(`duplicate operator id: ${e.id}`);
      seen.add(e.id);
      return { id: e.id, role: e.role, digest: Buffer.from(e.token_sha256, "hex") };
    });
    if (this.entries.length === 0) throw new Error("no operators configured");
  }

  static async load({ operatorsFile, legacyToken }) {
    const entries = [];
    if (operatorsFile) {
      const parsed = JSON.parse(await readFile(operatorsFile, "utf8"));
      entries.push(...(Array.isArray(parsed) ? parsed : parsed.operators || []));
    }
    if (legacyToken) {
      // A single shared secret cannot attribute actions to a person; the ledger records that honestly.
      entries.push({ id: "shared-operator", role: ROLES.operator, token_sha256: hashToken(legacyToken) });
    }
    const reg = new OperatorRegistry(entries);
    reg.usesSharedToken = Boolean(legacyToken);
    return reg;
  }

  /** Constant-time w.r.t. which operator matched: every entry is always compared. */
  authenticate(token) {
    if (!token) return null;
    const digest = Buffer.from(hashToken(token), "hex");
    let match = null;
    for (const e of this.entries) {
      if (timingSafeEqual(digest, e.digest) && !match) match = e;
    }
    return match ? { id: match.id, role: match.role } : null;
  }
}

/** Per-source brute-force throttle. */
export class AuthThrottle {
  constructor({ max = 10, windowMs = 5 * 60_000 } = {}) { this.max = max; this.windowMs = windowMs; this.hits = new Map(); }
  #prune(key, now) {
    const list = (this.hits.get(key) || []).filter((t) => now - t < this.windowMs);
    if (list.length) this.hits.set(key, list); else this.hits.delete(key);
    return list;
  }
  blocked(key, now = Date.now()) { return this.#prune(key, now).length >= this.max; }
  fail(key, now = Date.now()) { const l = this.#prune(key, now); l.push(now); this.hits.set(key, l); }
  ok(key) { this.hits.delete(key); }
}

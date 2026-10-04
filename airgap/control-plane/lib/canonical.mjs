// Canonical JSON used for every hash/signature (spec: docs/LEDGER_SPEC.md).
//  • keys sorted, ASCII-only keys, no whitespace, `undefined` dropped
//  • numbers: safe INTEGERS only by default — float formatting differs between languages
//    (JS `1` vs Python `1.0`), so hashed/signed structures carry decimals as strings.
//    `{ floats: true }` is for local-only digests (e.g. run output hashes).
export function canonical(value, opts = {}) {
  const floats = Boolean(opts.floats);
  const walk = (v) => {
    if (v === null || typeof v === "boolean") return JSON.stringify(v);
    if (typeof v === "number") {
      if (!Number.isFinite(v)) throw new TypeError("canonical JSON forbids NaN/Infinity");
      if (!Number.isInteger(v) && !floats) throw new TypeError("canonical JSON forbids non-integer numbers; encode decimals as strings");
      if (Number.isInteger(v) && !Number.isSafeInteger(v)) throw new TypeError("integer outside the safe range");
      return JSON.stringify(v);
    }
    if (typeof v === "string") return JSON.stringify(v);
    if (Array.isArray(v)) return `[${v.map((x) => walk(x === undefined ? null : x)).join(",")}]`;
    if (typeof v === "object") {
      const keys = Object.keys(v).filter((k) => v[k] !== undefined).sort();
      for (const k of keys) if (!/^[\x20-\x7e]*$/.test(k)) throw new TypeError("canonical JSON keys must be ASCII");
      return `{${keys.map((k) => `${JSON.stringify(k)}:${walk(v[k])}`).join(",")}}`;
    }
    throw new TypeError(`cannot canonicalise ${typeof v}`);
  };
  return walk(value);
}

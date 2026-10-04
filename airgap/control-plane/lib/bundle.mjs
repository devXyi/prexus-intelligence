// Signed import bundles (spec: docs/AIRGAP_RUNBOOK.md §Bundles). Everything that enters the
// enclave is a directory { manifest.json, manifest.sig, files/** } signed offline with Ed25519.
import { createHash, createPublicKey, verify as edVerify } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, readdir, realpath, stat } from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";
import { canonical } from "./canonical.mjs";

export const BUNDLE_FORMAT = "prexus-bundle/1";
const CLASSES = ["internal", "restricted"];

export const keyIdOf = (publicKeyPem) =>
  createHash("sha256").update(createPublicKey(publicKeyPem).export({ type: "spki", format: "der" })).digest("hex").slice(0, 16);

export class BundleError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

export async function loadTrustedKeys(dir) {
  const keys = new Map();
  if (!dir) return keys;
  for (const f of await readdir(dir)) {
    if (!f.endsWith(".pem")) continue;
    const pem = await readFile(join(dir, f), "utf8");
    if (!pem.includes("BEGIN PUBLIC KEY")) continue;     // never treat a private key (or junk) as a trust anchor
    keys.set(keyIdOf(pem), pem);
  }
  return keys;
}

export function sha256File(path) {
  return new Promise((res, rej) => {
    const h = createHash("sha256");
    createReadStream(path).on("data", (c) => h.update(c)).on("error", rej).on("end", () => res(h.digest("hex")));
  });
}

/** Verify signature + schema of a manifest. Throws BundleError. */
export function verifyManifest(manifest, signatureB64, trustedKeys, lastVersions = {}) {
  if (!manifest || manifest.format !== BUNDLE_FORMAT) throw new BundleError("unsupported bundle format");
  if (!/^[a-z0-9][a-z0-9._-]{2,63}$/.test(manifest.name || "")) throw new BundleError("invalid bundle name");
  if (!Number.isSafeInteger(manifest.version) || manifest.version < 1) throw new BundleError("bundle version must be a positive integer");
  const pem = trustedKeys.get(manifest.signer_key_id);
  if (!pem) throw new BundleError("bundle is signed by an untrusted key", 403);
  let ok = false;
  try { ok = edVerify(null, Buffer.from(canonical(manifest), "utf8"), createPublicKey(pem), Buffer.from(signatureB64.trim(), "base64")); } catch { ok = false; }
  if (!ok) throw new BundleError("bundle signature is invalid", 403);
  const last = lastVersions[manifest.name];
  if (last !== undefined && manifest.version <= last) {
    throw new BundleError(`rollback/replay refused: ${manifest.name} v${manifest.version} <= accepted v${last}`, 409);
  }
  if (!Array.isArray(manifest.files) || manifest.files.length === 0 || manifest.files.length > 5000) throw new BundleError("manifest.files must be a non-empty list");
  const seen = new Set();
  for (const f of manifest.files) {
    if (typeof f.path !== "string" || !f.path || f.path.startsWith("/") || f.path.split("/").includes("..") || f.path.includes("\\") || f.path.includes("\0")) throw new BundleError(`unsafe file path in manifest: ${JSON.stringify(f.path)}`);
    if (seen.has(f.path)) throw new BundleError(`duplicate file path: ${f.path}`);
    seen.add(f.path);
    if (!/^[a-f0-9]{64}$/.test(f.sha256 || "")) throw new BundleError(`bad sha256 for ${f.path}`);
    if (!Number.isSafeInteger(f.size) || f.size < 0) throw new BundleError(`bad size for ${f.path}`);
    if (!CLASSES.includes(f.classification)) throw new BundleError(`bad classification for ${f.path}`);
  }
  return manifest;
}

/** Verify a bundle directory on the import media. Confined to `root` (no traversal, no symlink escape). */
export async function verifyBundleDir(root, rel, trustedKeys, lastVersions = {}) {
  const rootReal = await realpath(root);
  const dir = await realpath(resolve(rootReal, rel)).catch(() => { throw new BundleError("bundle path not found", 404); });
  if (dir !== rootReal && !dir.startsWith(rootReal + sep)) throw new BundleError("bundle path escapes the import root", 403);
  const manifest = JSON.parse(await readFile(join(dir, "manifest.json"), "utf8"));
  const sig = await readFile(join(dir, "manifest.sig"), "utf8");
  verifyManifest(manifest, sig, trustedKeys, lastVersions);
  const problems = [];
  for (const f of manifest.files) {
    const full = await realpath(join(dir, "files", f.path)).catch(() => null);
    if (!full || !full.startsWith(join(dir, "files") + sep)) { problems.push(`${f.path}: missing or outside bundle`); continue; }
    const st = await stat(full);
    if (st.size !== f.size) { problems.push(`${f.path}: size ${st.size} != ${f.size}`); continue; }
    if ((await sha256File(full)) !== f.sha256) problems.push(`${f.path}: sha256 mismatch`);
  }
  if (problems.length) throw new BundleError(`bundle content verification failed: ${problems.join("; ")}`, 422);
  return { manifest, dir: relative(rootReal, dir) || "." };
}

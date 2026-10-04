import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { hashToken } from "./lib/auth.mjs";
import { keyIdOf } from "./lib/bundle.mjs";
import { canonical } from "./lib/canonical.mjs";
import { createApp } from "./server.mjs";

export const tmp = (p = "prexus-cp-") => mkdtemp(join(tmpdir(), p));
export const TOKENS = { alice: "tok-alice-0123456789abcdef0123456789abcdef", bob: "tok-bob-0123456789abcdef0123456789abcdef", audit: "tok-audit-0123456789abcdef0123456789abcdef" };

export async function operatorsFile(dir) {
  const file = join(dir, "operators.json");
  await writeFile(file, JSON.stringify([
    { id: "alice", role: "operator", token_sha256: hashToken(TOKENS.alice) },
    { id: "bob", role: "operator", token_sha256: hashToken(TOKENS.bob) },
    { id: "auditor-1", role: "auditor", token_sha256: hashToken(TOKENS.audit) },
  ]));
  return file;
}

export async function start(overrides = {}) {
  const stateDir = overrides.stateDir || (await tmp());
  const app = await createApp({ stateDir, operatorsFile: await operatorsFile(stateDir), ...overrides });
  await new Promise((r) => app.server.listen(0, "127.0.0.1", r));
  app.baseUrl = `http://127.0.0.1:${app.server.address().port}`;
  app.stateDir = stateDir;
  return app;
}

export const call = (app, path, { as = "alice", method = "GET", body, headers = {}, token } = {}) =>
  fetch(`${app.baseUrl}${path}`, {
    method, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
    headers: { ...(as || token ? { authorization: `Bearer ${token ?? TOKENS[as]}` } : {}), "content-type": "application/json", ...headers },
  });

export const run = (app, node, command, input, opts = {}) => call(app, `/v1/nodes/${node}/runs`, { method: "POST", body: { command, input }, ...opts });

export function makeKey() {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const pem = publicKey.export({ type: "spki", format: "pem" });
  return { privateKey, publicKey, pem, keyId: keyIdOf(pem) };
}

/** Build a signed bundle directory in `root/<name>-v<version>`. */
export async function makeBundle(root, { name = "meteorium-data", version = 1, files = { "data/a.bin": "hello world" }, key, tamper } = {}) {
  const dir = join(root, `${name}-v${version}`);
  const entries = [];
  for (const [path, content] of Object.entries(files)) {
    const full = join(dir, "files", path);
    await mkdir(dirname(full), { recursive: true });
    await writeFile(full, content);
    entries.push({ path, sha256: createHash("sha256").update(content).digest("hex"), size: Buffer.byteLength(content), classification: "restricted", license: "CC-BY-4.0", source: "fixture" });
  }
  const manifest = { format: "prexus-bundle/1", name, version, created_at: "2026-09-30T00:00:00Z", signer_key_id: key.keyId, files: entries };
  await writeFile(join(dir, "manifest.json"), JSON.stringify(manifest));
  await writeFile(join(dir, "manifest.sig"), sign(null, Buffer.from(canonical(manifest), "utf8"), key.privateKey).toString("base64"));
  if (tamper) await tamper(dir);
  return { dir, manifest, rel: `${name}-v${version}` };
}
export async function trustDirWith(...keys) {
  const d = await tmp("prexus-trust-");
  for (const [i, k] of keys.entries()) await writeFile(join(d, `k${i}.pem`), k.pem);
  return d;
}

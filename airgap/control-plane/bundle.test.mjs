import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { call, makeBundle, makeKey, run, start, tmp, trustDirWith } from "./testkit.mjs";
import { loadTrustedKeys, verifyBundleDir } from "./lib/bundle.mjs";

const setup = async () => {
  const key = makeKey(); const importDir = await tmp("prexus-import-");
  return { key, importDir, trustDir: await trustDirWith(key) };
};

test("valid signed bundle imports through the node and registers datasets", async (t) => {
  const { key, importDir, trustDir } = await setup();
  const b = await makeBundle(importDir, { key, files: { "era5/a.nc": "AAAA", "imd/b.csv": "x,y\n1,2\n" } });
  const app = await start({ importDir, trustDir }); t.after(() => app.close());
  const r = await run(app, "bundle-import", "register-bundle", { path: b.rel });
  assert.equal(r.status, 201, JSON.stringify(await r.clone().json()));
  const out = (await r.json()).run.output;
  assert.equal(out.bundle.files, 2); assert.equal(out.data_mode, "verified-signed-bundle");
  assert.equal(app.store.state.datasets.filter((d) => d.origin.startsWith("bundle:meteorium-data@1")).length, 2);
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: b.rel })).status, 409, "replay of the same version is refused");
});

test("rollback, tamper, wrong signature and untrusted signer are all refused", async (t) => {
  const { key, importDir, trustDir } = await setup();
  const app = await start({ importDir, trustDir }); t.after(() => app.close());
  const v2 = await makeBundle(importDir, { key, version: 2 });
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: v2.rel })).status, 201);
  const v1 = await makeBundle(importDir, { key, version: 1 });
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: v1.rel })).status, 409, "downgrade");
  const tampered = await makeBundle(importDir, { key, version: 3, tamper: (d) => writeFile(join(d, "files", "data", "a.bin"), "EVIL") });
  const t3 = await run(app, "bundle-import", "register-bundle", { path: tampered.rel });
  assert.equal(t3.status, 422); assert.match((await t3.json()).error, /size|sha256/);
  const badsig = await makeBundle(importDir, { key, version: 4, tamper: (d) => writeFile(join(d, "manifest.sig"), Buffer.alloc(64).toString("base64")) });
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: badsig.rel })).status, 403);
  const rogue = await makeBundle(importDir, { key: makeKey(), version: 5, name: "rogue-data" });
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: rogue.rel })).status, 403);
});

test("path traversal / symlink escape / unsafe manifest paths are refused", async (t) => {
  const { key, importDir, trustDir } = await setup();
  await assert.rejects(verifyBundleDir(importDir, "../../etc", await loadTrustedKeys(trustDir)), /escapes|not found/);
  const outside = await tmp("prexus-outside-");
  await symlink(outside, join(importDir, "link"));
  await assert.rejects(verifyBundleDir(importDir, "link", await loadTrustedKeys(trustDir)), /escapes/);
  for (const bad of ["../x", "/etc/passwd", "a/../../b", "a\\b"]) {
    const b = await makeBundle(importDir, { key, name: `bad-${Math.abs(bad.length * 7)}${bad.length}`, files: { [bad]: "x" } }).catch(() => null);
    if (!b) continue;   // helper refused to write outside root — good
    await assert.rejects(verifyBundleDir(importDir, b.rel, await loadTrustedKeys(trustDir)), /unsafe file path|not found|escapes/);
  }
});

test("not configured ⇒ 503; CLI verifier agrees with the library", async (t) => {
  const app = await start(); t.after(() => app.close());
  assert.equal((await run(app, "bundle-import", "register-bundle", { path: "x" })).status, 503);
  const { key, importDir, trustDir } = await setup();
  const b = await makeBundle(importDir, { key });
  const ok = spawnSync("node", ["tools/verify-bundle.mjs", importDir, b.rel, trustDir], { encoding: "utf8" });
  assert.equal(ok.status, 0, ok.stdout); assert.equal(JSON.parse(ok.stdout).valid, true);
  const none = spawnSync("node", ["tools/verify-bundle.mjs", importDir, b.rel, await trustDirWith(makeKey())], { encoding: "utf8" });
  assert.equal(none.status, 1);
});

#!/usr/bin/env node
// node tools/verify-bundle.mjs <import-root> <bundle-dir-relative> <trusted-keys-dir>
import { loadTrustedKeys, verifyBundleDir } from "../lib/bundle.mjs";
const [root, rel, trust] = process.argv.slice(2);
if (!root || !rel || !trust) { console.error("usage: verify-bundle.mjs <import-root> <bundle-dir> <trusted-keys-dir>"); process.exit(2); }
try {
  const r = await verifyBundleDir(root, rel, await loadTrustedKeys(trust));
  console.log(JSON.stringify({ valid: true, name: r.manifest.name, version: r.manifest.version, files: r.manifest.files.length }));
} catch (e) { console.log(JSON.stringify({ valid: false, reason: e.message })); process.exit(1); }

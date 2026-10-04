// Regenerates the Node-produced fixtures used by the cross-language tests:
//   node make_node_fixtures.mjs
// (Fixed key → committed fixtures; Python must verify what Node produced.)
import { generateKeyPairSync, createPrivateKey } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile, cp } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Ledger, Signer } from "../../../../airgap/control-plane/lib/ledger.mjs";
import { makeBundle } from "../../../../airgap/control-plane/testkit.mjs";
import { keyIdOf } from "../../../../airgap/control-plane/lib/bundle.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "node_made");
await rm(out, { recursive: true, force: true }); await mkdir(out, { recursive: true });
const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const pem = publicKey.export({ type: "spki", format: "pem" });
await writeFile(join(out, "signer.pub.pem"), pem);
await writeFile(join(out, "signer.key.pem"), privateKey.export({ type: "pkcs8", format: "pem" }));   // TEST KEY ONLY
const signer = new Signer(createPrivateKey(privateKey.export({ type: "pkcs8", format: "pem" })));
const led = join(out, "ledger"); await mkdir(led);
const l = await new Ledger({ dir: led, signer }).open();
for (let i = 1; i <= 5; i++) await l.append({ actor: "alice", action: `act.${i}`, resource: `r${i}`, metadata: { i, note: "héllo \"q\" \\ \n ✓" } });
await l.close();
const imp = join(out, "import"); await mkdir(imp);
const key = { privateKey, publicKey, pem, keyId: keyIdOf(pem) };
await makeBundle(imp, { name: "node-bundle", version: 3, key, files: { "data/a.txt": "ünïcode ✓", "b/c.bin": "0123456789" } });
console.log("fixtures written to", out, "key id", key.keyId);

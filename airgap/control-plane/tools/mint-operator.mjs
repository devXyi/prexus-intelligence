#!/usr/bin/env node
// Mint an operator credential:  node tools/mint-operator.mjs <id> <operator|auditor>
// Prints the token ONCE (give it to the person) and the registry entry (store in PREXUS_OPERATORS_FILE).
import { hashToken, mintToken } from "../lib/auth.mjs";
const [id, role] = process.argv.slice(2);
if (!id || !["operator", "auditor"].includes(role)) { console.error("usage: mint-operator.mjs <id> <operator|auditor>"); process.exit(2); }
const token = mintToken();
console.log(JSON.stringify({ token, registry_entry: { id, role, token_sha256: hashToken(token) } }, null, 2));

// Prexus air-gap control plane v2 — closed-loop operator console.
//
// v2 (audit fixes)
//  • Operators are authenticated individually (hashed 256-bit tokens, roles); the ledger's
//    `actor` is the authenticated identity, no longer a client-asserted header.
//  • Ledger is an append-only, fsync'd NDJSON hash chain with Ed25519-signed head anchors
//    (lib/ledger.mjs); all mutations are serialised (v1 could lose events under concurrency).
//  • Failed validation no longer leaves ghost "running" runs; failures are recorded.
//  • Egress policy: internal-only upstream URLs, plus a startup egress self-test. `air_gapped`
//    is reported as a measured property, not a constant.
//  • Real engine attaches as a node (`meteorium-engine`); signed offline bundles enter via
//    `bundle-import`. The deterministic demo scorer stays, clearly labelled.
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AuthThrottle, OperatorRegistry, ROLES } from "./lib/auth.mjs";
import { BundleError, loadTrustedKeys, verifyBundleDir } from "./lib/bundle.mjs";
import { canonical } from "./lib/canonical.mjs";
import { probeEgress } from "./lib/egress.mjs";
import { Ledger, Signer } from "./lib/ledger.mjs";
import { Mutex } from "./lib/mutex.mjs";
import { assertInternalUrl, isInternalHost } from "./lib/netpolicy.mjs";

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const MAX_BODY_BYTES = 64 * 1024;
const SCENARIO_PREMIUM = Object.freeze({ baseline: 0, disorderly: 0.09, failed: 0.16 });
const SIM_FIELDS = { asset_id: "string", asset_type: "string", scenario: "string", intensity: "number", duration_days: "number", rcp_year: "number", rcp_scenario: "string", value_usd_mm: "number", composite_risk: "number", seed: "number" };

const NODE_CATALOG = Object.freeze([
  { id: "meteorium-ingest", name: "Meteorium intake node", classification: "restricted", commands: ["register-dataset"] },
  { id: "bundle-import", name: "Signed bundle import node", classification: "restricted", commands: ["register-bundle"] },
  { id: "meteorium-score", name: "Meteorium offline simulation node (demonstration only)", classification: "restricted", commands: ["offline-simulate"] },
  { id: "meteorium-engine", name: "Meteorium engine node (real engine, internal network only)", classification: "restricted", commands: ["simulate"] },
  { id: "audit-ledger", name: "Audit verification node", classification: "restricted", commands: ["verify-ledger"] },
]);

const sha256 = (v) => createHash("sha256").update(v).digest("hex");
const httpError = (status, message) => Object.assign(new Error(message), { status });

function initialState() { return { schema_version: 2, datasets: [], runs: [], bundles: {} }; }

class StateStore {
  constructor(stateDir) { this.dir = stateDir; this.file = join(stateDir, "control-plane.json"); this.state = null; this.mutex = new Mutex(); }
  async load() {
    await mkdir(this.dir, { recursive: true, mode: 0o700 });
    try { this.state = JSON.parse(await readFile(this.file, "utf8")); }
    catch (e) { if (e.code !== "ENOENT") throw e; this.state = initialState(); await this.save(); }
    this.state.bundles ||= {};
  }
  async save() {
    const tmp = `${this.file}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(tmp, `${JSON.stringify(this.state, null, 2)}\n`, { mode: 0o600 });
    await rename(tmp, this.file);
  }
}

const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" });
  res.end(JSON.stringify(body));
};

async function readJson(req) {
  const chunks = []; let n = 0;
  for await (const c of req) { n += c.length; if (n > MAX_BODY_BYTES) throw httpError(413, "request body too large"); chunks.push(c); }
  try { const v = JSON.parse(Buffer.concat(chunks).toString("utf8")); if (v === null || typeof v !== "object" || Array.isArray(v)) throw 0; return v; }
  catch { throw httpError(400, "invalid JSON body (object expected)"); }
}

function requireString(value, field, max = 128) {
  if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw httpError(400, `${field} is required and must be at most ${max} characters`);
  return value.trim();
}

// ── node implementations ─────────────────────────────────────────────────────
function registerDataset(input, state) {
  const d = input?.dataset;
  const id = requireString(d?.id, "dataset.id");
  const digest = requireString(d?.sha256, "dataset.sha256", 64).toLowerCase();
  const classification = requireString(d?.classification, "dataset.classification", 32).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(digest)) throw httpError(400, "dataset.sha256 must be a SHA-256 hex digest");
  if (!["internal", "restricted"].includes(classification)) throw httpError(400, "dataset.classification must be internal or restricted");
  const record = { id, sha256: digest, classification, registered_at: new Date().toISOString(), origin: "operator-declared" };
  state.datasets = state.datasets.filter((x) => x.id !== id); state.datasets.push(record);
  return { dataset: record, data_mode: "operator-supplied-offline-artifact" };
}

function deterministicScore(input, datasets) {
  const asset = input?.asset || {};
  const assetId = requireString(asset.id, "asset.id");
  const value = Number(asset.value_usd);
  if (!Number.isFinite(value) || value <= 0 || value > 1e12) throw httpError(400, "asset.value_usd must be a positive number within the configured limit");
  const scenario = requireString(input?.scenario || "baseline", "scenario", 32).toLowerCase();
  if (!(scenario in SCENARIO_PREMIUM)) throw httpError(400, "scenario must be baseline, disorderly, or failed");
  const sample = Number.parseInt(sha256(`${assetId}:${scenario}:${value}`).slice(0, 8), 16) / 0xffffffff;
  const score = Math.min(0.99, 0.16 + sample * 0.58 + SCENARIO_PREMIUM[scenario]);
  return {
    asset_id: assetId, scenario, risk_score: Number(score.toFixed(4)), expected_loss_usd: Number((value * score * 0.12).toFixed(2)),
    dataset_count: datasets.length, data_mode: "offline-input-only", model_status: "demonstration-only",
    limitation: "This deterministic test result is not calibrated climate intelligence and must not be used for investment, insurance, public-safety, or regulatory decisions.",
  };
}

async function engineSimulate(config, input) {
  if (!config.engineUrl) throw httpError(503, "engine node not configured (PREXUS_ENGINE_URL)");
  const payload = {};
  for (const [k, t] of Object.entries(SIM_FIELDS)) {
    if (input?.[k] === undefined) continue;
    if (typeof input[k] !== t) throw httpError(400, `${k} must be a ${t}`);
    payload[k] = input[k];
  }
  const started = Date.now();
  let res;
  try {
    res = await fetch(new URL("/risk/simulate", config.engineUrl), {
      method: "POST", signal: AbortSignal.timeout(config.engineTimeoutMs),
      headers: { "content-type": "application/json", ...(config.engineSecret ? { authorization: `Bearer ${config.engineSecret}` } : {}) },
      body: JSON.stringify(payload),
    });
  } catch { throw httpError(502, "engine unreachable"); }
  const text = (await res.text()).slice(0, 1_000_000);
  if (!res.ok) throw httpError(502, `engine returned HTTP ${res.status}`);
  let out; try { out = JSON.parse(text); } catch { throw httpError(502, "engine returned invalid JSON"); }
  return {
    engine_output: out,
    receipt: {
      input_sha256: sha256(canonical(payload, { floats: true })), output_sha256: sha256(canonical(out, { floats: true })),
      engine_host: new URL(config.engineUrl).host, method: out.method ?? null, calibrated: out.calibrated ?? null,
      seed: payload.seed ?? null, latency_ms: Date.now() - started, data_mode: "offline-input-only",
    },
  };
}

async function registerBundle(config, store, input) {
  if (!config.importDir) throw httpError(503, "bundle import not configured (PREXUS_IMPORT_DIR)");
  if (!config.trustedKeys.size) throw httpError(503, "no trusted bundle-signing keys configured (PREXUS_BUNDLE_TRUST_DIR)");
  const rel = requireString(input?.path, "path", 256);
  const last = Object.fromEntries(Object.entries(store.state.bundles).map(([n, b]) => [n, b.version]));
  let verified;
  try { verified = await verifyBundleDir(config.importDir, rel, config.trustedKeys, last); }
  catch (e) { if (e instanceof BundleError) throw httpError(e.status, e.message); throw httpError(422, "bundle could not be read"); }
  const m = verified.manifest;
  for (const f of m.files) {
    const id = `${m.name}:${f.path}`;
    store.state.datasets = store.state.datasets.filter((x) => x.id !== id);
    store.state.datasets.push({ id, sha256: f.sha256, classification: f.classification, registered_at: new Date().toISOString(), origin: `bundle:${m.name}@${m.version}`, license: f.license ?? null, source: f.source ?? null });
  }
  store.state.bundles[m.name] = { version: m.version, signer_key_id: m.signer_key_id, manifest_sha256: sha256(canonical(m)), accepted_at: new Date().toISOString() };
  return { bundle: { name: m.name, version: m.version, files: m.files.length, signer_key_id: m.signer_key_id }, data_mode: "verified-signed-bundle" };
}

// ── app ──────────────────────────────────────────────────────────────────────
export async function createApp(options = {}) {
  const env = process.env;
  const production = (options.production ?? env.PREXUS_ENV === "production");
  const config = {
    production,
    stateDir: options.stateDir || env.PREXUS_STATE_DIR || join(MODULE_DIR, "state"),
    operatorsFile: options.operatorsFile || env.PREXUS_OPERATORS_FILE,
    operatorToken: options.operatorToken || env.PREXUS_OPERATOR_TOKEN,
    allowSharedToken: options.allowSharedToken ?? (env.PREXUS_ALLOW_SHARED_TOKEN === "1"),
    ledgerKeyFile: options.ledgerKeyFile || env.PREXUS_LEDGER_KEY_FILE,
    engineUrl: options.engineUrl || env.PREXUS_ENGINE_URL || "",
    engineSecret: options.engineSecret || env.PREXUS_ENGINE_SECRET || "",
    engineTimeoutMs: options.engineTimeoutMs || 15_000,
    importDir: options.importDir || env.PREXUS_IMPORT_DIR || "",
    trustDir: options.trustDir || env.PREXUS_BUNDLE_TRUST_DIR || "",
    egressProbe: options.egressProbe ?? (production ? env.PREXUS_EGRESS_PROBE !== "0" : env.PREXUS_EGRESS_PROBE === "1"),
    egressConnect: options.egressConnect,
  };
  if (!config.operatorsFile && !config.operatorToken) throw new Error("configure PREXUS_OPERATORS_FILE (or PREXUS_OPERATOR_TOKEN outside production)");
  if (production && config.operatorToken && !config.allowSharedToken) throw new Error("production refuses a shared operator token; use PREXUS_OPERATORS_FILE (or set PREXUS_ALLOW_SHARED_TOKEN=1 knowingly)");
  if (production && !config.ledgerKeyFile) throw new Error("production requires PREXUS_LEDGER_KEY_FILE (ledger signing key held by the operator organisation)");
  if (!config.engineSecret && env.PREXUS_ENGINE_SECRET_FILE) config.engineSecret = (await readFile(env.PREXUS_ENGINE_SECRET_FILE, "utf8")).trim();
  if (config.engineUrl) assertInternalUrl(config.engineUrl, "PREXUS_ENGINE_URL");

  const operators = await OperatorRegistry.load({ operatorsFile: config.operatorsFile, legacyToken: config.operatorToken });
  const store = new StateStore(config.stateDir);
  await store.load();
  const signer = await Signer.load({ keyFile: config.ledgerKeyFile, autogen: !production, stateDir: config.stateDir });
  const ledger = await new Ledger({ dir: config.stateDir, signer }).open();
  config.trustedKeys = await loadTrustedKeys(config.trustDir);
  const terminalHtml = await readFile(join(MODULE_DIR, "public", "terminal.html"), "utf8");
  const throttle = new AuthThrottle();
  const deniedLogged = new Map();
  let egress = { isolated: null, reached: [], checked: 0, at: null, note: "probe not run" };
  if (config.egressProbe) {
    egress = await probeEgress(config.egressConnect ? { connect: config.egressConnect } : {});
    await ledger.append({ actor: "system", action: "egress.probe", resource: "host", metadata: { isolated: egress.isolated, reached: egress.reached } }).catch(() => {});
    if (!egress.isolated) console.error(`SECURITY: outbound connectivity detected (${egress.reached.join(", ")}) — this host is NOT air-gapped`);
  }
  await ledger.append({ actor: "system", action: "controlplane.start", resource: "controlplane", metadata: { production, shared_token: Boolean(operators.usesSharedToken), engine_configured: Boolean(config.engineUrl), egress_isolated: egress.isolated === null ? "unknown" : String(egress.isolated) } }).catch(() => {});

  async function audit(actor, action, resource, metadata) {
    try { return await ledger.append({ actor, action, resource, metadata }); }
    catch (e) { throw httpError(503, "audit ledger unavailable — refusing to act without an audit trail"); }
  }

  async function executeRun(nodeId, command, input, principal) {
    const node = NODE_CATALOG.find((n) => n.id === nodeId);
    if (!node) throw httpError(404, "node not found");
    if (!node.commands.includes(command)) throw httpError(400, "command is not permitted for this node");
    if (principal.role === ROLES.auditor && nodeId !== "audit-ledger") throw httpError(403, "auditor role may only run audit-ledger");
    return store.mutex.run(async () => {
      const run = { id: randomUUID(), node_id: nodeId, command, requested_at: new Date().toISOString(), requested_by: principal.id, requested_role: principal.role, input_sha256: sha256(canonical(input ?? {}, { floats: true })), status: "running" };
      let output;
      try {
        if (nodeId === "meteorium-ingest") output = registerDataset(input, store.state);
        else if (nodeId === "bundle-import") output = await registerBundle(config, store, input);
        else if (nodeId === "meteorium-score") output = deterministicScore(input, store.state.datasets);
        else if (nodeId === "meteorium-engine") output = await engineSimulate(config, input);
        else if (nodeId === "audit-ledger") output = await ledger.verify();
        run.status = "completed"; run.output = output;
      } catch (e) {
        run.status = "failed"; run.error = { status: e.status || 500, message: e.status ? e.message : "internal error" };
        run.completed_at = new Date().toISOString();
        store.state.runs.push(run);
        await audit(principal.id, `node.${nodeId}.${command}.failed`, run.id, { status: String(run.error.status), input_sha256: run.input_sha256 });
        await store.save();
        throw e;
      }
      run.completed_at = new Date().toISOString();
      store.state.runs.push(run);
      const ev = await audit(principal.id, `node.${nodeId}.${command}`, run.id, { status: "completed", input_sha256: run.input_sha256, output_sha256: sha256(canonical(output, { floats: true })) });
      run.ledger_seq = ev.seq;
      await store.save();
      return run;
    });
  }

  function authenticate(req, res) {
    const remote = req.socket.remoteAddress || "unknown";
    if (throttle.blocked(remote)) { json(res, 429, { error: "too many failed attempts — try again later" }); return null; }
    const h = req.headers.authorization || "";
    const principal = operators.authenticate(h.startsWith("Bearer ") ? h.slice(7) : "");
    if (principal) { throttle.ok(remote); return principal; }
    throttle.fail(remote);
    const now = Date.now();
    if (now - (deniedLogged.get(remote) || 0) > 60_000) {           // sampled: one audit line per source per minute
      deniedLogged.set(remote, now);
      ledger.append({ actor: "anonymous", action: "auth.denied", resource: "api", metadata: { remote } }).catch(() => {});
    }
    json(res, 401, { error: "operator authorization required" });
    return null;
  }

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      if (req.method === "GET" && url.pathname === "/health") {
        const v = ledger.valid;
        return json(res, v ? 200 : 503, { status: v ? "ok" : "degraded", service: "prexus-airgap-control-plane", ledger: { valid: v, sequence: ledger.seq }, egress_isolated: egress.isolated, air_gapped_verified: egress.isolated === true, air_gapped_declared: true });
      }
      if (req.method === "GET" && url.pathname === "/") {
        res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", "content-security-policy": "default-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:" });
        return res.end(terminalHtml);
      }
      const principal = authenticate(req, res);
      if (!principal) return;
      if (req.method === "GET" && url.pathname === "/v1/nodes") return json(res, 200, { nodes: NODE_CATALOG, principal, air_gapped_verified: egress.isolated === true, air_gapped_declared: true });
      if (req.method === "GET" && url.pathname === "/v1/ledger/head") return json(res, 200, ledger.signedHead());
      if (req.method === "GET" && url.pathname === "/v1/ledger/events") return json(res, 200, { events: ledger.page(Number(url.searchParams.get("after")) || 0, url.searchParams.get("limit")) });
      if (req.method === "GET" && url.pathname === "/v1/ledger/public-key") return json(res, 200, { key_id: signer.keyId, alg: "Ed25519", public_key: signer.publicKeyPem });
      const runMatch = url.pathname.match(/^\/v1\/nodes\/([a-z-]+)\/runs$/);
      if (req.method === "POST" && runMatch) {
        const body = await readJson(req);
        const run = await executeRun(runMatch[1], body.command, body.input, principal);
        return json(res, 201, { run });
      }
      const detail = url.pathname.match(/^\/v1\/runs\/([0-9a-f-]+)$/);
      if (req.method === "GET" && detail) {
        const run = store.state.runs.find((r) => r.id === detail[1]);
        return run ? json(res, 200, { run }) : json(res, 404, { error: "run not found" });
      }
      return json(res, 404, { error: "route not found" });
    } catch (e) {
      return json(res, e.status || 500, { error: e.status ? e.message : "internal server error" });
    }
  });
  server.requestTimeout = 30_000; server.headersTimeout = 10_000; server.keepAliveTimeout = 5_000;
  const close = async () => { await new Promise((r) => server.close(r)); await ledger.close(); };
  return { server, store, ledger, signer, config, egress, close };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const bind = process.env.PREXUS_BIND || "127.0.0.1";
  if (process.env.PREXUS_ENV === "production" && !isInternalHost(bind) && bind !== "0.0.0.0") throw new Error(`PREXUS_BIND ${bind} is not an internal address`);
  const app = await createApp();
  const port = Number(process.env.PORT || 8787);
  app.server.listen(port, bind, () => console.log(`Prexus air-gap control plane listening on ${bind}:${port}`));
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, async () => { await app.close(); process.exit(0); });
}

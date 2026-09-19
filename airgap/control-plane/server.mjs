import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { readFile, mkdir, rename, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const MAX_BODY_BYTES = 64 * 1024;
const SCENARIO_PREMIUM = Object.freeze({ baseline: 0, disorderly: 0.09, failed: 0.16 });

const NODE_CATALOG = Object.freeze([
  {
    id: "meteorium-ingest",
    name: "Meteorium intake node",
    classification: "restricted",
    commands: ["register-dataset"],
  },
  {
    id: "meteorium-score",
    name: "Meteorium offline simulation node",
    classification: "restricted",
    commands: ["offline-simulate"],
  },
  {
    id: "audit-ledger",
    name: "Audit verification node",
    classification: "restricted",
    commands: ["verify-ledger"],
  },
]);

function hash(value) {
  return createHash("sha256").update(value).digest("hex");
}

function initialState() {
  return {
    schema_version: 1,
    datasets: [],
    runs: [],
    ledger: { head_hash: "GENESIS", events: [] },
  };
}

class StateStore {
  constructor(stateDir) {
    this.file = join(stateDir, "control-plane.json");
    this.stateDir = stateDir;
    this.state = null;
  }

  async load() {
    await mkdir(this.stateDir, { recursive: true });
    try {
      this.state = JSON.parse(await readFile(this.file, "utf8"));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      this.state = initialState();
      await this.save();
    }
  }

  async save() {
    const temporary = `${this.file}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(temporary, `${JSON.stringify(this.state, null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, this.file);
  }

  async appendEvent({ actor, action, resource, metadata }) {
    const event = {
      id: randomUUID(),
      at: new Date().toISOString(),
      actor,
      action,
      resource,
      metadata,
      previous_hash: this.state.ledger.head_hash,
    };
    event.hash = hash(JSON.stringify(event));
    this.state.ledger.events.push(event);
    this.state.ledger.head_hash = event.hash;
    return event;
  }
}

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(JSON.stringify(body));
}

function sameSecret(received, expected) {
  if (!received || !expected) return false;
  const receivedBytes = Buffer.from(received);
  const expectedBytes = Buffer.from(expected);
  return receivedBytes.length === expectedBytes.length && timingSafeEqual(receivedBytes, expectedBytes);
}

function requireOperator(request, response, config) {
  const authorization = request.headers.authorization || "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
  if (sameSecret(token, config.operatorToken)) {
    return request.headers["x-operator-id"] || "operator";
  }
  json(response, 401, { error: "operator authorization required" });
  return null;
}

async function readJson(request) {
  const chunks = [];
  let received = 0;
  for await (const chunk of request) {
    received += chunk.length;
    if (received > MAX_BODY_BYTES) {
      const error = new Error("request body too large");
      error.status = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    const error = new Error("invalid JSON body");
    error.status = 400;
    throw error;
  }
}

function requireString(value, field, maxLength = 128) {
  if (typeof value !== "string" || !value.trim() || value.trim().length > maxLength) {
    const error = new Error(`${field} is required and must be at most ${maxLength} characters`);
    error.status = 400;
    throw error;
  }
  return value.trim();
}

function registerDataset(input, state) {
  const dataset = input?.dataset;
  const id = requireString(dataset?.id, "dataset.id");
  const sha256 = requireString(dataset?.sha256, "dataset.sha256", 64).toLowerCase();
  const classification = requireString(dataset?.classification, "dataset.classification", 32).toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(sha256)) {
    const error = new Error("dataset.sha256 must be a SHA-256 hex digest");
    error.status = 400;
    throw error;
  }
  if (!["internal", "restricted"].includes(classification)) {
    const error = new Error("dataset.classification must be internal or restricted");
    error.status = 400;
    throw error;
  }
  const record = { id, sha256, classification, registered_at: new Date().toISOString() };
  state.datasets = state.datasets.filter((item) => item.id !== id);
  state.datasets.push(record);
  return { dataset: record, data_mode: "operator-supplied-offline-artifact" };
}

function deterministicScore(input, datasets) {
  const asset = input?.asset || {};
  const assetId = requireString(asset.id, "asset.id");
  const value = Number(asset.value_usd);
  if (!Number.isFinite(value) || value <= 0 || value > 1_000_000_000_000) {
    const error = new Error("asset.value_usd must be a positive number within the configured limit");
    error.status = 400;
    throw error;
  }
  const scenario = requireString(input?.scenario || "baseline", "scenario", 32).toLowerCase();
  if (!(scenario in SCENARIO_PREMIUM)) {
    const error = new Error("scenario must be baseline, disorderly, or failed");
    error.status = 400;
    throw error;
  }
  const sample = Number.parseInt(hash(`${assetId}:${scenario}:${value}`).slice(0, 8), 16) / 0xffffffff;
  const score = Math.min(0.99, 0.16 + sample * 0.58 + SCENARIO_PREMIUM[scenario]);
  return {
    asset_id: assetId,
    scenario,
    risk_score: Number(score.toFixed(4)),
    expected_loss_usd: Number((value * score * 0.12).toFixed(2)),
    dataset_count: datasets.length,
    data_mode: "offline-input-only",
    model_status: "demonstration-only",
    limitation: "This deterministic test result is not calibrated climate intelligence and must not be used for investment, insurance, public-safety, or regulatory decisions.",
  };
}

function verifyLedger(ledger) {
  let previousHash = "GENESIS";
  for (const event of ledger.events) {
    const { hash: eventHash, ...unsigned } = event;
    if (event.previous_hash !== previousHash || eventHash !== hash(JSON.stringify(unsigned))) {
      return { valid: false, checked_events: ledger.events.length, failed_event_id: event.id };
    }
    previousHash = eventHash;
  }
  return { valid: previousHash === ledger.head_hash, checked_events: ledger.events.length, head_hash: ledger.head_hash };
}

async function executeRun(store, nodeId, command, input, actor) {
  const node = NODE_CATALOG.find((item) => item.id === nodeId);
  if (!node) {
    const error = new Error("node not found");
    error.status = 404;
    throw error;
  }
  if (!node.commands.includes(command)) {
    const error = new Error("command is not permitted for this node");
    error.status = 400;
    throw error;
  }

  const run = {
    id: randomUUID(),
    node_id: node.id,
    command,
    requested_at: new Date().toISOString(),
    requested_by: actor,
    status: "running",
  };
  store.state.runs.push(run);

  let output;
  if (nodeId === "meteorium-ingest") output = registerDataset(input, store.state);
  if (nodeId === "meteorium-score") output = deterministicScore(input, store.state.datasets);
  if (nodeId === "audit-ledger") output = verifyLedger(store.state.ledger);

  run.status = "completed";
  run.completed_at = new Date().toISOString();
  run.output = output;
  await store.appendEvent({ actor, action: `node.${nodeId}.${command}`, resource: run.id, metadata: { status: run.status } });
  await store.save();
  return run;
}

export async function createApp(options = {}) {
  const config = {
    stateDir: options.stateDir || process.env.PREXUS_STATE_DIR || join(MODULE_DIR, "state"),
    operatorToken: options.operatorToken || process.env.PREXUS_OPERATOR_TOKEN,
  };
  if (!config.operatorToken) throw new Error("PREXUS_OPERATOR_TOKEN is required");
  const store = new StateStore(config.stateDir);
  await store.load();
  const terminalHtml = await readFile(join(MODULE_DIR, "public", "terminal.html"), "utf8");

  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url, "http://localhost");
      if (request.method === "GET" && url.pathname === "/health") {
        return json(response, 200, { status: "ok", service: "prexus-airgap-control-plane", air_gapped: true });
      }
      if (request.method === "GET" && url.pathname === "/") {
        response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" });
        return response.end(terminalHtml);
      }
      const actor = requireOperator(request, response, config);
      if (!actor) return;
      if (request.method === "GET" && url.pathname === "/v1/nodes") {
        return json(response, 200, { nodes: NODE_CATALOG, air_gapped: true });
      }
      const runMatch = url.pathname.match(/^\/v1\/nodes\/([a-z-]+)\/runs$/);
      if (request.method === "POST" && runMatch) {
        const body = await readJson(request);
        const run = await executeRun(store, runMatch[1], body.command, body.input, actor);
        return json(response, 201, { run });
      }
      const runDetailMatch = url.pathname.match(/^\/v1\/runs\/([0-9a-f-]+)$/);
      if (request.method === "GET" && runDetailMatch) {
        const run = store.state.runs.find((item) => item.id === runDetailMatch[1]);
        return run ? json(response, 200, { run }) : json(response, 404, { error: "run not found" });
      }
      return json(response, 404, { error: "route not found" });
    } catch (error) {
      return json(response, error.status || 500, { error: error.status ? error.message : "internal server error" });
    }
  });
  return { server, store };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { server } = await createApp();
  const port = Number(process.env.PORT || 8787);
  server.listen(port, "0.0.0.0", () => console.log(`Prexus air-gap control plane listening on ${port}`));
}

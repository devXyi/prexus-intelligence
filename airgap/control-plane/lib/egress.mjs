import net from "node:net";

const DEFAULT_TARGETS = [["1.1.1.1", 53], ["8.8.8.8", 53], ["9.9.9.9", 443]];

function tcpConnect(host, port, timeoutMs) {
  return new Promise((resolve) => {
    const s = net.connect({ host, port });
    const done = (ok) => { s.destroy(); resolve(ok); };
    s.setTimeout(timeoutMs, () => done(false));
    s.once("connect", () => done(true));
    s.once("error", () => done(false));
  });
}

/** Best-effort isolation self-test: try to reach public addresses. Any success means the
 *  "air-gapped" claim is FALSE for this host. (Absence of success is evidence, not proof.) */
export async function probeEgress({ targets = DEFAULT_TARGETS, timeoutMs = 1500, connect = tcpConnect } = {}) {
  const reached = [];
  await Promise.all(targets.map(async ([h, p]) => { if (await connect(h, p, timeoutMs)) reached.push(`${h}:${p}`); }));
  return { isolated: reached.length === 0, reached, checked: targets.length, at: new Date().toISOString() };
}

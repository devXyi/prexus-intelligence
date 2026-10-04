import net from "node:net";

function privateV4(ip) {
  const [a, b] = ip.split(".").map(Number);
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}

function privateV6(ip) {
  const h = ip.toLowerCase();
  if (h === "::1") return true;
  const mapped = h.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mapped) return privateV4(mapped[1]);
  const first = parseInt(h.split(":")[0] || "0", 16);
  return (first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80; // fc00::/7 ULA, fe80::/10 link-local
}

/** True only for loopback / RFC1918 / link-local / ULA addresses, `localhost`, single-label
 *  service names (docker/k8s) and reserved internal suffixes. Public FQDNs and IPs are refused. */
export function isInternalHost(hostname) {
  const h = String(hostname).toLowerCase().replace(/^\[|\]$/g, "");
  if (!h) return false;
  if (h === "localhost") return true;
  if (net.isIPv4(h)) return privateV4(h);
  if (net.isIPv6(h)) return privateV6(h);
  if (!h.includes(".")) return true;
  return /\.(internal|local|localdomain|lan|svc|cluster\.local|home\.arpa)$/.test(h);
}

export function assertInternalUrl(value, what = "URL") {
  let u;
  try { u = new URL(value); } catch { throw new Error(`${what} is not a valid URL`); }
  if (!["http:", "https:"].includes(u.protocol)) throw new Error(`${what} must be http(s)`);
  if (u.username || u.password) throw new Error(`${what} must not embed credentials`);
  if (!isInternalHost(u.hostname)) {
    throw new Error(`${what} host "${u.hostname}" is not an internal address — refusing (air-gap egress policy)`);
  }
  return u;
}

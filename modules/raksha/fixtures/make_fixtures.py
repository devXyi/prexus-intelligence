"""Deterministic SYNTHETIC fixtures (schema-faithful, values illustrative — not real data).
   python fixtures/make_fixtures.py   →   regenerates every file in this directory."""
import csv, io, json, math, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent
rng = random.Random(20260930)

KEV = [
    ("CVE-2021-44228", "Apache", "Log4j2", "Apache Log4j2 Remote Code Execution Vulnerability", "2021-12-10", "Known"),
    ("CVE-2023-34362", "Progress", "MOVEit Transfer", "Progress MOVEit Transfer SQL Injection Vulnerability", "2023-06-02", "Known"),
    ("CVE-2021-34527", "Microsoft", "Windows Print Spooler", "Microsoft Windows Print Spooler Remote Code Execution", "2021-11-03", "Known"),
    ("CVE-2023-4966", "Citrix", "NetScaler ADC and Gateway", "Citrix NetScaler Sensitive Information Disclosure", "2023-10-18", "Known"),
    ("CVE-2024-3400", "Palo Alto Networks", "PAN-OS", "Palo Alto Networks PAN-OS Command Injection", "2024-04-12", "Unknown"),
    ("CVE-2022-26134", "Atlassian", "Confluence Server and Data Center", "Atlassian Confluence OGNL Injection", "2022-06-02", "Known"),
    ("CVE-2020-1472", "Microsoft", "Netlogon", "Microsoft Netlogon Privilege Escalation", "2021-11-03", "Known"),
    ("CVE-2021-26855", "Microsoft", "Exchange Server", "Microsoft Exchange Server SSRF Vulnerability", "2021-11-03", "Known"),
]
(OUT / "kev.json").write_text(json.dumps({
    "title": "SYNTHETIC FIXTURE — schema-faithful sample of the CISA KEV catalog", "catalogVersion": "fixture", "dateReleased": "2026-09-29T00:00:00.000Z", "count": len(KEV),
    "vulnerabilities": [{"cveID": c, "vendorProject": v, "product": p, "vulnerabilityName": n, "dateAdded": d,
                         "shortDescription": f"Illustrative description for {c}.", "requiredAction": "Apply updates per vendor instructions.",
                         "dueDate": d, "knownRansomwareCampaignUse": r, "notes": "", "cwes": ["CWE-20"]} for c, v, p, n, d, r in KEV]}, indent=1))

epss = {"CVE-2021-44228": (0.944, 0.9995), "CVE-2023-34362": (0.930, 0.9990), "CVE-2021-34527": (0.968, 0.9999), "CVE-2023-4966": (0.9, 0.998),
        "CVE-2024-3400": (0.95, 0.9995), "CVE-2022-26134": (0.944, 0.9993), "CVE-2020-1472": (0.93, 0.9990), "CVE-2021-26855": (0.97, 0.9999)}
rows = ["#model_version:v2025.03.14,score_date:2026-09-29T00:00:00Z", "cve,epss,percentile"]
rows += [f"{c},{s},{p}" for c, (s, p) in epss.items()]
rows += [f"CVE-2019-{1000 + i},{rng.random() * 0.05:.5f},{rng.random() * 0.6:.5f}" for i in range(40)]
(OUT / "epss.csv").write_text("\n".join(rows) + "\n")

# 26 weeks of events around four areas; a violence burst near "Port Alpha" in the last 3 weeks.
AREAS = {"alpha": (17.70, 83.30, {"14": 2.0, "18": 0.3, "19": 0.2}), "beta": (19.07, 72.88, {"14": 0.6, "15": 0.1}),
         "gamma": (28.61, 77.21, {"14": 1.2, "17": 0.3}), "delta": (22.57, 88.36, {"14": 0.2})}
start = datetime(2026, 4, 6, tzinfo=timezone.utc)
lines, eid = [], 900000


def poisson(l):
    L, k, p = math.exp(-l), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


for w in range(26):
    for area, (lat0, lon0, rates) in AREAS.items():
        for root, rate in rates.items():
            r = rate * (4.0 if (area == "alpha" and w >= 23 and root in ("14", "18", "19")) else 1.0)
            for _ in range(poisson(r)):
                eid += 1
                t = start + timedelta(weeks=w, days=rng.random() * 7, hours=rng.random() * 24)
                lat, lon = lat0 + rng.gauss(0, 0.05), lon0 + rng.gauss(0, 0.05)
                c = [""] * 61
                c[0], c[1], c[6], c[16], c[28], c[30] = str(eid), t.strftime("%Y%m%d"), f"ACTOR{rng.randint(1, 9)}", f"GROUP{rng.randint(1, 9)}", root, f"{rng.uniform(-9, 2):.1f}"
                c[31], c[32], c[34] = str(rng.randint(1, 30)), str(rng.randint(1, 8)), f"{rng.uniform(-8, 1):.2f}"
                c[52], c[53], c[56], c[57] = f"{area.title()} (synthetic)", "IN", f"{lat:.4f}", f"{lon:.4f}"
                c[59], c[60] = t.strftime("%Y%m%d%H%M%S"), f"https://example.org/fixture/{eid}"
                lines.append("\t".join(c))
c = [""] * 61
c[0], c[28], c[56], c[57], c[59] = "1", "03", "10", "10", "20260401000000"
lines.append("\t".join(c))                       # untracked CAMEO root → silently ignored
lines.append("short\tline")                      # malformed → reported
(OUT / "gdelt_events.tsv").write_text("\n".join(lines) + "\n")

buf = io.StringIO()
wr = csv.writer(buf)
wr.writerow("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight".split(","))
for _ in range(120):
    lat0, lon0, _r = AREAS[rng.choice(list(AREAS))]
    d = start + timedelta(days=rng.randint(150, 175))
    wr.writerow([f"{lat0 + rng.gauss(0, 0.08):.5f}", f"{lon0 + rng.gauss(0, 0.08):.5f}", f"{rng.uniform(300, 360):.1f}", "0.4", "0.4", d.strftime("%Y-%m-%d"),
                 f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}", "N", "VIIRS", rng.choice(["l", "n", "n", "h"]), "2.0NRT", f"{rng.uniform(280, 300):.1f}", f"{rng.uniform(0.5, 30):.1f}", rng.choice(["D", "N"])])
(OUT / "firms_viirs.csv").write_text(buf.getvalue())

assets = [
    {"id": "port-alpha", "name": "Port Alpha (synthetic)", "asset_type": "port", "criticality": 5, "lat": 17.70, "lon": 83.30, "technologies": ["Microsoft Exchange Server", "Citrix NetScaler"], "owner_org": "operator-1"},
    {"id": "grid-beta", "name": "Grid Substation Beta (synthetic)", "asset_type": "power", "criticality": 5, "lat": 17.75, "lon": 83.20, "technologies": ["Apache Log4j2"], "owner_org": "operator-1"},
    {"id": "telecom-gamma", "name": "Telecom Hub Gamma (synthetic)", "asset_type": "telecom", "criticality": 4, "lat": 17.65, "lon": 83.25, "technologies": ["Palo Alto Networks PAN-OS"], "owner_org": "operator-1"},
    {"id": "refinery-delta", "name": "Refinery Delta (synthetic)", "asset_type": "energy", "criticality": 5, "lat": 17.62, "lon": 83.15, "technologies": [], "owner_org": "operator-1"},
    {"id": "depot-epsilon", "name": "Inland Depot Epsilon (synthetic)", "asset_type": "logistics", "criticality": 2, "lat": 22.57, "lon": 88.36, "technologies": [], "owner_org": "operator-1"}]
(OUT / "assets.json").write_text(json.dumps(assets, indent=1))
(OUT / "dependencies.json").write_text(json.dumps({"edges": [
    {"from": "grid-beta", "to": "port-alpha", "p": 0.6}, {"from": "telecom-gamma", "to": "port-alpha", "p": 0.4},
    {"from": "grid-beta", "to": "telecom-gamma", "p": 0.5}, {"from": "grid-beta", "to": "refinery-delta", "p": 0.7},
    {"from": "port-alpha", "to": "refinery-delta", "p": 0.5}]}, indent=1))
print("fixtures written:", sorted(p.name for p in OUT.iterdir() if p.suffix in (".json", ".csv", ".tsv")))

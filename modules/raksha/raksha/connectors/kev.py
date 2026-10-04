"""CISA Known Exploited Vulnerabilities catalog (JSON) → STIX Vulnerability."""
from __future__ import annotations

import json
import re
from typing import List, Tuple

import stix2

from ..model import Record, confidence_of, det_id, marking
from ..sources import labels_for

CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
NAME = "cisa-kev"


def parse(text: str, fetched_at: str = "") -> Tuple[List[Record], List[str]]:
    data = json.loads(text)
    lab, recs, errs = labels_for(NAME), [], []
    for v in data.get("vulnerabilities", []):
        cve = str(v.get("cveID", ""))
        if not CVE_RE.match(cve) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v.get("dateAdded", ""))):
            errs.append(f"skipped malformed KEV entry {cve!r}")
            continue
        added = f"{v['dateAdded']}T00:00:00.000Z"
        props = {**lab.props(), "x_prexus_vendor_project": v.get("vendorProject", ""), "x_prexus_product": v.get("product", ""),
                 "x_prexus_kev_date_added": v["dateAdded"], "x_prexus_kev_due_date": v.get("dueDate") or "",
                 "x_prexus_ransomware_use": v.get("knownRansomwareCampaignUse", "Unknown"),
                 "x_prexus_required_action": v.get("requiredAction", ""), "x_prexus_cwes": list(v.get("cwes") or [])}
        obj = stix2.Vulnerability(
            id=det_id("vulnerability", cve), name=cve, created=added, modified=added,
            description=f"{v.get('vulnerabilityName', '')}: {v.get('shortDescription', '')}".strip(": "),
            external_references=[stix2.ExternalReference(source_name="cve", external_id=cve),
                                stix2.ExternalReference(source_name="cisa-kev", url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog")],
            confidence=confidence_of(lab.credibility), object_marking_refs=[marking(lab.tlp)], custom_properties=props)
        recs.append(Record(obj, lab, None, added))
    return recs, errs

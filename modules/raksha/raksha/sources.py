"""Source registry: reliability grades and handling defaults. Grades are DEFAULTS — edit per deployment.

Admiralty system — reliability of source A (completely reliable) … F (cannot be judged);
credibility of information 1 (confirmed by other sources) … 6 (cannot be judged).
`license_redistribute=False` blocks the ABAC export action: set it True only after reading the licence.
"""
from __future__ import annotations

from dataclasses import asdict

from .model import Labels

SOURCES = {
    "cisa-kev": Labels("cisa-kev", classification=1, tlp="CLEAR", reliability="A", credibility="1", license_redistribute=True),
    "first-epss": Labels("first-epss", classification=1, tlp="CLEAR", reliability="B", credibility="3", license_redistribute=True),
    "gdelt": Labels("gdelt", classification=1, tlp="CLEAR", reliability="C", credibility="4", license_redistribute=False),
    "nasa-firms": Labels("nasa-firms", classification=1, tlp="CLEAR", reliability="A", credibility="2", license_redistribute=True),
    "operator-assets": Labels("operator-assets", classification=2, tlp="AMBER", reliability="A", credibility="1", license_redistribute=False),
}


def labels_for(source: str, **override) -> Labels:
    base = SOURCES[source]
    return Labels(**{**asdict(base), **override}) if override else base

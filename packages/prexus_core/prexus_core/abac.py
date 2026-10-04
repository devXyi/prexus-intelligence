"""Attribute-based access control — default-deny, deny-overrides, every decision explainable.

This replaces role-only RBAC for anything classified. Attributes:
  subject    id, org, clearance 0-5, compartments{...}, roles{...}
  resource   classification 0-5, compartments{...}, tlp, owner_org, share_orgs{...}, recipients{...},
             license_redistribute (bool), allowed_purposes{...} (empty = any)
  action     read | write | export | admin
  environment network ("enclave"|"connected"), purpose (str)

Clearance levels (convention): 0 PUBLIC, 1 INTERNAL, 2 RESTRICTED, 3 CONFIDENTIAL, 4 SECRET, 5 TOP-SECRET.
National classification schemes differ; map yours onto 0-5 in configuration, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, FrozenSet, Iterable, List, Optional

POLICY_VERSION = "abac-1"
ACTIONS = ("read", "write", "export", "admin")
TLP_LEVELS = ("CLEAR", "GREEN", "AMBER", "AMBER+STRICT", "RED")
EXPORT_BLOCK_CLASSIFICATION = 3          # ≥ this may not leave through a connected network


@dataclass(frozen=True)
class Subject:
    id: str
    org: str
    clearance: int = 0
    compartments: FrozenSet[str] = frozenset()
    roles: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class Resource:
    classification: int = 0
    compartments: FrozenSet[str] = frozenset()
    tlp: str = "AMBER"
    owner_org: str = ""
    share_orgs: FrozenSet[str] = frozenset()
    recipients: FrozenSet[str] = frozenset()
    license_redistribute: bool = False
    allowed_purposes: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class Environment:
    network: str = "enclave"
    purpose: str = ""


@dataclass(frozen=True)
class Decision:
    allow: bool
    reasons: tuple
    policy_version: str = POLICY_VERSION

    def __bool__(self) -> bool:
        return self.allow


class PermissionDenied(Exception):
    def __init__(self, decision: Decision):
        super().__init__("; ".join(decision.reasons))
        self.decision = decision


Rule = Callable[[Subject, str, Resource, Environment], Optional[str]]


def _valid_inputs(s, a, r, e):
    if a not in ACTIONS:
        return f"unknown action {a!r}"
    if not (0 <= s.clearance <= 5) or not (0 <= r.classification <= 5):
        return "clearance/classification outside 0-5"
    if r.tlp not in TLP_LEVELS:
        return f"unknown TLP {r.tlp!r}"
    if e.network not in ("enclave", "connected"):
        return f"unknown network {e.network!r}"
    return None


def _clearance(s, a, r, e):
    if s.clearance < r.classification:
        return f"clearance {s.clearance} below classification {r.classification}"


def _need_to_know(s, a, r, e):
    missing = set(r.compartments) - set(s.compartments)
    if missing:
        return f"missing compartments {sorted(missing)}"


def _tlp(s, a, r, e):
    if r.tlp in ("CLEAR", "GREEN"):
        return None
    if r.tlp == "RED":
        return None if s.id in r.recipients else "TLP:RED is limited to named recipients"
    if r.tlp == "AMBER+STRICT":
        return None if s.org == r.owner_org else "TLP:AMBER+STRICT is limited to the originating organisation"
    if s.org == r.owner_org or s.org in r.share_orgs or s.id in r.recipients:      # AMBER
        return None
    return "TLP:AMBER is limited to the originating organisation and named recipients"


def _purpose(s, a, r, e):
    if r.allowed_purposes and e.purpose not in r.allowed_purposes:
        return f"purpose {e.purpose!r} not in allowed purposes {sorted(r.allowed_purposes)}"


def _export(s, a, r, e):
    if a != "export":
        return None
    if "exporter" not in s.roles:
        return "export requires the exporter role"
    if not r.license_redistribute:
        return "source licence does not permit redistribution"
    if r.classification >= EXPORT_BLOCK_CLASSIFICATION and e.network == "connected":
        return f"classification ≥ {EXPORT_BLOCK_CLASSIFICATION} may not be exported onto a connected network"
    if r.tlp == "RED":
        return "TLP:RED may not be exported"


def _write(s, a, r, e):
    if a != "write":
        return None
    if not ({"analyst", "admin"} & set(s.roles)):
        return "write requires the analyst or admin role"
    if s.clearance >= 4 and r.classification < s.clearance - 1:
        return "no write-down: high-clearance subjects may not create lower-classified records"


def _admin(s, a, r, e):
    if a == "admin" and "admin" not in s.roles:
        return "admin requires the admin role"


DEFAULT_RULES: tuple = (_clearance, _need_to_know, _tlp, _purpose, _export, _write, _admin)


def decide(subject: Subject, action: str, resource: Resource, env: Environment = Environment(),
           rules: Iterable[Rule] = DEFAULT_RULES) -> Decision:
    """Deny-overrides: any rule returning a reason denies. No rule ⇒ allow only after all passed."""
    bad = _valid_inputs(subject, action, resource, env)
    if bad:
        return Decision(False, (bad,))
    reasons: List[str] = [r for r in (rule(subject, action, resource, env) for rule in rules) if r]
    return Decision(not reasons, tuple(reasons) if reasons else ("all rules satisfied",))


def enforce(subject: Subject, action: str, resource: Resource, env: Environment = Environment(), *,
            ledger=None, resource_id: str = "") -> Decision:
    d = decide(subject, action, resource, env)
    if ledger is not None:
        ledger.append(subject.id, f"abac.{'allow' if d.allow else 'deny'}.{action}", resource_id or "resource",
                      {"classification": resource.classification, "tlp": resource.tlp, "reasons": list(d.reasons)})
    if not d.allow:
        raise PermissionDenied(d)
    return d

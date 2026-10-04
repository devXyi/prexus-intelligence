import itertools

import pytest

from prexus_core.abac import (Decision, Environment, PermissionDenied, Resource, Subject, decide, enforce)
from prexus_core.ledger import Ledger

fs = frozenset


def S(**kw):
    base = dict(id="u1", org="orgA", clearance=3, compartments=fs({"SIGINT"}), roles=fs({"analyst"}))
    base.update(kw)
    return Subject(**base)


def R(**kw):
    base = dict(classification=2, compartments=fs(), tlp="AMBER", owner_org="orgA")
    base.update(kw)
    return Resource(**base)


def test_default_allow_path_and_default_deny_on_garbage():
    assert decide(S(), "read", R()).allow
    assert not decide(S(), "teleport", R()).allow
    assert not decide(S(clearance=9), "read", R()).allow
    assert not decide(S(), "read", R(tlp="PURPLE")).allow


def test_clearance_and_compartments():
    assert not decide(S(clearance=2), "read", R(classification=3)).allow
    assert decide(S(clearance=3), "read", R(classification=3)).allow
    d = decide(S(), "read", R(compartments=fs({"HUMINT"})))
    assert not d.allow and "HUMINT" in d.reasons[0]
    assert decide(S(compartments=fs({"SIGINT", "HUMINT"})), "read", R(compartments=fs({"HUMINT"}))).allow


@pytest.mark.parametrize("tlp,subject_kw,res_kw,expected", [
    ("CLEAR", dict(org="x"), {}, True), ("GREEN", dict(org="x"), {}, True),
    ("AMBER", dict(org="orgA"), {}, True), ("AMBER", dict(org="orgB"), {}, False),
    ("AMBER", dict(org="orgB"), dict(share_orgs=fs({"orgB"})), True),
    ("AMBER+STRICT", dict(org="orgB"), dict(share_orgs=fs({"orgB"})), False),
    ("AMBER+STRICT", dict(org="orgA"), {}, True),
    ("RED", dict(org="orgA"), {}, False), ("RED", dict(org="orgA"), dict(recipients=fs({"u1"})), True),
])
def test_tlp_matrix(tlp, subject_kw, res_kw, expected):
    assert decide(S(**subject_kw), "read", R(tlp=tlp, **res_kw)).allow is expected


def test_purpose_limitation():
    r = R(allowed_purposes=fs({"defence-planning"}))
    assert not decide(S(), "read", r, Environment(purpose="marketing")).allow
    assert decide(S(), "read", r, Environment(purpose="defence-planning")).allow


def test_export_rules():
    exp = S(roles=fs({"exporter"}))
    r = R(license_redistribute=True)
    assert decide(exp, "export", r).allow
    assert not decide(S(), "export", r).allow                                     # no exporter role
    assert not decide(exp, "export", R(license_redistribute=False)).allow          # licence forbids
    assert not decide(exp, "export", R(license_redistribute=True, classification=3), Environment(network="connected")).allow
    assert decide(S(clearance=3, roles=fs({"exporter"})), "export", R(license_redistribute=True, classification=3), Environment(network="enclave")).allow
    assert not decide(exp, "export", R(license_redistribute=True, tlp="RED", recipients=fs({"u1"}))).allow


def test_write_and_admin_rules():
    assert decide(S(), "write", R()).allow
    assert not decide(S(roles=fs()), "write", R()).allow
    assert not decide(S(clearance=5), "write", R(classification=2)).allow           # no write-down
    assert decide(S(clearance=5), "write", R(classification=5)).allow
    assert not decide(S(), "admin", R()).allow and decide(S(roles=fs({"admin"})), "admin", R()).allow


def test_deny_overrides_and_reasons_are_complete():
    d = decide(S(clearance=1, org="zzz"), "read", R(classification=3, compartments=fs({"X"})))
    assert not d.allow and len(d.reasons) == 3          # clearance + compartments + TLP all reported


def test_monotonic_in_clearance_for_reads():
    """Raising clearance can never turn an allowed read into a denied one."""
    for cls, c1, c2 in itertools.product(range(6), range(6), range(6)):
        if c1 <= c2 and decide(S(clearance=c1), "read", R(classification=cls)).allow:
            assert decide(S(clearance=c2), "read", R(classification=cls)).allow


def test_enforce_logs_every_decision(tmp_path):
    led = Ledger(tmp_path)
    enforce(S(), "read", R(), ledger=led, resource_id="obj-1")
    with pytest.raises(PermissionDenied):
        enforce(S(clearance=0), "read", R(classification=4), ledger=led, resource_id="obj-2")
    acts = [e["action"] for e in led.events]
    assert acts == ["abac.allow.read", "abac.deny.read"] and led.events[1]["metadata"]["reasons"]

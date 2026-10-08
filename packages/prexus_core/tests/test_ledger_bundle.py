import json

import pytest

from prexus_core.bundle import BundleError, build_bundle, load_trusted_keys, verify_bundle_dir
from prexus_core.canonical import canonical
from prexus_core.ledger import GENESIS, Ledger, LedgerIntegrityError, Signer, verify_event_chain


def _ledger(tmp_path, n=5):
    s = Signer.generate()
    l = Ledger(tmp_path, s)
    for i in range(n):
        l.append("alice", f"a{i}", f"r{i}", {"i": i})
    l.close()
    return s


def _lines(p):
    return (p / "ledger.ndjson").read_text().splitlines()


def test_roundtrip_and_restart(tmp_path):
    s = _ledger(tmp_path)
    l = Ledger(tmp_path, s)
    assert l.valid and l.seq == 5
    l.append("bob", "x", "y")
    assert l.verify()["head_sequence"] == 6


def test_modified_deleted_reordered_detected(tmp_path):
    for name, mut in {
        "modified": lambda ls: (ls.__setitem__(2, json.dumps({**json.loads(ls[2]), "actor": "m"})), ls)[1],
        "deleted": lambda ls: (ls.pop(2), ls)[1],
        "reordered": lambda ls: (ls.__setitem__(slice(1, 3), [ls[2], ls[1]]), ls)[1],
    }.items():
        d = tmp_path / name; d.mkdir(); s = _ledger(d)
        (d / "ledger.ndjson").write_text("\n".join(mut(_lines(d))) + "\n")
        l = Ledger(d, s)
        assert not l.valid, name
        with pytest.raises(LedgerIntegrityError):
            l.append("a", "b", "c")


def test_truncation_and_replacement_caught_by_anchor(tmp_path):
    d = tmp_path / "t"; d.mkdir(); s = _ledger(d, 6)
    (d / "ledger.ndjson").write_text("\n".join(_lines(d)[:3]) + "\n")
    assert verify_event_chain([json.loads(x) for x in _lines(d)])["valid"]        # still a valid chain…
    assert "truncated or replaced" in Ledger(d, s).failure["reason"]              # …but not the attested one


def test_torn_write_recovered(tmp_path):
    s = _ledger(tmp_path, 3)
    with open(tmp_path / "ledger.ndjson", "ab") as f:
        f.write(b'{"v":2,"seq":4,"id":"half')
    l = Ledger(tmp_path, s)
    assert l.valid and l.events[-1]["action"] == "ledger.recovered" and l.verify()["valid"]


def test_concurrent_appends_are_serialised(tmp_path):
    import threading
    l = Ledger(tmp_path, Signer.generate())
    ts = [threading.Thread(target=lambda i=i: l.append("a", "c", str(i))) for i in range(100)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert l.seq == 100 and l.verify()["valid"]
    assert [e["seq"] for e in l.events] == list(range(1, 101))


def test_canonical_rejects_floats_and_non_ascii_keys():
    with pytest.raises(TypeError):
        canonical({"a": 1.5})
    with pytest.raises(TypeError):
        canonical({"é": 1})
    assert canonical({"b": True, "a": [None, 2]}) == '{"a":[null,2],"b":true}'


def test_bundle_roundtrip_and_attacks(tmp_path):
    s = Signer.generate(); imp = tmp_path / "imp"
    trust = tmp_path / "trust"; trust.mkdir(); (trust / "k.pem").write_text(s.public_pem)
    keys = load_trusted_keys(trust)
    root = build_bundle(imp, "data-pack", 2, {"x/y.txt": b"hello"}, s)
    manifest, _ = verify_bundle_dir(imp, root.name, keys)
    assert manifest["version"] == 2
    with pytest.raises(BundleError) as e:
        verify_bundle_dir(imp, root.name, keys, {"data-pack": 2}); assert e.value.status == 409
    (root / "files" / "x" / "y.txt").write_bytes(b"HELLO")                      # same size, different bytes
    with pytest.raises(BundleError, match="sha256"):
        verify_bundle_dir(imp, root.name, keys)
    other = Signer.generate()
    r2 = build_bundle(imp, "rogue-pack", 1, {"a": b"1"}, other)
    with pytest.raises(BundleError) as e:
        verify_bundle_dir(imp, r2.name, keys); assert e.value.status == 403
    with pytest.raises(BundleError):
        verify_bundle_dir(imp, "../../etc", keys)
    with pytest.raises(BundleError):
        build_bundle(imp, "bad-pack", 1, {"../evil": b"x"}, s)

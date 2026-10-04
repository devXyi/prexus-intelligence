"""One spec, two implementations: Python and Node must agree byte-for-byte."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from prexus_core.bundle import BundleError, build_bundle, load_trusted_keys, verify_bundle_dir
from prexus_core.canonical import canonical
from prexus_core.ledger import Ledger, Signer, verify_event_chain, verify_signed_head

ROOT = Path(__file__).resolve().parents[3]
CP = ROOT / "airgap" / "control-plane"
FIX = Path(__file__).parent / "fixtures" / "node_made"
node = shutil.which("node")
needs_node = pytest.mark.skipif(not node or not CP.exists(), reason="node / control-plane not available")


def _node(*args, stdin=None):
    return subprocess.run([node, *args], capture_output=True, text=True, input=stdin, cwd=CP, timeout=60)


def _rand_value(rng, depth=0):
    kinds = ["int", "str", "bool", "null"] + (["list", "dict"] if depth < 3 else [])
    k = rng.choice(kinds)
    if k == "int":
        return rng.choice([0, 1, -1, 42, 2**31, -2**40, 2**53 - 1])
    if k == "bool":
        return rng.random() < 0.5
    if k == "null":
        return None
    if k == "str":
        pool = ["", "plain", 'quo"te', "back\\slash", "nl\nx", "tab\t", "é✓日本", "\u2028sep", "\x00\x1f", "emoji 😀", "~!@ #"]
        return rng.choice(pool) + str(rng.randint(0, 99))
    if k == "list":
        return [_rand_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(["a", "B", "key z", "k_1", "~x", "A", "0", "m.n"]) + str(i): _rand_value(rng, depth + 1) for i in range(rng.randint(0, 4))}


@needs_node
def test_canonical_json_is_byte_identical_to_node():
    rng = random.Random(1234)
    cases = [_rand_value(rng) for _ in range(300)]
    script = ('import {canonical} from "./lib/canonical.mjs"; import {readFileSync} from "node:fs";'
              'const cs=JSON.parse(readFileSync(0,"utf8")); console.log(JSON.stringify(cs.map(c=>canonical(c))));')
    r = _node("--input-type=module", "-e", script, stdin=json.dumps(cases))
    assert r.returncode == 0, r.stderr
    node_out = json.loads(r.stdout)
    assert node_out == [canonical(c) for c in cases]


@needs_node
def test_python_ledger_verified_by_node_cli(tmp_path):
    signer = Signer.generate()
    led = Ledger(tmp_path / "led", signer)
    for i in range(6):
        led.append("py-user", f"act.{i}", f"res{i}", {"i": i, "s": "ünï \"q\" ✓", "ok": True, "none": None})
    led.close()
    pub = tmp_path / "pub.pem"; pub.write_text(signer.public_pem)
    f, anchor = tmp_path / "led" / "ledger.ndjson", tmp_path / "led" / "anchors" / "head.json"
    ok = _node("tools/verify-ledger.mjs", str(f), "--anchor", str(anchor), "--pubkey", str(pub))
    assert ok.returncode == 0, ok.stdout
    assert json.loads(ok.stdout)["valid"] is True
    lines = f.read_text().splitlines(); ev = json.loads(lines[2]); ev["actor"] = "mallory"; lines[2] = json.dumps(ev)
    f.write_text("\n".join(lines) + "\n")
    bad = _node("tools/verify-ledger.mjs", str(f))
    assert bad.returncode == 1 and "modified" in bad.stdout


def test_node_ledger_verified_by_python():
    events = [json.loads(l) for l in (FIX / "ledger" / "ledger.ndjson").read_text("utf-8").splitlines()]
    assert verify_event_chain(events)["valid"] is True
    anchor = json.loads((FIX / "ledger" / "anchors" / "head.json").read_text())
    assert verify_signed_head(anchor, (FIX / "signer.pub.pem").read_text()) is True
    assert anchor["sequence"] == len(events) and events[-1]["hash"] == anchor["head_hash"]


def test_python_can_reopen_a_node_written_ledger_and_continue(tmp_path):
    shutil.copytree(FIX / "ledger", tmp_path / "led")
    signer = Signer.load(FIX / "signer.key.pem")
    led = Ledger(tmp_path / "led", signer)
    assert led.valid and led.seq == 5
    led.append("py", "continued", "x", {"from": "python"})
    assert led.verify()["valid"] and led.verify()["head_sequence"] == 6
    led.close()


@needs_node
def test_python_bundle_verified_by_node_cli(tmp_path):
    signer = Signer.generate()
    root = build_bundle(tmp_path / "imp", "py-bundle", 7, {"a/b.txt": "hello ✓".encode(), "c.bin": b"\x00\x01\x02"}, signer,
                        file_meta={"a/b.txt": {"connector": "kev", "license": "CC0-1.0"}})
    trust = tmp_path / "trust"; trust.mkdir(); (trust / "k.pem").write_text(signer.public_pem)
    ok = _node("tools/verify-bundle.mjs", str(tmp_path / "imp"), root.name, str(trust))
    assert ok.returncode == 0, ok.stdout
    assert json.loads(ok.stdout) == {"valid": True, "name": "py-bundle", "version": 7, "files": 2}
    (root / "files" / "c.bin").write_bytes(b"EVIL")
    bad = _node("tools/verify-bundle.mjs", str(tmp_path / "imp"), root.name, str(trust))
    assert bad.returncode == 1 and "verification failed" in bad.stdout


def test_node_bundle_verified_by_python(tmp_path):
    (tmp_path / "trust").mkdir(); shutil.copy(FIX / "signer.pub.pem", tmp_path / "trust" / "node.pem")
    shutil.copy(FIX / "signer.key.pem", tmp_path / "trust" / "private.pem")      # must be ignored, not trusted
    trusted = load_trusted_keys(tmp_path / "trust")
    assert len(trusted) == 1
    manifest, _ = verify_bundle_dir(FIX / "import", "node-bundle-v3", trusted)
    assert manifest["name"] == "node-bundle" and manifest["version"] == 3 and len(manifest["files"]) == 2
    with pytest.raises(BundleError, match="rollback"):
        verify_bundle_dir(FIX / "import", "node-bundle-v3", trusted, {"node-bundle": 3})

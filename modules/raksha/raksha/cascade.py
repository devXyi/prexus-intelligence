"""Cascading-failure Monte Carlo on an infrastructure dependency graph (independent-cascade / percolation).

Each node fails initially with probability p_i; every edge u→v, once u has failed, propagates with
probability q_uv (one independent draw per edge per trial). Vectorised across trials; verified in
tests against exact enumeration on small graphs.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

MAX_NODES, MAX_EDGES, MAX_TRIALS = 500, 5000, 500_000


@dataclass
class Graph:
    nodes: Dict[str, float]                                  # id → initial failure probability
    edges: List[Tuple[str, str, float]] = field(default_factory=list)

    def validate(self) -> "Graph":
        if not self.nodes or len(self.nodes) > MAX_NODES or len(self.edges) > MAX_EDGES:
            raise ValueError(f"graph must have 1–{MAX_NODES} nodes and ≤{MAX_EDGES} edges")
        for n, p in self.nodes.items():
            if not 0.0 <= p <= 1.0:
                raise ValueError(f"node {n}: probability {p} outside [0,1]")
        for u, v, q in self.edges:
            if u not in self.nodes or v not in self.nodes:
                raise ValueError(f"edge {u}→{v} references an unknown node")
            if u == v or not 0.0 <= q <= 1.0:
                raise ValueError(f"edge {u}→{v}: invalid")
        return self

    def without(self, drop: Iterable[Tuple[str, str]]) -> "Graph":
        d = set(drop)
        return Graph(dict(self.nodes), [e for e in self.edges if (e[0], e[1]) not in d])


def simulate(g: Graph, trials: int, rng: np.random.Generator) -> Dict[str, object]:
    g.validate()
    if not 1 <= trials <= MAX_TRIALS:
        raise ValueError(f"trials must be in [1, {MAX_TRIALS}]")
    ids = list(g.nodes)
    ix = {n: i for i, n in enumerate(ids)}
    failed = rng.random((trials, len(ids))) < np.array([g.nodes[n] for n in ids])
    if g.edges:
        active = rng.random((trials, len(g.edges))) < np.array([e[2] for e in g.edges])
        src = np.array([ix[e[0]] for e in g.edges]); dst = np.array([ix[e[1]] for e in g.edges])
        for _ in range(len(ids)):                           # at most |V| rounds to reach the fixpoint
            before = failed.sum()
            for k in range(len(g.edges)):
                failed[:, dst[k]] |= failed[:, src[k]] & active[:, k]
            if failed.sum() == before:
                break
    p_fail = failed.mean(axis=0)
    size = failed.sum(axis=1)
    return {"p_fail": {n: float(p_fail[i]) for n, i in ix.items()}, "expected_failed": float(size.mean()),
            "p_any_failure": float((size > 0).mean()), "size_quantiles": {q: float(np.quantile(size, q)) for q in (0.5, 0.9, 0.99)},
            "trials": trials}


def exact(g: Graph) -> Dict[str, float]:
    """Exact marginal failure probabilities by enumerating node and edge states (|V|+|E| ≤ 18)."""
    g.validate()
    ids = list(g.nodes)
    if len(ids) + len(g.edges) > 18:
        raise ValueError("graph too large for exact enumeration")
    p_fail = {n: 0.0 for n in ids}
    for ns in itertools.product([0, 1], repeat=len(ids)):
        pn = np.prod([g.nodes[n] if s else 1 - g.nodes[n] for n, s in zip(ids, ns)])
        if pn == 0:
            continue
        for es in itertools.product([0, 1], repeat=len(g.edges)):
            pe = np.prod([e[2] if s else 1 - e[2] for e, s in zip(g.edges, es)]) if g.edges else 1.0
            if pe == 0:
                continue
            fail = {n for n, s in zip(ids, ns) if s}
            changed = True
            while changed:
                changed = False
                for (u, v, _), s in zip(g.edges, es):
                    if s and u in fail and v not in fail:
                        fail.add(v); changed = True
            for n in fail:
                p_fail[n] += pn * pe
    return p_fail


def edge_criticality(g: Graph, target: str, trials: int, seed: int) -> List[Dict[str, object]]:
    """How much does removing each dependency reduce the target's failure probability? (common random numbers)"""
    base = simulate(g, trials, np.random.default_rng(seed))["p_fail"][target]
    out = []
    for u, v, q in g.edges:
        alt = simulate(g.without([(u, v)]), trials, np.random.default_rng(seed))["p_fail"][target]
        out.append({"edge": [u, v], "q": q, "target_p_without_edge": alt, "reduction": base - alt})
    return sorted(out, key=lambda r: -r["reduction"])


def graph_from_spec(initial: Dict[str, float], deps: Sequence[Dict[str, object]]) -> Graph:
    return Graph(dict(initial), [(d["from"], d["to"], float(d["p"])) for d in deps]).validate()

"""Finding the best assignment.

Three searches over the same problem, all judging a complete assignment with
evaluate() and nothing else:

  oracle  enumerates every legal assignment. Exact and simple enough to trust,
          exponential in the number of slots, so it exists to be the test's
          independent answer on small instances, not to be used on a real week.
  exact   depth-first branch and bound on the bounds in evaluate.prefix_bound.
          Optimal when it finishes (`proven`); if it hits its node or time limit
          it returns the best found so far and says it is not proven.
  beam    keeps the `width` most promising partial assignments at each slot. No
          guarantee, no dependency, fast: the fallback for a week too large for
          `exact`, and a cross-check.

Strict mode requires every hard constraint met. Relaxed mode instead minimises
the total violation first and only then maximises the score: it finds the
CLOSEST plan when none is feasible (diagnose.py).

docs/optimizer-design.md Sec 5 recommended an exact solver from a library
(CP-SAT or a MILP) behind this same interface. None is installed here and
adding a dependency is the owner's call (D8), so this is dependency-free; a
solver adapter can be added later without touching anything above it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

from mealplanner.planning.evaluate import (
    EPS, Evaluation, evaluate, initial_partial, options, prefix_bound,
)
from mealplanner.planning.model import PlanningProblem

TIE = 1e-9


@dataclass
class SearchResult:
    best: Evaluation | None
    proven: bool              # every assignment was covered, so `best is None` proves infeasibility
    nodes: int
    method: str
    feasible_count: int | None = None     # the oracle only
    total_count: int | None = None
    upper_bound: float | None = None      # the CP-SAT model's ceiling on the score, when it has one


def _key(ev: Evaluation, relaxed: bool) -> tuple[float, float]:
    """Smaller is better: violation first (relaxed mode only), then higher objective."""
    return (ev.violation_measure if relaxed else 0.0, -ev.objective)


def _beats(a: tuple[float, float], b: tuple[float, float] | None) -> bool:
    if b is None:
        return True
    if a[0] < b[0] - TIE:
        return True
    return abs(a[0] - b[0]) <= TIE and a[1] < b[1] - TIE


def enumerate_assignments(problem: PlanningProblem) -> Iterator[tuple]:
    """Every legal complete assignment, in a fixed order."""
    partial = initial_partial(problem)
    open_slots = problem.open_slots()

    def rec(k: int):
        if k == len(open_slots):
            yield tuple(partial)
            return
        i = open_slots[k]
        for pick in options(problem, partial, i):
            partial[i] = pick
            yield from rec(k + 1)
        partial[i] = None

    yield from rec(0)


def oracle(problem: PlanningProblem, relaxed: bool = False) -> SearchResult:
    best, best_key, feasible, total = None, None, 0, 0
    for picks in enumerate_assignments(problem):
        total += 1
        ev = evaluate(problem, picks)
        if ev.feasible:
            feasible += 1
        if not (relaxed or ev.feasible) or not ev.legal:
            continue
        key = _key(ev, relaxed)
        if _beats(key, best_key):
            best, best_key = ev, key
    return SearchResult(best, True, total, "oracle", feasible, total)


class _Stop(Exception):
    pass


def exact(
    problem: PlanningProblem, *, relaxed: bool = False, node_limit: int = 200_000, time_limit_s: float | None = None,
) -> SearchResult:
    partial = initial_partial(problem)
    open_slots = problem.open_slots()
    state = {"best": None, "key": None, "nodes": 0}
    deadline = None if time_limit_s is None else time.monotonic() + time_limit_s

    def cannot_improve(bound) -> bool:
        if not relaxed and bound.violation > EPS:
            return True
        if state["key"] is None:
            return False
        lower = (bound.violation if relaxed else 0.0, -bound.objective)
        best = state["key"]
        if lower[0] > best[0] + TIE:
            return True
        return abs(lower[0] - best[0]) <= TIE and lower[1] >= best[1] - TIE

    def rec(k: int):
        if k == len(open_slots):
            ev = evaluate(problem, tuple(partial))
            if ev.legal and (relaxed or ev.feasible):
                key = _key(ev, relaxed)
                if _beats(key, state["key"]):
                    state["best"], state["key"] = ev, key
            return
        i = open_slots[k]
        scored = []
        for pick in options(problem, partial, i):
            partial[i] = pick
            scored.append((prefix_bound(problem, partial), pick))
        partial[i] = None
        scored.sort(key=lambda item: (item[0].violation, -item[0].objective))
        for bound, pick in scored:
            state["nodes"] += 1
            if state["nodes"] > node_limit or (deadline is not None and time.monotonic() > deadline):
                raise _Stop
            if cannot_improve(bound):
                continue
            partial[i] = pick
            rec(k + 1)
        partial[i] = None

    proven = True
    try:
        rec(0)
    except _Stop:
        proven = False
    return SearchResult(state["best"], proven, state["nodes"], "exact")


def beam(problem: PlanningProblem, *, relaxed: bool = False, width: int = 40) -> SearchResult:
    states = [initial_partial(problem)]
    nodes = 0
    for i in problem.open_slots():
        candidates = []
        for partial in states:
            for pick in options(problem, partial, i):
                nodes += 1
                extended = list(partial)
                extended[i] = pick
                bound = prefix_bound(problem, extended)
                if not relaxed and bound.violation > EPS:
                    continue
                candidates.append((bound, extended))
        candidates.sort(key=lambda item: (item[0].violation, -item[0].objective))
        states = [extended for _, extended in candidates[:width]]
        if not states:
            break
    best, best_key = None, None
    for partial in states:
        if any(p is None for p in partial):
            continue
        ev = evaluate(problem, tuple(partial))
        if ev.legal and (relaxed or ev.feasible):
            key = _key(ev, relaxed)
            if _beats(key, best_key):
                best, best_key = ev, key
    return SearchResult(best, False, nodes, "beam")


SHORT_EXACT_S = 2.0


def auto(
    problem: PlanningProblem, *, relaxed: bool = False, time_limit_s: float = 10.0, node_limit: int = 200_000,
    beam_width: int = 40,
) -> SearchResult:
    """The best plan available within a time limit, labelled honestly.

    A portfolio, because measured on synthetic weeks neither solver dominates
    (docs/optimizer-design.md Sec 12): the dependency-free exact search proves some
    weeks in a fraction of a second that CP-SAT takes many seconds over, and
    CP-SAT proves others the exact search cannot. So: a short exact search first;
    then, if OR-tools is installed, CP-SAT under the time limit; then a beam search;
    and the best plan found by any of them. A proof from either solver is returned
    as soon as it exists; an unfinished result says it is not proven, and carries
    CP-SAT's ceiling when it has one. This is what plan_week uses."""
    from mealplanner.planning import cpsat

    def keyed(result):
        return None if result is None or result.best is None else _key(result.best, relaxed)

    first = exact(problem, relaxed=relaxed, node_limit=node_limit, time_limit_s=min(SHORT_EXACT_S, time_limit_s))
    if first.proven:
        return SearchResult(first.best, True, first.nodes, "exact")
    found, nodes, ceiling, label = first, first.nodes, None, ["exact"]
    if cpsat.available():
        solved = cpsat.solve(problem, relaxed=relaxed, time_limit_s=time_limit_s)
        if solved.proven:
            return solved
        nodes, ceiling = nodes + solved.nodes, solved.upper_bound
        label.append("cpsat")
        if solved.best is not None and _beats(keyed(solved), keyed(found)):
            found = solved
    second = beam(problem, relaxed=relaxed, width=beam_width)
    label.append("beam")
    if second.best is not None and _beats(keyed(second), keyed(found)):
        found = second
    return SearchResult(found.best, False, nodes + second.nodes, "+".join(label), upper_bound=ceiling)


def solve(problem: PlanningProblem, method: str = "auto", **kwargs) -> SearchResult:
    """method: "auto" (default), "cpsat" (needs OR-tools), "exact", "beam" or "oracle"."""
    if method == "auto":
        return auto(problem, **kwargs)
    if method == "cpsat":
        from mealplanner.planning import cpsat
        return cpsat.solve(problem, **kwargs)
    if method == "exact":
        return exact(problem, **kwargs)
    if method == "beam":
        return beam(problem, **kwargs)
    if method == "oracle":
        return oracle(problem, **kwargs)
    raise ValueError(f"unknown method {method!r}")

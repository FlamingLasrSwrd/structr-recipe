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
from dataclasses import dataclass, replace
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


def beam(problem: PlanningProblem, *, relaxed: bool = False, width: int = 40,
         time_limit_s: float | None = None, finish: bool = True) -> SearchResult:
    """Keep the `width` best partial plans, slot by slot. Under a time limit the beam
    narrows to one, finishing greedily (extending only the best partial plan), as soon
    as the time left looks too short for the remaining slots at full width, judged by
    how long one partial plan has taken to extend so far. With `finish` it then still
    ends with a complete plan, possibly after the limit; without, it stops at the limit
    and returns none, for a caller that already has a plan."""
    deadline = None if time_limit_s is None else time.monotonic() + time_limit_s
    states = [initial_partial(problem)]
    nodes, spent, extended_states = 0, 0.0, 0
    open_slots = problem.open_slots()
    for k, i in enumerate(open_slots):
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0 and not finish:
                return SearchResult(None, False, nodes, "beam")
            per_state = spent / extended_states if extended_states else 0.0
            if width > 1 and per_state * width * (len(open_slots) - k) > left:
                width, states = 1, states[:1]      # not enough time at full width: finish greedily
        candidates = []
        for n, partial in enumerate(states):
            if n and deadline is not None and time.monotonic() > deadline:
                break          # out of time: extend only the best partial plans (they come first), at least one
            started = time.monotonic()
            for pick in options(problem, partial, i):
                nodes += 1
                extended = list(partial)
                extended[i] = pick
                bound = prefix_bound(problem, extended)
                if not relaxed and bound.violation > EPS:
                    continue
                candidates.append((bound, extended))
            spent += time.monotonic() - started
            extended_states += 1
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
CPSAT_SHARE = 2 / 3             # of the time left after the short exact search; the beam search has the rest


def auto(
    problem: PlanningProblem, *, relaxed: bool = False, time_limit_s: float = 10.0, node_limit: int = 200_000,
    beam_width: int = 40,
) -> SearchResult:
    """The best plan available within a time limit, labelled honestly.

    A portfolio, because measured on synthetic weeks neither solver dominates
    (docs/optimizer-design.md Sec 12): the dependency-free exact search proves some
    weeks in a fraction of a second that CP-SAT takes many seconds over, and
    CP-SAT proves others the exact search cannot. So: a short exact search first;
    then, if OR-tools is installed, CP-SAT with two thirds of the time left; then a
    beam search with the rest, finishing greedily if it runs out; and the best plan
    found by any of them. Each solver starts from a plan when there is one to start
    from: a household's first plan meeting everyone's hard targets, or a one-eater
    week solved at one portion. The whole takes about `time_limit_s` (the owner's decision,
    2026-09-28: the beam search had no limit, and a household's week took an hour).
    A proof from either solver is returned as soon as it exists; an unfinished result
    says it is not proven, and carries CP-SAT's ceiling when it has one. This is what
    plan_week uses."""
    from mealplanner.planning import cpsat

    def keyed(result):
        return None if result is None or result.best is None else _key(result.best, relaxed)

    deadline = time.monotonic() + time_limit_s
    seed = None
    default = problem.servings_eaten
    levels = [problem.portion_levels(e) for e in problem.eater_keys()]
    if len(levels) > 1 and not relaxed and cpsat.available():
        # Several eaters: meeting everyone's hard targets at once is the hard part. On the
        # owner's household (2026-09-28) no search found a plan in 30 s, and none exists at
        # one portion each (one person's energy floor is above the other's ceiling); CP-SAT
        # asked for any plan meeting them found one in 4 s. So start from that.
        start = cpsat.first_plan(problem, time_limit_s=time_limit_s * 0.4)
        if start.proven:
            return start                     # no plan meets every hard target
        if start.best is not None:
            seed = SearchResult(start.best, False, 0, "first plan")
    elif any(len(lv) > 1 for lv in levels) and all(default in lv for lv in levels):
        # Portions multiply every slot's choices, and on a real week no search found a
        # first plan in the time left. So solve the week at the default portion first,
        # and start from it: varying the portions can then only improve on it.
        base = auto(replace(problem, portions=(), eater_portions={}, _cache={}), relaxed=relaxed,
                    time_limit_s=time_limit_s * 0.4, node_limit=node_limit, beam_width=beam_width)
        if base.best is not None:
            # its picks eat the default everywhere: one eater's portion unset, several eaters' shares at it
            picks = base.best.picks
            ev = evaluate(problem, picks)
            if ev.legal:
                seed = SearchResult(ev, False, base.nodes, "one portion")
        time_limit_s *= 0.6

    first = exact(problem, relaxed=relaxed, node_limit=node_limit, time_limit_s=min(SHORT_EXACT_S, time_limit_s))
    if first.proven:
        return SearchResult(first.best, True, first.nodes, "exact")
    found, nodes, ceiling, label = first, first.nodes, None, ["exact"]
    if seed is not None and _beats(keyed(seed), keyed(found)):
        found, label = seed, [seed.method, "exact"]
    if cpsat.available():
        solved = cpsat.solve(problem, relaxed=relaxed, time_limit_s=max(0.1, (deadline - time.monotonic()) * CPSAT_SHARE),
                             hint=seed.best.picks if seed is not None else None)
        if solved.proven:
            return solved
        nodes, ceiling = nodes + solved.nodes, solved.upper_bound
        label.append("cpsat")
        if solved.best is not None and _beats(keyed(solved), keyed(found)):
            found = solved
    # the beam narrows to finish in its time, and completes its plan even if that runs over:
    # measured on households, its greedy plan beat CP-SAT's in the same time
    second = beam(problem, relaxed=relaxed, width=beam_width, time_limit_s=max(0.0, deadline - time.monotonic()))
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

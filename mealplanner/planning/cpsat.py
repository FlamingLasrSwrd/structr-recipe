"""The planner's problem as a CP-SAT model (OR-tools): the exact solver
docs/optimizer-design.md Sec 5 recommended, behind the same interface as the
dependency-free searches.

OR-tools is OPTIONAL: nothing else in the package imports it, and `available()`
says whether it can be. Install it into a virtualenv with
`pip install -r requirements-solver.txt`.

The model, per open slot s: exactly one of
  x[s,c]    cook recipe c fresh (only recipes legal for the slot);
  y[s,j,c]  eat the leftovers of recipe c, cooked at slot j (only where the cook
            has finished, the food still keeps, and j itself cooks c).
With several eaters (a household, data-model.md Sec 19 K5) each eats one of their own
portion levels at each slot they eat (q[s, e, k]), and each person's targets count
their own servings only.
Everything else is linear in these: the day's intake of a nutrient, each hard
target as a bound on it, the time and soft-exclusion terms, and the piecewise
nutrition fit (a variable capped by its linear pieces, clamped at zero with one
switch). The variety bonus, which depends on the nearest other use of the same
recipe, is a variable capped by one implication per pair of slots that could
both use it.

CP-SAT works in integers, so amounts and scores are scaled by 10^6 and rounded.
evaluate() stays the single source of truth: the plan CP-SAT finds is re-scored by
it, and `proven` is claimed only when the two agree. Stock and waste depend on how
cooks share lots by expiry, which is not linear, so when they carry weight and
there is stock the model uses their ceiling (the same one the searches use); the
result then reports the gap between that ceiling and the plan's true score, and
says it is not proven unless the gap is zero.

Relaxed mode finds the closest plan when none is feasible, in two solves: minimise
the total normalised violation, then maximise the score among plans that achieve it.
"""

from __future__ import annotations

from datetime import timedelta

from mealplanner.planning.evaluate import (
    baseline_in, basic_reason, evaluate, ineligible_reason, initial_partial, intake, meal_type_reason, resolve, slot_groups,
)
from mealplanner.planning.model import Pick, PlanningProblem
from mealplanner.planning.search import SearchResult
from mealplanner.scoring import NEUTRAL
from mealplanner.scoring import VARIETY_CAP_DAYS, time_fit_score

NS = 10**6          # scale for nutrient amounts
OS = 10**6          # scale for score terms
VS = 10**7          # scale for the violation measure
AGREE = 1e-4        # how closely the model's score and evaluate()'s must agree to claim a proof


def available() -> bool:
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError:
        return False
    return True


def _days(a, b) -> float:
    return abs((a - b).total_seconds()) / 86400.0


def solve(
    problem: PlanningProblem, *, relaxed: bool = False, time_limit_s: float = 20.0, workers: int = 1,
    hint: tuple | None = None,
) -> SearchResult:
    """Solve with CP-SAT. workers=1 makes the result reproducible: with several the
    solver may return a different, equally good plan from run to run. `hint`: a
    complete plan to start from (the search may leave it)."""
    if not available():
        raise RuntimeError("OR-tools is not installed (pip install -r requirements-solver.txt)")
    from ortools.sat.python import cp_model

    built = _build(problem, relaxed)
    if hint is not None:
        _hint(built, problem, hint)
    first = _run(built, problem, time_limit_s, workers, minimise_violation=relaxed)
    if relaxed and first["status"] in ("OPTIMAL", "FEASIBLE"):
        built["model"].add(built["violation"] <= first["value"])
        # Start the second solve from the first one's plan: it already meets the bound, and
        # with portions the tight bound left the search without a first solution in 60 s.
        for var in list(built["x"].values()) + list(built["y"].values()) + list(built["q"].values()):
            built["model"].add_hint(var, first["solver"].boolean_value(var))
        second = _run(built, problem, time_limit_s, workers, minimise_violation=False)
        second["proven"] = second.get("proven", False) and first.get("proven", False)
        first = second
    return _result(problem, built, first, relaxed)


def first_plan(problem: PlanningProblem, *, time_limit_s: float = 10.0) -> SearchResult:
    """The first plan CP-SAT finds that meets every hard target, with no regard to its score.
    Asked for nothing more, CP-SAT found one for the owner's household in 4 s, where the
    full solve found none in 30 (docs/optimizer-design.md Sec 12). `proven` with no plan:
    no plan meets them all. A plan found is never called optimal."""
    if not available():
        raise RuntimeError("OR-tools is not installed (pip install -r requirements-solver.txt)")
    built = _build(problem, False)
    run = _run(built, problem, time_limit_s, 1, minimise_violation=None)
    if run["status"] == "INFEASIBLE":
        return SearchResult(None, True, 0, "cpsat")
    if "picks" not in run:
        return SearchResult(None, False, 0, "cpsat")
    ev = evaluate(problem, run["picks"])
    return SearchResult(ev if ev.feasible else None, False, 0, "cpsat")


# ---------------------------------------------------------------- the model

def _build(problem: PlanningProblem, relaxed: bool) -> dict:
    from ortools.sat.python import cp_model

    m = cp_model.CpModel()
    w = problem.weights
    n = len(problem.slots)
    open_slots = problem.open_slots()
    open_set = set(open_slots)
    fixed_resolved, _ = resolve(problem, initial_partial(problem))
    candidates = sorted(problem.candidates.values(), key=lambda c: (c.name, c.id))

    x: dict = {}
    for i in open_slots:
        for c in candidates:
            if ineligible_reason(problem, i, c) is None:
                x[i, c.id] = m.new_bool_var(f"x_{i}_{c.id}")
    y: dict = {}
    for s in open_slots:
        for j in range(s):
            for c in candidates:
                if c.leftover_days is None or basic_reason(problem, c) is not None:
                    continue
                if meal_type_reason(problem, s, c) is not None:
                    continue
                if j in open_set:
                    if (j, c.id) not in x:
                        continue
                else:
                    source = fixed_resolved[j]
                    if source is None or source.kind != "cook" or source.candidate != c.id:
                        continue
                start = problem.slots[j].start
                ready = start + timedelta(minutes=c.minutes or 0.0)
                keeps = start + timedelta(days=c.leftover_days)
                if problem.slots[s].start < ready or problem.slots[s].start > keeps:
                    continue
                y[s, j, c.id] = m.new_bool_var(f"y_{s}_{j}_{c.id}")
                if j in open_set:
                    m.add_implication(y[s, j, c.id], x[j, c.id])

    by_slot: dict = {s: [] for s in open_slots}
    uses_of: dict = {}                     # (s, candidate id) -> the variables that mean "slot s eats candidate"
    for (s, cid), var in x.items():
        by_slot[s].append(var)
        uses_of.setdefault((s, cid), []).append(var)
    for (s, j, cid), var in y.items():
        by_slot[s].append(var)
        uses_of.setdefault((s, cid), []).append(var)
    for s in open_slots:
        if by_slot[s]:
            m.add_exactly_one(by_slot[s])
        else:
            m.add_bool_or([])              # nothing may fill this slot: the problem is infeasible

    # ---- portions: when they vary, each eater of an open slot eats one of their levels (a
    # one-hot q[s, e, k]), and "eater e eats recipe c at level k at slot s" is the product
    # of the two, z[s, c, e, k]
    levels = {e: problem.portion_levels(e) for e in problem.eater_keys()}
    q: dict = {}
    for s in open_slots:
        for e in problem.slot_eaters(s):
            if len(levels[e]) > 1:
                for k in range(len(levels[e])):
                    q[s, e, k] = m.new_bool_var(f"q_{s}_{e}_{k}")
                m.add_exactly_one(q[s, e, k] for k in range(len(levels[e])))
    portioned_var: dict = {}

    def portioned(s: int, cid: str, eater: str) -> list:
        """(variable, servings eaten) pairs whose sum is what an eater eats of recipe cid at slot s."""
        if (s, cid) not in uses_of or eater not in problem.slot_eaters(s):
            return []
        if (s, eater, 0) not in q:
            return [(var, levels[eater][0]) for var in uses_of[s, cid]]
        if (s, cid, eater) not in portioned_var:
            u = use(s, cid)
            pairs = []
            for k, level in enumerate(levels[eater]):
                z = m.new_bool_var(f"z_{s}_{cid}_{eater}_{k}")
                m.add_bool_and([u, q[s, eater, k]]).only_enforce_if(z)
                m.add_bool_or([u.negated(), q[s, eater, k].negated(), z])
                pairs.append((z, level))
            portioned_var[s, cid, eater] = pairs
        return portioned_var[s, cid, eater]

    use_var: dict = {}

    def use(s: int, cid: str):
        """A 0/1 variable that is 1 when open slot s eats candidate cid (fresh or as leftovers)."""
        if (s, cid) not in uses_of:
            return None
        if (s, cid) not in use_var:
            v = m.new_bool_var(f"use_{s}_{cid}")
            m.add(v == sum(uses_of[s, cid]))
            use_var[s, cid] = v
        return use_var[s, cid]

    objective: list = []                   # (variable, integer coefficient)
    constant = 0
    exact_stock = True

    # ---- time, soft exclusion, and the stock/waste ceiling: coefficients on x and y
    optimistic = bool(problem.lots) and (w.stock + w.waste) > 0
    exact_stock = not optimistic
    for (s, cid), var in x.items():
        c = problem.candidates[cid]
        coef = round(w.time * time_fit_score(c.minutes, w.time_budget_minutes) * OS) - round(c.soft_penalty * OS)
        if optimistic:
            coef += round((w.stock + w.waste) * OS)
        objective.append((var, coef))
    for (s, j, cid), var in y.items():
        c = problem.candidates[cid]
        objective.append((var, round(w.time * 1.0 * OS) - round(c.soft_penalty * OS)))

    # ---- variety
    if w.variety > 0:
        cap = round(w.variety * OS)
        for s in open_slots:
            b = m.new_int_var(0, cap, f"variety_{s}")
            objective.append((b, 1))
            for c in candidates:
                mine = use(s, c.id)
                if mine is None:
                    continue
                start = problem.slots[s].start
                for other in c.uses:
                    bonus = _days(start, other) / VARIETY_CAP_DAYS
                    if bonus < 1.0:
                        m.add(b <= round(bonus * cap)).only_enforce_if(mine)
                for t in range(n):
                    if t == s:
                        continue
                    days = _days(start, problem.slots[t].start) / VARIETY_CAP_DAYS
                    if days >= 1.0:
                        continue
                    if t in open_set:
                        theirs = use(t, c.id)
                        if theirs is not None:
                            m.add(b <= round(days * cap)).only_enforce_if([mine, theirs])
                    elif fixed_resolved[t] is not None and fixed_resolved[t].candidate == c.id:
                        m.add(b <= round(days * cap)).only_enforce_if(mine)

    # ---- nutrition targets
    violation_terms: list = []             # (variable or None, coefficient) for the relaxed measure
    violation_constant = 0
    for target in problem.targets:
        for label, indices in slot_groups(problem, target):
            known_fixed, unknown_fixed = baseline_in(problem, target, indices)
            terms, has_open, most = [], False, 0
            unknown_uses = []                  # choices that would put an entry with no figure in the group
            for i in indices:
                if target.eater not in problem.slot_eaters(i):
                    continue                   # this person does not eat this meal
                if i in open_set:
                    has_open = True
                    best = 0
                    for c in candidates:
                        amount = c.nutrients.get(target.nutrient)
                        if amount is None:
                            unknown_uses.extend(uses_of.get((i, c.id), []))
                            continue
                        for var, eaten in (portioned(i, c.id, target.eater) if amount else []):
                            coef = round(amount * eaten * NS)
                            best = max(best, coef)
                            terms.append((var, coef))
                    most += best
                else:
                    value = intake(problem, fixed_resolved[i], target.nutrient, target.eater)
                    if value is None:
                        unknown_fixed = True
                    else:
                        known_fixed += value
            total = sum(var * coef for var, coef in terms) + round(known_fixed * NS)
            ceiling = most + round(known_fixed * NS)          # the most this group could hold
            lo = None if target.minimum is None else round(target.minimum * NS)
            hi = None if target.maximum is None else round(target.maximum * NS)
            if target.hard:
                if relaxed:
                    if hi is not None:
                        if unknown_fixed:
                            # as group_violation: a total over the maximum is an overshoot, measured
                            # below; one under it cannot be certified with an entry that has no
                            # figure, which costs the full measure
                            over = m.new_bool_var(f"over_known_{target.name}_{label}")
                            m.add(total >= hi + 1).only_enforce_if(over)
                            m.add(total <= hi).only_enforce_if(over.negated())
                            violation_constant += VS
                            violation_terms.append((over, -VS))
                        slack = m.new_int_var(0, max(ceiling, 1), f"over_{target.name}_{label}")
                        m.add(slack >= total - hi)
                        scale = VS if hi > 0 else 1
                        measure = m.new_int_var(0, (ceiling * scale) // max(hi, 1) + scale, f"over_measure_{target.name}_{label}")
                        m.add(measure * max(hi, 1) >= slack * scale)
                        violation_terms.append((measure, 1))
                    if lo is not None and lo > 0:
                        slack = m.new_int_var(0, lo, f"short_{target.name}_{label}")
                        m.add(slack >= lo - total)
                        measure = m.new_int_var(0, VS, f"short_measure_{target.name}_{label}")
                        m.add(measure * lo >= slack * VS)
                        violation_terms.append((measure, 1))
                else:
                    if hi is not None:
                        if unknown_fixed:
                            m.add_bool_or([])          # a maximum cannot be certified against an entry with no figure
                        else:
                            m.add(total <= hi)
                    if lo is not None:
                        m.add(total >= lo)
            if not has_open or target.weight <= 0:
                continue
            cap = round(target.weight * OS)
            if target.hard and not relaxed:
                constant += cap                       # a feasible plan sits inside the range: fit 1
                continue
            neutral = round(target.weight * NEUTRAL * OS)   # a soft target over an unknown total (evaluate.soft_fit)
            if unknown_fixed and not target.hard:
                constant += neutral
                continue
            fit = m.new_int_var(0, cap, f"fit_{target.name}_{label}")
            keep = m.new_bool_var(f"fit_on_{target.name}_{label}")
            known = []
            if unknown_uses and not target.hard:
                unknown = m.new_bool_var(f"unknown_{target.name}_{label}")
                m.add_max_equality(unknown, unknown_uses)
                m.add(fit == neutral).only_enforce_if(unknown)
                known = [unknown.negated()]
            m.add(fit == 0).only_enforce_if([keep.negated()] + known)
            if lo is not None and lo > 0:
                m.add(fit * lo <= cap * total).only_enforce_if([keep] + known)
            if hi is not None and hi > 0:
                m.add(fit * hi + cap * total <= 2 * cap * hi).only_enforce_if([keep] + known)
            if hi is not None and hi == 0:
                m.add(total == 0).only_enforce_if([keep] + known)
            objective.append((fit, 1))

    model_objective = sum(var * coef for var, coef in objective)
    violation = sum(var * coef for var, coef in violation_terms) + violation_constant
    return {
        "model": m, "x": x, "y": y, "q": q, "levels": levels, "objective": model_objective, "constant": constant,
        "violation": violation, "exact_stock": exact_stock, "open": open_slots,
    }


# ---------------------------------------------------------------- solving

def _run(built: dict, problem: PlanningProblem, time_limit_s: float, workers: int, minimise_violation: bool | None) -> dict:
    """minimise_violation None: no objective, so the first plan the model allows ends the solve."""
    from ortools.sat.python import cp_model

    m = built["model"]
    if minimise_violation:
        m.minimize(built["violation"])
    elif minimise_violation is not None:
        m.maximize(built["objective"])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 1
    status = solver.solve(m)
    name = solver.status_name(status)
    out = {"status": name, "solver": solver, "proven": name in ("OPTIMAL", "INFEASIBLE")}
    if name in ("OPTIMAL", "FEASIBLE"):
        out["value"] = round(solver.objective_value)
        out["bound"] = solver.best_objective_bound
        out["picks"] = _picks(built, problem, solver)
    return out


def _hint(built: dict, problem: PlanningProblem, picks) -> None:
    m, levels = built["model"], built["levels"]
    resolved, _ = resolve(problem, list(picks))
    for s in problem.open_slots():
        pick, r = picks[s], resolved[s]
        if r is None or r.candidate is None:
            continue
        var = built["x"].get((s, r.candidate)) if pick.candidate is not None else built["y"].get((s, pick.source, r.candidate))
        if var is not None:
            m.add_hint(var, 1)
        for e, servings in r.shares:
            for k, level in enumerate(levels[e]):
                if (s, e, k) in built["q"]:
                    m.add_hint(built["q"][s, e, k], int(abs(level - servings) < 1e-9))


def _picks(built: dict, problem: PlanningProblem, solver) -> tuple:
    picks = initial_partial(problem)
    chosen = {}                                        # (slot, eater) -> the level eaten
    for (s, e, k), var in built["q"].items():
        if solver.boolean_value(var):
            chosen[s, e] = built["levels"][e][k]

    def amounts(s: int) -> dict:
        eaters = problem.slot_eaters(s)
        if len(eaters) == 1:
            return {"portion": chosen.get((s, eaters[0]))}
        return {"shares": tuple(chosen.get((s, e), built["levels"][e][0]) for e in eaters)}

    for (s, cid), var in built["x"].items():
        if solver.boolean_value(var):
            picks[s] = Pick(candidate=cid, **amounts(s))
    for (s, j, cid), var in built["y"].items():
        if solver.boolean_value(var):
            picks[s] = Pick(source=j, **amounts(s))
    return tuple(picks)


def _result(problem: PlanningProblem, built: dict, run: dict, relaxed: bool) -> SearchResult:
    status = run["status"]
    if status == "INFEASIBLE":
        return SearchResult(None, True, 0, "cpsat")
    if status not in ("OPTIMAL", "FEASIBLE"):
        return SearchResult(None, False, 0, "cpsat")
    ev = evaluate(problem, run["picks"])
    if not ev.legal or not (relaxed or ev.feasible):
        return SearchResult(None, False, 0, "cpsat")         # rounding put the model's plan outside evaluate()'s rules
    ceiling = (run["bound"] + built["constant"]) / OS if not relaxed else None
    proven = run["proven"] and status == "OPTIMAL"
    if not relaxed:
        proven = proven and ev.objective >= ceiling - AGREE
    return SearchResult(ev, proven, 0, "cpsat", upper_bound=ceiling)

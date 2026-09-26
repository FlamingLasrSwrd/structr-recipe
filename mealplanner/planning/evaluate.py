"""What an assignment means: whether it is legal, whether it meets the hard
constraints, and what it scores. The single source of truth: the oracle and the
searches only ever *bound* a partial assignment; the verdict on a complete one
is always evaluate().

An assignment gives every slot a Pick: a fresh cook of a recipe, or the
leftovers of an earlier cook. From it everything else is derived, never chosen
(docs/optimizer-design.md Sec 4.3):
  - servings cooked at a slot = servings eaten there + servings drawn by the
    leftover slots that point at it. Ingredients scale uniformly, so cooking 2
    of a 4-serving recipe uses half of it; nothing is wasted by rounding.
  - a nutrient's intake at a slot = servings eaten x the recipe's grams per
    serving. A leftover slot eats the source's recipe.

Semantics carried over unchanged from the selector (scoring.py): time fit,
nutrition fit, variety, soft exclusion, stock coverage and waste urgency. What
is new is that a scoped target is judged ONCE, on its group's final total, not
once per pick against a running total (Sec 2.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta, timezone

from mealplanner.planning.model import DIFFICULTY_ORDER, Pick, PlanningProblem, Target
from mealplanner.scoring import nutrition_fit_score, time_fit_score, variety_bonus, waste_urgency

EPS = 1e-9


# ---------------------------------------------------------------- assignments

def initial_partial(problem: PlanningProblem) -> list:
    """One entry per slot: the fixed Pick for a fixed slot, None for an open one."""
    partial = []
    for slot in problem.slots:
        fixed = slot.fixed
        if fixed is None:
            partial.append(None)
        elif fixed.candidate is not None:
            partial.append(Pick(candidate=fixed.candidate))
        else:
            partial.append(Pick(source=fixed.source))
    return partial


def slot_eaten(problem: PlanningProblem, i: int) -> float:
    fixed = problem.slots[i].fixed
    return fixed.eaten if fixed else problem.servings_eaten


@dataclass(frozen=True)
class Resolved:
    kind: str                     # "cook" or "leftover"
    candidate: str | None         # the recipe eaten (a leftover's is its source's)
    source: int | None
    eaten: float


def resolve(problem: PlanningProblem, partial) -> tuple[list, list]:
    """(what each assigned slot resolves to, servings cooked at each slot)."""
    n = len(problem.slots)
    resolved: list = [None] * n
    for i, pick in enumerate(partial):
        if pick is None:
            continue
        eaten = slot_eaten(problem, i)
        if pick.candidate is not None:
            resolved[i] = Resolved("cook", pick.candidate, None, eaten)
        else:
            source = resolved[pick.source] if 0 <= pick.source < i else None
            resolved[i] = Resolved("leftover", source.candidate if source else None, pick.source, eaten)
    cooked = [0.0] * n
    for i, r in enumerate(resolved):
        if r is None:
            continue
        if r.kind == "cook":
            cooked[i] += r.eaten
        elif r.source is not None and 0 <= r.source < n:
            cooked[r.source] += r.eaten
    for i, slot in enumerate(problem.slots):
        fixed = slot.fixed
        if fixed and fixed.candidate is not None and fixed.cooked is not None:
            cooked[i] = fixed.cooked          # a fixed entry states how much it cooks
    return resolved, cooked


# ---------------------------------------------------------------- eligibility

def hard_nutrients(problem: PlanningProblem) -> list[str]:
    key = ("hard_nutrients",)
    if key not in problem._cache:
        problem._cache[key] = sorted({t.nutrient for t in problem.targets if t.hard})
    return problem._cache[key]


def _nutrient_label(problem: PlanningProblem, nutrient: str) -> str:
    for target in problem.targets:
        if target.nutrient == nutrient and target.nutrient_name:
            return target.nutrient_name
    return nutrient


def basic_reason(problem: PlanningProblem, candidate) -> str | None:
    """Why this recipe may not be eaten at all, whether cooked or as leftovers:
    a hard exclusion, or nutrition that cannot decide a hard target (unknown, or
    resting on placeholder or unmarked data; docs/optimizer-design.md Sec 4.6).
    Static for a problem, so it is computed once per recipe."""
    key = ("basic", candidate.id)
    if key not in problem._cache:
        problem._cache[key] = _basic_reason(problem, candidate)
    return problem._cache[key]


def _basic_reason(problem: PlanningProblem, candidate) -> str | None:
    if candidate.hard_excluded:
        return "requires an excluded ingredient"
    for nutrient in hard_nutrients(problem):
        label = _nutrient_label(problem, nutrient)
        if candidate.nutrients.get(nutrient) is None:
            return f"no {label} data, and a hard target needs it"
        if nutrient in candidate.untrusted:
            return f"its {label} figure is placeholder or unmarked, and a hard target needs sourced data"
    return None


def ineligible_reason(problem: PlanningProblem, i: int, candidate) -> str | None:
    """Why this recipe cannot be cooked fresh at open slot i, or None if it can.
    Static for a problem, so it is computed once per (slot, recipe)."""
    key = ("elig", i, candidate.id)
    if key not in problem._cache:
        problem._cache[key] = _ineligible_reason(problem, i, candidate)
    return problem._cache[key]


def _ineligible_reason(problem: PlanningProblem, i: int, candidate) -> str | None:
    slot = problem.slots[i]
    if slot.meal_type is not None and slot.meal_type not in candidate.meal_types:
        return f"not tagged for {slot.meal_type}"
    reason = basic_reason(problem, candidate)
    if reason:
        return reason
    cap = problem.max_difficulty
    if cap is not None:
        if candidate.difficulty is None:
            return "difficulty not stated, and a cap is set"
        if DIFFICULTY_ORDER.index(candidate.difficulty) > DIFFICULTY_ORDER.index(cap):
            return f"harder than {cap}"
    return None


def leftover_reason(problem: PlanningProblem, resolved, j: int, i: int) -> str | None:
    """Why slot i cannot eat the leftovers of the cook at slot j, or None if it can.
    Meal type is not checked: leftovers may serve any slot (last night's dinner at
    lunch)."""
    source = resolved[j] if 0 <= j < i else None
    if source is None or source.kind != "cook":
        return "the source is not a fresh cook"
    candidate = problem.candidates[source.candidate]
    if candidate.leftover_days is None:
        return "leftovers of this recipe are not planned"
    start = problem.slots[j].start
    now = problem.slots[i].start
    if now < start + timedelta(minutes=candidate.minutes or 0.0):
        return "not cooked yet"
    if now > start + timedelta(days=candidate.leftover_days):
        return "past its keeping time"
    return basic_reason(problem, candidate)


def options(problem: PlanningProblem, partial, i: int) -> list:
    """Every legal Pick for open slot i given the picks before it, in a fixed
    order (recipes by name, then leftovers by source) so results are deterministic."""
    key = ("cooks", i)
    if key not in problem._cache:
        problem._cache[key] = tuple(
            Pick(candidate=c.id)
            for c in sorted(problem.candidates.values(), key=lambda c: (c.name, c.id))
            if ineligible_reason(problem, i, c) is None
        )
    picks = list(problem._cache[key])
    if any(c.leftover_days is not None for c in problem.candidates.values()):
        resolved, _ = resolve(problem, partial[:i] + [None] * (len(partial) - i))
        for j in range(i):
            if leftover_reason(problem, resolved, j, i) is None:
                picks.append(Pick(source=j))
    return picks


def slot_max_intake(problem: PlanningProblem, i: int, nutrient: str) -> float:
    """The most of `nutrient` open slot i could possibly take in: an upper bound,
    so pruning on it is safe."""
    key = ("max_intake", i, nutrient)
    if key not in problem._cache:
        eaten = slot_eaten(problem, i)
        best = 0.0
        for c in problem.candidates.values():
            amount = c.nutrients.get(nutrient)
            if amount is None or basic_reason(problem, c) is not None:
                continue
            if c.leftover_days is not None or ineligible_reason(problem, i, c) is None:
                best = max(best, amount * eaten)
        problem._cache[key] = best
    return problem._cache[key]


# ---------------------------------------------------------------- nutrition

def slot_groups(problem: PlanningProblem, target: Target) -> list[tuple[str, list[int]]]:
    n = len(problem.slots)
    if target.scope == "per_meal":
        return [(problem.slots[i].key, [i]) for i in range(n)]
    if target.scope == "weekly":
        return [("week", list(range(n)))] if n else []
    days: dict[str, list[int]] = {}
    for i, slot in enumerate(problem.slots):
        days.setdefault(slot.start.astimezone(timezone.utc).date().isoformat(), []).append(i)
    return sorted(days.items())


def intake(problem: PlanningProblem, r: Resolved, nutrient: str) -> float | None:
    if r.candidate is None:
        return None
    amount = problem.candidates[r.candidate].nutrients.get(nutrient)
    return None if amount is None else amount * r.eaten


@dataclass
class GroupState:
    target: Target
    label: str
    slots: list
    total: float          # known intake so far; a lower bound if `unknown`
    unknown: bool         # some assigned slot has no figure
    unassigned: int       # open slots not yet assigned
    gain: float           # the most the unassigned open slots could still add
    has_open: bool = False  # the group contains at least one slot the planner decides


def group_states(problem: PlanningProblem, resolved) -> list[GroupState]:
    states = []
    for target in problem.targets:
        for label, indices in slot_groups(problem, target):
            total, unknown, unassigned, gain, has_open = 0.0, False, 0, 0.0, False
            for i in indices:
                open_slot = problem.slots[i].fixed is None
                has_open = has_open or open_slot
                r = resolved[i]
                if r is None:
                    unassigned += 1
                    gain += slot_max_intake(problem, i, target.nutrient)
                    continue
                value = intake(problem, r, target.nutrient)
                if value is None:
                    unknown = True
                else:
                    total += value
            states.append(GroupState(target, label, indices, total, unknown, unassigned, gain, has_open))
    return states


def _relative(amount: float, base: float) -> float:
    return amount / base if base > 0 else amount


def group_violation(g: GroupState) -> tuple[str | None, float, float | None]:
    """(kind, normalized measure, the bound broken) for a hard target's group.

    Totals only grow as meals are added, so a maximum can be broken while the
    group is still incomplete, and a minimum only counts as broken if even the
    best possible remaining picks cannot reach it. A group holding an entry with
    no figure cannot be certified against a maximum, and a shortfall against a
    minimum might be closed by the missing figure: both are "unverifiable", which
    a hard target treats as not met (docs/optimizer-design.md Sec 4.6)."""
    t = g.target
    if t.maximum is not None:
        if g.total > t.maximum + EPS:
            return "above_max", _relative(g.total - t.maximum, t.maximum), t.maximum
        if g.unassigned == 0 and g.unknown:
            return "unverifiable", 1.0, t.maximum
    if t.minimum is not None:
        if g.unassigned == 0:
            if g.total + EPS < t.minimum:
                return ("unverifiable" if g.unknown else "below_min"), _relative(t.minimum - g.total, t.minimum), t.minimum
        elif not g.unknown and g.total + g.gain + EPS < t.minimum:
            return "below_min", _relative(t.minimum - g.total - g.gain, t.minimum), t.minimum
    return None, 0.0, None


# ---------------------------------------------------------------- variety, stock

def variety_bonuses(problem: PlanningProblem, resolved) -> dict[int, float]:
    """For each open, assigned slot: the variety bonus, from the distance in days
    to the nearest OTHER use of the same recipe, whether another slot of this
    plan (fresh or leftover) or an outside use (`Candidate.uses`). Adding a use
    can only shrink it, which is what makes the value at a partial assignment an
    upper bound."""
    uses = [(i, r.candidate) for i, r in enumerate(resolved) if r is not None and r.candidate is not None]
    out = {}
    for i, r in enumerate(resolved):
        if r is None or r.candidate is None or problem.slots[i].fixed is not None:
            continue
        start = problem.slots[i].start
        nearest = None
        for j, candidate in uses:
            if j != i and candidate == r.candidate:
                days = abs((start - problem.slots[j].start).total_seconds()) / 86400.0
                nearest = days if nearest is None else min(nearest, days)
        for used in problem.candidates[r.candidate].uses:
            days = abs((start - used).total_seconds()) / 86400.0
            nearest = days if nearest is None else min(nearest, days)
        out[i] = variety_bonus(nearest)
    return out


def allocate_stock(problem: PlanningProblem, resolved, cooked) -> dict[int, tuple[float | None, float]]:
    """{slot: (stock coverage, waste urgency)} for every assigned cook slot.

    Cooks are served in time order, each from the eligible lots that are still
    good when it starts, the soonest-expiring first: for demands that need a lot
    to outlive them, that order maximises what stock can cover. Coverage is the
    mean over the recipe's pools of the fraction of its need met (the selector
    averages per ingredient the same way); urgency is the selector's, taken from
    the soonest-expiring lot still good at the cook's start."""
    if not problem.lots:
        return {}
    pools: dict[str, list] = {}
    for lot in problem.lots:
        pools.setdefault(lot.pool, []).append([lot.expires, lot.grams])
    for lots in pools.values():
        lots.sort(key=lambda lot: (lot[0] is None, lot[0].timestamp() if lot[0] else 0.0))
    out = {}
    for i, r in enumerate(resolved):
        if r is None or r.kind != "cook" or cooked[i] <= 0:
            continue
        candidate = problem.candidates[r.candidate]
        start = problem.slots[i].start
        coverages, urgency = [], 0.0
        for pool in sorted(candidate.demand):
            need = candidate.demand[pool] * cooked[i] / candidate.yield_servings
            if need <= 0:
                continue
            valid = [lot for lot in pools.get(pool, []) if lot[1] > EPS and (lot[0] is None or lot[0] > start)]
            soonest = min((lot[0] for lot in valid if lot[0] is not None), default=None)
            if soonest is not None:
                urgency = max(urgency, waste_urgency((soonest - start).total_seconds() / 86400.0))
            got = 0.0
            for lot in valid:
                take = min(lot[1], need - got)
                lot[1] -= take
                got += take
                if need - got <= EPS:
                    break
            coverages.append(min(1.0, got / need))
        out[i] = (sum(coverages) / len(coverages) if coverages else None, urgency)
    return out


# ---------------------------------------------------------------- evaluation

@dataclass
class Violation:
    target: str
    nutrient: str
    group: str
    kind: str                 # "above_max", "below_min", "unverifiable"
    total: float
    bound: float | None
    measure: float


@dataclass
class Evaluation:
    picks: tuple
    legal: bool
    problems: list
    violations: list
    violation_measure: float
    objective: float
    terms: dict
    slot_details: list = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.legal and not self.violations


def _violations(problem: PlanningProblem, groups) -> list[Violation]:
    found = []
    for g in groups:
        if not g.target.hard:
            continue
        kind, measure, bound = group_violation(g)
        if kind:
            found.append(Violation(g.target.name, _nutrient_label(problem, g.target.nutrient), g.label, kind, g.total, bound, measure))
    return found


def _time_term(problem: PlanningProblem, r: Resolved) -> float:
    if r.kind == "leftover":
        return 1.0                                    # nothing to cook, so nothing to overrun
    return time_fit_score(problem.candidates[r.candidate].minutes, problem.weights.time_budget_minutes)


def evaluate(problem: PlanningProblem, picks) -> Evaluation:
    """Check and score a COMPLETE assignment (one Pick per slot, fixed slots
    included and unchanged)."""
    picks = tuple(picks)
    n = len(problem.slots)
    if len(picks) != n:
        raise ValueError(f"expected {n} picks, got {len(picks)}")
    partial = list(picks)
    resolved, cooked = resolve(problem, partial)
    problems = []
    fixed_picks = initial_partial(problem)
    for i, slot in enumerate(problem.slots):
        pick = picks[i]
        if slot.fixed is not None:
            if pick != fixed_picks[i]:
                problems.append(f"{slot.key}: a fixed entry cannot be changed")
            continue
        if pick.candidate is not None:
            candidate = problem.candidates.get(pick.candidate)
            if candidate is None:
                problems.append(f"{slot.key}: unknown recipe {pick.candidate!r}")
                continue
            reason = ineligible_reason(problem, i, candidate)
        else:
            reason = leftover_reason(problem, resolved, pick.source, i)
        if reason:
            problems.append(f"{slot.key}: {reason}")

    weights = problem.weights
    groups = group_states(problem, resolved)
    violations = _violations(problem, groups)
    bonuses = variety_bonuses(problem, resolved)
    stock = allocate_stock(problem, resolved, cooked)

    terms = {"time": 0.0, "variety": 0.0, "nutrition": 0.0, "stock": 0.0, "waste": 0.0, "soft_exclusion": 0.0}
    details = []
    for i, slot in enumerate(problem.slots):
        r = resolved[i]
        if slot.fixed is not None or r is None or r.candidate is None:
            continue
        candidate = problem.candidates[r.candidate]
        time_fit = _time_term(problem, r)
        coverage, urgency = stock.get(i, (None, 0.0))
        terms["time"] += weights.time * time_fit
        terms["variety"] += weights.variety * bonuses.get(i, 1.0)
        terms["soft_exclusion"] -= candidate.soft_penalty
        terms["stock"] += weights.stock * (coverage or 0.0)
        terms["waste"] += weights.waste * urgency
        details.append({
            "slot": slot.key, "kind": r.kind, "recipe": candidate.name,
            "source": problem.slots[r.source].key if r.source is not None else None,
            "time_fit": time_fit, "variety": bonuses.get(i, 1.0), "coverage": coverage, "urgency": urgency,
            "cooked_servings": cooked[i] if r.kind == "cook" else 0.0,
        })
    for g in groups:
        if g.has_open:
            terms["nutrition"] += g.target.weight * nutrition_fit_score(g.total, g.target.minimum, g.target.maximum)
    return Evaluation(
        picks=picks, legal=not problems, problems=problems, violations=violations,
        violation_measure=sum(v.measure for v in violations), objective=sum(terms.values()),
        terms=terms, slot_details=details,
    )


# ---------------------------------------------------------------- partial bounds

@dataclass
class Bound:
    violation: float          # a lower bound on the eventual violation measure
    objective: float          # an upper bound on the eventual objective


def prefix_bound(problem: PlanningProblem, partial) -> Bound:
    """Bounds that hold for EVERY way of completing a partial assignment (None
    marks an unassigned open slot). Sound by construction, so a search may prune
    on them: totals only grow, the variety bonus of an already-placed slot can
    only shrink as uses are added, and every term of an unplaced slot is at most
    its weight. Stock and waste are bounded by their weights rather than
    computed, because a later leftover slot changes how much an earlier cook
    must produce. tests/test_planning_search.py checks the bound against
    evaluate() on every prefix of random assignments."""
    resolved, _ = resolve(problem, partial)
    groups = group_states(problem, resolved)
    weights = problem.weights
    violation = sum(group_violation(g)[1] for g in groups if g.target.hard)
    bonuses = variety_bonuses(problem, resolved)
    ceiling = 0.0
    for i, slot in enumerate(problem.slots):
        if slot.fixed is not None:
            continue
        r = resolved[i]
        if r is None:
            ceiling += weights.time + weights.variety + weights.stock + weights.waste
            continue
        if r.candidate is None:
            continue
        ceiling += weights.time * _time_term(problem, r) + weights.variety * bonuses.get(i, 1.0)
        ceiling -= problem.candidates[r.candidate].soft_penalty
        if r.kind == "cook":
            ceiling += weights.stock + weights.waste
    for g in groups:
        if not g.has_open:
            continue
        t = g.target
        if g.unassigned == 0:
            ceiling += t.weight * nutrition_fit_score(g.total, t.minimum, t.maximum)
        elif t.maximum is not None and g.total > t.maximum:
            ceiling += t.weight * nutrition_fit_score(g.total, t.minimum, t.maximum)   # can only get worse
        else:
            ceiling += t.weight
    return Bound(violation, ceiling)

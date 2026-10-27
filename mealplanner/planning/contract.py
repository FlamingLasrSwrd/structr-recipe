"""The planner's JSON contract: a problem in, a plan out (docs/architecture-decision.md §7a, stage 4).

Under Path S a Structr method builds the week's problem and a worker that touches no graph searches
it; the plan goes back to be committed. This module is that boundary. problem_to_json and
problem_from_json turn a PlanningProblem into plain JSON and back, exactly, so a problem built in
JavaScript is searched exactly as one extract.build_problem built; plan_to_json says what the search
chose, by slot, in the problem's own terms.

As JSON: a time is ISO 8601 with its offset, a set is a sorted list, candidates are a list in the
problem's order (which breaks ties in the search), and everything else is as the dataclasses in
model.py name it. FORMAT is the contract's version: a problem of another version is refused, never
guessed at.
"""

from __future__ import annotations

from datetime import datetime

from mealplanner.planning.evaluate import initial_partial
from mealplanner.planning.model import (Candidate, Fixed, Lot, Pick, PlanningProblem, PrepSession, Request, Slot, Target,
                                        Weights)

FORMAT = 1


class ContractError(ValueError):
    pass


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ContractError(f"{value!r}: a time needs its offset")
    return parsed


def _candidate(c: Candidate) -> dict:
    return {"id": c.id, "name": c.name, "meal_types": sorted(c.meal_types), "minutes": c.minutes, "difficulty": c.difficulty,
            "yield_servings": c.yield_servings, "nutrients": dict(c.nutrients), "untrusted": sorted(c.untrusted),
            "demand": dict(c.demand), "hard_excluded": c.hard_excluded, "soft_penalty": c.soft_penalty,
            "leftover_days": c.leftover_days, "uses": [_time(t) for t in c.uses], "recipe": c.recipe,
            "ahead_hours": c.ahead_hours}


def _from_candidate(d: dict) -> Candidate:
    return Candidate(id=d["id"], name=d["name"], meal_types=frozenset(d["meal_types"]), minutes=d["minutes"],
                     difficulty=d["difficulty"], yield_servings=d["yield_servings"], nutrients=dict(d["nutrients"]),
                     untrusted=frozenset(d["untrusted"]), demand=dict(d["demand"]), hard_excluded=d["hard_excluded"],
                     soft_penalty=d["soft_penalty"], leftover_days=d["leftover_days"],
                     uses=tuple(_parse_time(t) for t in d["uses"]), recipe=d["recipe"], ahead_hours=d["ahead_hours"])


def _fixed(f: Fixed | None) -> dict | None:
    if f is None:
        return None
    return {"eaten": f.eaten, "candidate": f.candidate, "source": f.source, "cooked": f.cooked, "name": f.name,
            "entry_id": f.entry_id, "shares": [[eater, servings] for eater, servings in f.shares]}


def _from_fixed(d: dict | None) -> Fixed | None:
    if d is None:
        return None
    return Fixed(eaten=d["eaten"], candidate=d["candidate"], source=d["source"], cooked=d["cooked"], name=d["name"],
                 entry_id=d["entry_id"], shares=tuple((eater, servings) for eater, servings in d["shares"]))


def _slot(s: Slot) -> dict:
    return {"key": s.key, "start": _time(s.start), "meal_type": s.meal_type, "fixed": _fixed(s.fixed),
            "eaters": list(s.eaters) if s.eaters is not None else None}


def _from_slot(d: dict) -> Slot:
    return Slot(key=d["key"], start=_parse_time(d["start"]), meal_type=d["meal_type"], fixed=_from_fixed(d["fixed"]),
                eaters=tuple(d["eaters"]) if d["eaters"] is not None else None)


def _target(t: Target) -> dict:
    return {"name": t.name, "nutrient": t.nutrient, "scope": t.scope, "minimum": t.minimum, "maximum": t.maximum,
            "hard": t.hard, "weight": t.weight, "nutrient_name": t.nutrient_name, "day_boundary": t.day_boundary,
            "eater": t.eater}


def _lot(lot: Lot) -> dict:
    return {"pool": lot.pool, "grams": lot.grams, "expires": _time(lot.expires), "name": lot.name}


def _weights(w: Weights) -> dict:
    return {"time": w.time, "variety": w.variety, "stock": w.stock, "waste": w.waste,
            "time_budget_minutes": w.time_budget_minutes, "cooking_time": w.cooking_time, "repeats": w.repeats}


def _prep(p: PrepSession) -> dict:
    return {"key": p.key, "start": _time(p.start), "minutes": p.minutes, "dishes": p.dishes}


def _request(r: Request) -> dict:
    return {"name": r.name, "candidates": sorted(r.candidates), "slot": r.slot}


def problem_to_json(p: PlanningProblem) -> dict:
    """The problem as plain JSON (dicts, lists, strings, numbers, booleans and nulls only)."""
    return {
        "format": FORMAT,
        "slots": [_slot(s) for s in p.slots],
        "candidates": [_candidate(c) for c in p.candidates.values()],
        "targets": [_target(t) for t in p.targets],
        "lots": [_lot(lot) for lot in p.lots],
        "weights": _weights(p.weights),
        "now": _time(p.now),
        "max_difficulty": p.max_difficulty,
        "servings_eaten": p.servings_eaten,
        "notes": list(p.notes),
        "baseline": dict(p.baseline),
        "units": dict(p.units),
        "portions": list(p.portions),
        "eaters": list(p.eaters),
        "eater_portions": {e: list(levels) for e, levels in p.eater_portions.items()},
        "baselines": {e: dict(b) for e, b in p.baselines.items()},
        "eater_names": dict(p.eater_names),
        "book_size": p.book_size,
        "requests": [_request(r) for r in p.requests],
        "preps": [_prep(s) for s in p.preps],
        "repeat_tolerance": p.repeat_tolerance,
    }


def problem_from_json(d: dict) -> PlanningProblem:
    """The problem again, checked by PlanningProblem as any problem is. Refuses another FORMAT."""
    if d.get("format") != FORMAT:
        raise ContractError(f"a problem of format {d.get('format')!r}; this planner reads format {FORMAT}")
    candidates = [_from_candidate(c) for c in d["candidates"]]
    return PlanningProblem(
        slots=tuple(_from_slot(s) for s in d["slots"]),
        candidates={c.id: c for c in candidates},
        targets=tuple(Target(**t) for t in d["targets"]),
        lots=tuple(Lot(pool=x["pool"], grams=x["grams"], expires=_parse_time(x["expires"]), name=x["name"]) for x in d["lots"]),
        weights=Weights(**d["weights"]),
        now=_parse_time(d["now"]),
        max_difficulty=d["max_difficulty"],
        servings_eaten=d["servings_eaten"],
        notes=list(d["notes"]),
        baseline=dict(d["baseline"]),
        units=dict(d["units"]),
        portions=tuple(d["portions"]),
        eaters=tuple(d["eaters"]),
        eater_portions={e: tuple(levels) for e, levels in d["eater_portions"].items()},
        baselines={e: dict(b) for e, b in d["baselines"].items()},
        eater_names=dict(d["eater_names"]),
        book_size=d["book_size"],
        requests=tuple(Request(name=r["name"], candidates=frozenset(r["candidates"]), slot=r["slot"]) for r in d["requests"]),
        preps=tuple(PrepSession(key=s["key"], start=_parse_time(s["start"]), minutes=s["minutes"], dishes=s["dishes"])
                    for s in d["preps"]),
        repeat_tolerance=d["repeat_tolerance"],
    )


def plan_to_json(p: PlanningProblem, picks, *, objective: float, legal: bool, proven: bool, method: str,
                 upper_bound: float | None = None, report: str = "") -> dict:
    """What the search chose for each open slot, by the slot's key: a fresh cook (its candidate,
    portion or one portion per eater, prep session) or the leftovers of an earlier slot (by key).
    A fixed slot is marked so, and stays as the problem has it."""
    chosen = []
    for slot, pick in zip(p.slots, picks):
        if slot.fixed is not None:
            chosen.append({"slot": slot.key, "fixed": True})
            continue
        chosen.append({"slot": slot.key, "fixed": False, "candidate": pick.candidate,
                       "leftovers_of": p.slots[pick.source].key if pick.source is not None else None,
                       "portion": pick.portion, "shares": list(pick.shares) if pick.shares is not None else None,
                       "prep": p.preps[pick.prep].key if pick.prep is not None else None})
    return {"format": FORMAT, "objective": objective, "legal": legal, "proven": proven, "method": method,
            "upper_bound": upper_bound, "picks": chosen, "report": report}


def picks_from_json(p: PlanningProblem, d: dict) -> list:
    """The picks of a plan_to_json result, for the problem it was made for (checked against its slots)."""
    if d.get("format") != FORMAT:
        raise ContractError(f"a plan of format {d.get('format')!r}; this planner reads format {FORMAT}")
    keys = [s.key for s in p.slots]
    if [c["slot"] for c in d["picks"]] != keys:
        raise ContractError("the plan's slots are not this problem's")
    if [c["fixed"] for c in d["picks"]] != [s.fixed is not None for s in p.slots]:
        raise ContractError("the plan's fixed slots are not this problem's")
    prep_keys = [s.key for s in p.preps]
    picks = initial_partial(p)
    for i, c in enumerate(d["picks"]):
        if not c["fixed"]:
            picks[i] = Pick(candidate=c["candidate"], source=keys.index(c["leftovers_of"]) if c["leftovers_of"] else None,
                            portion=c["portion"], shares=tuple(c["shares"]) if c["shares"] is not None else None,
                            prep=prep_keys.index(c["prep"]) if c["prep"] else None)
    return tuple(picks)

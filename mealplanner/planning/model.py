"""The planning problem as plain data: no Structr in it.

extract.py reads the graph and builds one of these; the code in evaluate.py and
search.py works only on it. That split is what lets every rule of the planner be
tested offline against hand-worked numbers (tests/test_planning_*.py), the same
way the rest of mealplanner/ is. See docs/optimizer-design.md (Sec 4.1).

Everything here is a proposal's data model, not a stored one: none of it is
persisted, and no structural type backs it (CLAUDE.md hard rule 3). The result
of planning becomes ordinary MealPlanEntry nodes (commit.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

DIFFICULTY_ORDER = ("easy", "medium", "hard")


@dataclass(frozen=True)
class Candidate:
    """A recipe that could be cooked, reduced to the numbers planning needs.

    nutrients: nutrient id -> grams per serving, None when unknown. `untrusted`
      names the nutrients whose figure rests on placeholder or unmarked data
      (NutrientProfile.provenance); a hard target will not be decided on those.
    demand: stock pool -> grams for ONE batch (the recipe as written, i.e. its
      whole yield). Cooking N servings uses N / yield_servings of it (uniform
      scaling, which the model adopts knowingly).
    uses: when this recipe is already used outside the problem's own slots (other
      MealPlans, earlier weeks); feeds the variety term.
    leftover_days: how long the cooked food keeps; None means leftovers of it
      are not planned.
    ahead_hours: how long before the meal it must be started, for waiting no one
      attends (overnight oats soaking; J29). `minutes` is the work alone.
    """

    id: str
    name: str
    meal_types: frozenset = frozenset()
    minutes: float | None = None
    difficulty: str | None = None
    yield_servings: float = 1.0
    nutrients: Mapping = field(default_factory=dict)
    untrusted: frozenset = frozenset()
    demand: Mapping = field(default_factory=dict)
    hard_excluded: bool = False
    soft_penalty: float = 0.0
    leftover_days: float | None = None
    uses: tuple = ()
    recipe: str | None = None       # the RecipeIdentity this Plan is a version of (planning/shortlist.py)
    ahead_hours: float = 0.0


@dataclass(frozen=True)
class Target:
    """A NutritionTarget at its declared scope ('per_meal', 'daily', 'weekly')."""

    name: str
    nutrient: str
    scope: str
    minimum: float | None = None
    maximum: float | None = None
    hard: bool = False
    weight: float = 0.0
    nutrient_name: str = ""
    day_boundary: str = "midnight"     # a daily scope's dayBoundaryRule: "midnight" (UTC) or "midnight <IANA zone>"
    eater: str = ""                    # whose target it is (data-model.md Sec 19 K4); "" is the one eater of a problem without named eaters


@dataclass(frozen=True)
class Lot:
    """Eligible stock of one pool that expires at a known time (None: no known expiry)."""

    pool: str
    grams: float
    expires: datetime | None = None
    name: str = ""


@dataclass(frozen=True)
class Weights:
    """The MealPlan's own weights, with the selector's defaults. `cooking_time` is the week file's
    alone (the owner's decision, 2026-10-24: "an optional preference that can be adjusted week-to-
    week"): points off the score per hour of the week's cooking; 0, the default, ignores it."""

    time: float = 0.5
    variety: float = 0.5
    stock: float = 0.0
    waste: float = 0.0
    time_budget_minutes: float = 60.0
    cooking_time: float = 0.0


@dataclass(frozen=True)
class Fixed:
    """An entry already in the MealPlan, which the planner respects and cannot change.

    Either a fresh cook (`candidate`, with `cooked` servings planned) or a
    leftover of the fixed slot at index `source`. `eaten` is the servings eaten;
    `shares`, where the entry has them (Sec 19 K3), is who ate how much of it."""

    eaten: float = 1.0
    candidate: str | None = None
    source: int | None = None
    cooked: float | None = None
    name: str = ""
    entry_id: str | None = None       # the MealPlanEntry it came from, so a new leftover can point at it
    shares: tuple = ()                # ((eater, servings), ...); empty: `eaten`, by the slot's first eater


@dataclass(frozen=True)
class Slot:
    """A place in the week: when it starts and which meal type it is for."""

    key: str
    start: datetime
    meal_type: str | None = None
    fixed: Fixed | None = None
    eaters: tuple | None = None       # who eats this meal; None: every eater of the problem


@dataclass(frozen=True)
class PrepSession:
    """A time set aside to cook ahead (docs/optimizer-design.md Sec 12): a dish made at it
    feeds later meals while it keeps. `minutes` is the working time it has, `dishes` the most
    dishes made in it; both are hard."""

    key: str
    start: datetime
    minutes: float
    dishes: int = 2


@dataclass(frozen=True)
class Pick:
    """What fills a slot: a fresh cook of `candidate`, or the leftovers of the
    cook at slot index `source`. Exactly one is set. `portion` is the servings
    eaten by a slot's one eater, one of their portion levels; None means the
    default. A slot with several eaters takes `shares` instead: one portion per
    eater, in the order of `slot_eaters` (data-model.md Sec 19 K5). A fresh cook
    with `prep` set is made at that prep session (an index into the problem's
    `preps`), not at the meal."""

    candidate: str | None = None
    source: int | None = None
    portion: float | None = None
    shares: tuple | None = None
    prep: int | None = None

    def __post_init__(self):
        if (self.candidate is None) == (self.source is None):
            raise ValueError("a Pick is either a fresh cook (candidate) or a leftover (source), not both or neither")
        if self.prep is not None and self.candidate is None:
            raise ValueError("only a fresh cook can be made at a prep session")


@dataclass(frozen=True)
class Request:
    """A recipe the owner asked for this week (docs/optimizer-design.md Sec 12): cooked fresh at
    least once, the planner choosing when, how much and who eats the leftovers; or, pinned to
    open slot `slot`, cooked fresh there. `candidates` are the Plans that answer it: the
    recipe's versions in the book. A recipe asked for twice is cooked at least twice. A hard
    rule: a week that leaves one out is not feasible, as one missing a hard target is not."""

    name: str
    candidates: frozenset
    slot: int | None = None


@dataclass
class PlanningProblem:
    slots: tuple
    candidates: dict
    targets: tuple = ()
    lots: tuple = ()
    weights: Weights = field(default_factory=Weights)
    now: datetime | None = None
    max_difficulty: str | None = None
    servings_eaten: float = 1.0
    notes: list = field(default_factory=list)
    # What the MealPlan's baseline (supplements, the morning coffee) adds to every
    # day: nutrient id -> amount per day in the targets' unit, None if unknown.
    baseline: Mapping = field(default_factory=dict)
    units: Mapping = field(default_factory=dict)       # nutrient id -> the unit its figures and targets are in
    # The servings an open slot may eat, when portions vary (the owner's decision 2026-09-27);
    # empty means every open slot eats `servings_eaten`.
    portions: tuple = ()
    # The people a household's week feeds (data-model.md Sec 19). Empty: one eater, "", as
    # before households. Each may have their own portion levels and their own baseline;
    # one without falls back to `portions` and to no baseline.
    eaters: tuple = ()
    eater_portions: Mapping = field(default_factory=dict)
    baselines: Mapping = field(default_factory=dict)
    eater_names: Mapping = field(default_factory=dict)  # eater -> a name to show
    # How many recipes the week could draw on: more than len(candidates) when only a
    # shortlist of them was read and searched (planning/shortlist.py); 0 when not counted.
    book_size: int = 0
    requests: tuple = ()               # Request: the recipes the owner asked to have cooked this week
    preps: tuple = ()                  # PrepSession: when the week may cook ahead, in time order
    # The most meals of the week one recipe may be, fresh, as leftovers or made at a prep session
    # (the owner's request, 2026-10-24: "How often would you tolerate eating the same meal in a
    # week?"); a hard limit, the week file's alone. None: no limit, as before.
    repeat_tolerance: int | None = None
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        self.slots = tuple(self.slots)
        self.targets = tuple(self.targets)
        self.portions = tuple(sorted(float(x) for x in self.portions))
        self.eaters = tuple(self.eaters)
        self.eater_portions = {e: tuple(sorted(float(x) for x in levels)) for e, levels in self.eater_portions.items()}
        known = set(self.eater_keys())
        for slot in self.slots:
            if slot.eaters is not None and (not slot.eaters or not set(slot.eaters) <= known):
                raise ValueError(f"slot {slot.key!r} names eaters {list(slot.eaters)} that are not the problem's {sorted(known)}")
        for target in self.targets:
            if target.eater not in known:
                raise ValueError(f"target {target.name!r} is for {target.eater!r}, who is not one of the problem's eaters")
        self.lots = tuple(self.lots)
        for slot in self.slots:
            if slot.start.tzinfo is None:
                raise ValueError(f"slot {slot.key!r} has a start time with no timezone; times must be timezone-aware")
        keys = [slot.key for slot in self.slots]
        if len(set(keys)) != len(keys):
            repeated = sorted({k for k in keys if keys.count(k) > 1})
            raise ValueError(f"slot keys must be unique (they name the entries created for them); repeated: {repeated}")
        for a, b in zip(self.slots, self.slots[1:]):
            if b.start < a.start:
                raise ValueError(f"slots must be in chronological order: {b.key!r} starts before {a.key!r}")
        for i, slot in enumerate(self.slots):
            fixed = slot.fixed
            if fixed is None:
                continue
            if (fixed.candidate is None) == (fixed.source is None):
                raise ValueError(f"fixed slot {slot.key!r} must be either a cook or a leftover")
            if fixed.candidate is not None and fixed.candidate not in self.candidates:
                raise ValueError(f"fixed slot {slot.key!r} cooks {fixed.candidate!r}, which is not among the candidates")
            if fixed.source is not None and not 0 <= fixed.source < i:
                raise ValueError(f"fixed slot {slot.key!r} takes leftovers from a slot that does not come before it")
        self.preps = tuple(self.preps)
        for session in self.preps:
            if session.start.tzinfo is None:
                raise ValueError(f"prep session {session.key!r} has a start time with no timezone")
            if session.minutes <= 0 or session.dishes < 1:
                raise ValueError(f"prep session {session.key!r} needs some minutes and at least one dish")
        self.requests = tuple(self.requests)
        pinned = [r.slot for r in self.requests if r.slot is not None]
        for r in self.requests:
            if not r.candidates or not set(r.candidates) <= set(self.candidates):
                raise ValueError(f"the request for {r.name!r} names recipes that are not among the candidates")
            if r.slot is not None and not (0 <= r.slot < len(self.slots) and self.slots[r.slot].fixed is None):
                raise ValueError(f"the request for {r.name!r} is pinned to a slot that is not an open slot of the week")
        if len(set(pinned)) != len(pinned):
            raise ValueError("two requests are pinned to one meal")
        for w in (self.weights.time, self.weights.variety, self.weights.stock, self.weights.waste, self.weights.cooking_time):
            if w < 0:
                raise ValueError("weights must not be negative (the search bounds rely on it)")
        if self.repeat_tolerance is not None and (isinstance(self.repeat_tolerance, bool)
                                                  or not isinstance(self.repeat_tolerance, int) or self.repeat_tolerance < 1):
            raise ValueError("repeat_tolerance must be a whole number of meals, at least 1")
        if self.max_difficulty is not None and self.max_difficulty not in DIFFICULTY_ORDER:
            raise ValueError(f"max_difficulty must be one of {DIFFICULTY_ORDER}")

    def open_slots(self) -> list[int]:
        return [i for i, s in enumerate(self.slots) if s.fixed is None]

    def portion_levels(self, eater: str = "") -> tuple:
        """The servings an eater may eat at an open slot: their own levels, the problem's, or the one default."""
        return self.eater_portions.get(eater) or self.portions or (self.servings_eaten,)

    def eater_keys(self) -> tuple:
        """Who eats: the named eaters, or the one unnamed eater of a problem without them."""
        return self.eaters or ("",)

    def slot_eaters(self, i: int) -> tuple:
        """Who eats slot i, in a fixed order (a Pick's `shares` follow it)."""
        return self.slots[i].eaters or self.eater_keys()

    def pinned(self) -> dict:
        """Open slot index -> the Request pinned to it."""
        return {r.slot: r for r in self.requests if r.slot is not None}

    def wanted(self) -> list:
        """(name, candidates, how many fresh cooks) for the requests pinned to no slot, one per recipe."""
        groups: dict = {}
        for r in self.requests:
            if r.slot is None:
                name, count = groups.get(r.candidates, (r.name, 0))
                groups[r.candidates] = (name, count + 1)
        return [(name, candidates, count) for candidates, (name, count) in groups.items()]

    def baseline_of(self, eater: str) -> Mapping:
        """What an eater takes every day outside the meals: nutrient -> amount a day, None if unknown."""
        if eater in self.baselines:
            return self.baselines[eater]
        return self.baseline if eater == "" else {}

    def eater_label(self, eater: str) -> str:
        return self.eater_names.get(eater, eater)

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


@dataclass(frozen=True)
class Lot:
    """Eligible stock of one pool that expires at a known time (None: no known expiry)."""

    pool: str
    grams: float
    expires: datetime | None = None
    name: str = ""


@dataclass(frozen=True)
class Weights:
    """The MealPlan's own weights, with the selector's defaults."""

    time: float = 0.5
    variety: float = 0.5
    stock: float = 0.0
    waste: float = 0.0
    time_budget_minutes: float = 60.0


@dataclass(frozen=True)
class Fixed:
    """An entry already in the MealPlan, which the planner respects and cannot change.

    Either a fresh cook (`candidate`, with `cooked` servings planned) or a
    leftover of the fixed slot at index `source`. `eaten` is the servings eaten."""

    eaten: float = 1.0
    candidate: str | None = None
    source: int | None = None
    cooked: float | None = None
    name: str = ""
    entry_id: str | None = None       # the MealPlanEntry it came from, so a new leftover can point at it


@dataclass(frozen=True)
class Slot:
    """A place in the week: when it starts and which meal type it is for."""

    key: str
    start: datetime
    meal_type: str | None = None
    fixed: Fixed | None = None


@dataclass(frozen=True)
class Pick:
    """What fills a slot: a fresh cook of `candidate`, or the leftovers of the
    cook at slot index `source`. Exactly one is set."""

    candidate: str | None = None
    source: int | None = None

    def __post_init__(self):
        if (self.candidate is None) == (self.source is None):
            raise ValueError("a Pick is either a fresh cook (candidate) or a leftover (source), not both or neither")


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
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        self.slots = tuple(self.slots)
        self.targets = tuple(self.targets)
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
        for w in (self.weights.time, self.weights.variety, self.weights.stock, self.weights.waste):
            if w < 0:
                raise ValueError("weights must not be negative (the search bounds rely on it)")
        if self.max_difficulty is not None and self.max_difficulty not in DIFFICULTY_ORDER:
            raise ValueError(f"max_difficulty must be one of {DIFFICULTY_ORDER}")

    def open_slots(self) -> list[int]:
        return [i for i, s in enumerate(self.slots) if s.fixed is None]

"""plan_week(): the whole path from a MealPlan to a proposed week, in one call."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from time import monotonic

from mealplanner.planning.commit import commit_plan
from mealplanner.planning.diagnose import Diagnosis, describe_violation, diagnose, settled
from mealplanner.planning.evaluate import Evaluation, evaluate
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import PlanningProblem
from mealplanner.planning.proposal import ProposalError, picks_from
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import SearchResult, solve
from mealplanner.planning.shortlist import FACTOR, SHORTLIST_ABOVE

REPORT_RESERVE_S = 30.0    # kept back from a whole run's budget for what follows the search: the reports, a diagnosis
MIN_SEARCH_S = 10.0        # the search's least time, even when reading has used up the budget
PROPOSAL = "saved proposal"


def keeps_requests(problem: PlanningProblem, evaluation: Evaluation) -> bool:
    """A legal week that cooks every recipe asked for, its only failings hard nutrition targets. The
    owner's decision (2026-10-24): "Keep the requested meal. Advise if a nutrient target isn't being
    met for the week." Such a week is proposed, and may be committed, naming what it misses."""
    return (bool(problem.requests) and evaluation.legal
            and not any(v.kind == "not_cooked" for v in evaluation.violations))


@dataclass
class PlanResult:
    problem: PlanningProblem
    search: SearchResult
    evaluation: Evaluation | None          # the plan; None if nothing feasible was found
    diagnosis: Diagnosis | None            # set when there is no feasible plan
    committed: list = field(default_factory=list)
    missed: list = field(default_factory=list)      # hard targets a plan keeping the requests misses (keeps_requests)
    without_requests: bool | None = None            # whether a week meeting them all was found without the requests

    @property
    def feasible(self) -> bool:
        return self.evaluation is not None

    def text(self) -> str:
        lines = list(self.problem.notes)
        if self.evaluation is not None:
            proof = ("the saved proposal, checked against the graph again" if self.search.method == PROPOSAL
                     else "optimal" if self.search.proven else f"best found by {self.search.method} (not proven optimal)")
            if self.missed:
                lines.extend(self.advice())
            lines.append(f"Plan ({proof}):")
            lines.append(describe_plan(self.problem, self.evaluation))
        elif self.diagnosis is not None:
            lines.append(self.diagnosis.summary())
        return "\n".join(lines)

    def advice(self) -> list[str]:
        """What a week keeping the requests misses, a line per target (the owner's decision, 2026-10-24)."""
        asked = ", ".join(r.name for r in self.problem.requests)
        lines = [f"ADVICE: no week cooking {asked} meets every hard target, so this one keeps the requests and misses:"]
        by_target: dict = {}
        for v in self.missed:
            by_target.setdefault(v.target, []).append(v)
        for target, found in sorted(by_target.items()):
            lines.append(f"  {target}: {len(found)} group(s), " + "; ".join(describe_violation(v) for v in found[:3])
                         + ("; ..." if len(found) > 3 else ""))
        if self.without_requests is True:
            lines.append("  Without the requests, a week meeting every hard target was found: the requests are the reason.")
        elif self.without_requests is False:
            lines.append("  Without the requests none was found either: the requests are not the only reason.")
        return lines


def plan_week(
    client, meal_plan_id: str, template: list[SlotSpec], now: datetime, *, method: str = "auto",
    commit: bool = False, name_prefix: str = "", servings_eaten: float = 1.0, max_difficulty: str | None = None,
    leftover_days: float | None = None, leftovers: bool = True, portions: tuple = (), eater_portions: dict | None = None,
    shortlist_above: int | None = SHORTLIST_ABOVE, deadline: float | None = None, proposal: dict | None = None,
    requests: tuple = (), preps: tuple = (), cooking_time: float = 0.0, repeat_tolerance: int | None = None,
    **search_options,
) -> PlanResult:
    """Read the MealPlan, search for the best week for the slots in `template`,
    and (only if asked, and only if a plan meets every hard constraint) write it
    as MealPlanEntries. A week with no feasible plan comes back with a Diagnosis
    saying why and what would change it, never a plan that breaks a hard
    constraint.

    A book of more than `shortlist_above` recipes is searched through a shortlist
    (planning/shortlist.py); one that holds no week meeting every hard target is
    doubled, read and searched again, until it is the whole book.

    deadline (a time.monotonic() value): when the whole run should be done (the
    owner's decision, 2026-10-22: about five minutes for a menu). Each search then
    has the time left, less REPORT_RESERVE_S for the reports, and at least
    MIN_SEARCH_S. Without one, `time_limit_s` is each search's own limit.

    requests: (recipe name, meal or None) pairs: recipes the owner asked to have cooked this week,
    each at least once, or at the meal named (extract.build_problem; model.Request).
    preps: model.PrepSessions, when the week may cook ahead (docs/optimizer-design.md Sec 12).
    cooking_time: how much the week's total cooking time counts against it, points an hour (Weights).
    repeat_tolerance: the most meals of the week one recipe may be, a hard limit; None: none.

    proposal: a week proposed earlier (planning/proposal.py), to be checked and committed
    instead of searching again. The whole book is read, so every recipe it names is there; it
    raises ProposalError if the week no longer fits it, or if it no longer meets every hard
    target, and nothing is written."""
    if proposal is not None:
        problem = build_problem(
            client, meal_plan_id, template, now, servings_eaten=servings_eaten, max_difficulty=max_difficulty,
            leftover_days=leftover_days, leftovers=leftovers, portions=portions, eater_portions=eater_portions,
            shortlist_above=None, requests=requests, preps=preps, cooking_time=cooking_time,
            repeat_tolerance=repeat_tolerance,
        )
        problem.notes.extend(settled(problem))
        evaluation = evaluate(problem, picks_from(problem, proposal))
        if not (evaluation.legal and (evaluation.feasible or keeps_requests(problem, evaluation))):
            raise ProposalError("the proposal no longer meets every rule and hard target: "
                                + "; ".join(evaluation.problems or [f"{len(evaluation.violations)} hard target group(s) missed"]))
        result = PlanResult(problem, SearchResult(evaluation, False, 0, PROPOSAL), evaluation, None,
                            missed=list(evaluation.violations))
        if commit:
            result.committed = commit_plan(client, meal_plan_id, problem, evaluation, name_prefix=name_prefix,
                                           missing_targets_ok=bool(result.missed))
        return result
    factor, widened = FACTOR, []
    while True:
        problem = build_problem(
            client, meal_plan_id, template, now, servings_eaten=servings_eaten, max_difficulty=max_difficulty,
            leftover_days=leftover_days, leftovers=leftovers, portions=portions, eater_portions=eater_portions,
            shortlist_above=shortlist_above, shortlist_factor=factor, requests=requests, preps=preps,
            cooking_time=cooking_time, repeat_tolerance=repeat_tolerance,
        )
        if deadline is not None:
            left = deadline - monotonic() - REPORT_RESERVE_S
            search_options["time_limit_s"] = max(MIN_SEARCH_S, left)
            if left < MIN_SEARCH_S:
                problem.notes.append(f"reading the week used up the time allowed, so the search had only {MIN_SEARCH_S:g} s")
        search = solve(problem, method, **search_options)
        if (search.best is not None and search.best.feasible) or problem.book_size <= len(problem.candidates):
            break
        widened.append(len(problem.candidates))
        factor *= 2
    for size in widened:
        problem.notes.append(f"a shortlist of {size} recipes held no week meeting every hard target, so it was doubled")
    problem.notes.extend(settled(problem))
    if search.best is not None and search.best.feasible:
        result = PlanResult(problem, search, search.best, None)
        if commit:
            result.committed = commit_plan(client, meal_plan_id, problem, search.best, name_prefix=name_prefix)
        return result
    diagnosis = diagnose(problem)
    if diagnosis.feasible and diagnosis.closest is not None:      # its search found what the first did not, in time
        result = PlanResult(problem, search, diagnosis.closest, None)
    elif diagnosis.closest is not None and keeps_requests(problem, diagnosis.closest):
        # keep the requests and say what the week misses; and whether the requests are why
        alone = solve(replace(problem, requests=(), _cache={}), method, **{**search_options, "time_limit_s": 10.0})
        result = PlanResult(problem, search, diagnosis.closest, diagnosis, missed=list(diagnosis.closest.violations),
                            without_requests=alone.best is not None and alone.best.feasible)
    else:
        return PlanResult(problem, search, None, diagnosis)
    if commit:
        result.committed = commit_plan(client, meal_plan_id, problem, result.evaluation, name_prefix=name_prefix,
                                       missing_targets_ok=bool(result.missed))
    return result

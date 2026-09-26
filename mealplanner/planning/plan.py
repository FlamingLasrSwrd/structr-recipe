"""plan_week(): the whole path from a MealPlan to a proposed week, in one call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from mealplanner.planning.commit import commit_plan
from mealplanner.planning.diagnose import Diagnosis, diagnose
from mealplanner.planning.evaluate import Evaluation
from mealplanner.planning.extract import SlotSpec, build_problem
from mealplanner.planning.model import PlanningProblem
from mealplanner.planning.report import describe_plan
from mealplanner.planning.search import SearchResult, solve


@dataclass
class PlanResult:
    problem: PlanningProblem
    search: SearchResult
    evaluation: Evaluation | None          # the plan; None if nothing feasible was found
    diagnosis: Diagnosis | None            # set when there is no feasible plan
    committed: list = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.evaluation is not None

    def text(self) -> str:
        lines = list(self.problem.notes)
        if self.evaluation is not None:
            proof = "optimal" if self.search.proven else f"best found by {self.search.method} (not proven optimal)"
            lines.append(f"Plan ({proof}):")
            lines.append(describe_plan(self.problem, self.evaluation))
        elif self.diagnosis is not None:
            lines.append(self.diagnosis.summary())
        return "\n".join(lines)


def plan_week(
    client, meal_plan_id: str, template: list[SlotSpec], now: datetime, *, method: str = "auto",
    commit: bool = False, name_prefix: str = "", servings_eaten: float = 1.0, max_difficulty: str | None = None,
    leftover_days: float | None = None, leftovers: bool = True, **search_options,
) -> PlanResult:
    """Read the MealPlan, search for the best week for the slots in `template`,
    and (only if asked, and only if a plan meets every hard constraint) write it
    as MealPlanEntries. A week with no feasible plan comes back with a Diagnosis
    saying why and what would change it, never a plan that breaks a hard
    constraint."""
    problem = build_problem(
        client, meal_plan_id, template, now, servings_eaten=servings_eaten, max_difficulty=max_difficulty,
        leftover_days=leftover_days, leftovers=leftovers,
    )
    search = solve(problem, method, **search_options)
    if search.best is not None and search.best.feasible:
        result = PlanResult(problem, search, search.best, None)
        if commit:
            result.committed = commit_plan(client, meal_plan_id, problem, search.best, name_prefix=name_prefix)
        return result
    return PlanResult(problem, search, None, diagnose(problem))

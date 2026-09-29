"""A plan in words: what goes in each slot and why it scored as it did."""

from __future__ import annotations

from mealplanner.planning.evaluate import Evaluation
from mealplanner.planning.model import PlanningProblem


def _eats(detail: dict, problem: PlanningProblem | None = None) -> str:
    shares = detail.get("shares")
    if shares and problem is not None and problem.eaters:
        return ", eat " + ", ".join(f"{servings:g} {problem.eater_label(e)}" for e, servings in shares.items())
    eaten = detail.get("eaten", 1.0)
    return "" if abs(eaten - 1.0) < 1e-9 else f", eat {eaten:g}"


def describe_plan(problem: PlanningProblem, evaluation: Evaluation) -> str:
    lines = []
    details = {d["slot"]: d for d in evaluation.slot_details}
    for slot, pick in zip(problem.slots, evaluation.picks):
        when = slot.start.strftime("%a %d %b %H:%M")
        if slot.fixed is not None:
            lines.append(f"  {when}  {slot.key}: (already planned) {slot.fixed.name or slot.key}")
            continue
        d = details.get(slot.key)
        if d is None:
            lines.append(f"  {when}  {slot.key}: (unresolved)")
        elif d["kind"] == "leftover":
            lines.append(f"  {when}  {slot.key}: leftover {d['recipe']} from {d['source']}{_eats(d, problem)}")
        else:
            servings = d["cooked_servings"]
            lines.append(f"  {when}  {slot.key}: cook {d['recipe']} for {servings:g} serving{'s' if servings != 1 else ''}{_eats(d, problem)}")
    terms = ", ".join(f"{name} {value:+.3f}" for name, value in evaluation.terms.items() if abs(value) > 1e-12)
    lines.append(f"  score {evaluation.objective:.3f} ({terms or 'no weighted terms'})")
    return "\n".join(lines)

"""Plan a week from a problem file: the planner as a worker that reads no graph (docs/architecture-decision.md §7a, stage 4).

    python3 tools/plan_problem.py private/week.problem.json                   # the plan beside it: week.plan.json
    python3 tools/plan_problem.py private/week.problem.json -o plan.json --time-limit 60 --method auto

Reads a problem in the planner's JSON contract (mealplanner/planning/contract.py), as
`tools/plan_week.py --export-problem` writes it now and a Structr method will under Path S; searches it
and concludes as plan_week does (planning/plan.py conclude: the plan if it meets every hard constraint,
else a diagnosis, with the closest week when it keeps every request); writes the plan in the same
contract, with the report, and prints the report. It needs no Structr and no credentials: the file is
all it reads, and the plan file all it writes. Exits 1 when no week is proposed. A problem holds a
household's data: keep its files in private/.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.planning.contract import ContractError, plan_to_json, problem_from_json
from mealplanner.planning.plan import conclude
from mealplanner.planning.search import solve


def plan(problem_data: dict, method: str = "auto", time_limit_s: float = 30.0) -> tuple[dict, str]:
    """(the plan in the contract, the report) for a problem in the contract."""
    problem = problem_from_json(problem_data)
    options = {"time_limit_s": time_limit_s} if method in ("auto", "cpsat") else {}
    result = conclude(problem, solve(problem, method, **options), method, **options)
    report = result.text()
    if result.evaluation is None:
        return {"format": problem_data["format"], "picks": None, "legal": False, "proven": result.search.proven,
                "method": result.search.method, "objective": None, "upper_bound": result.search.upper_bound,
                "report": report}, report
    return plan_to_json(problem, result.evaluation.picks, objective=result.evaluation.objective, legal=result.evaluation.legal,
                        proven=result.search.proven, method=result.search.method, upper_bound=result.search.upper_bound,
                        report=report), report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("problem", help="a problem file, e.g. private/week.problem.json")
    parser.add_argument("-o", "--out", help="where the plan goes (default: beside the problem, .plan.json)")
    parser.add_argument("--method", default="auto", help="auto (default), cpsat, exact, beam or oracle")
    parser.add_argument("--time-limit", type=float, default=30.0, help="the search's time limit in seconds (auto, cpsat)")
    args = parser.parse_args(argv)
    out = args.out or (args.problem[:-len(".problem.json")] if args.problem.endswith(".problem.json")
                       else os.path.splitext(args.problem)[0]) + ".plan.json"
    with open(args.problem, encoding="utf-8") as fh:
        data = json.load(fh)
    try:
        sent, report = plan(data, args.method, args.time_limit)
    except (ContractError, ValueError) as exc:
        print(f"problem: {exc}")
        return 1
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(sent, fh, indent=1)
    print(report)
    print(f"\n(the plan is in {out})")
    return 0 if sent["picks"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())

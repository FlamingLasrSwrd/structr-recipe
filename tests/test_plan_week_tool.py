"""tools/plan_week.py: reading the week file and laying out its slots."""

import importlib.util
import os
import tempfile
import unittest
from datetime import timezone

os.environ.setdefault("STRUCTR_SUPERUSER_PASSWORD", "unused-in-tests")
_spec = importlib.util.spec_from_file_location("plan_week_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "plan_week.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

from tests.fakegraph import FakeGraph, Ref

WEEK = """start = 2026-10-05
days = 2
timezone = "America/Denver"
meals = [{ type = "Breakfast", at = "08:00" }, { type = "Dinner", at = "18:30" }]
"""


def read(text):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
        fh.write(text)
    try:
        return tool.read_week(fh.name)
    finally:
        os.unlink(fh.name)


class TheWeekFile(unittest.TestCase):
    def test_every_problem_is_named(self):
        with self.assertRaises(tool.WeekError) as caught:
            read('start = "Monday"\ntimezone = "Mountain"\nmeals = [{ type = "Dinner", at = "dinnertime" }]\n')
        text = " ".join(caught.exception.args[0])
        for fragment in ("start must be a date", "not an IANA zone", "must be a time"):
            self.assertIn(fragment, text)

    def test_local_times_and_a_committed_meal_keeps_its_slot(self):
        week = read(WEEK)
        g = FakeGraph()
        g.add("TemporalRegion", "r", hasBeginning="2026-10-06T00:30:00+0000")     # Mon 18:30 in Denver
        g.add("MealPlanEntry", "e", isAbout=Ref("r"), isSkipped=False)
        g.add("MealPlan", "week", hasEntry=[Ref("e")])
        slots = tool.template(g, "week", week)
        self.assertEqual([s.key for s in slots], ["Mon 05 Oct Breakfast", "Tue 06 Oct Breakfast", "Tue 06 Oct Dinner"])
        self.assertEqual(slots[0].start.astimezone(timezone.utc).isoformat(), "2026-10-05T14:00:00+00:00")


class History(unittest.TestCase):
    """What keeps being missed: every committed week's days, judged against its targets."""

    def test_committed_days_are_tallied_and_this_week_is_left_out(self):
        from tests.fakegraph import at
        from tests.test_nutrition_derivation import kitchen
        g = kitchen()
        g.add("QuantitySpecification", "range", minValue=1800.0, maxValue=2500.0, unit="kcal")
        g.add("NutritionTarget", "energy", "energy", forNutrient=Ref("Energy"), hasTargetRange=Ref("range"),
              hasTimeScope="daily", dayBoundaryRule="midnight", strictness="soft")
        g.add("MealPlan", "past", "past", hasEntry=[], hasConstraint=[Ref("energy")])
        for i, hour in enumerate((12, 18)):                   # 2 x 333 kcal on one day: under 1800
            g.add("TemporalRegion", f"r{i}", hasBeginning=at(28, hour))
            g.add("MealPlanEntry", f"e{i}", f"e{i}", isAbout=Ref(f"r{i}"), isSkipped=False, references=Ref("stew"),
                  memberOf=Ref("past"))
            g.nodes["past"]["hasEntry"].append(Ref(f"e{i}"))
        g.add("MealPlan", "now", "now", hasEntry=[], hasConstraint=[Ref("energy")])
        self.assertIn("Energy: under on 1 of 1 days", tool.history(g, "now"))
        self.assertIn("No committed weeks yet", tool.history(g, "past"))


if __name__ == "__main__":
    unittest.main()

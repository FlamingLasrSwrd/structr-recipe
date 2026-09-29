"""A household and its people (mealplanner/household.py, data-model.md Sec 19 K1-K4).

Worked out by hand from tests/test_profiles.py's profiles:
  Elijah, "Man moderately active": protein 62.5-218.75 g, sodium at most 2300 mg (from "Adult")
  Cass, "Man low sodium" (its child): the same, but sodium at most 1500 mg
"""

import os
import tempfile
import unittest

from mealplanner.household import instantiate_household, latest_plan
from mealplanner.profiles import ProfileError, instantiate_nutrition
from tests.fakegraph import Ref
from tests.test_profiles import instance

ELIJAH = 'profile = "Man moderately active"\ntimezone = "America/Denver"\nhard = ["Protein"]\n'
CASS = 'profile = "Man low sodium"\n'


class Household(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for name, text in (("elijah.toml", ELIJAH), ("cass.toml", CASS)):
            with open(os.path.join(self.root, name), "w") as fh:
                fh.write(text)

    def g(self):
        g = instance()
        for version in (1, 2):
            g.add("Plan", f"supplements v{version}", f"Daily supplements v{version}")
        return g

    def selection(self, **kw):
        people = [{"name": "Elijah", "nutrition": "elijah.toml", "baseline": ["Daily supplements"], "adopts": True},
                  {"name": "Cass", "nutrition": "cass.toml"}]
        return {"name": "Home", "person": kw.pop("person", people), **kw}

    def target(self, g, name):
        return g.nodes[f"NutritionTarget:{name}"]

    def rng(self, g, name):
        return g.nodes[self.target(g, name)["hasTargetRange"].id]

    def test_each_person_has_their_own_targets_and_baseline(self):
        g = self.g()
        report = instantiate_household(g, self.selection(), self.root)
        home = g.nodes[report.household_id]
        self.assertEqual(sorted(r.id for r in home["members"]), ["Person:Cass", "Person:Elijah"])
        elijah = self.target(g, "Daily Protein target (Elijah)")
        self.assertEqual((elijah["forPerson"].id, elijah["strictness"]), ("Person:Elijah", "hard"))
        self.assertEqual((self.rng(g, "Daily Protein target (Elijah)")["minValue"], self.rng(g, "Daily Protein target (Elijah)")["maxValue"]),
                         (62.5, 218.75))
        self.assertEqual(self.rng(g, "Daily Sodium - Na target (Elijah)")["maxValue"], 2300)
        self.assertEqual(self.rng(g, "Daily Sodium - Na target (Cass)")["maxValue"], 1500)
        self.assertEqual(self.target(g, "Daily Sodium - Na target (Cass)")["forPerson"].id, "Person:Cass")
        self.assertEqual([r.id for r in g.nodes["Person:Elijah"]["hasBaseline"]], ["supplements v2"])     # the newest version
        self.assertEqual(g.nodes["Person:Cass"].get("hasBaseline"), [])
        self.assertFalse(any(n["type"] == "NutritionTarget" and not n["name"].endswith(("(Elijah)", "(Cass)"))
                             for n in g.nodes.values()))

    def test_the_targets_from_before_there_were_people_are_adopted_in_place(self):
        g = self.g()
        import tomllib
        instantiate_nutrition(g, tomllib.loads(ELIJAH))                     # the single-user setup
        before = self.target(g, "Daily Protein target")["id"]
        range_before = self.target(g, "Daily Protein target")["hasTargetRange"].id
        report = instantiate_household(g, self.selection(), self.root)
        adopted = g.nodes[before]
        self.assertEqual((adopted["name"], adopted["forPerson"].id), ("Daily Protein target (Elijah)", "Person:Elijah"))
        self.assertEqual(g.nodes[range_before]["name"], "Daily Protein target (Elijah) range")
        self.assertFalse([n for n in g.nodes.values() if n.get("name") == "Daily Protein target"])     # renamed, not copied
        self.assertEqual(len([n for n in g.nodes.values() if n.get("name") == "Daily Protein target (Elijah)"]), 1)
        self.assertEqual(len(report.people["Elijah"].adopted), len(report.people["Elijah"].written))
        self.assertEqual(report.people["Elijah"].counts["created"], 0)
        self.assertEqual(len(report.people["Cass"].adopted), 0)

    def test_again_changes_nothing_and_a_person_no_longer_listed_leaves_but_stays(self):
        g = self.g()
        instantiate_household(g, self.selection(), self.root)
        again = instantiate_household(g, self.selection(), self.root)
        self.assertEqual((again.counts["created"], again.counts["changed"]), (0, 0))
        self.assertEqual({p: r.counts["created"] for p, r in again.people.items()}, {"Elijah": 0, "Cass": 0})
        only = instantiate_household(g, self.selection(person=self.selection()["person"][:1]), self.root)
        self.assertEqual([r.id for r in g.nodes[only.household_id]["members"]], ["Person:Elijah"])
        self.assertIn("Person:Cass", g.nodes)

    def test_every_problem_is_reported(self):
        bad = [{"name": "Elijah", "nutrition": "elijah.toml", "adopts": True}, {"name": "Elijah", "nutrition": "missing.toml"},
               {"name": "Sam, Jo", "nutrition": "cass.toml"}, {"name": "Cass", "adopts": True}]
        with self.assertRaises(ProfileError) as caught:
            instantiate_household(self.g(), self.selection(person=bad), self.root)
        # twice listed, a missing file, a comma in a name, no nutrition file, two adopters
        self.assertEqual(len(caught.exception.problems), 5)
        with self.assertRaises(ProfileError):
            instantiate_household(self.g(), self.selection(person=[]), self.root)
        with self.assertRaises(ProfileError):
            latest_plan(self.g(), "Morning coffee")


class Adoption(unittest.TestCase):
    def test_a_target_already_someones_is_not_taken(self):
        import tomllib
        g = instance()
        instantiate_nutrition(g, tomllib.loads(ELIJAH))
        g.add("Person", "Person:Robin", "Robin")
        g.nodes["NutritionTarget:Daily Protein target"]["forPerson"] = Ref("Person:Robin")
        g.add("Person", "Person:Elijah", "Elijah")
        report = instantiate_nutrition(g, tomllib.loads(ELIJAH), person=("Elijah", "Person:Elijah"), adopt=True)
        self.assertNotIn("Daily Protein target (Elijah)", report.adopted)
        self.assertEqual(g.nodes["NutritionTarget:Daily Protein target"]["forPerson"].id, "Person:Robin")
        self.assertIn("NutritionTarget:Daily Protein target (Elijah)", g.nodes)       # written fresh instead


if __name__ == "__main__":
    unittest.main()

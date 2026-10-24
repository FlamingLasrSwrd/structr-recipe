"""USDA's retention factors: the table pinned (mealplanner/usda_retention.py) and loaded on retention
classes (mealplanner/vocabulary_import.py, J30), then resolved as any default is (nutrition_scope).

The fixture: Alliums is a retention class over Garlic and Onion, taking USDA row 3460 (roots,
sauteed: 95% of sodium, 90% of iron) for stir-frying. Iron has no USDA number of its own in the
fixture, so iron's row 303 stands in. Mixing applies no heat.
"""

import os
import tempfile
import unittest

from mealplanner.nutrition_scope import retention_factor
from mealplanner.usda_retention import pin, read_table
from mealplanner.vocabulary_import import VocabularyError, import_vocabulary, parse_vocabulary
from tests.test_vocabulary import fdc_subset, instance, vocabulary_data

LINES = """~3460~^~11~^~VEG,ROOTS,ETC,SAUTEED~^~307~^~Sodium, Na~^~95~^~05/2003~
~3460~^~11~^~VEG,ROOTS,ETC,SAUTEED~^~303~^~Iron, Fe~^~90~^~05/2003~
~3460~^~11~^~VEG,ROOTS,ETC,SAUTEED~^~401~^~Vitamin C, total ascorbic acid~^~~^~05/2003~
~3455~^~11~^~VEG,ROOTS,ETC,BOILED~^~307~^~Sodium, Na~^~70~^~05/2003~
"""


def table():
    return {"nutrients": {"307": "Sodium, Na", "303": "Iron, Fe"},
            "rows": {"3460": {"description": "VEG,ROOTS,ETC,SAUTEED", "group": "11", "factors": {"303": 90.0, "307": 95.0}},
                     "3455": {"description": "VEG,ROOTS,ETC,BOILED", "group": "11", "factors": {"307": 70.0}}}}


def subset():
    fdc = fdc_subset()
    fdc["nutrients"]["1093"]["number"] = "307"
    return fdc


def classed(rows=None, **retention):
    data = vocabulary_data()
    data["method"] = data["method"] + [{"name": "No-Heat Method"}, {"name": "Mixing", "parent": "No-Heat Method"}]
    data["food"][0] = {"name": "Alliums", "retention": {"Stir-Frying": "3460"} if rows is None else rows}
    data["retention"] = {"kept_in_cooking": [1003, 1008], "nutrients": [1093, 1089], "stand_ins": {"1089": 303},
                         "no_heat": ["Mixing"], **retention}
    return data


class Table(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(handle, "w", encoding="latin-1") as fh:
            fh.write(LINES)
        self.addCleanup(os.remove, self.path)

    def test_a_blank_percent_is_no_figure(self):
        rows = read_table(self.path)["rows"]
        self.assertEqual(rows["3460"]["factors"], {"307": 95.0, "303": 90.0})
        self.assertEqual(rows["3460"]["description"], "VEG,ROOTS,ETC,SAUTEED")

    def test_pinned_the_rows_and_nutrients_asked_for_with_the_files_checksum(self):
        pinned = pin(self.path, {"3460"}, {"307"})
        self.assertEqual(list(pinned["rows"]), ["3460"])
        self.assertEqual((pinned["rows"]["3460"]["factors"], pinned["nutrients"]), ({"307": 95.0}, {"307": "Sodium, Na"}))
        self.assertEqual(len(pinned["sha256"]), 64)
        with self.assertRaises(KeyError):
            pin(self.path, {"9999"}, {"307"})


class Parse(unittest.TestCase):
    def problems(self, data, rows=None):
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(data, subset(), table() if rows is None else rows)
        return " ".join(caught.exception.problems)

    def test_a_good_file(self):
        v = parse_vocabulary(classed(), subset(), table())
        self.assertEqual(v.foods[0].retention, (("Stir-Frying", "3460"),))
        self.assertEqual((v.retention.nutrients, v.retention.no_heat), ((("1093", "307"), ("1089", "303")), ("Mixing",)))

    def test_every_problem_is_reported(self):
        text = self.problems(classed(rows={"Grilling": "3460", "Stir-Frying": "9999"}, no_heat=["Juicing"]))
        for fragment in ("'Grilling' is not a method", "USDA row 9999 is not in the pinned table", "no_heat: 'Juicing'"):
            self.assertIn(fragment, text)

    def test_a_nutrient_needs_a_usda_number(self):
        self.assertIn("has no USDA nutrient number", self.problems(classed(stand_ins={})))

    def test_a_factor_outside_0_to_100_percent_is_refused(self):
        rows = table()
        rows["rows"]["3460"]["factors"]["307"] = 105.0
        self.assertIn("lies in (0, 1]", self.problems(classed(), rows))

    def test_rows_without_nutrients_to_load_are_refused(self):
        data = classed()
        data["retention"] = {"kept_in_cooking": [1003]}
        with self.assertRaises(VocabularyError):
            parse_vocabulary(data, subset(), table())


class Load(unittest.TestCase):
    def imported(self, g, data=None):
        return import_vocabulary(g, parse_vocabulary(data or classed(), subset(), table()))

    def node(self, g, type_name, name):
        (row,) = [r for r in g.get_all(type_name)["result"] if r["name"] == name]
        return row

    def test_a_class_factor_keyed_by_nutrient_and_method_with_its_row(self):
        g = instance()
        self.imported(g)
        sodium = self.node(g, "DefaultSpecification", "Retention of Sodium - Na in Alliums by Stir-Frying")
        self.assertEqual((sodium["forType"]["name"], sorted(k["name"] for k in sodium["keyedBy"]), sodium["provenance"]),
                         ("Alliums", ["Sodium - Na", "Stir-Frying"], "estimated"))
        self.assertIn("row 3460 VEG,ROOTS,ETC,SAUTEED: 95% of Sodium, Na", sodium["source"])
        self.assertNotIn("standing in", sodium["source"])
        self.assertEqual(self.node(g, "QuantitySpecification", f"{sodium['name']} value")["value"], 0.95)
        iron = self.node(g, "DefaultSpecification", "Retention of Iron - Fe in Alliums by Stir-Frying")
        self.assertIn("90% of Iron, Fe, standing in for Iron, Fe", iron["source"])
        mixing = self.node(g, "DefaultSpecification", "Retention of Sodium - Na in Food by Mixing")
        self.assertEqual(self.node(g, "QuantitySpecification", f"{mixing['name']} value")["value"], 1.0)

    def test_resolved_up_the_hierarchy_for_the_method_of_the_step(self):
        g = instance()
        self.imported(g)
        ids = {n: self.node(g, "DomainType", n)["id"] for n in ("Garlic", "Kosher salt", "Stir-Frying", "Mixing", "Sodium - Na", "Protein")}
        self.assertEqual(retention_factor(g, ids["Garlic"], ids["Stir-Frying"], ids["Sodium - Na"]), 0.95)
        self.assertEqual(retention_factor(g, ids["Garlic"], ids["Mixing"], ids["Sodium - Na"]), 1.0)
        self.assertEqual(retention_factor(g, ids["Garlic"], ids["Stir-Frying"], ids["Protein"]), 1.0)   # kept, on the root
        self.assertIsNone(retention_factor(g, ids["Kosher salt"], ids["Stir-Frying"], ids["Sodium - Na"]))  # in no class
        self.assertIsNone(retention_factor(g, ids["Garlic"], None, ids["Sodium - Na"]))                  # no method

    def test_a_second_load_changes_nothing(self):
        g = instance()
        self.imported(g)
        imported = self.imported(g)
        self.assertEqual((imported.counts["created"], imported.counts["changed"], imported.counts["deleted"], imported.affected),
                         (0, 0, 0, set()))

    def test_a_changed_row_changes_its_factors_and_deletes_what_it_no_longer_gives(self):
        g = instance()
        self.imported(g)
        imported = self.imported(g, classed(rows={"Stir-Frying": "3455"}))
        self.assertEqual(self.node(g, "QuantitySpecification", "Retention of Sodium - Na in Alliums by Stir-Frying value")["value"], 0.7)
        self.assertFalse([r for r in g.get_all("DefaultSpecification")["result"] if "Iron - Fe in Alliums" in r["name"]])
        self.assertFalse([r for r in g.get_all("QuantitySpecification")["result"] if "Iron - Fe in Alliums" in r["name"]])
        self.assertEqual(imported.affected, {self.node(g, "DomainType", "Alliums")["id"]})

    def test_a_class_given_up_loses_its_factors_but_the_kept_ones_stay(self):
        g = instance()
        self.imported(g)
        self.imported(g, classed(rows={}))
        names = [r["name"] for r in g.get_all("DefaultSpecification")["result"]]
        self.assertFalse([n for n in names if " in Alliums by " in n])
        self.assertIn("Retention of Protein in cooking", names)
        self.assertIn("Retention of Sodium - Na in Food by Mixing", names)


if __name__ == "__main__":
    unittest.main()

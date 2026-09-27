"""The FDC extraction (mealplanner/fdc.py) and the vocabulary loader (mealplanner/vocabulary_import.py).

Figures are worked out by hand from the fixtures below:
  garlic   "1 clove" = 3 g -> 3 g each;  "1 tsp" = 2.8 g -> 2.8 / 4.92892 = 0.568076 g per mL
  onion    "0.5 cup, sliced" = 57.5 g -> 57.5 / (0.5 x 236.588) = 0.486077 g per mL
"""

import csv
import io
import os
import tempfile
import unittest
import zipfile

from mealplanner.fdc import extract
from mealplanner.vocabulary_import import (
    VocabularyError, density, import_vocabulary, mass_per_each, nutrient_name, parse_vocabulary, volume_unit,
)
from tests.fakegraph import FakeGraph, Ref


def table(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def fdc_zip(directory: str) -> str:
    path = os.path.join(directory, "fdc.zip")
    tables = {
        "food.csv": [{"fdc_id": "2", "data_type": "sr_legacy_food", "description": "Garlic, raw"},
                     {"fdc_id": "1", "data_type": "sr_legacy_food", "description": "Onions, raw"},
                     {"fdc_id": "3", "data_type": "sr_legacy_food", "description": "Not wanted"}],
        "food_nutrient.csv": [{"fdc_id": "2", "nutrient_id": "1003", "amount": "6.36"},
                              {"fdc_id": "2", "nutrient_id": "1093", "amount": "17"},
                              {"fdc_id": "1", "nutrient_id": "1003", "amount": "1.1"},
                              {"fdc_id": "1", "nutrient_id": "1062", "amount": ""},
                              {"fdc_id": "3", "nutrient_id": "1110", "amount": "5"}],
        "measure_unit.csv": [{"id": "9999", "name": "undetermined"}, {"id": "1000", "name": "cup"}],
        "food_portion.csv": [{"fdc_id": "2", "amount": "1", "measure_unit_id": "9999", "portion_description": "",
                              "modifier": "tsp", "gram_weight": "2.8"},
                             {"fdc_id": "2", "amount": "1", "measure_unit_id": "9999", "portion_description": "",
                              "modifier": "clove", "gram_weight": "3"},
                             {"fdc_id": "1", "amount": "0.5", "measure_unit_id": "1000", "portion_description": "",
                              "modifier": "sliced", "gram_weight": "57.5"}],
        "nutrient.csv": [{"id": "1003", "name": "Protein", "unit_name": "G", "nutrient_nbr": "203"},
                         {"id": "1093", "name": "Sodium, Na", "unit_name": "MG", "nutrient_nbr": "307"},
                         {"id": "1110", "name": "Vitamin D (D2 + D3), International Units", "unit_name": "IU",
                          "nutrient_nbr": "324"}],
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, rows in tables.items():
            archive.writestr(f"dataset/{name}", table(rows))
    return path


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.subset = extract(fdc_zip(self.tmp.name), {1, 2})

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_the_wanted_foods_and_the_nutrients_they_report(self):
        self.assertEqual(list(self.subset["foods"]), ["1", "2"])                  # sorted by id
        self.assertEqual(self.subset["foods"]["2"]["nutrients"], {"1003": 6.36, "1093": 17.0})
        self.assertEqual(self.subset["foods"]["1"]["nutrients"], {"1003": 1.1})    # a blank amount is left out
        self.assertEqual(list(self.subset["nutrients"]), ["1003", "1093"])         # 1110 only by a food not wanted
        self.assertEqual(self.subset["nutrients"]["1093"], {"name": "Sodium, Na", "unit": "MG", "number": "307"})

    def test_portions_carry_their_label_and_grams(self):
        self.assertEqual(self.subset["foods"]["2"]["portions"],
                         [{"amount": 1.0, "label": "clove", "grams": 3.0}, {"amount": 1.0, "label": "tsp", "grams": 2.8}])
        self.assertEqual(self.subset["foods"]["1"]["portions"], [{"amount": 0.5, "label": "cup sliced", "grams": 57.5}])

    def test_an_id_the_download_lacks_is_an_error(self):
        with self.assertRaises(KeyError):
            extract(fdc_zip(self.tmp.name), {2, 99})


class Names(unittest.TestCase):
    def test_nutrient_names_lose_their_commas(self):
        self.assertEqual(nutrient_name("Sodium, Na"), "Sodium - Na")
        self.assertEqual(nutrient_name("Fatty acids, total saturated"), "Fatty acids - total saturated")
        self.assertEqual(nutrient_name("Protein"), "Protein")

    def test_volume_units_from_portion_labels(self):
        for label, unit in (("cup", "cup"), ("cup, chopped", "cup"), ("cup packed", "cup"), ("tsp, whole", "tsp"),
                            ("fl oz", "fl_oz"), ("tbsp chopped", "tbsp"), ("tsp or 1 packet", "tsp")):
            self.assertEqual(volume_unit(label), unit, label)
        for label in ("clove", "large", "cupful", "oz"):
            self.assertIsNone(volume_unit(label), label)


def fdc_subset():
    return {"nutrients": {"1003": {"name": "Protein", "unit": "G"}, "1093": {"name": "Sodium, Na", "unit": "MG"},
                          "1062": {"name": "Energy", "unit": "kJ"}, "1008": {"name": "Energy", "unit": "KCAL"}},
            "foods": {"2": {"nutrients": {"1003": 6.36, "1093": 17.0, "1008": 149.0, "1062": 623.0},
                            "portions": [{"amount": 1.0, "label": "clove", "grams": 3.0},
                                         {"amount": 1.0, "label": "tsp", "grams": 2.8}]},
                      "1": {"nutrients": {"1003": 1.1, "1008": 40.0},
                            "portions": [{"amount": 0.5, "label": "cup sliced", "grams": 57.5}]}}}


def vocabulary_data(**extra):
    data = {"source": {"subset": "data/fdc/x.json"}, "retention": {"kept_in_cooking": [1003, 1008]},
            "method": [{"name": "Dry-Heat Method"}, {"name": "Stir-Frying", "parent": "Dry-Heat Method"}],
            "food": [{"name": "Alliums"},
                     {"name": "Garlic", "parent": "Alliums", "fdc": 2, "each": "clove", "volume": "tsp"},
                     {"name": "Onion", "parent": "Alliums", "fdc": 1, "proxy": True, "volume": "cup sliced"}]}
    data.update(extra)
    return data


class Parse(unittest.TestCase):
    def test_a_good_file(self):
        v = parse_vocabulary(vocabulary_data(), fdc_subset())
        self.assertEqual([f.name for f in v.foods], ["Alliums", "Garlic", "Onion"])
        self.assertEqual(v.foods[0].parent, "Food")
        self.assertEqual(v.kept_in_cooking, ("1003", "1008"))

    def test_densities_and_masses_from_portions(self):
        v = parse_vocabulary(vocabulary_data(), fdc_subset())
        garlic, onion = v.foods[1], v.foods[2]
        self.assertEqual(mass_per_each(v.fdc, garlic), 3.0)
        self.assertAlmostEqual(density(v.fdc, garlic), 0.568076, places=6)
        self.assertAlmostEqual(density(v.fdc, onion), 0.486077, places=6)
        self.assertIsNone(mass_per_each(v.fdc, onion))

    def test_every_problem_is_reported(self):
        data = vocabulary_data()
        data["food"] += [{"name": "Salt", "proxy": True}, {"name": "Garlic", "fdc": 2}, {"name": "Leek", "fdc": 7},
                         {"name": "Chive", "fdc": 2, "each": "bunch"}, {"name": "Sodium - Na", "fdc": 1}]
        data["method"].append({"name": "Searing", "parent": "Hot Method"})
        data["retention"]["kept_in_cooking"].append(9999)
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(data, fdc_subset())
        problems = caught.exception.problems
        for fragment in ("'Salt': a proxy needs an fdc id", "'Garlic' is listed twice", "FDC 7 is not in the pinned",
                         "no single portion 'bunch'", "same name as a food", "parent 'Hot Method'", "9999"):
            self.assertTrue(any(fragment in p for p in problems), (fragment, problems))

    def test_a_nutrient_in_an_unknown_unit_is_refused(self):
        subset = fdc_subset()
        subset["nutrients"]["1003"]["unit"] = "PH"
        with self.assertRaises(VocabularyError):
            parse_vocabulary(vocabulary_data(), subset)


RELATIONS = {"hierarchy", "parent", "isAbout", "forNutrient", "identifierScheme", "denotesType", "inScheme",
             "forType", "hasKind", "hasValue", "keyedBy"}


class Writable(FakeGraph):
    """FakeGraph with the write side the loader uses. Relationship fields are stored as Refs, so they
    render the way Structr renders them."""

    def __init__(self):
        super().__init__()
        self.posts = self.patches = 0

    def _store(self, fields):
        out = {}
        for key, value in fields.items():
            if key in RELATIONS and value is not None:
                value = [Ref(v) for v in value] if isinstance(value, list) else Ref(value)
            out[key] = value
        return out

    def post(self, path, payload):
        type_name = path.rsplit("/", 1)[-1]
        node_id = f"{type_name}:{payload['name']}"
        self.add(type_name, node_id, **self._store({k: v for k, v in payload.items() if k != "name"}),
                 name=payload["name"])
        self.posts += 1
        return {"result": [node_id]}

    def patch(self, path, payload):
        self.nodes[path.rsplit("/", 1)[-1]].update(self._store(payload))
        self.patches += 1

    def delete(self, path):
        del self.nodes[path.rsplit("/", 1)[-1]]


def instance():
    g = Writable()
    for h in ("Food Identity", "Transformation Method", "Nutrient", "Default Kind"):
        g.add("TypeHierarchy", h, h)
    for kind in ("Density", "MassPerUnit", "RetentionFactor"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Default Kind"))
    g.add("DomainType", "Protein", "Protein", hierarchy=Ref("Nutrient"))
    g.add("DomainType", "Stir-Frying", "Stir-Frying", hierarchy=Ref("Transformation Method"), parent=Ref("Wet-Heat Method"))
    g.add("DomainType", "Wet-Heat Method", "Wet-Heat Method", hierarchy=Ref("Transformation Method"))
    return g


class Load(unittest.TestCase):
    def load(self, g, data=None):
        return import_vocabulary(g, parse_vocabulary(data or vocabulary_data(), fdc_subset()))

    def node(self, g, type_name, name):
        (row,) = [r for r in g.get_all(type_name)["result"] if r["name"] == name]
        return row

    def test_foods_nutrients_and_profiles(self):
        g = instance()
        self.load(g)
        garlic = self.node(g, "DomainType", "Garlic")
        self.assertEqual((garlic["parent"]["name"], self.node(g, "DomainType", "Alliums")["parent"]["name"]), ("Alliums", "Food"))
        sodium = self.node(g, "NutrientProfile", "Garlic -- Sodium - Na per 100 g")
        self.assertEqual((sodium["amount"], sodium["unit"], sodium["provenance"], sodium["forNutrient"]["name"]),
                         (17.0, "mg", "sourced", "Sodium - Na"))
        self.assertEqual(self.node(g, "NutrientProfile", "Onion -- Protein per 100 g")["provenance"], "placeholder")
        self.assertFalse([r for r in g.get_all("NutrientProfile")["result"] if "Energy" in r["name"]
                          and self.node(g, "NutrientProfile", r["name"])["unit"] == "kJ"])       # 1062 left out
        self.assertEqual(self.node(g, "Identifier", "Garlic FDC ID")["identifierValue"], "2")
        self.assertEqual(self.node(g, "Identifier", "Sodium - Na FDC nutrient id")["denotesType"]["name"], "Sodium - Na")

    def test_the_existing_protein_type_is_reused(self):
        g = instance()
        self.load(g)
        self.assertEqual(len([r for r in g.get_all("DomainType")["result"] if r["name"] == "Protein"]), 1)

    def test_defaults_from_portions_and_the_retention_decision(self):
        g = instance()
        self.load(g)
        self.assertEqual(self.node(g, "QuantitySpecification", "Garlic mass per each value")["value"], 3.0)
        self.assertEqual(self.node(g, "QuantitySpecification", "Onion density value")["value"], 0.486077)
        kept = self.node(g, "DefaultSpecification", "Retention of Protein in cooking")
        self.assertEqual((kept["forType"]["name"], [k["name"] for k in kept["keyedBy"]]), ("Food", ["Protein"]))
        self.assertEqual(self.node(g, "QuantitySpecification", "Retention of Energy in cooking value")["value"], 1.0)

    def test_stir_frying_moves_to_dry_heat(self):
        g = instance()
        self.load(g)
        self.assertEqual(self.node(g, "DomainType", "Stir-Frying")["parent"]["name"], "Dry-Heat Method")

    def test_a_second_load_changes_nothing(self):
        g = instance()
        self.load(g)
        posts, patches = g.posts, g.patches
        counts = self.load(g)
        self.assertEqual((g.posts, g.patches, counts["created"], counts["changed"], counts["deleted"]),
                         (posts, patches, 0, 0, 0))

    def test_a_nutrient_the_food_no_longer_reports_is_deleted(self):
        g = instance()
        self.load(g)
        subset = fdc_subset()
        del subset["foods"]["2"]["nutrients"]["1093"]
        counts = import_vocabulary(g, parse_vocabulary(vocabulary_data(), subset))
        self.assertEqual(counts["deleted"], 1)
        self.assertFalse([r for r in g.get_all("NutrientProfile")["result"] if r["name"] == "Garlic -- Sodium - Na per 100 g"])

    def test_a_name_taken_in_another_hierarchy_is_an_error_not_a_move(self):
        g = instance()
        g.add("DomainType", "Garlic", "Garlic", hierarchy=Ref("Nutrient"))
        with self.assertRaises(VocabularyError):
            self.load(g)
        self.assertEqual(self.node(g, "DomainType", "Garlic")["hierarchy"]["name"], "Nutrient")


if __name__ == "__main__":
    unittest.main()

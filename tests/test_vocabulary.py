"""The FDC extraction (mealplanner/fdc.py) and the vocabulary loader (mealplanner/vocabulary_import.py).

Figures are worked out by hand from the fixtures below:
  garlic   "1 clove" = 3 g -> 3 g each;  "1 tsp" = 2.8 g -> 2.8 / 4.92892 = 0.568076 g per mL
  onion    "0.5 cup, sliced" = 57.5 g -> 57.5 / (0.5 x 236.588) = 0.486077 g per mL
  sugar    brands 10 and 11 report 337 and 375 kcal -> mean 356; sodium only brand 10 (211 mg);
           iron from neither, so from the fallback, SR 12 (1.91 mg)
           volume: brand 10 "1 Tbsp" = 19 g and brand 11 "2 tsp" = 8 g ->
           (19 / 14.7868 + 8 / (2 x 4.92892)) / 2 = (1.284930 + 0.811536) / 2 = 1.048233 g per mL
  salt     a stated 3.8 g per tsp -> 3.8 / 4.92892 = 0.770960 g per mL
  beans    energy and fiber reported only under the newer ids 2048 (113.7) and 2033 (6.9): those are
           its energy and fiber; sugars from a drier food (2.07 g, 55.7% water) scaled to the beans'
           71.2% water: 2.07 x (100 - 71.2) / (100 - 55.7) = 2.07 x 28.8 / 44.3 = 1.345734
"""

import csv
import io
import json
import os
import tempfile
import unittest
import zipfile

from mealplanner.fdc import ImplausibleRecord, extract, extract_branded, extract_survey, household, unit_name
from mealplanner.vocabulary_import import (
    VocabularyError, _with_equivalents, composition, core_gaps, import_vocabulary, measure_value, merge, nutrient_name,
    parse_vocabulary, volume_unit,
)
from tests.fakegraph import Ref, WritableGraph as Writable


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

    def test_an_id_the_download_lacks_is_an_error_unless_not_strict(self):
        with self.assertRaises(KeyError):
            extract(fdc_zip(self.tmp.name), {2, 99})
        self.assertEqual(list(extract(fdc_zip(self.tmp.name), {2, 99}, strict=False)["foods"]), ["2"])


class Survey(unittest.TestCase):
    def test_the_fndds_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "survey.zip")
            record = {"fdcId": 7, "description": "Shrimp, dried", "foodNutrients": [
                {"nutrient": {"id": 1003, "name": "Protein", "unitName": "g", "number": "203"}, "amount": 58.9},
                {"nutrient": {"id": 1093, "name": "Sodium, Na", "unitName": "mg", "number": "307"}, "amount": None},
                {"nutrient": {"id": 1109, "name": "Vitamin E", "unitName": "µg", "number": "323"}, "amount": 12.0}],
                "foodPortions": [{"portionDescription": "1 cup", "gramWeight": 135},
                                 {"portionDescription": "Quantity not specified", "gramWeight": 85}]}
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("surveyDownload.json", json.dumps({"SurveyFoods": [record]}))
            subset = extract_survey(path, {7})
        food = subset["foods"]["7"]
        self.assertEqual((food["nutrients"], food["portions"], food["data_type"]),
                         ({"1003": 58.9, "1109": 12.0}, [{"amount": 1.0, "label": "cup", "grams": 135.0}], "survey_fndds_food"))
        self.assertEqual((subset["nutrients"]["1003"]["unit"], subset["nutrients"]["1109"]["unit"]), ("G", "UG"))


def branded(fdc_id, kcal, carbs, serving, household_text, unit="g"):
    return {"fdcId": fdc_id, "description": "PALM SUGAR", "brandName": f"BRAND {fdc_id}", "servingSize": serving,
            "servingSizeUnit": unit, "householdServingFullText": household_text,
            "foodNutrients": [{"nutrientId": 1008, "nutrientName": "Energy", "unitName": "KCAL", "value": kcal},
                              {"nutrientId": 1005, "nutrientName": "Carbohydrate, by difference", "unitName": "G",
                               "value": carbs}]}


class Branded(unittest.TestCase):
    def extract(self, records, ids):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "palm sugar.json"), "w") as fh:
                json.dump({"foods": records}, fh)
            return extract_branded(tmp, ids)

    def test_a_label_with_its_household_serving(self):
        subset = self.extract([branded(10, 337, 84.2, 19.0, "1 Tbsp")], {10})
        food = subset["foods"]["10"]
        self.assertEqual((food["brand"], food["nutrients"], food["portions"]),
                         ("BRAND 10", {"1008": 337.0, "1005": 84.2}, [{"amount": 1.0, "label": "tbsp", "grams": 19.0}]))

    def test_an_impossible_label_is_refused(self):
        with self.assertRaises(ImplausibleRecord):
            self.extract([branded(12, 740, 184, 50.0, "1.75 ONZ")], {12})     # 184 g of carbohydrate in 100 g

    def test_a_label_per_millilitre_is_refused(self):
        with self.assertRaises(ImplausibleRecord):
            self.extract([branded(13, 0, 0, 15.0, "1 Tbsp", unit="ml")], {13})

    def test_household_servings(self):
        for text, want in (("1/4 tsp", (0.25, "tsp")), ("1 Tbsp", (1.0, "tbsp")), ("1 tsp (5g)", (1.0, "tsp")),
                           ("1 1/2 cups", (1.5, "cup")), ("1.75 ONZ", (1.75, "oz")), ("1 cup, shredded", (1.0, "cup, shredded"))):
            self.assertEqual(household(text), want, text)
        self.assertIsNone(household("Quantity not specified"))


class Names(unittest.TestCase):
    def test_nutrient_names_lose_their_commas(self):
        self.assertEqual(nutrient_name("Sodium, Na"), "Sodium - Na")
        self.assertEqual(nutrient_name("Fatty acids, total saturated"), "Fatty acids - total saturated")
        self.assertEqual(nutrient_name("Protein"), "Protein")

    def test_one_spelling_for_micrograms(self):
        self.assertEqual([unit_name(u) for u in ("µg", "μg", "mcg", "UG", "mg", "KCAL")], ["UG", "UG", "UG", "UG", "MG", "KCAL"])

    def test_volume_units_from_portion_labels(self):
        for label, unit in (("cup", "cup"), ("cup, chopped", "cup"), ("cup packed", "cup"), ("tsp, whole", "tsp"),
                            ("fl oz", "fl_oz"), ("tbsp chopped", "tbsp"), ("tsp or 1 packet", "tsp")):
            self.assertEqual(volume_unit(label), unit, label)
        for label in ("clove", "large", "cupful", "oz"):
            self.assertIsNone(volume_unit(label), label)


def fdc_subset():
    sr = {"nutrients": {"1003": {"name": "Protein", "unit": "G"}, "1093": {"name": "Sodium, Na", "unit": "MG"},
                        "1062": {"name": "Energy", "unit": "kJ"}, "1008": {"name": "Energy", "unit": "KCAL"},
                        "1089": {"name": "Iron, Fe", "unit": "MG"}, "2048": {"name": "Energy (Atwater Specific Factors)", "unit": "KCAL"},
                        "2047": {"name": "Energy (Atwater General Factors)", "unit": "KCAL"},
                        "2033": {"name": "Total dietary fiber (AOAC 2011.25)", "unit": "G"},
                        "1051": {"name": "Water", "unit": "G"}, "2000": {"name": "Sugars, Total", "unit": "G"},
                        "1079": {"name": "Fiber, total dietary", "unit": "G"}, "1063": {"name": "Sugars, Total", "unit": "G"}},
          "foods": {"20": {"description": "Beans, drained", "data_type": "foundation_food",
                           "nutrients": {"2048": 113.7, "2047": 116.8, "2033": 6.9, "1051": 71.2, "1003": 7.0},
                           "portions": []},
                    "22": {"description": "Onions, red, raw", "data_type": "foundation_food",
                           "nutrients": {"2047": 44.0, "1063": 4.0, "1051": 88.5}, "portions": []},
                    "21": {"description": "White beans, from canned", "data_type": "survey_fndds_food",
                           "nutrients": {"1008": 168.0, "2000": 2.07, "1079": 7.2, "1051": 55.7}, "portions": []},
                    "2": {"description": "Garlic, raw", "data_type": "sr_legacy_food",
                          "nutrients": {"1003": 6.36, "1093": 17.0, "1008": 149.0, "1062": 623.0},
                          "portions": [{"amount": 1.0, "label": "clove", "grams": 3.0},
                                       {"amount": 1.0, "label": "tsp", "grams": 2.8}]},
                    "1": {"description": "Onions, raw", "data_type": "sr_legacy_food",
                          "nutrients": {"1003": 1.1, "1008": 40.0},
                          "portions": [{"amount": 0.5, "label": "cup sliced", "grams": 57.5}]},
                    "12": {"description": "Sugars, brown", "data_type": "sr_legacy_food",
                           "nutrients": {"1008": 380.0, "1093": 28.0, "1089": 1.91, "1003": 0.12}, "portions": []}}}
    brands = {"nutrients": {"1008": {"name": "Energy", "unit": "KCAL"}, "1093": {"name": "Sodium, Na", "unit": "MG"}},
              "foods": {"10": {"description": "PALM SUGAR", "brand": "DRAGONFLY", "data_type": "branded_food",
                               "nutrients": {"1008": 337.0, "1093": 211.0},
                               "portions": [{"amount": 1.0, "label": "tbsp", "grams": 19.0}]},
                        "11": {"description": "COCONUT PALM SUGAR", "brand": "GOOD & GATHER", "data_type": "branded_food",
                               "nutrients": {"1008": 375.0}, "portions": [{"amount": 2.0, "label": "tsp", "grams": 8.0}]}}}
    return merge([sr, brands])


def vocabulary_data(**extra):
    data = {"source": {"subsets": ["data/fdc/x.json"]}, "retention": {"kept_in_cooking": [1003, 1008]},
            "method": [{"name": "Dry-Heat Method"}, {"name": "Stir-Frying", "parent": "Dry-Heat Method"}],
            "equipment": [{"name": "Cookware"}, {"name": "Wok", "parent": "Cookware"}],
            "food": [{"name": "Alliums"},
                     {"name": "Garlic", "parent": "Alliums", "fdc": 2, "each": "clove", "volume": "tsp"},
                     {"name": "Onion", "parent": "Alliums", "fdc": 1, "proxy": True, "volume": "cup sliced"},
                     {"name": "Palm sugar", "sources": [
                         {"mean": [10, 11], "note": "two labels"},
                         {"fdc": 12, "status": "estimated", "only": [1089], "note": "brown sugar for iron"}],
                      "volume": {"portions": [[10, "tbsp"], [11, "tsp"]]}},
                     {"name": "Shallot", "fdc": 1, "sources": [{"fdc": 2, "status": "estimated"}]},
                     {"name": "Kosher salt", "fdc": 2, "proxy": True,
                      "volume": {"grams": 3.8, "per": "tsp", "source": "mean of two labels"}}]}
    data.update(extra)
    return data


class Parse(unittest.TestCase):
    def vocabulary(self):
        return parse_vocabulary(vocabulary_data(), fdc_subset())

    def test_a_good_file(self):
        v = self.vocabulary()
        self.assertEqual([f.name for f in v.foods], ["Alliums", "Garlic", "Onion", "Palm sugar", "Shallot", "Kosher salt"])
        self.assertEqual(v.foods[0].parent, "Food")
        self.assertEqual(v.kept_in_cooking, ("1003", "1008"))
        self.assertEqual([(e.name, e.parent) for e in v.equipment], [("Cookware", None), ("Wok", "Cookware")])
        self.assertEqual((v.foods[1].fdc, v.foods[3].fdc), (2, None))       # a mean has no single FDC ID

    def test_measures(self):
        v = self.vocabulary()
        garlic, onion, sugar, salt = v.foods[1], v.foods[2], v.foods[3], v.foods[5]
        self.assertEqual(measure_value(v.fdc, garlic.each), 3.0)
        self.assertAlmostEqual(measure_value(v.fdc, garlic.volume), 0.568076, places=6)
        self.assertAlmostEqual(measure_value(v.fdc, onion.volume), 0.486077, places=6)
        self.assertAlmostEqual(measure_value(v.fdc, sugar.volume), 1.048233, places=5)
        self.assertAlmostEqual(measure_value(v.fdc, salt.volume), 0.770960, places=6)
        self.assertEqual((garlic.volume.status, onion.volume.status, sugar.volume.status, salt.volume.status),
                         ("sourced", "estimated", "estimated", "estimated"))

    def test_a_composition_takes_each_nutrient_from_the_first_source_that_reports_it(self):
        v = self.vocabulary()
        sugar = composition(v.fdc, v.foods[3])
        self.assertEqual(sugar["1008"][:2], (356.0, "estimated"))           # mean of 337 and 375
        self.assertEqual(sugar["1093"][:2], (211.0, "estimated"))           # only one label reports it
        self.assertEqual(sugar["1089"][:2], (1.91, "estimated"))            # the fallback, allowed only iron
        self.assertNotIn("1003", sugar)                                     # the fallback may give iron only

        self.assertIn("mean of USDA FoodData Central Branded 10 (DRAGONFLY PALM SUGAR); Branded 11 (GOOD & GATHER COCONUT PALM "
                      "SUGAR) (estimated: two labels)", sugar["1008"][2])
        self.assertIn("SR Legacy 12 (Sugars, brown)", sugar["1089"][2])

    def test_a_later_source_only_fills_what_the_earlier_ones_lack(self):
        v = self.vocabulary()
        shallot = composition(v.fdc, v.foods[4])
        self.assertEqual(shallot["1003"][:2], (1.1, "sourced"))             # its own FDC food's, not garlic's 6.36
        self.assertEqual(shallot["1093"][:2], (17.0, "estimated"))          # which it lacks, from garlic

    def test_a_direct_match_is_sourced_and_a_proxy_estimated_and_kj_is_left_out(self):
        v = self.vocabulary()
        garlic, onion = composition(v.fdc, v.foods[1]), composition(v.fdc, v.foods[2])
        self.assertEqual({k: s for k, (_, s, _) in garlic.items()}, {"1003": "sourced", "1093": "sourced", "1008": "sourced"})
        self.assertEqual(onion["1003"][1], "estimated")
        self.assertIn("SR Legacy 2 (Garlic, raw)", garlic["1003"][2])

    def test_an_older_id_the_record_has_is_kept(self):
        self.assertEqual(_with_equivalents({"1008": 100.0, "2048": 110.0, "2047": 112.0})["1008"], 100.0)
        self.assertEqual(_with_equivalents({"2047": 112.0, "2048": 110.0})["1008"], 110.0)   # Atwater specific first

    def test_vitamin_d_in_iu_is_40_times_its_micrograms_when_only_those_are_given(self):
        self.assertEqual(_with_equivalents({"1114": 2.5})["1110"], 100.0)
        self.assertEqual(_with_equivalents({"1114": 2.5, "1110": 90.0})["1110"], 90.0)   # a record's own IU figure wins

    def test_an_id_repeated_in_a_mean_counts_twice(self):
        data = vocabulary_data()
        data["food"].append({"name": "Blend", "sources": [{"mean": [2, 2, 12], "status": "calculated", "note": "2:1"}]})
        v = parse_vocabulary(data, fdc_subset())
        blend = composition(fdc_subset(), next(f for f in v.foods if f.name == "Blend"))
        self.assertAlmostEqual(blend["1008"][0], (149.0 * 2 + 380.0) / 3)      # garlic twice, brown sugar once

    def test_foundations_total_sugars_are_read_as_total_sugars(self):
        data = vocabulary_data()
        data["food"].append({"name": "Red onion", "fdc": 22})
        v = parse_vocabulary(data, fdc_subset())      # 1063 and 2000 share FDC's name: 1063 is not loaded as its own
        onion = composition(fdc_subset(), next(f for f in v.foods if f.name == "Red onion"))
        self.assertEqual((onion["2000"][0], onion["1008"][0]), (4.0, 44.0))
        self.assertNotIn("1063", onion)

    def test_a_newer_id_is_the_records_own_figure_and_a_fill_is_moisture_adjusted(self):
        data = vocabulary_data()
        data["food"].append({"name": "Beans", "fdc": 20, "sources": [{"fdc": 21, "status": "estimated", "moisture": True}]})
        v = parse_vocabulary(data, fdc_subset())
        beans = composition(v.fdc, v.foods[-1])
        self.assertEqual(beans["1008"][:2], (113.7, "sourced"))             # its own 2048, not the other food's 168
        self.assertEqual(beans["1079"][:2], (6.9, "sourced"))               # its own 2033, not 7.2
        self.assertAlmostEqual(beans["2000"][0], 1.345734, places=6)
        self.assertIn("adjusted to this food's water content", beans["2000"][2])

    def test_a_moisture_adjustment_needs_both_waters(self):
        data = vocabulary_data()
        data["food"].append({"name": "Beans", "fdc": 2, "sources": [{"fdc": 21, "moisture": True}]})   # garlic: no water
        v = parse_vocabulary(data, fdc_subset())
        with self.assertRaises(VocabularyError):
            composition(v.fdc, v.foods[-1])

    def test_core_gaps(self):
        v = self.vocabulary()
        gaps = core_gaps(v.fdc, v.foods[1])
        self.assertNotIn("Protein", gaps)
        self.assertIn("Vitamin C", gaps)

    def test_every_problem_is_reported(self):
        data = vocabulary_data()
        data["food"] += [{"name": "Salt", "proxy": True}, {"name": "Garlic", "fdc": 2}, {"name": "Leek", "fdc": 7},
                         {"name": "Chive", "fdc": 2, "each": "bunch"}, {"name": "Sodium - Na", "fdc": 1},
                         {"name": "Honey", "sources": [{"fdc": 2, "mean": [1]}]},
                         {"name": "Treacle", "sources": [{"mean": [10, 11], "status": "guessed"}]},
                         {"name": "Stock", "fdc": 1, "volume": {"grams": 1.0, "per": "each", "source": "x"}},
                         {"name": "Brine", "fdc": 1, "volume": {"grams": 1.0, "per": "tsp"}}]
        data["method"].append({"name": "Searing", "parent": "Hot Method"})
        data["retention"]["kept_in_cooking"].append(9999)
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(data, fdc_subset())
        problems = caught.exception.problems
        for fragment in ("'Salt': a proxy needs an fdc id", "'Garlic' is listed twice", "FDC 7 is not in the pinned",
                         "no single portion 'bunch'", "same name as a food", "parent 'Hot Method'", "9999",
                         "exactly one of fdc or mean", "'guessed'", "per a volume unit", "needs its source"):
            self.assertTrue(any(fragment in p for p in problems), (fragment, problems))

    def test_a_nutrient_in_an_unknown_unit_is_refused(self):
        subset = fdc_subset()
        subset["nutrients"]["1003"]["unit"] = "PH"
        with self.assertRaises(VocabularyError):
            parse_vocabulary(vocabulary_data(), subset)


def instance():
    g = Writable()
    for h in ("Food Identity", "Transformation Method", "Nutrient", "Default Kind", "Equipment Type"):
        g.add("TypeHierarchy", h, h)
    for kind in ("Density", "MassPerUnit", "RetentionFactor"):
        g.add("DomainType", kind, kind, hierarchy=Ref("Default Kind"))
    g.add("DomainType", "Protein", "Protein", hierarchy=Ref("Nutrient"))
    g.add("DomainType", "Stir-Frying", "Stir-Frying", hierarchy=Ref("Transformation Method"), parent=Ref("Wet-Heat Method"))
    g.add("DomainType", "Wet-Heat Method", "Wet-Heat Method", hierarchy=Ref("Transformation Method"))
    return g


class Load(unittest.TestCase):
    def load(self, g, data=None, subset=None):
        return import_vocabulary(g, parse_vocabulary(data or vocabulary_data(), subset or fdc_subset()))

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
        self.assertIn("SR Legacy 2 (Garlic, raw)", sodium["source"])
        self.assertEqual(self.node(g, "NutrientProfile", "Onion -- Protein per 100 g")["provenance"], "estimated")
        self.assertEqual(self.node(g, "Identifier", "Garlic FDC ID")["identifierValue"], "2")
        self.assertEqual(self.node(g, "Identifier", "Sodium - Na FDC nutrient id")["denotesType"]["name"], "Sodium - Na")
        self.assertFalse([r for r in g.get_all("Identifier")["result"] if r["name"] == "Palm sugar FDC ID"])

    def test_a_mean_and_its_fallback_are_written_with_their_sources(self):
        g = instance()
        self.load(g)
        energy = self.node(g, "NutrientProfile", "Palm sugar -- Energy per 100 g")
        iron = self.node(g, "NutrientProfile", "Palm sugar -- Iron - Fe per 100 g")
        self.assertEqual((energy["amount"], energy["provenance"]), (356.0, "estimated"))
        self.assertIn("mean of", energy["source"])
        self.assertEqual((iron["amount"], iron["provenance"]), (1.91, "estimated"))

    def test_a_label_food_is_written_per_unit_with_none_of_the_rest(self):
        data = vocabulary_data()
        data["food"].append({"name": "Vitamin pill", "label": {
            "per": "each", "status": "estimated", "source": "the owner's dose", "figures": {"1093": 5, "1089": 18}}})
        g = instance()
        self.load(g, data)
        iron = self.node(g, "NutrientProfile", "Vitamin pill -- Iron - Fe per unit")
        self.assertEqual((iron["amount"], iron["basis"], iron["unit"], iron["provenance"], iron["source"]),
                         (18.0, "per_unit", "mg", "estimated", "the owner's dose"))
        protein = self.node(g, "NutrientProfile", "Vitamin pill -- Protein per unit")
        self.assertEqual((protein["amount"], protein["source"]), (0.0, "not on the label: taken as none"))
        self.assertFalse([r for r in g.get_all("NutrientProfile")["result"] if r["name"].startswith("Vitamin pill") and "per 100 g" in r["name"]])

    def test_a_label_food_takes_nothing_else_and_names_its_source(self):
        data = vocabulary_data()
        data["food"].append({"name": "Pill", "fdc": 2, "label": {"per": "each", "figures": {"9999": -1}}})
        with self.assertRaises(VocabularyError) as caught:
            parse_vocabulary(data, fdc_subset())
        text = " ".join(caught.exception.problems)
        for fragment in ("takes no fdc", "names its source", "number from 0"):
            self.assertIn(fragment, text)

    def test_defaults_carry_provenance_and_source(self):
        g = instance()
        self.load(g)
        self.assertEqual(self.node(g, "QuantitySpecification", "Garlic mass per each value")["value"], 3.0)
        clove = self.node(g, "DefaultSpecification", "Garlic mass per each")
        self.assertEqual(clove["provenance"], "sourced")
        self.assertIn("1 clove = 3 g", clove["source"])
        salt = self.node(g, "DefaultSpecification", "Kosher salt density")
        self.assertEqual((salt["provenance"], salt["source"]), ("estimated", "3.8 g per tsp: mean of two labels"))
        self.assertEqual(self.node(g, "QuantitySpecification", "Kosher salt density value")["value"], 0.77096)
        kept = self.node(g, "DefaultSpecification", "Retention of Protein in cooking")
        self.assertEqual((kept["forType"]["name"], [k["name"] for k in kept["keyedBy"]]), ("Food", ["Protein"]))

    def test_methods_and_equipment(self):
        g = instance()
        self.load(g)
        self.assertEqual(self.node(g, "DomainType", "Stir-Frying")["parent"]["name"], "Dry-Heat Method")
        wok = self.node(g, "DomainType", "Wok")
        self.assertEqual((wok["parent"]["name"], wok["hierarchy"]["name"]), ("Cookware", "Equipment Type"))

    def test_the_existing_protein_type_is_reused(self):
        g = instance()
        self.load(g)
        self.assertEqual(len([r for r in g.get_all("DomainType")["result"] if r["name"] == "Protein"]), 1)

    def test_a_second_load_changes_nothing(self):
        g = instance()
        self.load(g)
        posts, patches = g.posts, g.patches
        counts = self.load(g)
        self.assertEqual((g.posts, g.patches, counts["created"], counts["changed"], counts["deleted"]),
                         (posts, patches, 0, 0, 0))

    def test_a_nutrient_no_source_reports_any_more_is_deleted(self):
        g = instance()
        self.load(g)
        subset = fdc_subset()
        del subset["foods"]["2"]["nutrients"]["1093"]
        counts = self.load(g, subset=subset)
        self.assertEqual(counts["deleted"], 3)                 # garlic's, shallot's and kosher salt's (all from FDC 2)
        self.assertFalse([r for r in g.get_all("NutrientProfile")["result"] if r["name"] == "Garlic -- Sodium - Na per 100 g"])

    def test_a_name_taken_in_another_hierarchy_is_an_error_not_a_move(self):
        g = instance()
        g.add("DomainType", "Garlic", "Garlic", hierarchy=Ref("Nutrient"))
        with self.assertRaises(VocabularyError):
            self.load(g)
        self.assertEqual(self.node(g, "DomainType", "Garlic")["hierarchy"]["name"], "Nutrient")


if __name__ == "__main__":
    unittest.main()

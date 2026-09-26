"""resolve_default(): resolution by (kind, keyedBy), data-model.md Sec 8.
The StructrScript resolveDefault ignored keyedBy; these are the cases it got
wrong or could not express."""

import unittest

from mealplanner.defaults import AmbiguousDefaultError, resolve_default
from mealplanner.material_accounting import resolve_yield_or_default
from tests.fakegraph import FakeGraph, Ref, type_tree


def graph(defaults, tree=None):
    """defaults: [(type, kind, [key names], value, unit)]"""
    g = FakeGraph()
    type_tree(g, tree or {"Food": {"Chicken": {}}})
    for name in ("Yield", "ShelfLife", "Braising", "Grilling", "Boiling", "Fridge", "Sealed", "Opened"):
        g.add("DomainType", name, name, defaultSpecifications=[], parent=None, children=[])
    for i, (type_name, kind, keys, value, unit) in enumerate(defaults):
        g.add("QuantitySpecification", f"q{i}", value=value, unit=unit)
        g.add("DefaultSpecification", f"d{i}", hasKind=Ref(kind), keyedBy=[Ref(k) for k in keys], hasValue=Ref(f"q{i}"))
        g.nodes[type_name]["defaultSpecifications"].append(Ref(f"d{i}"))
    return g


def value_of(g, type_name, kind, keys):
    r = resolve_default(g, type_name, kind, frozenset(keys))
    return None if r is None else r.quantity["value"]


class KeyedDefaults(unittest.TestCase):
    def test_two_transformations_each_get_their_own_yield(self):
        g = graph([("Chicken", "Yield", ["Braising"], 0.75, "ratio"), ("Chicken", "Yield", ["Grilling"], 0.85, "ratio")])
        self.assertEqual(value_of(g, "Chicken", "Yield", {"Braising"}), 0.75)
        self.assertEqual(value_of(g, "Chicken", "Yield", {"Grilling"}), 0.85)

    def test_a_default_keyed_by_something_you_dont_have_does_not_apply(self):
        g = graph([("Chicken", "Yield", ["Braising"], 0.75, "ratio")])
        self.assertIsNone(value_of(g, "Chicken", "Yield", {"Boiling"}))
        self.assertIsNone(value_of(g, "Chicken", "Yield", set()))

    def test_the_kind_is_respected(self):
        g = graph([("Chicken", "ShelfLife", ["Fridge"], 5.0, "days")])
        self.assertIsNone(value_of(g, "Chicken", "Yield", {"Fridge"}))

    def test_exact_match_beats_partial_beats_unkeyed(self):
        g = graph([("Chicken", "ShelfLife", [], 30.0, "days"),
                   ("Chicken", "ShelfLife", ["Fridge"], 7.0, "days"),
                   ("Chicken", "ShelfLife", ["Fridge", "Sealed"], 5.0, "days")])
        self.assertEqual(value_of(g, "Chicken", "ShelfLife", {"Fridge", "Sealed"}), 5.0)   # exact
        self.assertEqual(value_of(g, "Chicken", "ShelfLife", {"Fridge", "Opened"}), 7.0)   # partial
        self.assertEqual(value_of(g, "Chicken", "ShelfLife", {"Sealed"}), 30.0)            # unkeyed

    def test_two_equally_specific_defaults_are_ambiguous_not_arbitrary(self):
        g = graph([("Chicken", "Yield", ["Braising"], 0.75, "ratio"), ("Chicken", "Yield", ["Grilling"], 0.85, "ratio")])
        with self.assertRaises(AmbiguousDefaultError):
            resolve_default(g, "Chicken", "Yield", frozenset({"Braising", "Grilling"}))


class WalkingTheHierarchy(unittest.TestCase):
    def test_an_ancestors_default_is_found(self):
        g = graph([("Food", "Yield", ["Braising"], 0.9, "ratio")])
        r = resolve_default(g, "Chicken", "Yield", frozenset({"Braising"}))
        self.assertEqual((r.quantity["value"], r.found_at_type_id), (0.9, "Food"))

    def test_the_nearest_type_wins_even_over_a_better_key_match(self):
        g = graph([("Food", "Yield", ["Braising"], 0.9, "ratio"), ("Chicken", "Yield", [], 0.5, "ratio")])
        self.assertEqual(value_of(g, "Chicken", "Yield", {"Braising"}), 0.5)   # Sec 8: start at the Type

    def test_nothing_found_is_none_never_a_guess(self):
        self.assertIsNone(value_of(graph([]), "Chicken", "Yield", {"Braising"}))


class YieldFallback(unittest.TestCase):
    def test_no_default_means_mass_conserving(self):
        self.assertEqual(resolve_yield_or_default(graph([]), "Chicken", "Braising"), 1.0)

    def test_the_transformation_picks_the_right_factor(self):
        g = graph([("Chicken", "Yield", ["Braising"], 0.75, "ratio"), ("Chicken", "Yield", ["Grilling"], 0.85, "ratio")])
        self.assertEqual(resolve_yield_or_default(g, "Chicken", "Grilling"), 0.85)

    def test_a_yield_not_stated_as_a_ratio_is_refused(self):
        g = graph([("Chicken", "Yield", ["Braising"], 0.75, "g")])
        with self.assertRaises(ValueError):
            resolve_yield_or_default(g, "Chicken", "Braising")


if __name__ == "__main__":
    unittest.main()

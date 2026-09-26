"""current_magnitude() and instance_expiration(): time bounds and units.

Every case here failed against the version reviewed in round 2. Run with:
    python3 -m unittest discover -s tests -t .
"""

import unittest

from mealplanner.inventory import instance_expiration
from mealplanner.inventory import current_magnitude
from mealplanner.unit_conversion import QuantityError
from tests.fakegraph import FakeGraph, Ref, at, type_tree, when


def build(baselines, allocations=(), food_type="Chicken"):
    """One portion with one Mass quality.
    baselines: [(day, hour, value, unit, status)]; allocations: [(day, hour, value, unit)]."""
    g = FakeGraph()
    type_tree(g, {"Chicken": {}})
    for kind in ("Mass", "Density", "MassPerUnit"):
        g.add("DomainType", kind, kind, defaultSpecifications=[], parent=None, children=[])
    g.add("PortionOfSubstance", "p1", instanceOf=Ref(food_type), bearerOf=[Ref("q1")], allocationsAbout=[Ref(f"a{i}") for i in range(len(allocations))])
    ms = []
    for i, (day, hour, value, unit, status) in enumerate(baselines):
        g.add("Measurement", f"m{i}", status=status, hasTime=at(day, hour), value=value, unit=unit)
        ms.append(Ref(f"m{i}"))
    g.add("Quality", "q1", hasKind=Ref("Mass"), inheresIn=Ref("p1"), measurements=ms)
    for i, (day, hour, value, unit) in enumerate(allocations):
        g.add("Measurement", f"aq{i}", value=value, unit=unit, status="observed", hasTime=at(day, hour))
        g.add("TemporalRegion", f"r{i}", hasBeginning=at(day, hour))
        g.add("Process", f"pr{i}", occupiesTemporalRegion=Ref(f"r{i}"))
        g.add("Allocation", f"a{i}", hasParticipationRole="input", process=Ref(f"pr{i}"), hasActualQuantity=Ref(f"aq{i}"))
    return g


class BaselineIsBoundedByNow(unittest.TestCase):
    def test_a_future_measurement_is_not_the_current_baseline(self):
        g = build([(25, 10, 500.0, "g", "observed"), (26, 10, 420.0, "g", "observed")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 500.0)

    def test_it_is_the_baseline_once_its_time_arrives(self):
        g = build([(25, 10, 500.0, "g", "observed"), (26, 10, 420.0, "g", "observed")])
        self.assertEqual(current_magnitude(g, "q1", when(26, 11)), 420.0)

    def test_no_measurement_yet_is_unknown_not_zero(self):
        g = build([(26, 10, 420.0, "g", "observed")])
        self.assertIsNone(current_magnitude(g, "q1", when(25, 12)))

    def test_an_unobserved_status_is_not_a_baseline(self):
        g = build([(25, 10, 500.0, "g", "derived")])
        self.assertIsNone(current_magnitude(g, "q1", when(25, 12)))


class ConsumptionIsBoundedByNow(unittest.TestCase):
    def test_a_process_that_has_not_happened_yet_consumes_nothing(self):
        g = build([(25, 10, 500.0, "g", "observed")], [(26, 9, 200.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 500.0)

    def test_a_process_between_baseline_and_now_consumes(self):
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 11, 200.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 300.0)

    def test_a_process_before_the_baseline_is_already_reflected_in_it(self):
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 9, 200.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 500.0)

    def test_a_process_at_the_same_instant_as_the_baseline_counts(self):
        # The documented (and open) convention: REVIEW.md #18.
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 10, 200.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 300.0)


class QuantitiesAreConverted(unittest.TestCase):
    def test_a_kilogram_allocation_takes_grams_off_a_gram_baseline(self):
        # 500 g - 0.5 kg used to be 500 - 0.5 = 499.5
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 11, 0.5, "kg")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 0.0)

    def test_the_baseline_may_be_in_another_unit_too(self):
        g = build([(25, 10, 0.5, "kg", "observed")], [(25, 11, 100.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 12)), 400.0)

    def test_pounds_convert(self):
        g = build([(25, 10, 2.0, "lb", "observed")])
        self.assertAlmostEqual(current_magnitude(g, "q1", when(25, 12)), 907.184, places=3)


class UnusableQuantitiesAreLoud(unittest.TestCase):
    """The old code turned each of these into 0 and carried on."""

    def test_baseline_without_a_unit(self):
        g = build([(25, 10, 500.0, None, "observed")])
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))

    def test_unrecognised_unit(self):
        g = build([(25, 10, 500.0, "bushel", "observed")])
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))

    def test_a_volume_needs_the_foods_density(self):
        g = build([(25, 10, 2.0, "cup", "observed")])   # Chicken has no Density default
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))

    def test_an_input_allocation_without_a_quantity(self):
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 11, 1.0, "g")])
        del g.nodes["a0"]["hasActualQuantity"]
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))

    def test_a_process_with_no_start_time(self):
        g = build([(25, 10, 500.0, "g", "observed")], [(25, 11, 1.0, "g")])
        del g.nodes["pr0"]["occupiesTemporalRegion"]
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))

    def test_only_mass_qualities_are_supported(self):
        g = build([(25, 10, 500.0, "g", "observed")])
        g.add("DomainType", "Volume", "Volume")
        g.nodes["q1"]["hasKind"] = Ref("Volume")
        with self.assertRaises(QuantityError):
            current_magnitude(g, "q1", when(25, 12))


class ExpiryIsBoundedByNow(unittest.TestCase):
    def portion(self, weighings):
        g = build(weighings)
        for name in ("Fridge", "Sealed", "ShelfLife"):
            g.add("DomainType", name, name, defaultSpecifications=[], parent=None, children=[])
        g.add("DomainType", "Fresh Meat", "Fresh Meat", defaultSpecifications=[Ref("ds")], parent=None, children=[])
        g.add("QuantitySpecification", "five_days", value=5.0, unit="days")
        g.add("DefaultSpecification", "ds", hasKind=Ref("ShelfLife"), keyedBy=[Ref("Fridge"), Ref("Sealed")], hasValue=Ref("five_days"))
        g.nodes["p1"]["hasPerishabilityType"] = Ref("Fresh Meat")
        return g, g.get_all("PortionOfSubstance", "p1")["result"]

    def test_expiry_counts_from_the_latest_weighing_up_to_now(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertFalse(expired)
        self.assertAlmostEqual(days_left, 2.0)

    def test_a_weighing_dated_in_the_future_does_not_extend_it(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed"), (24, 0, 480.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertAlmostEqual(days_left, 2.0)      # not 6: the day-24 weighing hasn't happened


if __name__ == "__main__":
    unittest.main()

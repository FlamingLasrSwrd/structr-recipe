"""current_magnitude() and instance_expiration(): time bounds and units.

Every case here failed against the version reviewed in round 2. Run with:
    python3 -m unittest discover -s tests -t .
"""

import unittest

from mealplanner.inventory import current_magnitude, find_overdraws, instance_expiration, overdraws
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
        # The stated convention (data-model.md Sec 18 J8): a tie is read as the weighing
        # coming first, so the use is subtracted. Conservative: it never overstates stock.
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

    def test_with_only_one_weighing_expiry_counts_from_it(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertFalse(expired)
        self.assertAlmostEqual(days_left, 2.0)

    def test_a_weighing_dated_in_the_future_does_not_extend_it(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed"), (24, 0, 480.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertAlmostEqual(days_left, 2.0)      # not 6: the day-24 weighing hasn't happened


class ExpiryStartsWhenTheFoodBeganToExist(unittest.TestCase):
    """Shelf life runs from purchase (data-model.md Sec 5.5), not from the latest weighing.
    Fridge/Sealed shelf life is 5 days throughout."""

    def portion(self, weighings, purchased=None):
        g, portion = ExpiryIsBoundedByNow.portion(self, weighings)
        if purchased is not None:
            day, hour = purchased
            g.add("TemporalRegion", "buy_region", hasBeginning=at(day, hour))
            g.add("Process", "purchase", occupiesTemporalRegion=Ref("buy_region"))
            g.nodes["p1"]["beginsToExistDuring"] = Ref("purchase")
            portion = g.get_all("PortionOfSubstance", "p1")["result"]
        return g, portion

    def test_reweighing_does_not_restart_the_clock(self):
        # bought and first weighed on the 20th, weighed again on the 22nd, asked about on the 23rd:
        # 5 days from the 20th leaves 2 (the old code counted from the 22nd and said 4)
        g, portion = self.portion([(20, 0, 500.0, "g", "observed"), (22, 0, 480.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertAlmostEqual(days_left, 2.0)
        self.assertFalse(expired)

    def test_a_late_weighing_cannot_rescue_expired_food(self):
        # first weighed on the 20th, reweighed on the 26th: expired on the 25th, so expired on the 26th
        g, portion = self.portion([(20, 0, 500.0, "g", "observed"), (26, 0, 300.0, "g", "observed")])
        expired, days_left = instance_expiration(g, portion, when(27))
        self.assertTrue(expired)
        self.assertAlmostEqual(days_left, -2.0)

    def test_the_purchase_time_beats_every_weighing(self):
        # bought on the 15th, first weighed at home on the 20th: 5 days from the 15th ran out on the 20th
        g, portion = self.portion([(20, 0, 500.0, "g", "observed")], purchased=(15, 0))
        expired, days_left = instance_expiration(g, portion, when(23))
        self.assertTrue(expired)
        self.assertAlmostEqual(days_left, -3.0)

    def test_a_purchase_on_the_day_it_is_weighed_agrees_with_the_weighing(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed")], purchased=(20, 0))
        self.assertAlmostEqual(instance_expiration(g, portion, when(23))[1], 2.0)

    def test_a_purchase_with_no_start_time_is_an_error_not_a_guess(self):
        g, portion = self.portion([(20, 0, 500.0, "g", "observed")], purchased=(15, 0))
        del g.nodes["buy_region"]["hasBeginning"]
        with self.assertRaises(QuantityError):
            instance_expiration(g, portion, when(23))

    def test_unweighed_food_still_has_no_expiry_to_report(self):
        g, portion = self.portion([], purchased=(15, 0))
        self.assertEqual(instance_expiration(g, portion, when(23)), (False, None))


class Invariant15NoMoreUsedThanThereWas(unittest.TestCase):
    """Summed input quantities per bearer cannot exceed physical on-hand at the time of the Process."""

    def audit(self, baselines, allocations):
        g = build(baselines, allocations)
        return overdraws(g, g.get_all("PortionOfSubstance", "p1")["result"])

    def test_using_less_than_there_was_is_fine(self):
        self.assertEqual(self.audit([(25, 10, 500.0, "g", "observed")], [(25, 11, 200.0, "g"), (25, 12, 300.0, "g")]), [])

    def test_using_exactly_everything_is_fine(self):
        self.assertEqual(self.audit([(25, 10, 500.0, "g", "observed")], [(25, 11, 500.0, "g")]), [])

    def test_500_from_200_is_an_overdraw_of_300(self):
        (found,) = self.audit([(25, 10, 200.0, "g", "observed")], [(25, 11, 500.0, "g")])
        self.assertEqual((found.at, found.shortfall_grams, found.fatal), (when(25, 11), 300.0, True))

    def test_the_second_use_is_the_one_that_overdraws(self):
        # 200 g: 150 g is fine, then another 100 g runs 50 g short
        (found,) = self.audit([(25, 10, 200.0, "g", "observed")], [(25, 11, 150.0, "g"), (25, 12, 100.0, "g")])
        self.assertEqual((found.at, found.shortfall_grams), (when(25, 12), 50.0))

    def test_units_are_converted_first(self):
        # 0.5 kg on hand; 300 g is fine, then 0.25 kg takes the total to 550 g: 50 g short, at the second use only
        (found,) = self.audit([(25, 10, 0.5, "kg", "observed")], [(25, 11, 300.0, "g"), (25, 12, 0.25, "kg")])
        self.assertEqual(found.at, when(25, 12))
        self.assertAlmostEqual(found.shortfall_grams, 50.0)

    def test_an_imputed_baseline_makes_it_informative_not_fatal(self):
        (found,) = self.audit([(25, 10, 200.0, "g", "imputed")], [(25, 11, 500.0, "g")])
        self.assertFalse(found.fatal)

    def test_two_uses_at_one_instant_are_reported_once(self):
        found = self.audit([(25, 10, 200.0, "g", "observed")], [(25, 11, 150.0, "g"), (25, 11, 150.0, "g")])
        self.assertEqual([(f.at, f.shortfall_grams) for f in found], [(when(25, 11), 100.0)])

    def test_a_later_weighing_cannot_hide_an_earlier_overdraw(self):
        # 200 g at 10:00, 500 g used at 11:00, weighed again at 12:00 (nothing left): the level NOW is 0
        # and looks fine, but at 11:00 the use exceeded the stock
        g = build([(25, 10, 200.0, "g", "observed"), (25, 12, 0.0, "g", "observed")], [(25, 11, 500.0, "g")])
        self.assertEqual(current_magnitude(g, "q1", when(25, 13)), 0.0)
        (found,) = overdraws(g, g.get_all("PortionOfSubstance", "p1")["result"])
        self.assertEqual((found.at, found.shortfall_grams), (when(25, 11), 300.0))

    def test_use_before_the_first_weighing_cannot_be_judged(self):
        self.assertEqual(self.audit([(25, 12, 200.0, "g", "observed")], [(25, 11, 500.0, "g")]), [])

    def test_an_unusable_quantity_is_still_an_error(self):
        g = build([(25, 10, 200.0, "g", "observed")], [(25, 11, 1.0, "bushel")])
        with self.assertRaises(QuantityError):
            overdraws(g, g.get_all("PortionOfSubstance", "p1")["result"])

    def test_find_overdraws_scans_every_portion(self):
        g = build([(25, 10, 200.0, "g", "observed")], [(25, 11, 500.0, "g")])
        self.assertEqual([o.portion for o in find_overdraws(g)], ["p1"])


if __name__ == "__main__":
    unittest.main()

"""Invariant 12 as a format (mealplanner/domain_invariants.py NON_NEGATIVE_FORMAT, scripts/45a): the
interval, and every declaration of the four properties carrying it, since the schema helpers refuse
a re-run whose declaration differs from the instance (structr_client SchemaDriftError)."""

import pathlib
import unittest

from mealplanner import meal_planning_schema, metamodel_types
from mealplanner.domain_invariants import NON_NEGATIVE_FORMAT, NON_NEGATIVE_PROPERTIES

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Interval(unittest.TestCase):
    def test_closed_from_zero_with_an_upper_bound(self):
        # An open end ("[0,]") is accepted by Structr 6.0 and checks nothing (the format spike)
        self.assertEqual(NON_NEGATIVE_FORMAT, "[0,1000000000]")

    def test_the_four_quantity_bearing_values(self):
        self.assertEqual(set(NON_NEGATIVE_PROPERTIES), {("QuantitySpecification", "value"), ("QuantitySpecification", "minValue"),
                                                        ("QuantitySpecification", "maxValue"), ("Measurement", "value")})


class Declarations(unittest.TestCase):
    def declared(self, module, type_name, key):
        return next(p for p in module.PROPERTIES[type_name] if p["name"] == key)

    def test_the_metamodel_declares_a_quantity_value_with_it(self):
        self.assertEqual(self.declared(metamodel_types, "QuantitySpecification", "value")["format"], NON_NEGATIVE_FORMAT)

    def test_the_meal_planning_schema_declares_the_range_with_it(self):
        for key in ("minValue", "maxValue"):
            self.assertEqual(self.declared(meal_planning_schema, "QuantitySpecification", key)["format"], NON_NEGATIVE_FORMAT)

    def test_script_04_declares_a_measurement_value_with_it(self):
        source = (ROOT / "scripts" / "04_lifecycle_invariant.py").read_text()
        self.assertIn('ensure_property(mid, "value", "Double", format=NON_NEGATIVE_FORMAT)', source)


if __name__ == "__main__":
    unittest.main()

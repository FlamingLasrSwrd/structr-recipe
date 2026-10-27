"""The onSave twins of six validators (mealplanner/domain_invariants.py ONSAVE_TWINS, scripts/46a): which
six, their sources, and as_check, which turns a validator into an expression that reports instead of
refusing, for 46a's check of the stored data."""

import re
import unittest

from mealplanner import domain_invariants as inv


class Twins(unittest.TestCase):
    def test_the_six_whose_result_a_removed_link_cannot_turn(self):
        self.assertEqual([t for t, _ in inv.ONSAVE_TWINS], ["QuantitySpecification", "Measurement", "Specification",
                                                             "Allocation", "StockPolicy", "PlanningConstraint"])

    def test_each_is_its_onCreate_validator_word_for_word(self):
        self.assertEqual(dict(inv.ONSAVE_TWINS), {
            "QuantitySpecification": inv.QUANTITY_SPECIFICATION_ONCREATE, "Measurement": inv.MEASUREMENT_ONCREATE,
            "Specification": inv.SPECIFICATION_ONCREATE, "Allocation": inv.ALLOCATION_ONCREATE,
            "StockPolicy": inv.STOCK_POLICY_ONCREATE, "PlanningConstraint": inv.PLANNING_CONSTRAINT_ONCREATE})

    def test_the_four_that_would_refuse_deletes_elsewhere_are_left_out(self):
        sources = {s for _, s in inv.ONSAVE_TWINS}
        for left_out in (inv.MEAL_PLAN_ENTRY_ONCREATE, inv.SUBSTITUTION_RULE_ONCREATE, inv.DEFAULT_SPECIFICATION_ONCREATE,
                         inv.ROLE_ONCREATE):
            self.assertNotIn(left_out, sources)


class AsCheck(unittest.TestCase):
    def test_an_error_becomes_the_words_it_would_refuse_with(self):
        self.assertEqual(inv.as_check('if(lt(this.v, 0), error("v", "negative"), null)'),
                         'if(lt(this.v, 0), "v: negative", null)')

    def test_every_error_of_every_twin_turned_and_none_left(self):
        for type_name, source in inv.ONSAVE_TWINS:
            tokens = re.findall(r'error\("([^"]*)", "([^"]*)"\)', source)
            check = inv.as_check(source)
            self.assertNotIn("error(", check, type_name)
            self.assertTrue(tokens, type_name)
            for prop, token in tokens:
                self.assertIn(f'"{prop}: {token}"', check, type_name)

    def test_an_error_it_cannot_read_is_refused(self):
        with self.assertRaises(ValueError):
            inv.as_check('if(lt(this.v, 0), error(this.name, "negative"), null)')


if __name__ == "__main__":
    unittest.main()

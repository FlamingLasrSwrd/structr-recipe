"""The structural type table (mealplanner/structural_types.py): its order and parents, including
the two types that also inherit one of Structr's own traits (data-model.md Sec 19)."""

import unittest

from mealplanner.structural_types import BUILTIN_TRAITS, STRUCTURAL_TYPES, _validate, parents_of


class Table(unittest.TestCase):
    def test_the_people_and_households_inherit_ours_and_structrs(self):
        table = {name: parents_of(parent) for name, _, parent in STRUCTURAL_TYPES}
        self.assertEqual(table["Person"], ["BfoObject", "User"])
        self.assertEqual(table["Household"], ["ObjectAggregate", "Group"])
        self.assertEqual(table["MealShare"], ["DirectiveICE"])
        self.assertEqual(parents_of(None), [])
        self.assertEqual(BUILTIN_TRAITS, {"User", "Group"})

    def test_every_type_is_concrete_or_abstract_as_declared(self):
        abstract = {name for name, is_abstract, _ in STRUCTURAL_TYPES if is_abstract}
        self.assertEqual((len(STRUCTURAL_TYPES), len(abstract)), (54, 16))
        self.assertFalse({"Person", "Household", "MealShare"} & abstract)

    def test_a_bad_table_is_refused(self):
        for table, why in (([("A", False, "B"), ("B", False, None)], "a parent after its child"),
                           ([("A", False, None), ("A", False, None)], "a name twice"),
                           ([("A", False, ("User",))], "only Structr's own traits"),
                           ([("A", False, None), ("B", False, ("A", "Account"))], "an unknown second parent")):
            with self.subTest(why=why), self.assertRaises(ValueError):
                _validate(table)
        _validate([("A", False, None), ("B", False, ("A", "User"))])   # ours and Structr's: accepted


if __name__ == "__main__":
    unittest.main()

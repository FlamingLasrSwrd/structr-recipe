"""Where each food usually goes (mealplanner/places.py): a person's own place, their household's, everyone's,
then the rule, and when a choice is remembered; over tests/test_pantry_bought.py's kitchen.

Expected values worked out by hand from the rule in places.py's docstring, not from the code:
  - By the rule alone potatoes go to the pantry (30 days there, 7 in the fridge), grapes to the fridge (1 day
    in the pantry), frozen peas and their 12 oz product to the freezer.
  - Jamie (household "TEST -- Home", with Alex) buys potatoes and says the fridge: nothing is stored yet, so it
    becomes everyone's place and the household's, and Jamie keeps none of their own (the household's says the
    same). Alex then goes by the household's (fridge); Sam, in no household, by everyone's (fridge).
  - Alex then says the pantry for potatoes: the household's and everyone's stay the fridge, so the pantry is
    Alex's own; Jamie still gets the fridge. Alex says the fridge again: the household's says so, so Alex's
    own place is forgotten (deleted), and Alex goes by the household's again.
  - New potatoes (below potatoes, nothing of their own) go where potatoes go.
  - Jamie buys the 12 oz peas product and says the pantry: remembered for Frozen green peas, the food it is
    a product of, so the peas go to the pantry too, and the product goes there as its food's place.
  - A place said that the levels and the rule already give writes nothing (grapes said to the fridge).
  - Grapes bought (fridge, by the rule) and moved to the pantry 2 hours later: remembered. Another bag moved
    30 hours after buying: not (a day has passed, so it is not correcting where it was put away).
"""

import unittest
from datetime import timedelta

from mealplanner import places
from mealplanner.pantry import buy, buy_line, move
from tests.fakegraph import Ref, when
from tests.test_pantry import portion_named
from tests.test_pantry_bought import kitchen, storage_of

NOW = when(25, 12)


def home():
    g = kitchen()
    g.add("TypeHierarchy", "Default Kind", "Default Kind")
    g.add("Household", "TEST -- Home", "TEST -- Home")
    for person, groups in (("TEST -- Jamie", [Ref("TEST -- Home")]), ("TEST -- Alex", [Ref("TEST -- Home")]),
                           ("TEST -- Sam", [])):
        g.add("Person", person, person, groups=groups)
    places.ensure_vocabulary(g)
    return g


def specs(g):
    """{entry name: storage} of every remembered place."""
    return {n["name"]: g.nodes[n["targetType"].id]["name"] for n in g.nodes.values()
            if n["type"] == "DefaultSpecification" and n.get("hasKind") and g.nodes[n["hasKind"].id]["name"] == places.KIND}


def usual(g, food, person):
    u = places.usual_place(g, food, person)
    return u.storage, u.source


EVERY, HOME = places.EVERYONE, places.household_level_name("TEST -- Home")
ALEX = places.person_level_name("TEST -- Alex")


class LookingOneUp(unittest.TestCase):
    def test_with_nothing_remembered_the_rule_decides(self):
        g = home()
        for food, where in (("Potatoes", "Pantry"), ("Grapes", "Fridge"), ("Frozen green peas", "Freezer"),
                            ("Peas 12 oz", "Freezer")):
            self.assertEqual(usual(g, food, "TEST -- Jamie"), (where, places.RULE), food)
        self.assertEqual(usual(g, "Potatoes", None), ("Pantry", places.RULE))


    def test_the_nearest_food_wins_before_the_nearest_level(self):
        """As a price is found (prices.food_price): Jamie's own place for potatoes (the freezer) does not
        override the household's for new potatoes (the pantry), the more particular food."""
        g = home()
        buy(g, "New potatoes", 500, "g", NOW, "n1", storage="Fridge", by="TEST -- Alex")
        buy(g, "Potatoes", 500, "g", NOW, "n2", storage="Fridge", by="TEST -- Alex")
        buy(g, "Potatoes", 500, "g", NOW, "n3", storage="Freezer", by="TEST -- Jamie")
        buy(g, "New potatoes", 500, "g", NOW, "n4", storage="Pantry", by="TEST -- Alex")
        self.assertEqual(usual(g, "Potatoes", "TEST -- Jamie"), ("Freezer", places.YOURS))
        self.assertEqual(usual(g, "New potatoes", "TEST -- Alex"), ("Pantry", places.YOURS))
        self.assertEqual(usual(g, "New potatoes", "TEST -- Jamie"), ("Fridge", places.HOUSEHOLD))


class Remembering(unittest.TestCase):
    def test_a_first_choice_is_shared_then_a_different_one_is_the_persons_own(self):
        g = home()
        booking = buy(g, "Potatoes", 1000, "g", NOW, "a1", storage="Fridge", by="TEST -- Jamie")
        self.assertEqual(specs(g), {f"{EVERY} -- Potatoes": "Fridge", f"{HOME} -- Potatoes": "Fridge"})
        self.assertTrue(any("everyone's usual place now" in n for n in booking.notes), booking.notes)
        self.assertEqual(usual(g, "Potatoes", "TEST -- Alex"), ("Fridge", places.HOUSEHOLD))
        self.assertEqual(usual(g, "Potatoes", "TEST -- Sam"), ("Fridge", places.SHARED))
        self.assertEqual(usual(g, "New potatoes", "TEST -- Jamie"), ("Fridge", places.HOUSEHOLD))

        buy(g, "Potatoes", 1000, "g", NOW, "a2", storage="Pantry", by="TEST -- Alex")
        self.assertEqual(specs(g)[f"{ALEX} -- Potatoes"], "Pantry")
        self.assertEqual(specs(g)[f"{HOME} -- Potatoes"], "Fridge")
        self.assertEqual(usual(g, "Potatoes", "TEST -- Alex"), ("Pantry", places.YOURS))
        self.assertEqual(usual(g, "Potatoes", "TEST -- Jamie"), ("Fridge", places.HOUSEHOLD))
        level = g.nodes[f"DomainType:{ALEX}"]
        self.assertEqual(g.nodes[level["parent"].id]["name"], HOME)            # a person's level sits under their household's

        buy(g, "Potatoes", 1000, "g", NOW, "a3", storage="Fridge", by="TEST -- Alex")
        self.assertNotIn(f"{ALEX} -- Potatoes", specs(g))
        self.assertEqual(usual(g, "Potatoes", "TEST -- Alex"), ("Fridge", places.HOUSEHOLD))

    def test_a_purchase_without_a_place_goes_where_the_food_usually_goes_and_remembers_nothing(self):
        g = home()
        buy(g, "Potatoes", 1000, "g", NOW, "b1", storage="Fridge", by="TEST -- Jamie")
        before = specs(g)
        buy_line(g, "Potatoes", [500.0, 500.0], NOW, "b2", by="TEST -- Alex")
        buy(g, "Potatoes", 1000, "g", NOW, "b3", by="TEST -- Sam")
        self.assertEqual([storage_of(g, n) for n in ("Purchase b2 -- Potatoes", "Purchase b2 -- Potatoes #2",
                                                     "Purchase b3 -- Potatoes")], ["Fridge", "Fridge", "Fridge"])
        self.assertEqual(specs(g), before)

    def test_a_line_changed_before_it_is_put_away_is_remembered(self):
        g = home()
        buy_line(g, "Grapes", [500.0], NOW, "c1", storage="Pantry", by="TEST -- Jamie")
        self.assertEqual(specs(g), {f"{EVERY} -- Grapes": "Pantry", f"{HOME} -- Grapes": "Pantry"})

    def test_a_product_is_remembered_for_its_food(self):
        g = home()
        buy(g, "Peas 12 oz", 1, "g", NOW, "d1", storage="Pantry", by="TEST -- Jamie")
        self.assertEqual(specs(g), {f"{EVERY} -- Frozen green peas": "Pantry", f"{HOME} -- Frozen green peas": "Pantry"})
        self.assertEqual(places.usual_place(g, "Peas 12 oz", "TEST -- Alex"),
                         places.Usual("Pantry", places.HOUSEHOLD, "Frozen green peas"))

    def test_a_choice_the_rule_already_makes_writes_nothing(self):
        g = home()
        buy(g, "Grapes", 500, "g", NOW, "e1", storage="Fridge", by="TEST -- Jamie")
        self.assertEqual(specs(g), {})
        self.assertEqual([n["name"] for n in g.nodes.values() if n["name"].startswith("Storage places")], [EVERY])

    def test_the_same_booking_again_changes_nothing(self):
        g = home()
        buy(g, "Potatoes", 1000, "g", NOW, "f1", storage="Fridge", by="TEST -- Jamie")
        buy(g, "Potatoes", 1000, "g", NOW, "f2", storage="Pantry", by="TEST -- Alex")
        posts, patches, before = g.posts, g.patches, specs(g)
        buy(g, "Potatoes", 1000, "g", NOW, "f2", storage="Pantry", by="TEST -- Alex")
        self.assertEqual((g.posts, g.patches, specs(g)), (posts, patches, before))

    def test_no_person_no_memory(self):
        g = home()
        buy(g, "Potatoes", 1000, "g", NOW, "g1", storage="Fridge")
        self.assertEqual(specs(g), {})

    def test_before_the_script_nothing_is_remembered_and_the_booking_says_so(self):
        g = kitchen()
        g.add("Person", "TEST -- Jamie", "TEST -- Jamie", groups=[])
        booking = buy(g, "Potatoes", 1000, "g", NOW, "h1", storage="Fridge", by="TEST -- Jamie")
        self.assertEqual(storage_of(g, "Purchase h1 -- Potatoes"), "Fridge")
        self.assertTrue(any("scripts/52a" in n for n in booking.notes), booking.notes)
        self.assertEqual(usual(g, "Potatoes", "TEST -- Jamie"), ("Pantry", places.RULE))


class Moving(unittest.TestCase):
    def test_a_move_soon_after_buying_corrects_the_place_and_a_later_one_does_not(self):
        g = home()
        buy(g, "Grapes", 500, "g", NOW, "m1", by="TEST -- Jamie")
        buy(g, "Grapes", 500, "g", NOW, "m2", by="TEST -- Jamie")
        self.assertEqual(storage_of(g, "Purchase m1 -- Grapes"), "Fridge")
        move(g, portion_named(g, "Purchase m2 -- Grapes"), "Freezer", NOW + timedelta(hours=30), "m3", by="TEST -- Jamie")
        self.assertEqual(specs(g), {})
        move(g, portion_named(g, "Purchase m1 -- Grapes"), "Pantry", NOW + timedelta(hours=2), "m4", by="TEST -- Jamie")
        self.assertEqual(specs(g), {f"{EVERY} -- Grapes": "Pantry", f"{HOME} -- Grapes": "Pantry"})


if __name__ == "__main__":
    unittest.main()

"""Expected output of a Plan whose Steps chain: material_accounting.total_output_grams
and expected_combination_output.

Expected values are worked out by hand in each test. The chained cases are the
ones the old "sum every input of every Step" version got wrong: it counted
boiled pasta once as raw pasta and again as an input of the next Step.

Yields used throughout (dry pasta x2.0 when boiled, boiled pasta x0.9 when
tossed, everything else conserved): a step's kind is "boil" or "toss".
"""

import unittest

from mealplanner.material_accounting import FlowStep, expected_combination_output, total_output_grams
from mealplanner.unit_conversion import QuantityError
from tests.fakegraph import FakeGraph, Ref, type_tree

YIELDS = {("dry", "boil"): 2.0, ("cooked", "toss"): 0.9}


def yield_of(type_id, kind_id):
    return YIELDS.get((type_id, kind_id), 1.0)


def total(*steps):
    return total_output_grams(list(steps), yield_of)


class SingleStep(unittest.TestCase):
    def test_each_input_uses_its_own_yield_then_sums(self):
        # 100 g dry pasta x 2.0 + 20 g butter + 15 g parmesan
        step = FlowStep("s", "boil", [("dry", 100.0), ("butter", 20.0), ("parm", 15.0)], ["dish"])
        self.assertAlmostEqual(total(step), 235.0)

    def test_an_input_with_no_stated_amount_contributes_nothing(self):
        step = FlowStep("s", "boil", [("dry", 100.0), ("salt", None)], ["dish"])
        self.assertAlmostEqual(total(step), 200.0)

    def test_a_step_with_no_outputs_is_still_a_terminal_step(self):
        self.assertAlmostEqual(total(FlowStep("s", "boil", [("dry", 100.0)], [])), 200.0)

    def test_no_steps_is_zero(self):
        self.assertEqual(total(), 0.0)


class ChainedSteps(unittest.TestCase):
    def boil(self):
        return FlowStep("boil", "boil", [("dry", 100.0)], ["cooked"])          # flow 200

    def test_the_intermediate_takes_the_producing_steps_flow(self):
        # boil 100 g -> 200 g cooked; toss takes 200 x 0.9 = 180, plus 20 g butter = 200.
        # (The old code, skipping the amountless intermediate, gave 200 + 20 = 220.)
        toss = FlowStep("toss", "toss", [("cooked", None), ("butter", 20.0)], ["dish"])
        self.assertAlmostEqual(total(self.boil(), toss), 200.0)

    def test_a_stated_intermediate_amount_is_not_counted_twice(self):
        # Same recipe, with "200 g cooked pasta" written into the toss step.
        # The old code summed 200 (boil) + 180 (cooked x 0.9) + 20 = 400.
        toss = FlowStep("toss", "toss", [("cooked", 200.0), ("butter", 20.0)], ["dish"])
        self.assertAlmostEqual(total(self.boil(), toss), 200.0)

    def test_a_stated_amount_wins_over_the_computed_one(self):
        # The recipe says use 250 g of it: 250 x 0.9 + 20 = 245, whatever boil worked out to.
        toss = FlowStep("toss", "toss", [("cooked", 250.0), ("butter", 20.0)], ["dish"])
        self.assertAlmostEqual(total(self.boil(), toss), 245.0)

    def test_step_order_in_the_list_does_not_matter(self):
        toss = FlowStep("toss", "toss", [("cooked", None), ("butter", 20.0)], ["dish"])
        self.assertAlmostEqual(total(toss, self.boil()), 200.0)

    def test_three_steps_deep(self):
        # boil 100 dry -> 200 cooked; toss 200 x 0.9 = 180 -> dish; garnish takes the dish and 10 g parm = 190.
        toss = FlowStep("toss", "toss", [("cooked", None)], ["dish"])
        garnish = FlowStep("garnish", "garnish", [("dish", None), ("parm", 10.0)], ["plated"])
        self.assertAlmostEqual(total(self.boil(), toss, garnish), 190.0)

    def test_independent_terminal_steps_add(self):
        # 100 dry x 2.0 = 200, and separately 20 g butter melted = 20.
        a = FlowStep("a", "boil", [("dry", 100.0)], ["cooked"])
        b = FlowStep("b", "melt", [("butter", 20.0)], ["melted"])
        self.assertAlmostEqual(total(a, b), 220.0)

    def test_an_intermediate_split_between_steps_with_stated_shares(self):
        # 200 g cooked, 120 g to one dish and 80 g to another, each x 0.9 = 108 + 72 = 180.
        a = FlowStep("toss a", "toss", [("cooked", 120.0)], ["dish a"])
        b = FlowStep("toss b", "toss", [("cooked", 80.0)], ["dish b"])
        self.assertAlmostEqual(total(self.boil(), a, b), 180.0)


class WhenTheFlowCannotBeTraced(unittest.TestCase):
    def test_an_intermediate_split_with_no_stated_shares(self):
        a = FlowStep("toss a", "toss", [("cooked", None)], ["dish a"])
        b = FlowStep("toss b", "toss", [("cooked", None)], ["dish b"])
        with self.assertRaises(QuantityError):
            total(FlowStep("boil", "boil", [("dry", 100.0)], ["cooked"]), a, b)

    def test_a_step_making_both_an_intermediate_and_a_final_output(self):
        # a broth and the meat it cooked: how the mass divides is not stated
        cook = FlowStep("cook", "boil", [("dry", 100.0)], ["broth", "meat"])
        use = FlowStep("use", "toss", [("broth", None)], ["soup"])
        with self.assertRaises(QuantityError):
            total(cook, use)

    def test_a_cycle_reachable_from_a_final_step(self):
        a = FlowStep("a", "toss", [("y", None), ("butter", 5.0)], ["x"])
        b = FlowStep("b", "toss", [("x", None)], ["y", "z"])
        end = FlowStep("end", "toss", [("z", None)], ["done"])
        with self.assertRaisesRegex(QuantityError, "cycle"):
            total(a, b, end)

    def test_two_steps_feeding_each_other_are_not_a_silent_zero(self):
        a = FlowStep("a", "toss", [("y", None)], ["x"])
        b = FlowStep("b", "toss", [("x", None)], ["y"])
        with self.assertRaises(QuantityError):
            total(a, b)


def plan_graph(chained: bool):
    """The same recipe as real Structr data: 100 g dry pasta boiled, then tossed with 20 g butter.
    If `chained`, the boiled pasta is a separate Step's output; otherwise everything is one Step."""
    g = FakeGraph()
    type_tree(g, {"Food": {"dry": {}, "cooked": {}, "butter": {}, "dish": {}}})
    for name in ("Yield", "boil", "toss"):
        g.add("DomainType", name, name, defaultSpecifications=[], parent=None, children=[])
    g.add("QuantitySpecification", "q_yield", value=2.0, unit="ratio")
    g.add("DefaultSpecification", "d_yield", hasKind=Ref("Yield"), keyedBy=[Ref("boil")], hasValue=Ref("q_yield"))
    g.nodes["dry"]["defaultSpecifications"].append(Ref("d_yield"))
    g.add("QuantitySpecification", "q_yield2", value=0.9, unit="ratio")
    g.add("DefaultSpecification", "d_yield2", hasKind=Ref("Yield"), keyedBy=[Ref("toss")], hasValue=Ref("q_yield2"))
    g.nodes["cooked"]["defaultSpecifications"].append(Ref("d_yield2"))

    def spec(node_id, role, type_id, qty=None, unit="g"):
        props = dict(hasParticipationRole=role, specifies=Ref(type_id))
        if qty is not None:
            g.add("QuantitySpecification", f"q_{node_id}", value=qty, unit=unit)
            props["hasSpecifiedQuantity"] = Ref(f"q_{node_id}")
        g.add("Specification", node_id, **props)
        return Ref(node_id)

    if chained:
        g.add("Step", "s1", instanceOf=Ref("boil"), hasSpecification=[spec("s1_in", "input", "dry", 100.0), spec("s1_out", "output", "cooked")])
        g.add("Step", "s2", instanceOf=Ref("toss"), hasSpecification=[
            spec("s2_in", "input", "cooked", 0.2, "kg"),      # stated in another unit: 200 g
            spec("s2_b", "input", "butter", 20.0), spec("s2_out", "output", "dish")])
        steps = [Ref("s1"), Ref("s2")]
    else:
        g.add("Step", "s1", instanceOf=Ref("boil"), hasSpecification=[
            spec("s1_in", "input", "dry", 100.0), spec("s1_b", "input", "butter", 20.0), spec("s1_out", "output", "dish")])
        steps = [Ref("s1")]
    g.add("Plan", "plan", steps=steps)
    return g


class ThroughTheGraph(unittest.TestCase):
    def test_a_one_step_recipe(self):
        g = plan_graph(chained=False)
        # 100 x 2.0 (boil) + 20 x 1.0 (butter has no yield: conserved)
        self.assertAlmostEqual(expected_combination_output(g, g.get_all("Plan", "plan")["result"]), 220.0)

    def test_a_chained_recipe_reads_units_and_yields_per_step(self):
        g = plan_graph(chained=True)
        # boil: 100 x 2.0 = 200 (not terminal). toss: 0.2 kg = 200 g x 0.9 + 20 = 200.
        self.assertAlmostEqual(expected_combination_output(g, g.get_all("Plan", "plan")["result"]), 200.0)

    def test_an_input_that_will_not_convert_still_raises(self):
        g = plan_graph(chained=False)
        g.nodes["q_s1_b"]["unit"] = "bushel"
        with self.assertRaises(QuantityError):
            expected_combination_output(g, g.get_all("Plan", "plan")["result"])


if __name__ == "__main__":
    unittest.main()

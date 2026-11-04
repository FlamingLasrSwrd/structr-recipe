"""The planner refuses a week read while the instance changed (REVIEW.md round 3, #14): build_problem
marks the newest change before its reads, asks what changed since after them, reads again once if
anything did, and then refuses. A household member signing in is no change (review of 2026-11-01)."""

import json
import unittest
from pathlib import Path

from mealplanner.planning.extract import (CHANGE_ROOTS, READ_ATTEMPTS, RELATIONSHIPS, UNMARKED, ReadChangedError,
                                          build_problem, change_mark, changes_since)
from tests.test_planning_extract import DINNERS, NOW, kitchen

SCHEMA = {key.split("type ", 1)[1]: value for key, value in
          json.loads((Path(__file__).resolve().parent.parent / "tools" / "expected_state.json").read_text()).items()
          if key.startswith("@schema | type ")}


def below(type_name: str, root: str) -> bool:
    """Whether Structr answers a query on `root` with nodes of `type_name`: the type is the root or inherits it."""
    return type_name == root or any(below(t, root) for t in SCHEMA.get(type_name, {}).get("inheritedTraits", ()))


def stamp(second: int) -> str:
    return f"2026-10-31T05:00:{second:02d}+0000"


class Changing:
    """The planning fixture with Structr's record of changes: `changed` holds (type, id, name,
    lastModifiedDate), the type RELATIONSHIPS for a relationship, answered as Structr answers a sort by
    lastModifiedDate and a range read on it below a root: every node whose type is below the root.
    `writes` are made one at each read of the MealPlan, which every read of the week starts with."""

    def __init__(self, writes=(), changed=(("MealPlanEntry", "old", "TEST -- old", stamp(0)),)):
        self.graph, self.writes, self.changed, self.reads = kitchen(), list(writes), list(changed), 0

    def get_all(self, type_name, node_id=None, **kwargs):
        if type_name == "MealPlan" and node_id is not None:
            self.reads += 1
            if self.writes:
                write = self.writes.pop(0)
                if write:
                    self.changed = [c for c in self.changed if c[:2] != write[:2]] + [write]
        return self.graph.get_all(type_name, node_id, **kwargs)

    def get(self, path, params=None):
        params = params or {}
        root = path.removeprefix("/structr/rest/").removesuffix("/all")
        rows = [{"id": i, "type": t, "name": n, "lastModifiedDate": d} for t, i, n, d in self.changed
                if t != RELATIONSHIPS and below(t, root)]
        if root == RELATIONSHIPS:
            rows = [{"id": i, "type": "MealPlanREQUESTS_RECIPERecipeIdentity", "relType": "REQUESTS_RECIPE",
                     "sourceNode": {"name": "week"}, "targetNode": {"name": n}, "lastModifiedDate": d}
                    for t, i, n, d in self.changed if t == RELATIONSHIPS]
        if not path.endswith("/all"):
            return self.graph.get(path, params)
        if params.get("_sort") == "lastModifiedDate" and params.get("_order") == "desc":
            return {"result": sorted(rows, key=lambda r: r["lastModifiedDate"], reverse=True)[:params.get("_pageSize")]}
        if "lastModifiedDate" in params:
            low, high = params["lastModifiedDate"].strip("[]").split(" TO ")
            rows = [r for r in rows if low <= r["lastModifiedDate"] <= high]
            return {"result": rows[:params.get("_pageSize")]}
        return self.graph.get(path, params)


BOOKED = ("MealPlanEntry", "new", "TEST -- booked", stamp(5))
MEMBER = ("Person", "jamie", "TEST -- Jamie", stamp(0))


class ReadsAgainOrRefuses(unittest.TestCase):
    def expected(self):
        return build_problem(kitchen(), "week", DINNERS, NOW)

    def test_an_unchanged_instance_is_read_once(self):
        graph = Changing()
        self.assertEqual(build_problem(graph, "week", DINNERS, NOW), self.expected())
        self.assertEqual(graph.reads, 1)

    def test_a_write_during_the_first_read_is_read_again(self):
        graph = Changing(writes=[BOOKED])
        self.assertEqual(build_problem(graph, "week", DINNERS, NOW), self.expected())
        self.assertEqual(graph.reads, 2)

    def test_a_write_during_every_read_is_refused(self):
        writes = [("MealPlanEntry", f"new{i}", "TEST -- booked", stamp(5 + i)) for i in range(READ_ATTEMPTS)]
        graph = Changing(writes=writes)
        with self.assertRaises(ReadChangedError) as caught:
            build_problem(graph, "week", DINNERS, NOW)
        self.assertEqual(graph.reads, READ_ATTEMPTS)
        self.assertIn(f"{READ_ATTEMPTS} times running", str(caught.exception))
        self.assertIn(f"MealPlanEntry 'TEST -- booked' at {stamp(5 + READ_ATTEMPTS - 1)}", str(caught.exception))

    def test_a_one_pass_template_survives_a_second_read(self):
        graph = Changing(writes=[BOOKED])
        self.assertEqual(len(build_problem(graph, "week", iter(DINNERS), NOW).slots), len(DINNERS))

    def test_a_member_signing_in_during_every_read_is_read_once(self):
        """Structr keeps a session on its user, so each sign-in changes the member's node."""
        writes = [(*MEMBER[:3], stamp(5 + i)) for i in range(READ_ATTEMPTS)]
        graph = Changing(writes=writes, changed=(("MealPlanEntry", "old", "TEST -- old", stamp(0)), MEMBER))
        self.assertEqual(build_problem(graph, "week", DINNERS, NOW), self.expected())
        self.assertEqual(graph.reads, 1)


class ChangesSince(unittest.TestCase):
    def changes(self, write, changed=(("MealPlanEntry", "old", "TEST -- old", stamp(0)),)):
        graph = Changing(changed=changed)
        mark = change_mark(graph)
        graph.changed = [c for c in graph.changed if c[:2] != write[:2]] + [write]
        return changes_since(graph, mark)

    def test_a_change_in_the_same_second_as_the_newest_is_seen(self):
        self.assertEqual(self.changes(("MealPlanEntry", "new", "TEST -- new", stamp(0))),
                         [f"MealPlanEntry 'TEST -- new' at {stamp(0)}"])

    def test_the_newest_changed_again_is_seen(self):
        self.assertEqual(self.changes(("MealPlanEntry", "old", "TEST -- old", stamp(3))),
                         [f"MealPlanEntry 'TEST -- old' at {stamp(3)}"])

    def test_a_change_below_a_root_that_had_none_is_seen(self):
        self.assertEqual(self.changes(("RelationKind", "kind", "TEST -- kind", stamp(1))),
                         [f"RelationKind 'TEST -- kind' at {stamp(1)}"])

    def test_a_relationship_made_is_seen_by_its_ends(self):
        """A relationship made changes neither end's lastModifiedDate on Structr (7.1.0): asking for a
        recipe is a relationship from the week, and only the relationship's own date says so."""
        self.assertEqual(self.changes((RELATIONSHIPS, "asked", "TEST -- stew", stamp(4))),
                         [f"MealPlanREQUESTS_RECIPERecipeIdentity from 'week' to 'TEST -- stew' at {stamp(4)}"])

    def test_an_older_node_written_again_is_seen(self):
        older = (("MealPlanEntry", "old", "TEST -- old", stamp(0)),
                 ("MealPlanEntry", "older", "TEST -- older", "2026-10-30T09:00:00+0000"))
        self.assertEqual(self.changes(("MealPlanEntry", "older", "TEST -- older", stamp(2)), older),
                         [f"MealPlanEntry 'TEST -- older' at {stamp(2)}"])

    def test_nothing_written_is_nothing_changed(self):
        graph = Changing()
        self.assertEqual(changes_since(graph, change_mark(graph)), [])

    def test_a_member_signing_in_is_no_change(self):
        self.assertEqual(self.changes((*MEMBER[:3], stamp(3)), (("MealPlanEntry", "old", "TEST -- old", stamp(0)), MEMBER)), [])

    def test_a_members_target_changed_is_seen(self):
        self.assertEqual(self.changes(("NutritionTarget", "fibre", "TEST -- Jamie fibre", stamp(3)), (MEMBER,)),
                         [f"NutritionTarget 'TEST -- Jamie fibre' at {stamp(3)}"])


class TheRootsAreTheSchemas(unittest.TestCase):
    def test_every_type_the_project_made_but_person_is_below_exactly_one_root(self):
        for name in SCHEMA:
            with self.subTest(type=name):
                roots = [root for root in CHANGE_ROOTS if below(name, root)]
                if roots or not any(below(unmarked, name) for unmarked in UNMARKED):
                    self.assertEqual(len(roots), 1, roots)

    def test_below_none_is_person_and_its_ancestors_which_hold_no_node_of_their_own(self):
        unrooted = {name for name in SCHEMA if not any(below(name, root) for root in CHANGE_ROOTS)}
        self.assertEqual(unrooted, {"Person", "BfoObject", "MaterialEntity", "IndependentContinuant", "Continuant", "Entity"})
        self.assertEqual({name for name in unrooted if not SCHEMA[name]["isAbstract"]}, set(UNMARKED))


if __name__ == "__main__":
    unittest.main()

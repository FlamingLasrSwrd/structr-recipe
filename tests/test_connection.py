"""The guard between the demo scripts and the owner's data (mealplanner/connection.py)."""

import os
import unittest
from unittest import mock

from mealplanner import connection
from mealplanner.connection import OWNER_MARKER, OwnerInstanceError, connect, is_owner_instance
from structr_client.client import StructrError
from tests.fakegraph import FakeGraph


class Instance(FakeGraph):
    """A fake instance that also answers wait_until_ready, and can be built only up to before the
    Concept type exists (Structr then answers 404 for it)."""

    def __init__(self, marked=False, has_concepts=True):
        super().__init__()
        self.has_concepts = has_concepts
        self.waited = False
        if marked:
            self.add("Concept", "marker", OWNER_MARKER)

    def wait_until_ready(self):
        self.waited = True

    def get(self, path, params=None):
        if not self.has_concepts and path.endswith("/Concept"):
            raise StructrError("GET", path, 404, {"code": 404})
        return super().get(path, params)


class Marker(unittest.TestCase):
    def test_a_marked_instance_is_the_owners(self):
        self.assertTrue(is_owner_instance(Instance(marked=True)))
        self.assertFalse(is_owner_instance(Instance()))

    def test_an_instance_without_the_concept_type_yet_is_not(self):
        self.assertFalse(is_owner_instance(Instance(has_concepts=False)))

    def test_any_other_error_is_not_read_as_an_answer(self):
        class Broken(Instance):
            def get(self, path, params=None):
                raise StructrError("GET", path, 401, {"code": 401})
        with self.assertRaises(StructrError):
            is_owner_instance(Broken())


class Connect(unittest.TestCase):
    def connect_to(self, instance, **kwargs):
        with mock.patch.object(connection, "StructrClient", return_value=instance), \
                mock.patch.dict(os.environ, {"STRUCTR_SUPERUSER_PASSWORD": "x"}):
            return connect(**kwargs)

    def test_a_script_is_refused_on_the_owners_instance(self):
        with self.assertRaises(OwnerInstanceError):
            self.connect_to(Instance(marked=True))

    def test_a_script_runs_on_any_other(self):
        instance = Instance()
        self.assertIs(self.connect_to(instance), instance)
        self.assertTrue(instance.waited)

    def test_a_tool_for_owner_data_may_connect(self):
        instance = Instance(marked=True)
        self.assertIs(self.connect_to(instance, owner_data_ok=True), instance)


if __name__ == "__main__":
    unittest.main()

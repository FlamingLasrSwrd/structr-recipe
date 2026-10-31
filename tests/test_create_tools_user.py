"""The account the tools log in as (tools/create_tools_user.py, mealplanner/connection.py)."""

import importlib.util
import os
import unittest
from unittest import mock

from mealplanner import connection
from mealplanner.connection import SUPERUSER, TOOLS_USER, connect
from tests.fakegraph import WritableGraph

_spec = importlib.util.spec_from_file_location(
    "create_tools_user", os.path.join(os.path.dirname(__file__), "..", "tools", "create_tools_user.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class EnsureToolsUser(unittest.TestCase):
    def test_a_missing_account_is_made_an_admin_that_owns_nothing_and_nobody_sees(self):
        graph = WritableGraph()
        self.assertEqual(tool.ensure_tools_user(graph, "a-long-password"), "created")
        (user,) = graph.get_all("User")["result"]
        self.assertEqual(user["name"], "mealplanner-tools")
        self.assertEqual(user["password"], "a-long-password")
        self.assertIs(user["isAdmin"], True)
        self.assertIs(user["skipSecurityRelationships"], True)        # what it makes gets no OWNS, as the superuser's
        self.assertIs(user["visibleToAuthenticatedUsers"], False)
        self.assertIs(user["visibleToPublicUsers"], False)

    def test_an_existing_account_is_brought_back_into_line_and_unlocked(self):
        graph = WritableGraph()
        graph.add("User", "u1", name=TOOLS_USER, password="old", isAdmin=False, skipSecurityRelationships=False,
                  passwordAttempts=7)
        self.assertEqual(tool.ensure_tools_user(graph, "the-new-password"), "brought into line")
        user = graph.get_all("User", "u1")["result"]
        self.assertEqual((user["password"], user["isAdmin"], user["skipSecurityRelationships"], user["passwordAttempts"]),
                         ("the-new-password", True, True, 0))
        self.assertEqual(graph.posts, 0)
        self.assertEqual(len(graph.get_all("User")["result"]), 1)

    def test_other_accounts_are_left_alone(self):
        graph = WritableGraph()
        graph.add("User", "u1", name="Jamie", password="theirs", isAdmin=False)
        tool.ensure_tools_user(graph, "a-long-password")
        self.assertEqual(graph.get_all("User", "u1")["result"]["password"], "theirs")
        self.assertEqual(sorted(u["name"] for u in graph.get_all("User")["result"]), ["Jamie", TOOLS_USER])

    def test_two_accounts_of_that_name_are_refused(self):
        graph = WritableGraph()
        graph.add("User", "u1", name=TOOLS_USER)
        graph.add("User", "u2", name=TOOLS_USER)
        with self.assertRaises(RuntimeError):
            tool.ensure_tools_user(graph, "a-long-password")
        self.assertEqual(graph.patches, 0)

    def test_a_short_or_missing_password_stops_before_any_request(self):
        for env in ({}, {"STRUCTR_TOOLS_PASSWORD": "short"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, {"STRUCTR_SUPERUSER_PASSWORD": "x", **env}, clear=True), \
                    mock.patch.object(tool, "StructrClient") as client, mock.patch("builtins.print"):
                self.assertEqual(tool.main(), 1)
                client.assert_not_called()


class ToolsLogInAsTheirOwnAccount(unittest.TestCase):
    def test_connect_uses_the_tools_account_and_its_password_never_the_superuser(self):
        with mock.patch.object(connection, "StructrClient") as client, \
                mock.patch.dict(os.environ, {"STRUCTR_TOOLS_PASSWORD": "tools-pw", "STRUCTR_SUPERUSER_PASSWORD": "su-pw"}):
            connect(owner_data_ok=True)
        (_, user, password), options = client.call_args
        self.assertEqual((user, password), (TOOLS_USER, "tools-pw"))
        self.assertIs(options.get("session_login"), True)          # a password per request costs 0.4 s on 7.1
        self.assertNotEqual(user, SUPERUSER)

    def test_without_the_tools_password_connect_stops(self):
        with mock.patch.object(connection, "StructrClient"), \
                mock.patch.dict(os.environ, {"STRUCTR_SUPERUSER_PASSWORD": "su-pw"}, clear=True):
            with self.assertRaises(KeyError):
                connect(owner_data_ok=True)


if __name__ == "__main__":
    unittest.main()

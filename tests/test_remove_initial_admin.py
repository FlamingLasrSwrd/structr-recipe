"""scripts/48a: Structr's initial admin/admin account goes, and nothing else does."""

import importlib.util
import os
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "remove_48a", os.path.join(os.path.dirname(__file__), "..", "scripts", "48a_remove_initial_admin.py"))
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


class Accounts:
    """Users as REST lists them (a Person is a User too, listed with its own type); patch and delete by id."""

    def __init__(self, *users):
        self.users = [dict(u) for u in users]
        self.deleted, self.patched = [], []

    def get(self, path, params=None):
        return {"result": [u for u in self.users if u["name"] == (params or {}).get("name")]}

    def patch(self, path, body):
        self.patched.append((path.rsplit("/", 1)[1], body))

    def delete(self, path):
        user_id = path.rsplit("/", 1)[1]
        self.deleted.append(user_id)
        self.users = [u for u in self.users if u["id"] != user_id]


def password(right):
    """A stand-in for signing in: true only for admin with `right`."""
    return lambda url, name, given: name == "admin" and given == right


class RemoveInitialAdmin(unittest.TestCase):
    def test_the_account_as_structr_made_it_is_removed(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"}, {"id": "u2", "name": "Jamie", "type": "Person"})
        self.assertEqual(migration.remove_initial_admin(accounts, "http://x", signs_in=password("admin")), "removed")
        self.assertEqual(accounts.deleted, ["u1"])

    def test_an_admin_whose_password_was_changed_is_kept_and_its_count_put_back(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"})
        self.assertEqual(migration.remove_initial_admin(accounts, "http://x", signs_in=password("something long")), "kept")
        self.assertEqual(accounts.deleted, [])
        self.assertEqual(accounts.patched, [("u1", {"passwordAttempts": 0})])   # the probe's one failed sign-in

    def test_a_household_member_named_admin_is_never_touched(self):
        accounts = Accounts({"id": "p1", "name": "admin", "type": "Person"})
        self.assertEqual(migration.remove_initial_admin(accounts, "http://x", signs_in=password("admin")), "none")
        self.assertEqual((accounts.deleted, accounts.patched), ([], []))

    def test_a_database_without_one_is_left_as_it_is_and_a_second_run_finds_nothing(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"})
        migration.remove_initial_admin(accounts, "http://x", signs_in=password("admin"))
        self.assertEqual(migration.remove_initial_admin(accounts, "http://x", signs_in=password("admin")), "none")
        self.assertEqual(accounts.deleted, ["u1"])

    def test_two_accounts_of_that_name_are_refused(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"}, {"id": "u2", "name": "admin", "type": "User"})
        with self.assertRaises(RuntimeError):
            migration.remove_initial_admin(accounts, "http://x", signs_in=password("admin"))
        self.assertEqual(accounts.deleted, [])


class TheScript(unittest.TestCase):
    """main(): what it reports, and that a kept account is signed in to once only."""

    def run_main(self, accounts, right):
        tries = []

        def signs_in(url, name, given):
            tries.append(given)
            return accounts.users and name == "admin" and given == right and any(u["name"] == "admin" for u in accounts.users)

        accounts.base_url = "http://x"
        accounts.wait_until_ready = lambda: None
        with mock.patch.object(migration, "connect", return_value=accounts), mock.patch("builtins.print"):
            migration.main(signs_in=signs_in)
        return tries

    def test_a_kept_account_is_tried_once_so_its_count_stays_put_back(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"})
        self.assertEqual(self.run_main(accounts, right="changed"), ["admin"])
        self.assertEqual(accounts.patched, [("u1", {"passwordAttempts": 0})])

    def test_a_removed_account_is_checked_gone(self):
        accounts = Accounts({"id": "u1", "name": "admin", "type": "User"})
        self.assertEqual(self.run_main(accounts, right="admin"), ["admin", "admin"])
        self.assertEqual(accounts.deleted, ["u1"])


if __name__ == "__main__":
    unittest.main()

"""Who owns what: a household's data private to it, a person's private to them, shared knowledge shared
(docs/verification-and-sharing.md §3.4, "Who owns what"; Path S stage 5, docs/architecture-decision.md §7a).

The rule itself is the claimHousehold method (methods/claimHousehold.js), which works out from the graph
which node is whose and sets its visibility and grants, as the tools' admin account. This module gives it
what only the repository knows (the public recipes' names, the public price and package levels), calls it
until nothing is left to change, and makes sure the pantry's kinds of booking exist, since a household's
booking never makes shared vocabulary itself.

scripts/50a calls claim() once to move an instance's existing data over. The tools that write a
household's data (recipes from private/, profiles instantiated, the household, a committed week, bookings
from the terminal, recipe figures) call after_writing() when they are done, so what they wrote is the
household's at once: they write as the tools' account, which makes nodes every signed-in user sees.
On an instance with no household (a development stack) that does nothing.
"""

from __future__ import annotations

import glob
import os
import tomllib
from dataclasses import dataclass, field

from mealplanner import packages, places, prices
from structr_client.client import StructrError

METHOD = "claimHousehold"
OPERATIONS = "Pantry Operation"                       # pantry.OPERATIONS
# The kinds of a pantry booking's Process (pantry.py, pages/lib/50_pantry.js): made here, shared, since a
# household's booking finds its kind and never makes one
KINDS = ("Purchase", "Use", "Discarding", "Stock take", "Opening", "Move")
PUBLIC_LEVELS = {level for level, _ in prices.LEVELS} | {packages.PUBLIC_LEVEL, places.EVERYONE}
# A household's own levels; a person's level of storage places is theirs (claimHousehold finds it by its name first)
LEVEL_HIERARCHIES = (prices.PRICE_HIERARCHY, packages.PACKAGE_HIERARCHY, places.HIERARCHY)


class OwnershipError(RuntimeError):
    pass


@dataclass
class Claimed:
    household: str | None = None
    changed: int = 0
    remaining: int = 0
    owned: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    note: str = ""


def shared_recipes(root: str) -> list[str]:
    """The public recipes' names (data/recipes/*.toml): shared with every user. Every other recipe on an
    instance is a household's own, or, as a baseline, a person's."""
    names = []
    for path in sorted(glob.glob(os.path.join(root, "data", "recipes", "*.toml"))):
        with open(path, "rb") as fh:
            names.append(tomllib.load(fh)["name"])
    return names


def household_levels(client) -> list[str]:
    """The price, package and storage-place levels that are a household's own: every level in those hierarchies
    but the public ones (prices.LEVELS, packages.PUBLIC_LEVEL, places.EVERYONE). A person's own level of storage
    places is listed too; claimHousehold makes it the person's before it comes to the household's."""
    out = []
    for hierarchy in LEVEL_HIERARCHIES:
        rows = client.get("/structr/rest/TypeHierarchy", params={"name": hierarchy})["result"]
        if not rows:
            continue
        for ref in client.get_all("TypeHierarchy", rows[0]["id"])["result"].get("domainTypes") or []:
            if ref.get("name") not in PUBLIC_LEVELS:
                out.append(ref["name"])
    return sorted(out)


def households(client) -> list[dict]:
    try:
        return [r for r in client.get("/structr/rest/Household")["result"] if r.get("type") == "Household"]
    except StructrError as exc:
        if exc.status == 404:             # before scripts/34a: no households at all
            return []
        raise


def ensure_operations(client) -> list[str]:
    """The Pantry Operation kinds, check-then-create (hard rule 5), seen by every signed-in user: what this made."""
    made = []
    found = client.get("/structr/rest/TypeHierarchy", params={"name": OPERATIONS})["result"]
    if found:
        hierarchy = found[0]["id"]
    else:
        hierarchy = client.post("/structr/rest/TypeHierarchy", {"name": OPERATIONS, "visibleToAuthenticatedUsers": True,
                                                                "visibleToPublicUsers": False})["result"][0]
        made.append(OPERATIONS)
    for kind in KINDS:
        if [r for r in client.get("/structr/rest/DomainType", params={"name": kind})["result"] if r.get("type") == "DomainType"]:
            continue
        client.post("/structr/rest/DomainType", {"name": kind, "hierarchy": hierarchy, "isLookupBearing": False,
                                                 "visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False})
        made.append(kind)
    return made


def claim(client, root: str, *, check: bool = False, limit: int = 500) -> Claimed:
    """Make the instance's one household's data its own, and its people's theirs (claimHousehold), in calls
    of at most `limit` changes until none is left; with `check`, say only how much would change."""
    found = households(client)
    if len(found) != 1:
        raise OwnershipError(f"this instance has {len(found)} households: ownership is worked out for an instance of one")
    args = {"household": found[0]["id"], "shared": shared_recipes(root), "levels": household_levels(client),
            "limit": limit, "check": check}
    done = Claimed(household=found[0]["name"])
    while True:
        try:
            answer = client.post(f"/structr/rest/{METHOD}", args)["result"]
        except StructrError as exc:
            if exc.status == 404:
                raise OwnershipError(f"the {METHOD} method is not installed: run tools/install_methods.py") from exc
            raise
        if answer.get("problem"):
            raise OwnershipError(answer["problem"])
        done.changed += answer["changed"]
        done.owned = answer["owned"]
        for type_name, n in (answer.get("counts") or {}).items():
            done.counts[type_name] = done.counts.get(type_name, 0) + n
        done.remaining = answer["remaining"]
        if check or not answer["remaining"] or not answer["changed"]:
            return done


def after_writing(client, root: str) -> Claimed:
    """After a tool wrote a household's data as the tools' account: make it the household's (claim), where the
    instance has one household. None: nothing; several: nothing, and a note saying why."""
    found = households(client)
    if not found:
        return Claimed(note="no household on this instance, so everything stays shared")
    if len(found) > 1:
        return Claimed(note=f"{len(found)} households on this instance: what was written stays shared "
                            "(ownership is worked out for an instance of one)")
    ensure_operations(client)
    return claim(client, root)


def report(done: Claimed) -> str:
    """One line for a tool's output."""
    if done.note:
        return f"ownership: {done.note}"
    what = ", ".join(f"{t} {n}" for t, n in sorted(done.counts.items())) or "nothing new"
    return f"ownership: {done.changed} node(s) made {done.household!r}'s or its people's ({what}); {done.owned} are theirs"


def settle(client, root: str, out=print) -> bool:
    """For a tool that has written a household's data: after_writing, its line printed. False (and a problem
    printed) if the household's data could not be made its own."""
    try:
        out(report(after_writing(client, root)))
        return True
    except OwnershipError as exc:
        out(f"problem: ownership: {exc}")
        return False

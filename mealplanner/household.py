"""A household and its people, from the owner's selection file (data-model.md Sec 19, K1-K4).

    name = "Home"                          # the Household: a BFO object aggregate and a Structr Group
    [[person]]
    name = "Elijah"                        # a Person: also a Structr account, with no password until one is set
    nutrition = "private/nutrition.toml"   # their dietary selection (docs/profiles.md)
    baseline = ["Daily supplements"]       # what they take every day (recipe files with baseline = true)
    adopts = true                          # the targets set up before there were people are theirs
    [[person]]
    name = "Cass"
    nutrition = "private/nutrition-cass.toml"

Each person gets their own standing daily targets, named "Daily <nutrient> target (<name>)"
and linked to them (profiles.instantiate_nutrition), and their own baseline. The household's
members are its Group members. Nobody is given a password here: a person signs in only once
someone sets one in Structr. Running it again changes nothing unless the files did; a person no
longer listed stops being a member but is not deleted, since what they did is history.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

from mealplanner.profiles import ProfileError, Report, _name_ok, instantiate_nutrition
from mealplanner.vocabulary_import import Sync


def latest_plan(client, name: str) -> dict:
    """The newest version of the recipe (or baseline) with this name: "<name> v<n>"."""
    versions = [p for p in client.get_all("Plan")["result"] if p["name"].rsplit(" v", 1)[0] == name
                and p["name"].rsplit(" v", 1)[-1].isdigit()]
    if not versions:
        raise ProfileError([f"no recipe or baseline named {name!r} (load it with tools/import_recipe.py)"])
    return max(versions, key=lambda p: int(p["name"].rsplit(" v", 1)[1]))


@dataclass
class HouseholdReport:
    household: str
    household_id: str = ""
    members: list[str] = field(default_factory=list)
    people: dict[str, Report] = field(default_factory=dict)     # person -> their targets' report
    baselines: dict[str, list[str]] = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


def parse_household(selection: dict, root: str) -> tuple[str, list[dict]]:
    """(household name, people with their nutrition selections read), or ProfileError naming every problem."""
    problems: list[str] = []
    name = selection.get("name", "Home")
    _name_ok("name", name, problems)
    people, seen, adopters = [], set(), []
    for i, raw in enumerate(selection.get("person", []), 1):
        where = f"person {i}"
        if not _name_ok(where, raw.get("name"), problems):
            continue
        where = f"person {raw['name']!r}"
        if raw["name"] in seen:
            problems.append(f"{where} is listed twice")
        seen.add(raw["name"])
        if raw.get("adopts"):
            adopters.append(raw["name"])
        path = raw.get("nutrition")
        nutrition = None
        if not path:
            problems.append(f"{where}: name their dietary selection file (nutrition = \"private/...\")")
        elif not os.path.exists(os.path.join(root, path)):
            problems.append(f"{where}: {path} does not exist")
        else:
            with open(os.path.join(root, path), "rb") as fh:
                nutrition = tomllib.load(fh)
        baseline = raw.get("baseline", [])
        if not isinstance(baseline, list) or not all(isinstance(b, str) for b in baseline):
            problems.append(f"{where}: baseline is a list of names")
        people.append({"name": raw["name"], "nutrition": nutrition, "baseline": baseline, "adopts": bool(raw.get("adopts"))})
    if not people:
        problems.append("a household needs at least one [[person]]")
    if len(adopters) > 1:
        problems.append(f"only one person can adopt the targets set up before there were people, not {adopters}")
    if problems:
        raise ProfileError(problems)
    return name, people


def instantiate_household(client, selection: dict, root: str, *, reset: bool = False) -> HouseholdReport:
    """The household, its people, and each person's targets and baseline (see the module)."""
    name, people = parse_household(selection, root)
    baselines = {p["name"]: [latest_plan(client, b)["id"] for b in p["baseline"]] for p in people}
    sync = Sync(client)
    ids = {p["name"]: sync.ensure("Person", p["name"], {"hasBaseline": sorted(baselines[p["name"]])}) for p in people}
    household = sync.ensure("Household", name, {"members": sorted(ids.values())})
    report = HouseholdReport(name, household, members=[p["name"] for p in people])
    for p in people:
        report.baselines[p["name"]] = list(p["baseline"])
        report.people[p["name"]] = instantiate_nutrition(client, p["nutrition"], reset=reset,
                                                         person=(p["name"], ids[p["name"]]), adopt=p["adopts"])
    report.counts = sync.counts
    return report

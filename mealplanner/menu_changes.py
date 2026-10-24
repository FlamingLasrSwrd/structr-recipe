"""Changing a committed week as it goes (the owner's request, 2026-10-24; data-model.md Sec 18 J34).

"Sometimes I don't cook an option on the menu instead eating something else." A planned meal not
made is skipped (MealPlanEntry.isSkipped, which the nutrition report, the shopping list and the
planner already leave out), and what was eaten in its place is recorded:

  - a recipe from the book: an entry of its own at the same meal, cooking what was eaten, with the
    same people eating the same servings, so the nutrition page counts it and "Mark cooked" can
    draw it from the pantry;
  - anything else: its words on the skipped entry (eatenInstead), and since its nutrition is not
    known, the targets of its people over that meal's scopes become unknown, not short;
  - nothing: the meal counts for nothing, and its slot is free for the planner to fill again
    (tools/plan_week.py plans a week's free meals still to come once it is under way).

Skipping a cook skips the meals that were to eat its leftovers too, since there is nothing for
them to eat; undoing it restores them, unless something else has been planned there since. A
meal already cooked is not skipped: it happened (skip the meals eating its leftovers instead).

pages/week.js does the same, function by function, from the week page's buttons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from structr_client import StructrError

SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}


class MenuError(ValueError):
    pass


@dataclass
class Change:
    skipped: list = field(default_factory=list)       # entry names skipped
    restored: list = field(default_factory=list)      # entry names no longer skipped
    created: list = field(default_factory=list)       # names of the nodes written new
    notes: list = field(default_factory=list)


def _entry(client, entry_id: str) -> dict:
    try:
        entry = client.get_all("MealPlanEntry", entry_id)["result"]
    except (StructrError, KeyError):
        entry = None
    if not entry or entry.get("type") != "MealPlanEntry":
        raise MenuError("no such meal")
    return entry


def _start(client, entry: dict) -> str | None:
    region = entry.get("isAbout")
    return client.get_all("TemporalRegion", region["id"])["result"].get("hasBeginning") if region else None


def _servings(client, holder: dict) -> float:
    """nutrition_scope.entry_servings_eaten: the stated servings, else one."""
    ref = holder.get("hasPlannedConsumption")
    q = client.get_all("QuantitySpecification", ref["id"])["result"] if ref else None
    return q["value"] if q and q.get("value") is not None and q["value"] >= 0 and q.get("unit") == "servings" else 1.0


def book_recipe(client, text: str) -> dict | None:
    """The recipe named, ignoring case: a version by its full name ("Veggie Bowls v2"), or a recipe
    by its own ("Veggie Bowls", its newest version). None when the book has no such recipe."""
    wanted = text.strip().lower()
    if not wanted:
        return None
    plans = [p for p in client.get_all("Plan")["result"] if p.get("specializationOf")]
    exact = [p for p in plans if p["name"].lower() == wanted]
    if exact:
        return exact[0]
    versions = []
    for p in plans:
        base, _, version = p["name"].rpartition(" v")
        if base.lower() == wanted and version.isdigit():
            versions.append((int(version), p))
    return max(versions, key=lambda vp: vp[0])[1] if versions else None


def _ensure(client, change: Change, type_name: str, name: str, fields: dict) -> str:
    """Find by name, else create (CLAUDE.md hard rules 4 and 5); an existing node gets `fields`."""
    found = [r for r in client.get(f"/structr/rest/{type_name}", params={"name": name})["result"] if r.get("type") == type_name]
    if len(found) > 1:
        raise MenuError(f"two {type_name} nodes are named {name!r}")
    if found:
        client.patch(f"/structr/rest/{type_name}/{found[0]['id']}", fields)
        return found[0]["id"]
    change.created.append(name)
    return client.post(f"/structr/rest/{type_name}", {"name": name, **fields, **SEEN})["result"][0]


def _held(client, entry: dict, start: str | None) -> str | None:
    """The name of another meal of the week planned at this one's time, not skipped, if any."""
    week = entry.get("memberOf")
    if not week or start is None:
        return None
    for ref in client.get_all("MealPlan", week["id"])["result"].get("hasEntry") or []:
        if ref["id"] == entry["id"]:
            continue
        other = client.get_all("MealPlanEntry", ref["id"])["result"]
        if not other.get("isSkipped") and _start(client, other) == start:
            return other["name"]
    return None


def _replacement(client, change: Change, entry: dict, plan: dict) -> None:
    """An entry cooking `plan` at the skipped meal, eaten by the same people in the same servings."""
    slot = entry["name"].split(" -- ")[0]
    name = f"{slot} -- {plan['name']}"
    if name == entry["name"]:
        raise MenuError(f"{plan['name']} is the meal skipped")
    region = client.get_all("TemporalRegion", entry["isAbout"]["id"])["result"]
    shares = [client.get_all("MealShare", s["id"])["result"] for s in entry.get("hasShare") or []]
    eaten = sum(_servings(client, s) for s in shares) if shares else _servings(client, entry)
    fields = {"memberOf": entry["memberOf"]["id"], "isSkipped": False, "references": plan["id"], "hasPlannedServings": eaten,
              "isAbout": _ensure(client, change, "TemporalRegion", f"{name} region",
                                 {"hasBeginning": region.get("hasBeginning"), "hasEnd": region.get("hasEnd")})}
    if abs(eaten - 1.0) > 1e-9:
        fields["hasPlannedConsumption"] = _ensure(client, change, "QuantitySpecification", f"{name} servings eaten",
                                                  {"value": eaten, "unit": "servings", "status": "specified"})
    entry_id = _ensure(client, change, "MealPlanEntry", name, fields)
    for share in shares:
        who = (share.get("eatenBy") or {}).get("name", "?")
        qty = _ensure(client, change, "QuantitySpecification", f"{name} -- {who} servings",
                      {"value": _servings(client, share), "unit": "servings", "status": "specified"})
        _ensure(client, change, "MealShare", f"{name} -- {who}",
                {"shareOf": entry_id, "eatenBy": share["eatenBy"]["id"], "hasPlannedConsumption": qty})
    change.notes.append(f"{name}: planned in its place, for {eaten:g} serving{'s' if eaten != 1 else ''}.")


def skip(client, entry_id: str, instead: str = "") -> Change:
    """Skip a planned meal, and record what was eaten instead: a recipe of the book's, other words, or
    nothing (module docstring)."""
    change = Change()
    entry = _entry(client, entry_id)
    if entry.get("isSkipped"):
        raise MenuError(f"{entry['name']}: skipped already")
    if entry.get("fulfilledBy"):
        raise MenuError(f"{entry['name']}: cooked already, so it happened; skip the meals that were to eat it instead")
    instead = " ".join(instead.split())
    plan = book_recipe(client, instead) if instead else None
    if plan is not None:
        _replacement(client, change, entry, plan)
    client.patch(f"/structr/rest/MealPlanEntry/{entry['id']}",
                 {"isSkipped": True, "eatenInstead": instead if instead and plan is None else None})
    change.skipped.append(entry["name"])
    if instead and plan is None:
        change.notes.append(f"{entry['name']}: skipped; {instead} eaten instead, which the book has no figures for.")
    else:
        change.notes.append(f"{entry['name']}: skipped.")
    pending = [ref["id"] for ref in entry.get("sourceForLeftoverEntries") or []]
    while pending:                                  # the meals that were to eat its leftovers
        later = client.get_all("MealPlanEntry", pending.pop(0))["result"]
        if later.get("isSkipped"):
            continue
        client.patch(f"/structr/rest/MealPlanEntry/{later['id']}", {"isSkipped": True})
        change.skipped.append(later["name"])
        change.notes.append(f"{later['name']}: skipped too, as there are no leftovers to eat.")
        pending.extend(ref["id"] for ref in later.get("sourceForLeftoverEntries") or [])
    return change


def unskip(client, entry_id: str) -> Change:
    """Undo a skip: the meal is planned again, and so are the leftover meals its skip took with it,
    unless another meal has been planned at its time since."""
    change = Change()
    entry = _entry(client, entry_id)
    if not entry.get("isSkipped"):
        raise MenuError(f"{entry['name']}: not skipped")
    source = entry.get("consumesLeftoverFrom")
    if source and client.get_all("MealPlanEntry", source["id"])["result"].get("isSkipped"):
        raise MenuError(f"{entry['name']}: its leftovers come from {source['name']}, which is skipped; undo that first")
    held = _held(client, entry, _start(client, entry))
    if held:
        raise MenuError(f"{held} is planned at this meal now; skip it first")
    client.patch(f"/structr/rest/MealPlanEntry/{entry['id']}", {"isSkipped": False, "eatenInstead": None})
    change.restored.append(entry["name"])
    change.notes.append(f"{entry['name']}: planned again.")
    pending = [ref["id"] for ref in entry.get("sourceForLeftoverEntries") or []]
    while pending:
        later = client.get_all("MealPlanEntry", pending.pop(0))["result"]
        if not later.get("isSkipped") or later.get("eatenInstead"):
            continue                                # never skipped, or skipped for a reason of its own
        held = _held(client, later, _start(client, later))
        if held:
            change.notes.append(f"{later['name']}: left skipped, as {held} is planned there now.")
            continue
        client.patch(f"/structr/rest/MealPlanEntry/{later['id']}", {"isSkipped": False})
        change.restored.append(later["name"])
        change.notes.append(f"{later['name']}: planned again too.")
        pending.extend(ref["id"] for ref in later.get("sourceForLeftoverEntries") or [])
    return change

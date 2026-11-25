"""Where each food is usually kept: a person's own place for it, else their household's, else everyone's, else
the rule (docs/pantry.md, "Where each food goes"; the owner, 2026-11-25).

The first remembered value of the owner's "remembered values inherit user, then household, then the food
across all users" (2026-11-23), stored the way prices and package sizes are (prices.py, packages.py): a
level is a DomainType in the "Storage Place Reference" hierarchy, and a remembered place is a
DefaultSpecification of kind "Storage Place" on a level, keyed by the food, whose `targetType` is the
storage condition (Fridge, Freezer, Pantry). No schema change: `targetType` has been on DefaultSpecification
since scripts/05, for a Yield's product, and a place has no QuantitySpecification (data-model.md §8, J43).

  Storage places -- everyone                   shared with every user (scripts/52a makes it)
    Storage places -- household <name>         private to the household (its Group reads and writes it)
      Storage places -- person <name>          the person's own (they read and write it; their household reads it)

On an instance with no household, a person's level sits under everyone's.

**Looking one up** (usual_place): the food bought, or for a product the food it is a product of (a brand
keeps where its food does), then each food above it, nearest first; for each, the person's level, then
their household's, then everyone's; the first that has a place for it wins, as a price is found
(prices.food_price). With none, the rule: pantry.default_storage (frozen by name, else the fridge or the
pantry, whichever FoodKeeper says keeps it longer).

**Remembering one** (remember): when a person picks a place for a food themselves (Buy, or a shopping line
changed before it is put away, or a move within FRESH_HOURS of buying it, which corrects where it was put
away). New knowledge that overrides nothing is shared at once (the owner's rule, docs/todo.md "New shared
data reaches every user at once"): where everyone's level has no place for the food, the choice becomes
everyone's; where the household's has none, the household's. Then, if the levels above the person now say
what they chose, they keep no place of their own (one they had is removed, so they follow the household
again); otherwise the choice is their own. A choice the levels above already make writes nothing. A
household's or everyone's place someone else gave is never changed from a booking: that stays theirs, or a
suggestion to curate (docs/verification-and-sharing.md §3.6).

pages/lib/57_places.js does the same on the pages; tools/check_bookings.py compares the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from mealplanner.typetree import ancestors_or_self, dt
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

HIERARCHY = "Storage Place Reference"
KIND = "Storage Place"
EVERYONE = "Storage places -- everyone"
STORAGE = ("Fridge", "Freezer", "Pantry")
FRESH_HOURS = 24                  # a move this soon after buying corrects where it was put away, and is remembered
SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}

YOURS, HOUSEHOLD, SHARED, RULE = "yours", "your household's", "everyone's", "the usual rule"


def _clean(name: str) -> str:
    """A name as a level's name holds it: no comma or semicolon, which a name looked up exactly cannot hold."""
    return "".join(c for c in str(name) if c not in UNSAFE_EXACT_MATCH_CHARS).strip()


def household_level_name(household: str) -> str:
    return f"Storage places -- household {_clean(household)}"


def person_level_name(person: str) -> str:
    return f"Storage places -- person {_clean(person)}"


def entry_name(level: str, food: str) -> str:
    return f"{level} -- {food}"


@dataclass(frozen=True)
class Usual:
    storage: str                  # Fridge, Freezer or Pantry
    source: str                   # YOURS, HOUSEHOLD, SHARED or RULE
    food: str | None = None       # the food whose place it is (the one bought, or a food above it); None by the rule

    def words(self) -> str:
        """As the pages say it: "the freezer (yours)"."""
        return f"the {self.storage.lower()} ({self.source})"


def _one(client, type_name: str, name: str) -> dict | None:
    rows = [r for r in client.get(f"/structr/rest/{type_name}", params={"name": name})["result"] if r.get("type") == type_name]
    return rows[0] if len(rows) == 1 else None


def installed(client) -> bool:
    """Whether scripts/52a has made the kind and everyone's level."""
    return _one(client, "DomainType", KIND) is not None and _one(client, "DomainType", EVERYONE) is not None


def place_food(client, food_id: str) -> str:
    """The food a place is remembered for: the food itself, or for a product the food it is a product of."""
    from mealplanner.products import product_ids          # products reads the vocabulary module; only here
    products = product_ids(client)
    for type_id in ancestors_or_self(client, food_id):
        if type_id not in products:
            return type_id
    return food_id


def household_of(client, person_id: str | None) -> dict | None:
    """The person's one household (a Structr Group they are in), or None for none or several."""
    if not person_id:
        return None
    groups = [g for g in client.get_all("Person", person_id)["result"].get("groups") or [] if g.get("type") == "Household"]
    return groups[0] if len(groups) == 1 else None


def levels(client, person_id: str | None) -> list[tuple[str, dict]]:
    """[(source, level)] of the levels that exist for this person, nearest first."""
    out = []
    if person_id:
        person = client.get_all("Person", person_id)["result"]
        mine = _one(client, "DomainType", person_level_name(person["name"]))
        if mine:
            out.append((YOURS, mine))
        household = household_of(client, person_id)
        theirs = _one(client, "DomainType", household_level_name(household["name"])) if household else None
        if theirs:
            out.append((HOUSEHOLD, theirs))
    everyone = _one(client, "DomainType", EVERYONE)
    if everyone:
        out.append((SHARED, everyone))
    return out


def entry(client, level_id: str, food_id: str) -> dict | None:
    """The place a level gives this food itself (not a food above it), as its DefaultSpecification."""
    for ref in client.get_all("DomainType", level_id)["result"].get("defaultSpecifications") or []:
        spec = client.get_all("DefaultSpecification", ref["id"])["result"]
        if (spec.get("hasKind") or {}).get("name") == KIND and [k["id"] for k in spec.get("keyedBy") or []] == [food_id] \
                and (spec.get("targetType") or {}).get("name") in STORAGE:
            return spec
    return None


def _resolve(client, food_id: str, found: list[tuple[str, dict]]) -> Usual:
    from mealplanner.pantry import default_storage        # pantry books with this module; only here
    for type_id in ancestors_or_self(client, place_food(client, food_id)):
        for source, level in found:
            spec = entry(client, level["id"], type_id)
            if spec:
                return Usual(spec["targetType"]["name"], source, client.get_all("DomainType", type_id)["result"]["name"])
    return Usual(default_storage(client, food_id), RULE)


def usual_place(client, food_id: str, person_id: str | None = None) -> Usual:
    """Where this food goes for this person (the module's docstring, "Looking one up")."""
    return _resolve(client, food_id, levels(client, person_id))


def fresh(client, portion: dict, when: datetime) -> bool:
    """Whether the portion was bought within FRESH_HOURS before `when`: a move then corrects where it was put away."""
    from mealplanner.inventory import FMT
    process = portion.get("beginsToExistDuring")
    if not process:
        return False
    process = client.get_all("Process", process["id"])["result"]
    if (process.get("hasKind") or {}).get("name") != "Purchase" or not process.get("occupiesTemporalRegion"):
        return False
    began = client.get_all("TemporalRegion", process["occupiesTemporalRegion"]["id"])["result"].get("hasBeginning")
    if not began:
        return False
    bought = datetime.strptime(began, FMT)
    return timedelta(0) <= when - bought <= timedelta(hours=FRESH_HOURS)


def remember(client, writer, food_id: str, storage: str, person_id: str | None) -> list[str]:
    """Remember that this person put this food in `storage` (the module's docstring, "Remembering one"),
    writing through the booking's writer (pantry._Writer). Notes for the booking."""
    if storage not in STORAGE or not person_id:
        return []
    if not installed(client):
        return ["where it was kept isn't remembered yet: run scripts/52a_storage_places.py"]
    person = client.get_all("Person", person_id)["result"]
    food = place_food(client, food_id)
    food_name = client.get_all("DomainType", food)["result"]["name"]
    kind, place = dt(client, KIND), dt(client, storage)
    hierarchy = _one(client, "TypeHierarchy", HIERARCHY)["id"]
    everyone = _one(client, "DomainType", EVERYONE)
    household = household_of(client, person_id)
    source = f"chosen by {_clean(person['name'])}"

    def level_of(name: str, parent: str) -> str:
        return writer.ensure("DomainType", name, {"hierarchy": hierarchy, "isLookupBearing": True, "parent": parent})

    def put(level_id: str, level_name: str) -> str:
        return writer.ensure("DefaultSpecification", entry_name(level_name, food_name), {
            "forType": level_id, "hasKind": kind, "keyedBy": [food], "targetType": place, "source": source})

    def above() -> Usual:
        found = [lv for lv in levels(client, person_id) if lv[0] != YOURS]
        return _resolve(client, food_id, found)

    mine = _one(client, "DomainType", person_level_name(person["name"]))
    own = entry(client, mine["id"], food) if mine else None
    if above().storage == storage and not own:
        return []
    notes = []
    if not entry(client, everyone["id"], food):
        put(everyone["id"], EVERYONE)
        notes.append(f"{food_name}: everyone's usual place now, the {storage.lower()}")
    parent = everyone["id"]
    if household:
        name = household_level_name(household["name"])
        parent = level_of(name, everyone["id"])
        if not entry(client, parent, food):
            put(parent, name)
            notes.append(f"{food_name}: your household's usual place now, the {storage.lower()}")
    if above().storage == storage:
        if own:
            client.delete(f"/structr/rest/DefaultSpecification/{own['id']}")
            notes.append(f"{food_name}: your own place for it is forgotten, so it goes to the usual place again")
        return notes
    if own:
        if (own.get("targetType") or {}).get("id") != place:
            client.patch(f"/structr/rest/DefaultSpecification/{own['id']}", {"targetType": place, "source": source})
            notes.append(f"{food_name}: your usual place now, the {storage.lower()}")
        return notes
    name = person_level_name(person["name"])
    put(level_of(name, parent), name)
    notes.append(f"{food_name}: your usual place now, the {storage.lower()}")
    return notes


def ensure_vocabulary(client) -> list[str]:
    """The hierarchy, the kind and everyone's level, check-then-create (hard rule 5), seen by every signed-in
    user (rule 4): what this made (scripts/52a)."""
    made = []
    found = _one(client, "TypeHierarchy", HIERARCHY)
    if found:
        hierarchy = found["id"]
    else:
        hierarchy = client.post("/structr/rest/TypeHierarchy", {"name": HIERARCHY, "singleParent": True, **SEEN})["result"][0]
        made.append(HIERARCHY)
    if not _one(client, "DomainType", KIND):
        kinds = _one(client, "TypeHierarchy", "Default Kind")
        if not kinds:
            raise LookupError("no Default Kind hierarchy: run the build scripts first")
        client.post("/structr/rest/DomainType", {"name": KIND, "hierarchy": kinds["id"], "isLookupBearing": False, **SEEN})
        made.append(KIND)
    if not _one(client, "DomainType", EVERYONE):
        client.post("/structr/rest/DomainType", {"name": EVERYONE, "hierarchy": hierarchy, "isLookupBearing": True, **SEEN})
        made.append(EVERYONE)
    return made


def places_of(client, person_id: str | None) -> list[tuple[str, str, str]]:
    """Every place remembered on this person's levels: [(food, storage, source)], by food then nearest level."""
    out = []
    for source, level in levels(client, person_id):
        for ref in client.get_all("DomainType", level["id"])["result"].get("defaultSpecifications") or []:
            spec = client.get_all("DefaultSpecification", ref["id"])["result"]
            keys = spec.get("keyedBy") or []
            if (spec.get("hasKind") or {}).get("name") == KIND and len(keys) == 1 and spec.get("targetType"):
                out.append((keys[0]["name"], spec["targetType"]["name"], source))
    order = {YOURS: 0, HOUSEHOLD: 1, SHARED: 2}
    return sorted(out, key=lambda r: (r[0].lower(), order[r[2]]))

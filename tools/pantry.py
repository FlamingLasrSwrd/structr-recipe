"""Book what happens to the pantry, as Grocy does (mealplanner/pantry.py, docs/pantry.md).

    python3 tools/pantry.py list [FOOD] [--sort expires|food|kept]   # what is on hand, soonest to expire first
    python3 tools/pantry.py buy FOOD AMOUNT UNIT [--storage Fridge|Freezer|Pantry] [--keeps CLASS]
    python3 tools/pantry.py scan BARCODE [PACKAGES]     # buy a product by its barcode: one package, or so many
    python3 tools/pantry.py use PORTION AMOUNT UNIT
    python3 tools/pantry.py count PORTION AMOUNT UNIT   # stock take: what it holds now
    python3 tools/pantry.py open PORTION
    python3 tools/pantry.py move PORTION Freezer        # freeze, or keep it anywhere else
    python3 tools/pantry.py discard PORTION             # everything left, thrown away
    python3 tools/pantry.py meals private/week.toml     # the week's meals not yet cooked
    python3 tools/pantry.py cook ENTRY                  # a planned meal, cooked: its ingredients drawn

`list` sorts as the pantry page does (pages/pantry.js): by --sort expires (soonest first, unknown last), food
(by name) or kept (fridge, freezer, pantry), a "-" before it reversing (--sort=-food); every order breaks
ties soonest first. Where a portion is kept is its container's storage condition, or for one in no
container where its food keeps longest, marked "(assumed)" (inventory.assumed_storage, J31).
A PORTION is its name as `list` prints it, or its id; an ENTRY is an id as `meals` prints it. A FOOD
is a food or a product; a BARCODE is one a product was loaded with (tools/import_products.py).
Every booking happens now unless --at gives an ISO time, and is named by --token, else a new
one, so running the same booking twice with the same token writes nothing new. A purchase, a use,
a discard and a cook name who made them: the Person --by names, else the Person the tool signs in as,
if it signs in as one (the tools' own account is none, so they then name no one). Writes the
instance's data, the owner's included; needs STRUCTR_TOOLS_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import secrets
import sys
import tomllib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import ownership, pantry, products
from mealplanner.connection import connect
from mealplanner.inventory import assumed_storage, container_storage_condition, instance_expiration
from mealplanner.unit_conversion import QuantityError
from mealplanner.nutrition_scope import FMT, active_entries

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_portion(client, ref: str) -> str:
    rows = client.get("/structr/rest/PortionOfSubstance", params={"name": ref})["result"]
    if len(rows) == 1:
        return rows[0]["id"]
    try:
        return client.get_all("PortionOfSubstance", ref)["result"]["id"]
    except Exception:
        raise pantry.PantryError(f"no portion named {ref!r} (tools/pantry.py list shows them)") from None


STORAGE = ("Fridge", "Freezer", "Pantry")          # pages/lib/50_pantry.js STORAGE: the order --sort kept lists them in
SORTS = ("expires", "food", "kept")


def sort_rows(rows: list[dict], sort: str = "expires") -> list[dict]:
    """Rows ({food, name, days, kept}) in the pantry page's order (pages/pantry.js): `sort` is expires, food or
    kept, a "-" before it reversing; each breaks ties by the default (soonest first, unknown last, then by
    food and name). An order it does not know is the default."""
    key = sort.lstrip("-") if sort.lstrip("-") in SORTS and sort.count("-") <= 1 else "expires"
    reverse = sort == "-" + key

    def by_expiry(r):
        return (r["days"] is None, r["days"] or 0.0, r["food"].casefold(), r["name"])

    out = sorted(rows, key=by_expiry)
    if key == "food":
        out.sort(key=lambda r: r["food"].casefold(), reverse=reverse)        # stable: ties stay soonest first
    elif key == "kept":
        out.sort(key=lambda r: STORAGE.index(r["kept"]) if r["kept"] in STORAGE else len(STORAGE), reverse=reverse)
    elif reverse:
        known = [r for r in out if r["days"] is not None]
        out = sorted(known, key=lambda r: -r["days"]) + [r for r in out if r["days"] is None]
    return out


def show(client, food: str | None, now: datetime, sort: str = "expires") -> None:
    rows = []
    for portion in client.get_all("PortionOfSubstance")["result"]:
        name = (portion.get("instanceOf") or {}).get("name", "")
        if food and name != food:
            continue
        stated = container_storage_condition(client, portion)
        row = {"food": name, "name": portion["name"], "days": None, "expiry": "",
               "kept": stated or assumed_storage(client, portion), "assumed": not stated}
        try:
            grams = pantry.on_hand(client, portion, now)
        except QuantityError as exc:
            rows.append(dict(row, amount=f"? ({exc})"))
            continue
        if grams is None or grams < pantry.USED_UP_G:
            continue
        _, days = instance_expiration(client, portion, now)
        rows.append(dict(row, amount=f"{grams:,.0f} g", days=days,
                         expiry="" if days is None else (f"expired {-days:.0f} days ago" if days < 0 else f"{days:.1f} days left")))
    for r in sort_rows(rows, sort):
        kept = r["kept"] + (" (assumed)" if r["assumed"] else "")
        print(f"{r['name']:55} {r['amount']:>10}  {kept:18} {r['expiry']}")


def meals(client, week_file: str) -> int:
    with open(week_file, "rb") as fh:
        week = tomllib.load(fh)
    name = week.get("name") or f"Week of {week['start'].isoformat()}"
    zone = ZoneInfo(week.get("timezone", "UTC"))
    plans = client.get("/structr/rest/MealPlan", params={"name": name})["result"]
    if len(plans) != 1:
        print(f"problem: no single MealPlan named {name!r}")
        return 1
    rows = []
    for entry in active_entries(client, client.get_all("MealPlan", plans[0]["id"])["result"]):
        if entry.get("fulfilledBy") or not entry.get("references"):
            continue
        region = client.get_all("TemporalRegion", entry["isAbout"]["id"])["result"]
        rows.append((datetime.strptime(region["hasBeginning"], FMT).astimezone(zone), entry))
    for start, entry in sorted(rows, key=lambda row: row[0]):
        print(f"{entry['id']}  {start:%a %d %b %H:%M}  {entry['references']['name']} ({entry.get('hasPlannedServings'):g} servings)")
    return 0


def scan(client, barcode: str, packages: float, when: datetime, token: str, **how) -> pantry.Booking:
    """Buy so many packages of the product a barcode names, each holding what the product says one holds."""
    if packages <= 0:
        raise pantry.PantryError("the number of packages must be more than 0")
    try:
        found = products.find(client, barcode)
    except ValueError as exc:               # not a product's barcode at all, or one two products share
        raise pantry.PantryError(str(exc)) from None
    if found is None:
        raise pantry.PantryError(f"no product has barcode {products.normalize(barcode)}: add it on the pantry page "
                                 "(Add a product) or to the products file (tools/import_products.py), or buy the food by name")
    if found.amount is None:
        raise pantry.PantryError(f"{found.product}: no package size is known for it, so buy it by name with an amount")
    booking = pantry.buy(client, found.product, found.amount * packages, found.unit, when, token, **how)
    booking.notes.insert(0, f"{found.product}: {packages:g} x {found.amount:g} {found.unit}")
    return booking


def report(booking: pantry.Booking) -> None:
    if booking.process and not booking.created:
        print(f"{booking.process}: booked before; nothing new written")
    elif booking.process:
        print(f"{booking.process}: wrote {len(booking.created)} node(s)")
    for note in booking.notes:
        print(note)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["list", "buy", "scan", "use", "count", "open", "move", "discard", "meals", "cook"])
    parser.add_argument("args", nargs="*")
    parser.add_argument("--storage", default="Fridge")
    parser.add_argument("--keeps", help="its Perishability Class, for a shelf life")
    parser.add_argument("--at", help="when it happened, ISO with a zone; default now")
    parser.add_argument("--token", help="the booking's name; default a new one")
    parser.add_argument("--by", help="the Person who made it, by name; default the Person signed in, if any")
    parser.add_argument("--sort", default="expires", help="list's order: expires, food or kept; -food etc. reverses")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
    token = args.token or secrets.token_hex(4)
    wants = {"list": (0, 1), "buy": (3, 3), "scan": (1, 2), "use": (3, 3), "count": (3, 3), "open": (1, 1), "move": (2, 2),
             "discard": (1, 1), "meals": (1, 1), "cook": (1, 1)}[args.action]
    if not wants[0] <= len(args.args) <= wants[1]:
        parser.error(f"{args.action} takes {wants[0]}" + ("" if wants[0] == wants[1] else f" to {wants[1]}") + " argument(s)")
    client = connect(owner_data_ok=True)        # the pantry's own data: the owner's too
    client.wait_until_ready()
    a = args.args
    try:
        by = pantry.person_named(client, args.by) if args.by else pantry.signed_in_person(client)
        if args.action == "list":
            show(client, a[0] if a else None, now, args.sort)
        elif args.action == "meals":
            return meals(client, a[0])
        elif args.action == "buy":
            report(pantry.buy(client, a[0], float(a[1]), a[2], now, token, storage=args.storage, keeps=args.keeps, by=by))
        elif args.action == "scan":
            report(scan(client, a[0], float(a[1]) if len(a) > 1 else 1.0, now, token, storage=args.storage,
                        keeps=args.keeps, by=by))
        elif args.action == "use":
            report(pantry.use(client, find_portion(client, a[0]), float(a[1]), a[2], now, token, by=by))
        elif args.action == "count":
            report(pantry.stock_take(client, find_portion(client, a[0]), float(a[1]), a[2], now, token, by=by))
        elif args.action == "open":
            report(pantry.open_portion(client, find_portion(client, a[0]), now, token, by=by))
        elif args.action == "move":
            report(pantry.move(client, find_portion(client, a[0]), a[1], now, token, by=by))
        elif args.action == "discard":
            report(pantry.discard(client, find_portion(client, a[0]), now, token, by=by))
        elif args.action == "cook":
            booking, short = pantry.cook(client, a[0], now, token, by=by)
            report(booking)
            for s in short:
                print(f"not in the pantry: {s.food}, {s.needed - s.drawn:,.0f} g of the {s.needed:,.0f} g it took")
    except (pantry.PantryError, LookupError) as exc:
        print(f"problem: {exc}")
        return 1
    if args.action not in ("list", "meals") and not ownership.settle(client, ROOT):   # what it booked is the household's
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Book what happens to the pantry, as Grocy does (mealplanner/pantry.py, docs/pantry.md).

    python3 tools/pantry.py list [FOOD]                 # what is on hand, soonest to expire first
    python3 tools/pantry.py buy FOOD AMOUNT UNIT [--storage Fridge|Freezer|Pantry] [--keeps CLASS]
    python3 tools/pantry.py use PORTION AMOUNT UNIT
    python3 tools/pantry.py count PORTION AMOUNT UNIT   # stock take: what it holds now
    python3 tools/pantry.py open PORTION
    python3 tools/pantry.py move PORTION Freezer        # freeze, or keep it anywhere else
    python3 tools/pantry.py discard PORTION             # everything left, thrown away
    python3 tools/pantry.py meals private/week.toml     # the week's meals not yet cooked
    python3 tools/pantry.py cook ENTRY                  # a planned meal, cooked: its ingredients drawn

A PORTION is its name as `list` prints it, or its id; an ENTRY is an id as `meals` prints it.
Every booking happens now unless --at gives an ISO time, and is named by --token, else a new
one, so running the same booking twice with the same token writes nothing new. Writes the
instance's data, the owner's included; needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import secrets
import sys
import tomllib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import pantry
from mealplanner.connection import connect
from mealplanner.inventory import instance_expiration
from mealplanner.unit_conversion import QuantityError
from mealplanner.nutrition_scope import FMT, active_entries


def find_portion(client, ref: str) -> str:
    rows = client.get("/structr/rest/PortionOfSubstance", params={"name": ref})["result"]
    if len(rows) == 1:
        return rows[0]["id"]
    try:
        return client.get_all("PortionOfSubstance", ref)["result"]["id"]
    except Exception:
        raise pantry.PantryError(f"no portion named {ref!r} (tools/pantry.py list shows them)") from None


def show(client, food: str | None, now: datetime) -> None:
    rows = []
    for portion in client.get_all("PortionOfSubstance")["result"]:
        name = (portion.get("instanceOf") or {}).get("name", "")
        if food and name != food:
            continue
        try:
            grams = pantry.on_hand(client, portion, now)
        except QuantityError as exc:
            rows.append((float("inf"), portion["name"], f"? ({exc})", ""))
            continue
        if grams is None or grams <= 0:
            continue
        _, days = instance_expiration(client, portion, now)
        rows.append((days if days is not None else float("inf"), portion["name"], f"{grams:,.0f} g",
                     "" if days is None else (f"expired {-days:.0f} days ago" if days < 0 else f"{days:.1f} days left")))
    for _, name, amount, expiry in sorted(rows):
        print(f"{name:55} {amount:>10}  {expiry}")


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


def report(booking: pantry.Booking) -> None:
    if booking.process and not booking.created:
        print(f"{booking.process}: booked before; nothing new written")
    elif booking.process:
        print(f"{booking.process}: wrote {len(booking.created)} node(s)")
    for note in booking.notes:
        print(note)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["list", "buy", "use", "count", "open", "move", "discard", "meals", "cook"])
    parser.add_argument("args", nargs="*")
    parser.add_argument("--storage", default="Fridge")
    parser.add_argument("--keeps", help="its Perishability Class, for a shelf life")
    parser.add_argument("--at", help="when it happened, ISO with a zone; default now")
    parser.add_argument("--token", help="the booking's name; default a new one")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
    token = args.token or secrets.token_hex(4)
    wants = {"list": (0, 1), "buy": (3, 3), "use": (3, 3), "count": (3, 3), "open": (1, 1), "move": (2, 2),
             "discard": (1, 1), "meals": (1, 1), "cook": (1, 1)}[args.action]
    if not wants[0] <= len(args.args) <= wants[1]:
        parser.error(f"{args.action} takes {wants[0]}" + ("" if wants[0] == wants[1] else f" to {wants[1]}") + " argument(s)")
    client = connect(owner_data_ok=True)        # the pantry's own data: the owner's too
    client.wait_until_ready()
    a = args.args
    try:
        if args.action == "list":
            show(client, a[0] if a else None, now)
        elif args.action == "meals":
            return meals(client, a[0])
        elif args.action == "buy":
            report(pantry.buy(client, a[0], float(a[1]), a[2], now, token, storage=args.storage, keeps=args.keeps))
        elif args.action == "use":
            report(pantry.use(client, find_portion(client, a[0]), float(a[1]), a[2], now, token))
        elif args.action == "count":
            report(pantry.stock_take(client, find_portion(client, a[0]), float(a[1]), a[2], now, token))
        elif args.action == "open":
            report(pantry.open_portion(client, find_portion(client, a[0])))
        elif args.action == "move":
            report(pantry.move(client, find_portion(client, a[0]), a[1]))
        elif args.action == "discard":
            report(pantry.discard(client, find_portion(client, a[0]), now, token))
        elif args.action == "cook":
            booking, short = pantry.cook(client, a[0], now, token)
            report(booking)
            for s in short:
                print(f"not in the pantry: {s.food}, {s.needed - s.drawn:,.0f} g of the {s.needed:,.0f} g it took")
    except (pantry.PantryError, LookupError) as exc:
        print(f"problem: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

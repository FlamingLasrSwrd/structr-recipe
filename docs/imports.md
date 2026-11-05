# Imports from similar applications

**Status: a guide, as built (2026-11-04), first stage: Grocy's pantry.** Not yet run against a live
instance: a live run on a throwaway stack waits for session S1's pantry changes to merge
(`docs/session-plan.md`). The owner asked for imports from similar applications on 2026-10-26
(`docs/todo.md`, "Imports from similar applications, Grocy first").

## Grocy, first stage

Grocy (grocy.info) is a self-hosted pantry manager; the pantry bookings here were modelled on its stock
actions (`docs/pantry.md`). This stage reads what Grocy holds about a pantry and books it here:

| Grocy | Becomes | How |
|---|---|---|
| products | foods of `data/vocabulary.toml` | **only through the owner's map file.** A match is a judgment (J19), so the importer never makes one: it proposes foods whose names look alike, and books a product only once the map names its food |
| quantity units | grams, millilitres or items | a unit whose name or plural is one of ours (Gram, Kilogram, Liter, Milliliter, Piece, Ounce, Pound, Cup, ...) is that unit; any other (Pack, Glass, Tin, Bottle) is a count of its own, which only a conversion turns into a mass |
| quantity unit conversions | the grams a stock amount is booked in; weights per item and densities, reported | the fewest conversions from the stock unit to a mass, read in either direction, a product's own conversion standing in for the general one between the same two units, as in Grocy. Where none reaches a mass, a volume (millilitres) or items, which the vocabulary's density or weight per item turns into grams when it is booked |
| locations | storage conditions (Fridge, Freezer, Pantry) | a location Grocy marks a freezer is the Freezer; one named Fridge, Freezer or Pantry is that one; every other is named in the map |
| stock entries | Purchase bookings | `pantry.buy` for each, at the start of its purchase date in the owner's time zone, kept where its location says, and `pantry.open_portion` for one Grocy has opened. Each is named `grocy <stock id>`, so importing the same export twice writes nothing new |

What the conversions say about a product that crosses from a count or a volume to a mass (a Piece of
chocolate is 100 g, a Liter of milk 1,030 g) is reported, not written: a weight per item or a density
belongs in the vocabulary, where every figure carries its source and is reviewed, and the report says
whether the matched food has one already. A conversion from a Pack or a Bottle to grams is a package
size, reported for the later "What ingredients are sold in" (`docs/todo.md`).

### Running it

```bash
python3 tools/import_grocy.py --fetch https://grocy.example private/grocy/       # needs GROCY_API_KEY
python3 tools/import_grocy.py private/grocy/ --draft > private/grocy-map.toml     # then review every line
python3 tools/import_grocy.py private/grocy/ --map private/grocy-map.toml --check
STRUCTR_URL=http://localhost:8085 python3 tools/import_grocy.py private/grocy/ --map private/grocy-map.toml --timezone America/Edmonton
```

An export is one JSON file per Grocy REST object, as `GET /api/objects/<name>` returns it: `products`,
`quantity_units`, `quantity_unit_conversions`, `locations` and `stock`. `--fetch` records them, with an
API key from Grocy's "Manage API keys" in `GROCY_API_KEY`. The owner's export and map are the owner's
data and go in `private/`, which git ignores.

`--check` reads no instance and writes nothing. It lists the products the map matches, each other
product with the vocabulary foods that look like it (or none: a new food to add, or not a food), each
location's storage condition and where it came from, the purchases it would book, every stock entry it
would not book and why, the facts the conversions state, and what it leaves for a later stage. It
fails on a map that cannot be right: a product mapped to a group of foods (such as "Eggs", which other
foods sit under), or a product the export does not hold. Booking without `--check` stops on the same
problems, and needs `--timezone`, since Grocy keeps a date without one.

`--draft` prints a map for the owner to review: what the map already says, each product whose name is a
vocabulary food's (ignoring case) filled in and marked "check it", and every other product commented out
with the foods that look like it. Nothing in it is confirmed until the owner saves it as the map.

### The map file

```toml
[foods]
"Eggs" = "Egg"                 # a Grocy product -> a food in the vocabulary (or the instance)
"Pickles" = ""                 # not a food here: its stock is not booked

[locations]
"Candy cupboard" = "Pantry"    # a Grocy location -> Fridge, Freezer or Pantry
```

### What it does not do yet

- **What is left, as bought.** A Grocy stock entry holds what is left of a purchase, not what was bought
  (that is in Grocy's stock journal), so what is left is booked as bought on the purchase date. Its
  shelf life then runs from the purchase, as every purchase's does.
- **When it was opened.** An opened entry is booked opened; its opened date is not kept, as the pantry
  keeps no date for an opening (`docs/pantry.md`).
- **Left for a later stage**, each counted in the report: best-before dates, until a printed date can be
  recorded (`docs/todo.md`); prices, as `PriceObservation`s (J27, not built); the shopping list; and
  Grocy's recipes, as recipe files under `docs/recipe-copyright.md`. Then Mealie, Tandoor, Paprika and
  KitchenOwl exports, and schema.org `Recipe` data, the same way.

### The fixtures

`tests/fixtures/grocy/` is an export **written by hand** in the shape of Grocy 4's REST API, with
product and location names like those of Grocy's demo, not a recording: this session could not reach
Grocy's public demo (network access was refused). It holds no personal data. Replace it with a
recording from the demo (`--fetch https://demo.grocy.info` with a demo API key) when one can be made,
and work out the tests' expected values again by hand. `tests/test_grocy.py` states the hand-worked
values it checks against.

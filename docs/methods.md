# Structr methods and households

**Status: a guide, as built** (2026-10-26), for stages 1 and 2 of Path S (`architecture-decision.md`
§7a). What a request does is moving into Structr's JavaScript methods, run as the person who calls
them, with Structr's own access control keeping households apart. Python keeps the planner's search
and the batch work. Two methods exist so far; the pages still do the rest, as the superuser.

## Methods as code

Each `methods/<name>.js` is the body of one Structr user-defined function, installed by
`tools/install_methods.py`. Its source is the engine code in `pages/lib/` (every file, in name order)
and then the file, in one `{ ... }` block, which is how Structr knows to run it as JavaScript
(`structr-cheatsheet.md` §3a). The pages run the same files, then `pages/common.js` (their own shell:
escaping, navigation, the week a page is about, a booking from a page's address), then their own
script. So a method runs the engine code the pages run, not a copy of it.

| `pages/lib/` | What |
|---|---|
| `10_units.js` | units, defaults resolved along a Type's hierarchy, days, how numbers are written |
| `20_week.js` | a week's entries, who eats how much, a recipe's stored nutrition per serving |
| `30_stock.js` | stock on hand and expiry |
| `40_bookings.js` | how every booking writes, and one booking in a transaction of its own |
| `50_pantry.js` | the pantry's bookings |
| `60_requests.js` | recipes asked for a week |

- **Calling one:** `POST /structr/rest/<name>` with a JSON body of its arguments (read as
  `$.methodParameters`), or `$.<name>({...})` from a page or another method. The answer is under `result`.
- **Who it runs as:** whoever calls it. A member who is not an admin needs a `ResourceAccess` grant for
  the method's name (and one per type to read nodes by id); without one, every call is a 401.
- **Installing:** each run replaces each method whole, removes the ones whose file is gone, and never
  touches a function it did not install. It knows its own by their source's second line, which names
  the file. `tools/snapshot_state.py` leaves those out, as it leaves out the pages: they are code, not
  instance state. No restart is needed: a new or changed method answers at once.
- **Warming up:** every method answers a call whose arguments are `{"warmUp": true}` with nothing, and
  the installer makes that call after installing or changing one. Several calls to a brand-new method
  at once, before its first call has finished, answered some of them 404 ("Cannot resolve URL path").

| Method | Arguments | Answers |
|---|---|---|
| `stockOnHand` | none | every portion the caller may see that has been weighed: grams on hand now and days to expiry, as the pantry page and `inventory.py` work them out |
| `bookPantry` | `do` (buy, use, count, open, move, discard), `token`, and the booking's fields (food, amount, unit, storage, keeps, portion) | the booking, as the pages record one: `{action, problem, process, created, notes}` |

## Households, kept apart by Structr

A household is a `Household`, which is also a Structr `Group`, and its members are `Person`s, which
are also Structr `User`s (data-model K1, K2).

- **What a household's booking writes is private to it.** `bookPantry` books for the caller's one
  household (a caller in none, or in several, is refused). Every node it makes is visible to no one
  by its flags and is granted (read, write, delete) to the household's Group, so each member reads and
  changes it and no one else sees it. A portion of another household is "no such portion", because the
  caller cannot read it.
- **It never makes shared vocabulary.** A pantry operation's kind ("Purchase", "Use") must already
  exist. The pages, as the superuser, still make one on first use.
- **Shared data stays readable to every member and changeable by none.** A member's attempt to change
  a shared `DomainType` is a 403.
- **Bookings for one household take turns.** Each first writes `Household.bookingTurn` (`scripts/40a`),
  with a value never written before, as the superuser. Neo4j holds that write until the booking
  commits, so a second booking for the same household waits there, then finds what the first made.
  Households do not wait on each other.

  The pages' bookings still lock with a Cypher write until they too book as a household (stage 5).
  A Cypher write could not serve here: while one ran, other methods called at the same moment answered
  404.

## The gate: `tools/check_households.py`

For a development or throwaway instance. It sets up:
- two test households: A with members A1 and A2, B with member B1;
- each member signed in as themselves, with a generated password that is never shown;
- the grants they need.

Then it checks, removing everything at the end:
- A1 and B1 each buy, and A1 uses some of A's;
- one purchase sent four times at once makes one;
- A2 sees A's portion and B1 does not, through `stockOnHand`;
- B1 cannot use A's portion, and nothing is written;
- every node the bookings made is read by its household and is a 404 to the other;
- a member cannot change shared vocabulary;
- both households' grams and days to expiry are Python's.

**Results on the development instance (2026-10-26):**

| Check | Result |
|---|---|
| Purchases, as each member | A1 600 g, B1 450 g; A1 then used 150 g |
| B1 using A's portion | "no such portion", nothing written |
| One purchase sent four times at once | one made, one said so |
| What each household's member sees | its own portion, not the other's: 1.1 s and 0.7 s for `stockOnHand` |
| The 22 nodes the bookings made | each read by its household, a 404 to the other |
| A member changing shared vocabulary | 403, unchanged |
| Grams and days, method against Python | both portions 450 g, 5.00 days, both ways |

**Broken on purpose, each caught:**
- the household's nodes written visible to everyone: 47 failures, B1 could book on A's portion;
- no grant to the household: 17 failures, A2 could not see A1's purchase;
- no turn taken: four said they booked one purchase.

`tools/check_bookings.py` and `tools/check_pages.py` still found the pages the same as Python after
the pantry's bookings moved into `pages/common.js`, which both the pantry page and `bookPantry` run.

## What Structr did that was not expected

All recorded in `structr-cheatsheet.md` §3a:

- **A Cypher write breaks other calls.** A method whose transaction wrote through `$.cypher` made other
  methods called at the same moment answer 404. A Cypher read did not.
- **Cypher bypasses access control.** A member who is not an admin may run `$.cypher`, and what it reads
  is not filtered. A method must never read data through it.
- **An object keeps the rights it was loaded with.** Writing, inside `$.doPrivileged`, to a node the
  method had loaded as the member was refused (403). Loaded again inside the privileged block, it could
  be written.

## Not done yet

- The rest of the request-time engines (stage 3): net requirements and the shopping list, the nutrition
  report, menu changes, requests.
- The planner's JSON contract (stage 4).
- The real data marked shared or private, and the pages and tools acting as their household (stage 5).
  Until then, the existing data on any instance is visible to every signed-in user, as before.
- Permission propagation along relationships is not used. Grants are per node, made by the writer.

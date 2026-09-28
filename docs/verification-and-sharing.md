# Verification and sharing: a proposal

**Status: proposal for the owner's review, 2026-09-28. Nothing structural in it is built.** Part of it
reverses a decision CLAUDE.md records ("Person/Agent: single-user by design"), and CLAUDE.md says to
stop and ask before adding a structural type. Sections 6 and 7 are the decisions to make.

## 1. What was asked

The owner, 2026-09-28:

> I'd like to build some sort of verification system for recipes, nutrient profiles, etc. For
> example, when a user purchases all the ingredients for a recipe, their total cost can update some
> default value as suggested. When someone verifies that an ingredient density is right (or changes
> it), then it updates. Similarly, a user running inventory on their pantry would need some way to
> mark stock as verified at a particular date time. I want to move toward a multi-user platform with
> some shared data (some private).

The three examples share one shape. Someone observes something at a time: a price paid, a density
confirmed or corrected, a count of what is on the shelf. The observation is recorded with who and
when. Where it bears on a default (a Type-level figure), it may change that default, but as a
suggestion someone accepts, not by overwriting it.

## 2. Most of it is already in the model

| Example | The model already has | Missing |
|---|---|---|
| Stock take at a date and time | §4.1.1 and invariant 19: a **StockReconciliation** produces a new `observed` Measurement at the recount time; the unexplained difference is its value minus what §4.1.1 predicted for that moment. The pantry's `imputed` amounts (J26) are exactly what a count replaces | a tool to record one |
| Bought the ingredients, so the price updates | §5.5: a **Purchase** is a Process whose outputs are the food bought, whose temporal region is when, and which generates `PriceObservation`s | `PriceObservation` has no properties or relations yet; no rule for turning observations into a suggested price |
| A density is right, or is changed | §8, "learning from user confirmations": an observed fact is stored at a leaf Type, and a promoted default `wasGeneratedBy` a **default-verification Process** that `used` the observations as evidence. PROV-O `wasInvalidatedBy` is already in §7's relation list | the verification Process and its links; a way to ask "has anyone checked this since it changed?" |

`Process` is kind-reified (it takes `hasKind`), so a stock take, a purchase and a check are three
kinds of one structural type: data, not schema. What none of them can say today is **who**, because
the model has no agent. For one user that does not matter; for several it does.

## 3. The proposal

### 3.1 A verification is a Process by someone, and "verified" is a query

Every check is a `Process` of a kind ("Stock take", "Purchase", "Default check", "Recipe check"),
with:

- `occupies temporal region`: when it was done;
- `wasAssociatedWith` a Person (§3.3): who did it;
- `used`: what it checked (a DefaultSpecification, a NutrientProfile, a lot of stock, a Plan);
- an outcome, one of `confirmed`, `corrected` or `rejected`, and a note;
- what it generated: an `observed` Measurement (a count, a weighing), a `PriceObservation`, or, for
  a correction, the replacing value, while the replaced one `wasInvalidatedBy` it.

A "verified" tag is then **computed, not stored**: a figure is verified if a check `used` it with
the outcome `confirmed` after it last changed. A stored flag would go stale silently the moment a
food was remapped or a figure edited; this cannot. It is the same reasoning that keeps nutrient
totals and inventory computed.

### 3.2 Defaults change by accepted suggestion

An observation never overwrites a default by itself. It produces a **suggestion**, and accepting it
is itself a check (outcome `corrected`) that writes the new value with the observations as its
evidence (§8's default-verification Process):

- **Prices.** Each purchased item's `PriceObservation` (paid, for how much of which food, where,
  when) is compared with the price the owner's level resolves to. A proposed first rule: suggest the
  mean of the last three purchases within six months when it differs by more than 15%. Accepted, it
  becomes the owner's own price (`specified`, J27), and every recipe's cost follows, since cost is
  computed. **A receipt total for a whole recipe** does not say what each ingredient cost; it can only
  suggest scaling that recipe's prices together. Itemized purchases are the useful form.
- **Densities, weights per item, nutrient figures.** A weighing ("1 cup of this flour weighed 128 g")
  is an `observed` Measurement about an instance; several of them suggest a Type's default. "It is
  right" with no new number is a check with the outcome `confirmed`.
- **Stock.** A count replaces the lot's current amount from its time on (§4.1.1), with no default
  involved. Counting the same amount as predicted is a `confirmed` stock take.

### 3.3 Who: a Person

| Option | For | Against |
|---|---|---|
| **A: Structr's `User` is the agent** | nothing new in the model; the login and the actor are one thing | a login account is not a BFO entity; someone without an account (a child, a guest) cannot do anything; ties the model to Structr |
| **B: a `Person` type, linked to an account** (recommended) | BFO object and PROV Agent; a household member without a login can still have done a stock take; access control stays Structr's job | one new structural type. Safe: it has no instances, so hard rule 2 does not apply |

With B: `Person` (concrete, under `BfoObject`), `Process -[WAS_ASSOCIATED_WITH]-> Person`, and
`Person -[HAS_ACCOUNT]-> User` (optional).

### 3.4 Shared and private data

Structr already has users, groups, node ownership and grants. The model's data divides cleanly:

| Shared: curated, everyone reads | Private: one household |
|---|---|
| The vocabulary: food, method and equipment Types; nutrients, NutrientProfiles, densities, weights per item, shelf lives | Stock: portions and their Measurements; stock takes |
| Profiles: dietary, kitchen, pantry; the public price levels | What a household instantiated: targets, kitchen, pantry, its own price level |
| Published recipes | Its own recipes, meal plans and entries, cooks, baseline |
| Checks of shared figures | Purchases, price observations, checks of its own data |

The design choice that matters most is **how shared figures change**. A household's own level
already overrides a shared one for that household (the price levels work this way, and densities or
shelf lives could get the same layer). Changing the shared figure for everyone should take a
suggestion accepted by a curator. Otherwise one person's miscount changes everyone's nutrition
figures.

Mechanically, multi-user touches everything that reads or writes:

- **Visibility.** Every node today is `visibleToAuthenticatedUsers`, so any user would see all of it.
  Private nodes must become owner-only, with a grant to the household's Group. Hard rule 4 already
  makes every write set visibility, so the change is in one place per writer.
- **Who a tool acts as.** Every tool connects as the superuser, which sees everything. Per-user work
  means connecting as that user, so Structr's access control filters what the planner, the inventory
  engine and the reports read. Several places assume one kitchen today: the on-hand scan reads every
  portion, and the history reads every MealPlan. Under a user's own login they would be scoped for
  free; under the superuser they would mix households.
- **Migration.** The owner's instance holds shared and private data in one graph. Moving to this
  means marking which is which, which the table above makes mechanical.

## 4. What can be built now, without deciding any of this

- **A stock-take tool** (§4.1.1, invariant 19): a file of counts at a date and time, written as a
  StockReconciliation Process with an `observed` Measurement per lot. It reports each lot's
  unexplained difference, confirmed where the count matches. Single-user, no new type.
- **Purchases and price observations**: the `PriceObservation` properties the model implies (amount
  paid, currency, for what quantity, of which food) and a Purchase Process, with suggestions to the
  owner's price level. Schema, but no new structural type.

## 5. Build order, if accepted

1. Stock take (§4).
2. Purchases, price observations and price suggestions.
3. Checks of shared figures: the verification Process, `used`, outcomes, and "verified" as a query.
4. Person, accounts and households, visibility, tools acting as a user, migration. Largest, and
   last, because it touches every write.

## 6. Decisions for the owner

1. **Person** as a model type (recommended) or Structr's `User` directly.
2. **Who changes shared figures**: a curator accepts suggestions (recommended), anyone edits them, or
   households override and nothing shared changes.
3. **The suggestion rule** for prices (proposed: the mean of the last three purchases within six
   months, when it differs by more than 15%) and for densities.
4. **Itemized purchases** (recommended) or recipe totals.
5. **Households**: is a user one person, or does a household of several share private data?

## 7. What this reverses

CLAUDE.md, "Deliberately out of scope": "Person/Agent: single-user by design. There are no agents in
the model; equipment participates, it does not act." Accepting §3.3 replaces that line with the
decision and its date. The model's own reasoning for the exclusion was that nothing needed an agent;
verification by several people is the first thing that does.

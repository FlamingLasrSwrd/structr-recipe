# Verification and sharing: a proposal

**Status: proposal for the owner's review, 2026-09-28, with the owner's first answers in §6. Nothing structural in it is built.** Part of it
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
  when) is compared with the price the household's level resolves to. The rule (the owner's, 2026-09-28):
  suggest the mean of the last three purchases within six months when it differs by more than 15%.
  Accepted, it becomes the household's own price (`specified`, J27), and every recipe's cost follows, since cost is
  computed. **Purchases are itemized** (the owner's decision): a receipt total for a whole recipe would
  not say what each ingredient cost, only suggest scaling that recipe's prices together.
- **Densities, weights per item, nutrient figures.** A weighing ("1 cup of this flour weighed 128 g")
  is an `observed` Measurement about an instance; several of them suggest a Type's default. "It is
  right" with no new number is a check with the outcome `confirmed`.
- **Stock.** A count replaces the lot's current amount from its time on (§4.1.1), with no default
  involved. Counting the same amount as predicted is a `confirmed` stock take.

### 3.3 Who: a Person that is also a Structr account

Structr has no `Person` type. Its account types are `User` (a login) and `Group` (members), both
principals: what owns nodes and holds grants. Probed on a throwaway instance (2026-09-28,
structr-cheatsheet.md "Users, groups and grants"), a type of ours can inherit Structr's `User`
trait next to our own traits. The instance is then **both** at once: listed as a `User`, it logs
in, owns what it creates and can be a Group member; listed under our abstract trait, it satisfies
a relationship aimed at that trait, read back in both directions.

| Option | For | Against |
|---|---|---|
| **A: `Person` inherits `BfoObject` and `User`** (recommended) | one node per human, who is the agent in the model and the principal Structr checks, so its login, ownership and grants apply with nothing to keep in step; in a Structr script, `me` is the Person | Structr's account properties (password, e-mail, admin flag) sit on a model type. A household member who never signs in is a Person with no password, which cannot log in |
| B: a `Person` of ours, linked to a `User` (`targetType: "User"`, which works) | the model type stays free of account fields | two nodes to keep in step; ownership and grants land on the `User`, so every "who did this" goes through the link |

Hard rule 2 does not stand in the way: `Person` is a new type with no instances, and it is the
new type that takes the traits. It is the first structural type added since the build (51 → 52),
which hard rule 3 reserves for the owner to approve. Relations: `Process -[WAS_ASSOCIATED_WITH]->
Person` (PROV), for who carried out a check, a stock take or a purchase.

What it costs: a non-admin user needs a `ResourceAccess` grant, itself visible to them, for every
REST path they use (probed: without one, every request is a 401). With pages or tools acting as
a user, that is one grant per type and per type-with-id, written by a setup script like the rest
of the schema.

### 3.4 Shared and private data

Structr already has users, groups, node ownership and grants. The model's data divides cleanly:

| Shared: curated, everyone reads | Private: one household |
|---|---|
| The vocabulary: food, method and equipment Types; nutrients, NutrientProfiles, densities, weights per item, shelf lives | Stock: portions and their Measurements; stock takes |
| Profiles: dietary, kitchen, pantry; the public price levels | What a household instantiated: kitchen, pantry, its own price level; each person's targets (§3.5) |
| Published recipes | Its own recipes, meal plans and entries, cooks; each person's baseline (§3.5) |
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

### 3.5 Households: separate profiles, shared meals

The owner's case: "Users can have different profiles but be in the same household and share meals."
Each person is fed from one kitchen, with one set of stock, at one table, but has their own needs.

**A household is a BFO object aggregate of persons**, like the kitchen's `UtensilSet` of tools:
`Household` under `ObjectAggregate`, whose members are Persons (`has member part`). For
permissions it has a Structr `Group` whose members are the same Persons, and private data is
granted to that group. Whether `Household` can inherit Structr's `Group` trait, as `Person` inherits
`User`, is not probed yet; if it can, the aggregate and the group are one node, as for people.

What belongs to whom:

| A person's own | The household's, shared by its members |
|---|---|
| Dietary profile and `NutritionTarget`s (`forPerson`) | Kitchen (`UtensilSet`), pantry and stock |
| Baseline (their supplements, their coffee) | Purchases, price observations, the household's price level |
| Exclusions (an allergy, a dislike) | Meal plans and their entries: the week |
| Portion levels (how much they tend to eat) | The household's own recipes; stock takes |

**Shared meals: a share per eater.** Today a `MealPlanEntry` (a cook, or eating its leftovers) says
how many servings are eaten, by the one person there is. With several eaters, each entry has one
**meal share** per person at the table: the person, and the servings they eat
(`MealPlanEntry -[HAS_SHARE]-> MealShare -[EATEN_BY]-> Person`, the servings a QuantitySpecification).
The cook makes the sum of its shares, plus planned leftovers. Each person's nutrition, day by day,
is their own shares and their own baseline, against their own targets. A person who eats out has
no share in that meal. This is **not** the deferred `MealServing` of §17 (one serving made
differently, tofu for a vegetarian guest): everyone eats the same dish, in different amounts.
That stays deferred.

**What it asks of the planner** (a change to its problem, so the owner's to approve, like any change
to its objective): the recipe in a slot is chosen once for the household, and the portion once
per eater, from that person's portion levels. Every eater's hard targets must hold. The nutrition
term sums over people, and variety and time stay per slot. A slot can also be one person's: a
breakfast eaten alone. The week file would say who eats each meal. The search grows with eaters
times portion levels; CP-SAT's one-hot portion variable becomes one per slot and eater.

**Migration:** the owner becomes the one Person of a one-person household. Each existing target
becomes theirs (`forPerson`), and each existing entry gets one share.

### 3.6 Curation now, consensus later

The owner: "There needs to be some sort of curation ability. If there are enough users in the
future, perhaps we can move to a group consensus model."

**Now, curators.** Shared data (the vocabulary, profiles, public prices, published recipes) is
readable by every signed-in user and writable only by a `Curators` Group, which Structr's grants
enforce. Anyone else changes a shared figure only by suggesting a new one:

- a **suggestion** is a check (§3.1) by a Person, which `used` the shared figure, generated the
  proposed value, and has the outcome `proposed`;
- others may **second or dispute** it, each with a check of their own that `used` the suggestion;
- a **curator's decision** is a check with the outcome `accepted` or `rejected`. An accepted value
  becomes the shared figure, and the old one `wasInvalidatedBy` that check.

**Later, consensus, without changing the records.** Whether a suggestion is accepted is a rule over
those checks, not a flag someone sets. With curators, the rule is that a curator accepted it and
none rejected it. A consensus rule would read the same records: for example, accepted once people
from at least three households have seconded it, and no curator has rejected it. Counting
households rather than people keeps one household from outvoting the rest. Moving from one to the
other is a change of rule, not a migration. Weighting people by how often their accepted checks
held up would be a later refinement of the same rule.

**Meanwhile, households are not held up.** A household's own level overrides the shared one for
that household alone: its own prices today, and its own densities or nutrient figures by the same
mechanism. So a household uses its correction at once, while the shared figure waits for review.

## 4. What can be built now, without deciding any of this

- **A stock-take tool** (§4.1.1, invariant 19): a file of counts at a date and time, written as a
  StockReconciliation Process with an `observed` Measurement per lot. It reports each lot's
  unexplained difference, confirmed where the count matches. Single-user, no new type.
- **Purchases and price observations** (decisions 3 and 4, 2026-09-28): a receipt entered line by
  line, each line a `PriceObservation` (the food, how much, the price paid, the store as free
  text) generated by one Purchase Process dated when it happened. A food's price is suggested
  from the mean of its last three purchases within six months, when that differs from the
  household's current price by more than 15%; accepting it writes the household's own price
  (J27). Schema, but no new structural type.

## 5. Build order, if accepted

1. Stock take (§4).
2. Purchases, price observations and price suggestions.
3. Checks of shared figures: the verification Process, `used`, outcomes, and "verified" as a query.
4. Person (§3.3), households and meal shares (§3.5), curators (§3.6), visibility, tools and pages
   acting as a user, migration. Largest, and last, because it touches every write. The planner's
   per-eater portions come with it.

## 6. Decisions

Decided by the owner, 2026-09-28:

- **The price suggestion rule**: the mean of the last three purchases within six months, when it
  differs from the current price by more than 15%.
- **Purchases are itemized**, a line per food.
- **Curation is needed**, with a move to group consensus if there are enough users later (§3.6).
- **Households**: people with their own profiles share a household and its meals (§3.5).

Still for the owner:

1. **Person** as one node that is also the Structr account (§3.3, option A, recommended; verified
   to work), or linked to one (option B).
2. **Accept §3.5 as the household model**: a person's own targets, baseline, exclusions and
   portions; the household's kitchen, stock, prices and meals; a meal share per eater. And the
   planner change it brings.
3. **The first consensus rule**, when it is time: the proposal is seconds from three households
   and no curator rejection.

## 7. What this reverses

CLAUDE.md, "Deliberately out of scope": "Person/Agent: single-user by design. There are no agents in
the model; equipment participates, it does not act." Accepting §3.3 replaces that line with the
decision and its date. The model's own reasoning for the exclusion was that nothing needed an agent;
verification by several people is the first thing that does.

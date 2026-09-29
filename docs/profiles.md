# Profiles: a default you pick, then change

A **profile** is a named bundle of defaults for a kind of situation: the daily intakes
recommended for a moderately active man of 31-50, the tools a kitchen that is cooked in most
days usually has, or the staples a pantry usually holds. The owner picks one, it is **instantiated** into their own data, and from
then on that data is theirs to change. The profile is never edited to suit one person.

Built for three things (data-model.md §18 J22, J26): dietary targets, kitchen equipment and
stock on hand.

## How it sits in the model

Nothing new was needed structurally, which is the point of building it this way.

- A profile is a **Type** (`DomainType`) in its own hierarchy: `Dietary Reference Profile`,
  `Kitchen Profile` or `Pantry Profile`. A narrower profile is a child Type: `Adult male 31-50 moderately active`
  under `Adult male 31-50` under `Adult male` under `Adult`.
- Each entry is a **`DefaultSpecification`** on that Type (§8, the InstantiationPattern), of a
  kind (`Recommended Daily Intake`, `Kitchen Equipment`, `Pantry Stock`) and **keyed by** what it
  is about: a nutrient, optionally with an intake basis, an equipment Type or a food Type. Its
  value is a `QuantitySpecification`: a range for an intake, a count for a tool, an amount of a
  food. It carries `provenance`
  and `source` like every other default (J21).
- **Resolution** walks up the hierarchy (`mealplanner/defaults.py resolve_all`): for each key the
  nearest Type's default wins. A child inherits everything its parents say and overrides only
  what it restates. `resolve_default` already did this for one key; `resolve_all` returns every
  key at once, and it is the only new mechanism.
- **Instantiating** turns the resolved defaults into ordinary data the rest of the system
  already reads: `NutritionTarget`s with their ranges (status `default`, or `specified` where
  the owner overrode one), a `UtensilSet` whose members (BFO `has member part`) are
  `EquipmentObject`s, and stock on hand: per food a `PortionOfSubstance` bearing a Mass
  `Quality`, with an `imputed` `Measurement` of the amount. That is §4.1's distinction between
  a Type-level directive and what applying it produces. A target or tool records the profile it
  came from in `source`; an imputed amount `wasDerivedFrom` the `QuantitySpecification` it
  resolved, the relation §4.1 and invariant 2b name for exactly this.

## The owner's selection

The owner's choice lives in a small file in `private/`, which git ignores, and is applied with
`tools/instantiate_profile.py`. Running it again changes nothing unless the file or the profile
changed.

```toml
# private/nutrition.toml
profile = "Adult male 31-50 moderately active"
timezone = "America/Denver"  # a day ends at local midnight (default UTC)
strictness = "soft"          # every target, unless named in hard
weight = 0.1                 # every soft target
hard = []                    # nutrient names that must be met
leave_out = []               # nutrients not to target at all
[overrides]                  # the owner's own range for a nutrient
# "Sodium - Na" = { max = 2000, unit = "mg" }
```

```toml
# private/kitchen.toml
name = "Home kitchen"
profile = "Everyday home kitchen"
add = ["Wok", { item = "Chef's knife", count = 2 }]
remove = ["Microwave"]
```

```toml
# private/pantry.toml
name = "Home pantry"
profile = "Basic pantry"
add = [{ item = "Sesame oil", amount = 5, unit = "fl_oz" },   # a food the profile lacks,
       { item = "Jasmine rice (dry)", amount = 2, unit = "lb" }]  # or a profile item's own amount
remove = ["Honey"]
```

```bash
python3 tools/instantiate_profile.py nutrition --show "Adult male 31-50 moderately active"
python3 tools/instantiate_profile.py kitchen --list --profile "Everyday home kitchen"
python3 tools/instantiate_profile.py pantry --show "Basic pantry"
python3 tools/instantiate_profile.py pantry --list --profile "Basic pantry"
python3 tools/instantiate_profile.py nutrition private/nutrition.toml
python3 tools/instantiate_profile.py kitchen private/kitchen.toml
python3 tools/instantiate_profile.py pantry private/pantry.toml
```

`--list` prints every equipment Type (for a kitchen) or food (for a pantry) in the vocabulary,
grouped, with the chosen profile's items marked. It is the list to choose from, so nothing has to
be named from memory.

Rules for re-running:

- A target whose range, or an assumed amount that, differs from the profile is **kept**, since
  the owner may have changed it in Structr. It is reported, and `--reset` replaces it with the
  profile's value. A range or amount that came from an override the file no longer has goes back
  to the profile (an amount is then dated again, as a new assumption).
- Something the selection no longer includes is **deleted**, unless it has history. A tool a cook
  used (it has Allocations or took part in a Process), stock a cook used or that was weighed, or a
  target a `MealPlan` uses stays, and is reported. History is never removed to make the data match
  a file.

## People in a household

Since 2026-09-28 a household may hold several people, each with their own dietary profile
(data-model.md §19). `private/household.toml` names the household, its people, each person's
dietary selection file (the `private/nutrition.toml` form above) and their daily baseline:

```toml
name = "Home"
[[person]]
name = "Elijah"                          # also a Structr login name; no password is set by the tool
nutrition = "private/nutrition.toml"
baseline = ["Daily supplements"]
adopts = true                            # the targets set up before there were people are this person's
[[person]]
name = "Cass"
nutrition = "private/nutrition-cass.toml"
```

```bash
python3 tools/instantiate_household.py private/household.toml
```

Each person's targets are named "Daily Protein target (Cass)" and linked to them. With `adopts`,
the targets instantiated before there were people ("Daily Protein target") become that person's,
renamed in place, so a MealPlan that uses them is undisturbed. A person no longer listed leaves
the household but is not deleted. The kitchen, pantry and prices stay the household's.

## The dietary profiles (`data/profiles/dietary.toml`)

29 profiles from the *Dietary Guidelines for Americans 2020-2025*: Appendix 1 Table A1-2 (the
National Academies' Dietary Reference Intakes) and Appendix 2 Table A2-2 (estimated calorie
needs).

- `Adult`: sodium at most 2,300 mg; protein 10-35%, carbohydrate 45-65% and fat 20-35% of
  energy; carbohydrate at least 130 g; fiber 14 g per 1,000 kcal; added sugars and saturated
  fat each under 10% of energy.
- `Adult female` / `Adult male`, each with age groups 19-30, 31-50 and 51+: the RDA or AI for
  protein, the two essential fatty acids, and 18 vitamins and minerals.
- Each age group has a `sedentary`, `moderately active` and `active` child with the calorie range
  of Table A2-2 over that age band (`calculated`: the table gives one figure per age year).
- `Adult female 31-50 weight loss` (1,200-1,500 kcal) and `Adult male 31-50 weight loss`
  (1,500-1,800 kcal) from the 2013 AHA/ACC/TOS obesity guideline.

A share of energy or an amount per 1,000 kcal is turned into grams from the middle of the
profile's energy range, at 4 kcal/g for protein, carbohydrate and sugars and 9 for fats. That
figure is `calculated`. Where a nutrient has two goals (the protein RDA of 56 g and 10% of
2,500 kcal = 62.5 g), the target takes the greatest floor and the smallest ceiling, and a
profile whose goals cannot both be met is refused.

**Not included:** Table A1-2 has no copper, manganese or selenium rows, and the Tolerable Upper
Intake Levels are not listed. Both exist in the National Academies' DRI tables and can be added
as intakes with their source. These are population guidelines, not personal advice.

## The kitchen profiles (`data/profiles/kitchen.toml`)

Four tiers, each the one before plus more (16, 29, 44 and 54 kinds of tool): `Minimal kitchen` (someone
who rarely cooks: one nonstick skillet, a saucepan, a chef's knife, the oven and microwave),
`Everyday home kitchen` (a Dutch oven, cast iron, a thermometer, the usual hand tools),
`Enthusiast kitchen` (a wok, a food processor, a scale, a mandoline) and `Prosumer kitchen`
(stand mixer, pressure cooker, sous vide, vacuum sealer, pasta machine). Drawn from America's
Test Kitchen's lists for beginners and for a new home, and marked `estimated`: a tier is a
judgment about typical kitchens, not a measurement.

## The pantry profiles (`data/profiles/pantry.toml`)

Five profiles: three tiers, each the one before plus more, and two kinds of cooking beside the
middle one. `Bare pantry` (4 items: salt, pepper, two oils) for someone who rarely cooks;
`Basic pantry` (18) adds what a meal kit leaves to the cook (butter, sugar, flour, eggs), garlic,
onions, soy sauce, honey, rice and a few spices; `Well-stocked pantry` (43) adds canned goods,
pasta, condiments, vinegars, milk, parmesan and more spices. `East and Southeast Asian pantry`
(27) and `Baker's pantry` (29) each extend the basic one. The items came from what 33 HelloFresh
recipes ask the cook to supply and use most; six foods (baking powder and soda, yeast, cornstarch,
vanilla, sesame oil) were added to the vocabulary for them. Every amount is half of a common US
retail package, since stock is anywhere between full and empty, or a whole can or carton when it
is kept unopened. All `estimated`.

What the instantiated stock does today, and what it does not:

- It is **counted like any stock** (§4.1.1): the inventory engine reads it in grams, cooking
  recorded after it was written uses it up, and a weighing replaces it. The planner reads it as
  lots, but its stock and waste terms weigh 0 by default (optimizer-design §4.5), so the week
  it proposes does not change. The acquisition list's arithmetic (`reservation.net_requirements`)
  subtracts it; nothing prints a shopping list yet.
- It **never expires**: the lots carry no Perishability type, which is the assumption a pantry
  profile makes (a staple is restocked as it is used). Eggs and milk are the weak case.
- It writes **no `StockPolicy`**. "Keep at least this much" is a rule for a shopping list, the
  next piece; the same profile entries could give each policy its target level.

## Other places the same mechanism fits

Anywhere a set of sensible defaults depends on a kind of situation the owner can name, and
the result is ordinary data they then change. Each of these below would be data only, a profile
hierarchy plus instantiation into a type that already exists, unless marked otherwise.

| Use | Profiles | Keyed by | Instantiates into | Notes |
|---|---|---|---|---|
| **Standing stock** | the pantry profiles above | Food Type | `StockPolicy` per staple (keep at least this much) | **Built as stock on hand** (J26); the policy half waits for a shopping list, which is what would read it |
| **Dietary patterns** | "Vegetarian", "Pescatarian", "No pork", "Gluten-free" | Food Type (an excluded root) | `ExclusionConstraint`s, hard or soft (J10) | Exclusions already exist; a profile saves naming each excluded root. "Gluten-free" needs Food Types grouped by gluten, which the vocabulary does not have yet |
| **Shelf life** | "USDA FoodKeeper" | Perishability Class × storage condition × opened | the shelf-life defaults the expiry logic reads | Shelf life is already a default keyed by storage condition and opened status (§3), resolved this way. What a profile adds is only a choice between published sets, and FoodKeeper is the obvious first one to load, with its source |
| **Retention factors** | "USDA Table of Nutrient Retention Factors, Release 6" | Nutrient × transformation method | `RetentionFactor` defaults | Replaces the single "keep 100% of macronutrients" decision on `Food` with published figures. Not something the owner picks per person; the same resolution, used as a sourced data set |
| **Package sizes** | "US supermarket", "Warehouse club" | Food Type | a purchase quantity for the acquisition list | Needs somewhere to put a pack size, which the model does not have: a property on an existing type (through `ExtensionPropertyDefinition`), not a new class |
| **Week shape** | "Busy weeknights", "Batch cook on Sunday", "Three meals at home" | meal type × day | the slot template and `MealPlan.timeBudgetMinutes` | **Owner decision.** The optimizer design keeps slots as a call-time template on purpose (D1). A profile would store the template's defaults, not the slots, which keeps D1, but it is a design choice to make, not a default to add |
| **Planner priorities** | "Nutrition first", "Use what's expiring", "Fast" | objective term | the optimizer's weights | **Owner decision.** The objective's weights are an unreviewed proposal (optimizer-design §4.5). Presets would make retuning explicit instead of silent, but what each preset means has to come from the owner |
| **Skill** | "Beginner", "Confident", "Ambitious" | transformation method, difficulty | a difficulty limit and soft exclusions of methods (deep frying, tempering) | Difficulty is already a planning input; methods are Types, so a soft exclusion of a method would need J10 to count a Step's method, which it does not today |
| **Equipment feasibility** | (uses the kitchen already instantiated) | | a check, not new data | With the owner's kitchen a `UtensilSet`, a recipe whose instrument Specification names a tool the kitchen lacks can be flagged or excluded; a need for `Skillet` is met by any skillet, since each is a subtype. Not built. Of the 20 recipes loaded (2026-09-27), the Minimal tier can cook 6, the Everyday tier 13 (it lacks a wok, fine-mesh sieve, meat pounder and Microplane) and the Enthusiast tier all 20 |

The pattern does not fit where the right value is a measurement of this household (what is in
the fridge now, what a portion weighed). Those are observations, and a profile must never stand
in for them silently. §4.1's `imputed` status exists to keep the two apart, and it is why the
pantry's amounts are `imputed`: an assumption that says it is one, replaced by the first
weighing.

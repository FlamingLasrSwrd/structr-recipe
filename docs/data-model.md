# Meal Planning Tool — Data Model (Rev. 4)

Implementation-agnostic. **BFO is the controlling scheme**: where BFO (or its standard companions IAO, CCO, RO) already provides a class or relation, this model uses it. Bespoke terms exist only where nothing suitable does, and each is marked. Also draws on PROV-O, P-Plan, SKOS, OWL-Time, QUDT/UCUM, and published USDA/EuroFIR food-composition method.

Rev. 4 is a correction pass following a BFO conformance review. Seven relation errors are fixed, two classes split, and one long-standing conflation — SKOS Concepts silently doing the work of BFO universals — is resolved. §14 lists every change.

---

## 1. The Type / Concept split

This is the structural change from which most of the rest follows.

BFO distinguishes **universals** (types, which particulars instantiate) from **particulars** (instances). A SKOS Concept is neither: it is an Information Content Entity — a *name for* something. Through Rev. 3 this model used SKOS Concepts to do both jobs at once: "AP Flour" was simultaneously a vocabulary term and the kind of stuff a portion instantiates. It worked because nothing traversed the seam, but it was load-bearing and undeclared.

Under BFO-controlling, they separate:

| | **Type** (universal) | **Concept** (Designative ICE) |
|---|---|---|
| What it is | a kind of thing that particulars instantiate | a term that *denotes* a Type |
| Example | the universal `AP Flour` | the vocabulary entry "AP Flour", label "all-purpose flour" |
| Relation to instances | `#F1 instance_of AP Flour` | none — Concepts never classify particulars |
| Hierarchy | **subsumption** (`AP Flour` ⊑ `Wheat Flour` ⊑ `Flour`) | SKOS `broader`, for thesaurus browsing only |
| Carries | subsumption, InstantiationPattern defaults | labels, Identifiers, external mappings |

**Consequences, all simplifications:**

- **Default lookups walk subsumption, not `skos:broader`.** This removes the awkwardness noted since the beginning — `skos:broader` is not formally transitive and was being walked as an application-level traversal anyway. Subsumption *is* transitive, natively, and is exactly the semantics the lookup always needed.
- **`skos:related` retires.** It existed so a food wouldn't have to be independently classified in every facet. With Types, an instance simply instantiates types from several hierarchies at once (`AP Flour` ⊑ `Wheat Flour` and `AP Flour` ⊑ `Dry Goods`), so the shelf-life lookup starts from the same instance and walks a different superclass chain. No cross-link needed.
- **The single-parent constraint survives, scoped per hierarchy**: within any one subsumption hierarchy used for default lookup, a Type has at most one direct parent, so "nearest wins" stays unambiguous. Multiple *inheritance across* hierarchies is expected and fine.
- **Lookup-bearing facets become Type hierarchies; browsing-only facets stay SKOS.** Cuisine and Meal Type never drove a lookup and need only thesaurus semantics, so they remain Concept schemes. The distinction that was drawn on instinct turns out to track a real semantic difference.

Domain Types slot into the BFO tree directly: Food-Identity types under `PortionOfSubstance`/`DiscreteWholeItem`, Transformation-Method types under `Process`, Equipment types under `EquipmentObject`, Nutrient types under `Quality`, and **Culinary Role types under BFO `Role`** — which they always literally were.

---

## 2. Class Hierarchy

```
Entity
│
├── Continuant
│   ├── Independent Continuant
│   │   ├── Material Entity
│   │   │   ├── Object
│   │   │   │   ├── FoodObject
│   │   │   │   │   ├── DiscreteWholeItem      ⊐ Food-Identity types (countable)
│   │   │   │   │   └── PortionOfSubstance     ⊐ Food-Identity types (bulk)
│   │   │   │   ├── ContainerObject            ⊐ Container-Type types
│   │   │   │   │                              a jar, carton, tub. Contents are
│   │   │   │   │                              `located in` it, NOT part of it
│   │   │   │   └── EquipmentObject            ⊐ Equipment-Type types
│   │   │   ├── Object Aggregate
│   │   │   │   ├── FoodAggregate               `has member part` → any FoodObjects,
│   │   │   │   │                               alike or not (a dozen eggs; a plated
│   │   │   │   │                               meal). Members stay self-connected;
│   │   │   │   │                               causally-unified wholes use has part
│   │   │   │   └── UtensilSet
│   │   │   └── Fiat Object Part                [deferred — empty]
│   │   └── Immaterial Entity                    [out of scope — empty]
│   │
│   ├── Specifically Dependent Continuant
│   │   ├── Quality                              mass, volume, density, cleanliness,
│   │   │   │                                    opened_status
│   │   │   └── NutrientContent                  ⊐ Nutrient types; the actual magnitude
│   │   │                                        of a nutrient in THIS bearer
│   │   └── Realizable Entity
│   │       ├── Role                             ⊐ Culinary-Role types; also
│   │       │                                    reservation roles
│   │       └── Disposition                      shelf-life / spoilage propensity
│   │           └── Function                     ⊐ capability types (cutting, heating)
│   │
│   └── Generically Dependent Continuant
│       └── Information Content Entity
│           ├── Directive ICE                    prescribes
│           │   ├── RecipeIdentity
│           │   ├── Plan                         one immutable version
│           │   ├── Step
│           │   ├── Specification                what a Step calls for
│           │   ├── QuantitySpecification        a prescribed magnitude — NOT a
│           │   │                                Measurement (§4)
│           │   ├── StateRequirement
│           │   ├── SubstitutionRule
│           │   ├── InstantiationPattern           holds DefaultSpecifications for
│           │   │                                  one Type
│           │   ├── DefaultSpecification           ONE default value: hasKind +
│           │   │                                  optional keys + a
│           │   │                                  QuantitySpecification (§8)
│           │   ├── MealPlan
│           │   ├── MealPlanEntry
│           │   ├── PlanningConstraint             abstract — something a MealPlan
│           │   │   │                              must satisfy, checked by rollup
│           │   │   ├── StockPolicy
│           │   │   └── NutritionTarget
│           │   ├── ExtensionPropertyDefinition
│           │   └── AcquisitionList
│           ├── Designative ICE                  denotes
│           │   ├── Concept                      denotes a Type; carries labels,
│           │   │                                external mappings
│           │   └── Identifier                   denotes ANY Entity
│           └── Descriptive ICE                  describes what is
│               ├── Measurement                  `is about` an actual Quality, at a
│               │                                stated time (§4.1.1)
│               ├── NutrientProfile              type-level reference amount per
│               │                                basis — NOT a Quality (§4)
│               ├── Allocation
│               ├── PriceObservation
│               └── ExtensionPropertyValue
│
└── Occurrent
    ├── Process                                  ⊐ Transformation-Method types;
    │                                            also Purchase, Opening, Portioning,
    │                                            Cleaning, Disposal, Reconciliation,
    │                                            DefaultVerification
    ├── Process Boundary                          [placeholder — empty]
    └── Temporal Region
```

---

## 3. Type hierarchies and Concept schemes

**Type hierarchies** (subsumption; single direct parent within each; drive lookups):

| Hierarchy | Subsumed under | Drives |
|---|---|---|
| Food Identity — incl. cooked forms and branded/packaged forms | FoodObject | density, mass-per-unit, purchase-quantity, edible-fraction, nutrient-profile defaults |
| Transformation Method — heat (braise, roast) and mechanical (juice, grate) branches | Process | Step duration, output-type mapping, yield factor, retention factors |
| Perishability Class — raw branches (Fresh Meat, Produce, Dairy, Dry Goods) plus a **Prepared Dish** branch for cooked outputs | FoodObject | shelf-life, keyed by (Storage Condition, opened_status) |
| Storage Condition | Quality | second shelf-life key |
| Container Type | ContainerObject | resealability → post-open shelf life |
| Culinary Role | **BFO Role** | the hierarchy substitution similarity is **scored over** (candidates themselves are Food-Identity types, §5.3); may also be named directly by a Specification |
| Biological Origin | FoodObject | allergen/dietary filtering |
| Equipment Type / Material | EquipmentObject | cleaning-time default |
| Capability | **BFO Function** | what a tool can do; matched by Specification |
| Nutrient | **BFO Quality** | nutrient-profile and retention keys |

**Concept schemes** (SKOS; browsing only): Cuisine, Meal Type, Identifier Scheme, Unit.

Units stay a Concept scheme rather than a Type hierarchy: a unit is a designation, not a kind of thing, and QUDT/UCUM grounding is exactly what SKOS mapping is for.

**The Equipment Capability hierarchy replaces the Equipment Function *facet* introduced in Rev. 3** — that facet duplicated, as a Concept, a fact the BFO Function already asserted. Capabilities are now Function types, asserted once.

---

## 4. Two splits forced by BFO conformance

### 4.1 Measurement vs. QuantitySpecification

IAO's `is about` requires something to be about. A Measurement reading "500 g required" is about no existing Quality — nothing has that mass yet, which is the point of a requirement. Rev. 3's invariant ("every Measurement `is about` exactly one Quality") was therefore false for every prescribed value in the model.

They are different kinds of ICE and now say so:

| | **Measurement** (Descriptive ICE) | **QuantitySpecification** (Directive ICE) |
|---|---|---|
| Claim | this Quality had this magnitude at this time | this magnitude ought to hold |
| `is about` | exactly one Quality or Disposition | nothing existing |
| `hasTime` | required — an Instant or Interval | none |
| Statuses | `observed`, `imputed`, `derived`, `estimated` | `specified`, `default` |
| Used by | Allocation quantities, instance Qualities, PriceObservation | Specification requirements, NutritionTarget ranges, StockPolicy thresholds, **all InstantiationPattern defaults** |

A class-level default is a directive — "when instantiating flour, use this density." **Applying** one produces an `imputed` Measurement that *is about* the resulting instance's own Quality, `wasDerivedFrom` the QuantitySpecification it resolved. Without this status there is no object in the model that is about an unmeasured instance's mass, and a resolved default would be indistinguishable from a human guess (`estimated`). Imputed Measurements are always recomputable from the Type default, so storing them is optional — but the model must be able to name what the application is computing.

Both may hold a single value, a closed range, an open-bounded range (min-only or max-only), or `unconvertible`, and both reference a unit.

### 4.1.1 Magnitude over time — how a Quality's value changes

BFO continuants persist through time *and change*; a Quality instance survives while its magnitude does not. Nothing in the model previously said how. Mutation is not available (a Measurement is an immutable ICE), and `wasRevisionOf` is the wrong relation — the earlier value was not mistaken, it was correct when made.

The resolution is that **Measurements are time-indexed** (`hasTime`, OWL-Time), and a Quality's current magnitude is *computed*, never stored:

> **current magnitude** = the latest `observed` or `imputed` Measurement about that Quality, minus the summed quantities of every input Allocation about its bearer whose Process occurred after that Measurement's time.

Nothing is mutated and no decrement relation is needed. Grating 30 g off a 227 g wedge produces an input Allocation; the wedge's mass at any later moment follows arithmetically. Where a value is materialized for convenience, it is a `derived` Measurement `wasDerivedFrom` both the prior Measurement and the Allocation — a full audit trail.

This also sharpens two things that were previously blurred:

- **Stock reconciliation is not a revision.** A physical recount is simply a new `observed` Measurement at a later time. The discrepancy is between it and the value predicted for that moment; the earlier Measurement was never wrong. `wasRevisionOf` accordingly retires from Measurement.
- **Genuine data-entry error survives as the one revision case**: typing 227 when 277 was meant produces a Measurement that *was* wrong, and `wasRevisionOf` says so. Value-changed-over-time and value-recorded-wrongly are different facts and are now different structures.

### 4.2 NutrientContent vs. NutrientProfile

"Protein per 100 g" is not the magnitude of anything inhering in a particular portion — it is reference data about a *type*. "This 383 g portion holds 84 g of protein" is a genuine Quality of a particular.

- **NutrientProfile** (Descriptive ICE, type-level): `is about` a Food-Identity Type; `for_nutrient` → a Nutrient type; amount per stated basis (per 100 g, per unit). Reached via InstantiationPattern.
- **NutrientContent** (Quality, instance-level): a subclass of Quality, `inheres in` a FoodObject, `for_nutrient` → a Nutrient type, described by a Measurement of actual magnitude.

---

## 5. Core Entities

### Specification and Allocation

**`Specification`** (Directive ICE) — what a Step calls for. `has_participation_role` ∈ {input, output, instrument}.

| Attribute | Notes |
|---|---|
| `specifies` → **Entity** | for input/output: a Food-Identity Type ("butter") **or a Culinary Role type ("any baking fat")**; for instrument: an Equipment Type, a **Function**, or a **Quality**. The range is unrestricted because the question — "what must be true of whatever fills this slot?" — genuinely admits all of these |
| `has_participation_role` | input \| output \| **instrument** (renamed from `agent`, §14) |
| `has_specified_quantity` → QuantitySpecification | absent for instrument role |
| `is_optional` | |
| `has_state_requirement` → StateRequirement | zero or more |
| `has_substitution_rule` → SubstitutionRule | input role only |

### 5.3 Substitution — what candidates are drawn from vs. what similarity is scored over

Rev. 4 confined both `substitutableFor` and `candidate_type` to the Culinary Role hierarchy. That was simply wrong, and the contradiction is visible directly against `specifies`: a Specification names **Butter**, a Food-Identity Type, so whatever substitutes for it must be able to fill that slot — **Margarine**, also a Food-Identity Type. Culinary Role is not where candidates come from. It is the hierarchy over which their *similarity is measured*, and conflating the two made the rule unusable.

The two are now separated:

- **`candidate_type` ranges over the same hierarchy as `specifies`** — Food-Identity Types for a food slot. A substitute must be the kind of thing that can occupy the slot.
- **Similarity is computed over Culinary Role**, because that is the hierarchy that groups by function rather than composition. Butter and margarine sit far apart in Food Identity (dairy vs. plant fat, meeting only near the root) and close together in Culinary Role (both baking fats) — which is the whole reason Culinary Role was split out as a separate hierarchy in the first place.

A Food-Identity Type is linked to the roles its instances can play by **`may_bear_role`** → Culinary Role type. This is a type-level claim about *possibility* ("butter can act as a baking fat"), not an assertion that every portion of butter currently bears that Role — butter sitting in the fridge plays no role at all. OWL expresses possibility-at-the-type-level awkwardly; this is a documented bespoke relation rather than a class axiom for that reason.

**`substitutableFor` retires.** It was described as a graded, Wu-Palmer-style score — but a Wu-Palmer score is *computed from hierarchy structure*, not authored. Storing it stored something derivable, against the compute-don't-store discipline applied everywhere else. Similarity between two Food-Identity Types is now computed at query time by walking `may_bear_role` into Culinary Role and measuring there.

The default/override shape survives intact, just with the layers named correctly: the computed score **suggests** candidates; an authored `SubstitutionRule` **decides**, with a real ratio and the power to exclude outright.

**And often neither is needed.** Because `specifies` may now name a Culinary Role directly, a recipe that genuinely doesn't care can say "any baking fat" instead of naming butter and then enumerating substitutes for it. That is more honest about what the recipe requires, and it removes the substitution question rather than answering it.

**`Allocation`** (Descriptive ICE) — what a Process actually did.

| Attribute | Notes |
|---|---|
| `is about` → Independent Continuant | the real thing used, produced, or employed (renamed from `entity`, now explicitly an aboutness subproperty) |
| `has_participation_role` | input \| output \| instrument |
| `has_actual_quantity` → Measurement (`observed`) | absent for instrument role |
| `fulfills` → Specification | optional |
| `via_substitution` → SubstitutionRule | optional |

The three roles map to: RO `has_input`, RO `has_output`, and — for instrument — plain BFO **`has participant`**. Neither BFO nor RO provides an instrument-specific relation, and inventing one is not warranted; what matters is that `has_agent` is *not* used, since an oven is not causally responsible for anything.

**One mechanism, three transformation shapes**: two inputs and one output is a combination; one input and several outputs is a division; one input, no output, plus a Quality change on that same participant is a pure state change.

### 5.1 Material accounting — a diagnostic, not a constraint

A home kitchen is an **open system**. Water enters from the tap, fat is poured off, steam leaves. Demanding that summed inputs equal summed outputs would require recording entities no cook will ever create, and 454 g of dry spaghetti becoming 900 g of cooked spaghetti would read as 446 g appearing from nowhere.

So input-minus-output is not the accounting. **The yield factor is the authoritative account of expected mass change**, because it already incorporates the ambient exchange — that is precisely what USDA cooking yields measure. Balance checks reality against that expectation:

```
expected output mass  = summed input mass × has_default_yield[transformation]
                        (absent a yield factor, the transformation is assumed
                         mass-conserving, factor 1.0)
unaccounted           = summed actual output mass − expected output mass
```

`unaccounted` is a **derived diagnostic**, never a constraint. Small values are ordinary — evaporation varies, pans differ. Large or systematically-signed values are informative in exactly one direction: they suggest the *yield factor* is wrong for this Type, which is a finding, not a data error. Accumulated `unaccounted` values across many Processes on one Type are therefore evidence for the default-verification Process (§8) to revise that factor — the same feedback path the nutrition-learning case uses.

Worked through the cases that previously broke:

| Process | In | Yield | Expected | Actual | Unaccounted |
|---|---|---|---|---|---|
| Boil spaghetti | 454 g dry | 2.00 | 908 g | 900 g | −8 g |
| Brown ground beef | 454 g | 0.75 | 340 g | 340 g | 0 |
| Peel + dice onion | 180 g whole | 0.90 | 162 g | 162 g | 0 |
| Braise chicken | 510 g | 0.75 | 383 g | 383 g | 0 |

None requires an entity for tap water, rendered fat, or onion peel.

**This retires `has_default_edible_fraction`.** Trimming is a transformation like any other, and its "edible fraction" *is* its yield factor — 180 g whole onion in, 162 g prepared onion out, target Type `Prepared Onion`, factor 0.90. Keeping both meant two relations for one fact, and it was the direct cause of the contradiction where balance demanded a trim-waste output Allocation that edible-fraction existed to make unnecessary. AcquisitionList's purchase scaling walks the same yield chain in reverse (`required ÷ yield`) rather than a separate relation.

**§5.1.1 — the formula above is single-input shaped; combinations apply it per input, then sum.** Found implementing it: every worked case above has exactly one input Type, so "summed input mass × yield[transformation]" reads as one combined mass times one factor. That doesn't generalize — a genuinely combined recipe (pasta + butter + parmesan, tossed together) has no single meaningful yield, because each input transforms differently: pasta absorbs water (factor ≈ 2.0), butter and cheese barely change (factor ≈ 1.0). Forcing one combination-level factor would either be meaningless or would have to vary per recipe by ingredient ratio, which is exactly the kind of stored-but-derivable fact this section already argues against for edible fraction.

The formula already contains its own fix: "summed input mass" sums *before* the single term is applied, but the correct reading for heterogeneous inputs is to resolve each input's *own* yield independently — the same `has_default_yield` lookup any single-ingredient recipe already uses, keyed by the same transformation — and sum the already-yielded amounts:

```
expected output mass = Σ over inputs of (input mass × has_default_yield[input Type, transformation])
                        (absent a yield factor for a given input, that input's factor is 1.0,
                         same fallback as the single-input case)
```

Worked: 454 g dry pasta (×2.00) + 30 g butter (×1.0, no default) + 20 g parmesan (×1.0, no default) = 908 + 30 + 20 = 958 g expected. Pasta's own water-absorption fact is unaffected by what it's combined with — it resolves identically whether boiled alone or as part of a larger dish. No new relation or `DefaultSpecification` shape is needed; this is the existing single-input mechanism applied per input rather than assumed to only ever see one.

### Physical things

| Entity | Attributes | Notes |
|---|---|---|
| **DiscreteWholeItem** | `instance_of` a Food-Identity Type; mass Quality; shelf-life Disposition; NutrientContent Qualities | one egg, one cooked steak. Count is always 1 — a plurality is an Object Aggregate |
| **PortionOfSubstance** | `instance_of` a Food-Identity Type; **mass Quality (this *is* the quantity on hand)**; volume, density; shelf-life Disposition; NutrientContent | flour, milk, a leftover portion. The former separate `quantity` Quality is gone — it was the same Quality twice |
| **ContainerObject** | `instance_of` a Container Type; `opened_status` Quality; optional `partOfLot` | the jar, not the jam. Contents are **`located in`** it |
| **FoodAggregate** | **`has member part`** → FoodObjects; member count | BFO-native membership. Members need not be alike — a dozen eggs and a plated dinner are both aggregates (§5.4) |
| **EquipmentObject** | `instance_of` Equipment Type and Material Type; cleanliness Quality; one or more **Functions**; optional reservation Role | |

### 5.4 Aggregates, unified wholes, and mixtures

Rev. 4 restricted `has member part` to "like independent items" and routed composite meals to `has continuant part` instead. That restriction was **my invention, not BFO's** — BFO's Object Aggregate is simply "a collection of objects, each independently self-connected," with no likeness requirement. It was added to patch an earlier bug and created a new gap: a plated dinner then fit no class at all, being neither naturally bounded nor bulk.

BFO's actual criterion is **causal unity**, and it settles all three cases cleanly:

| Thing | Class | Why |
|---|---|---|
| A dozen eggs | **FoodAggregate** | separate self-connected objects, collected |
| A plated dinner (steak, gratin, salad) | **FoodAggregate** | the components touch but are not fused; move the steak and the salad stays |
| A sandwich; a layered casserole | **Object**, with `has continuant part` | genuinely unified — picked up, served, and eaten as one thing |

So both relations survive with distinct jobs, and the restriction is dropped.

**Heterogeneous mixtures dissolve rather than needing a class.** A can of tomatoes is tomatoes plus packing liquid, and recipes say "drained." Two existing mechanisms already cover it, and which applies depends on whether the discarded part is used:

- *Discarded*: draining is a mechanical Transformation Method with a yield factor. `Canned Tomatoes` + `Draining` → `Canned Tomatoes, Drained`, factor ≈ 0.6. No internal structure needed, because nothing downstream depends on it.
- *Both parts used*: it is a division — one input Allocation, two output Allocations with different Types (drained tomatoes; tomato liquid). The Allocation mechanism already handles this shape.

Modeling a can's internal composition would only be warranted if something needed to reason about it *before* separation, and nothing does.

### 5.5 Purchase

Rev. 4 asserted that purchase provenance comes from a Purchase Process without ever declaring one. It is an ordinary Process:

- `has_output` → the FoodObjects and ContainerObjects acquired
- `occupies temporal region` → when it happened
- generates the `PriceObservation`s for what was paid

**Purchase date needs no attribute anywhere.** It is the Process's temporal region, reached the same way every other "when did this happen" question is answered. An instance's original expiration is then that time plus its shelf-life Disposition default, which closes the chain §4.1.1 depends on.

### 5.2 Where a cooked dish's Type comes from

Every FoodObject must `instance_of` a Food-Identity Type — that is how shelf life, nutrition, and every default lookup work. Cooking bolognese produces a `PortionOfSubstance` that instantiates *what*? "Bolognese Sauce" is not a food anyone authored into a vocabulary, and until it exists as a Type the resulting leftover has no shelf life and no nutrition path.

Two cases, and the model needs both:

- **The output is a known food.** "Braised chicken breast" already exists as a Type, with an FDC mapping and analytically-measured NutrientProfiles. The output Specification simply `specifies` it. Nothing new is defined.
- **The output is particular to this recipe.** "My Bolognese" is genuinely a kind of dish — instances of it get made repeatedly, they share properties, and that is what a universal *is*. The recipe defines it: `defines_output_type`.

**The definition hangs off `RecipeIdentity`, not off `Plan`.** This is the non-obvious part. A Plan is one immutable version; editing the recipe produces a new Plan. If the Type were defined per version, adjusting the salt would create a *different kind of dish*, and last week's leftovers would cease to be the same food as this week's. The dish kind endures across edits, exactly as the RecipeIdentity does. Only the enduring entity may define it.

Two consequences follow without new machinery:

- **Perishability**: a recipe-defined Type is subsumed by default under **Prepared Dish** in the Perishability hierarchy (≈3–4 days refrigerated, largely independent of contents), overridable by the author. This is what the leftover's shelf life resolves against.
- **Nutrition**: the Type has no NutrientProfile, and needs none — §8 rule 8 derives a cooked output's NutrientContent from its input Allocations. But after the dish has been made several times, those `derived` values are exactly the evidence a default-verification Process needs to *populate* the Type's NutrientProfile, at which point rule 7(a) starts applying. The same learning loop as the cooked-food-matching case, arriving at the same place from the other direction.

**Intermediate Step outputs** (browned beef, softened soffritto) are ordinary Food-Identity Types, authored and shared like any other — "browned ground beef" is a generic culinary intermediate, not specific to one recipe. Only the final dish is recipe-particular. Intermediates that never persist need no Perishability placement at all.

### Recipes, plans, policies

| Entity | Attributes |
|---|---|
| **RecipeIdentity** | name; `is_retired`; `defines_output_type` → a Food-Identity Type (optional); current version computed as the head of the `wasRevisionOf` chain |
| **Plan** | `specializationOf` → RecipeIdentity; `wasRevisionOf` → prior version; ordered Steps; `has_recipe_yield` → QuantitySpecification |
| **Step** | `has_specification` → Specifications; `instance_of` a Transformation-Method Type |
| **StateRequirement** | `targets_property` → a Quality or Disposition type; `expected_value` → QuantitySpecification or literal |
| **SubstitutionRule** | `for_specification`; `candidate_type`; `has_substitution_ratio`; `is_excluded` |
| **MealPlan** | `has_entry` → MealPlanEntry; `is about` a Temporal Region; `has_constraint` → NutritionTarget |
| **MealPlanEntry** | `member_of` a MealPlan; `is about` a Temporal Region; `fulfilledBy` → Process; `is_skipped`; `has_planned_consumption`; and exactly one of (`references` a Plan version + `has_planned_servings`) or `consumes_leftover_from` |
| **StockPolicy** | `applies_to` a Food-Identity Type; `has_reorder_threshold`, `has_target_level` → QuantitySpecification; `includes_subtypes`; `eligible_storage_conditions`; `eligible_opened_statuses` |
| **NutritionTarget** | `for_nutrient`; `has_target_range` → QuantitySpecification (may be open-bounded); `has_time_scope` with an explicit day-boundary rule |
| **AcquisitionList** | computed: (Specification inputs of **not-yet-fulfilled** fresh-cooking entries, scaled by planned-servings ÷ recipe-yield, then divided by the yield factor of any trimming/prep transformation between the purchased form and the required form) + (StockPolicy shortfalls up to target level) − **eligible** on-hand |

### Identity

**`Identifier`** (Designative ICE): `identifier_scheme` → a Concept; `identifier_value` → literal; **`denotes` → any Entity**. One class covers system UUIDs, GTINs, user QR codes, and UCUM unit codes — `skos:notation` is retired in favour of it. The scheme determines cardinality: UUIDs and user QRs are 1:1; a GTIN denotes a packaged-offering Type shared by many instances.

`exactMatch`/`closeMatch` remain distinct from Identifier and are not redundant with it: they are *semantic* claims between Concepts ("my term and FoodOn's term mean the same"), symmetric; an Identifier is a *referential* claim from a code to a thing, asymmetric.

---

## 6. Aboutness: fourteen relations, one parent

Every ICE-to-something relation in this model is a claim that the ICE concerns its target — which is exactly `iao:is about`, whose range is unrestricted `Entity`. They are now declared as **subproperties of `is about`**, following established practice (NFDIcore and others introduce subproperties of `iao:is about` for domain-specific aboutness while keeping the general relation queryable):

`denotes` · `fulfills` · `specifies` · `for_nutrient` · `applies_to` · `candidate_type` · `for_specification` · `for_definition` · `for_instance` · `has_domain` · `references` · `targets_property` · `is about` (Measurement → Quality) · Allocation's `is about` · **`for_type`** · **`for_meal_plan`**

This merges nothing. Each keeps its own meaning and range; they gain a common parent, so "everything this Plan concerns" becomes one query instead of fourteen.

**`for_type`** (`DefaultSpecification` → a Type) and **`for_meal_plan`** (`AcquisitionList` → `MealPlan`) were added on implementation contact, not at design time — both relations were used constantly in prose ("`InstantiationPattern` holds `DefaultSpecification`s **for one Type**"; `AcquisitionList` is computed **for** a `MealPlan`) without ever being named here. This is the same failure mode as the original E9 finding (an instance's tie to a Concept, used everywhere, named nowhere) recurring twice more independently — worth a standing check when adding any new invariant or worked example: does every relation it leans on actually have an entry in this section?

---

## 7. Relations

**BFO-native** (used as declared): `instance_of`, `continuant part of` / `has continuant part`, **`has member part`**, **`located in`**, `inheres in` / `bearer of`, `realizes` / `realized in`, `participates in` / `has participant`, `occupies temporal region`, `begins to exist during` / `ceases to exist during`, **`concretizes`**, `precedes` / `preceded by`.

**IAO/CCO**: `is about` and its fourteen subproperties (§6).

**RO**: `has_input`, `has_output`. (`has_agent` is **not used** — see §14.)

**PROV-O**: `specializationOf`, `wasInvalidatedBy`, `qualifiedUsage` / `qualifiedGeneration`. **`wasDerivedFrom`** now carries real weight — it links an `imputed` Measurement to the QuantitySpecification it resolved, and a `derived` Measurement to the prior Measurement and Allocations it was computed from. For *material* lineage between physical things it remains descriptive shorthand only; authoritative quantitative lineage lives in Allocations. **`wasRevisionOf`** is now used for Plan versions and for genuine data-entry corrections only — not for magnitude change over time (§4.1.1).

**OWL-Time** additionally: `hasTime` on every Measurement.

**P-Plan**: `isPreceededBy` (Step ↔ Step, within a Plan).

**SKOS**: `inScheme`, `broader` / `narrower` (browsing schemes only), `exactMatch` / `closeMatch`, `prefLabel`.

**OWL-Time**: `hasBeginning`, `hasEnd`, `hasDuration`, `before`, `after`, `during`, `overlaps`.

**Bespoke** (nothing suitable exists upstream): `defines_output_type`, `has_participation_role`, `has_specified_quantity`, `has_actual_quantity`, `has_state_requirement`, `expected_value`, `has_substitution_ratio`, `is_excluded`, `via_substitution`, `identifier_scheme`, `identifier_value`, `has_status`, `is_reversible`, `partOfLot`, `member_of` / `has_entry`, `has_constraint`, `has_recipe_yield`, `has_planned_servings`, `has_planned_consumption`, `consumes_leftover_from`, `fulfilledBy`, `is_skipped`, `is_retired`, `applies_within`, **`hasKind`**, **`keyedBy`**, **`hasValue`**, **`targetType`** (the DefaultSpecification fields, §8), `has_reorder_threshold`, `has_target_level`, `includes_subtypes`, `eligible_storage_conditions`, `eligible_opened_statuses`, `has_time_scope`, `has_target_range`, `has_value_type`, `has_value`, **`may_bear_role`** (Food-Identity Type → Culinary Role type, §5.3), **`subsumed_by`** / **`subsumes`** (Type → Type within one hierarchy, §1 — the ⊑ relation itself; used everywhere `resolveDefault` walks, never previously named here even though the build sketch's Structr mapping already calls it `SUBCLASS_OF`), **`targets_entry`** (Role → MealPlanEntry, invariant 27a — see §11's note), **`has_opened_status`** (ContainerObject → a Type, §8's `ShelfLife` compound key — see §17 H4), **`has_storage_condition`** (ContainerObject → a Type, the other half of the same compound key — see §17 H5).

---

## 8. InstantiationPattern

Defaults attach to a **Type** and are **QuantitySpecifications**, not Measurements (§4.1):

Defaults attach to a **Type**. Rather than eight named relations, an `InstantiationPattern` holds a set of **`DefaultSpecification`** nodes, each carrying:

| Field | Notes |
|---|---|
| `hasKind` → a Default-Kind Type | Density, MassPerUnit, PurchaseQuantity, Duration, ShelfLife, NutrientAmount, Yield, RetentionFactor |
| `keyedBy` → zero or more Types | the former "keyed table" dimensions |
| `hasValue` → QuantitySpecification | the default itself |
| `targetType` → a Type | Yield only — what the transformation produces |

The former keyed tables become several `DefaultSpecification` nodes, one per cell, which is cleaner than a table structure: each cell is independently looked up, independently overridable, and carries its own provenance. Worked examples:

```
hasKind: Density          keyedBy: —                         value: 0.59 g/mL
hasKind: ShelfLife        keyedBy: [Fridge, Sealed]          value: 21 days
hasKind: ShelfLife        keyedBy: [Fridge, Opened]          value: 7 days
hasKind: Yield            keyedBy: [Braising]                value: 0.75
                          targetType: Chicken Breast (braised)
hasKind: RetentionFactor  keyedBy: [Braising, Protein]       value: 0.94
hasKind: NutrientAmount   keyedBy: [Protein]                 value: 31 g / 100 g
```

*Why reified rather than eight named relations*: the relations would live on `InstantiationPattern`, a type with many live instances, so adding a ninth default kind would mean modifying a populated schema type — the specific case Structr handles badly. As data nodes, a ninth kind is a new Default-Kind Type and costs nothing. The pattern matches the kind-reification already used for Quality, Role, and Process.

**Algorithm:**

1. Start at the instance's Type in the relevant hierarchy.
2. If absent, walk **subsumption** upward (single direct parent per hierarchy, so unambiguous) and repeat. This is now native transitive subsumption, not an application-level SKOS traversal.
3. Reaching the hierarchy root with nothing found yields explicitly undefined/unconvertible — never a guess.
4. A resolved default is **applied** to the instance as an `imputed` Measurement about that instance's own Quality (§4.1). An `observed` Measurement of the same Quality at the same or a later time always takes precedence over an `imputed` one — a comparison now made between two Measurements rather than across a class boundary.
5. Each `DefaultSpecification` resolves independently by its (`hasKind`, `keyedBy`) signature; a Type may define some and inherit the rest.
6. Rollups walk subsumption *downward*.
7. **Cooked-food nutrition**, in published order of preference: (a) if `has_default_yield` resolves to a cooked Food-Identity Type, use that type's own NutrientProfiles — analytically measured values; (b) otherwise apply yield factor and retention factors to the raw values. Cooked food codes preferred; factors are the documented fallback.
8. Any FoodObject generated by a cooking Process has `derived` NutrientContent computed from its input Allocations — stable, because those Allocations are immutable once cooking completes.

**Learning from user confirmations**: a user matching a branded raw chicken + braise → a cooked type writes an `observed` fact at a leaf Type. Generalizing it requires only storing the fact at a supertype, after which subsumption finds it for every brand. *Where* to store it is an application inference decision. When promoted, the new default is `wasGeneratedBy` a default-verification Process that `used` the observations as evidence.

---

## 9. Physical vs. eligible inventory

**Physical on-hand** — everything that exists, expired included; needed for disposal and waste feedback. **Eligible on-hand** — physical, minus expired, minus anything failing a query's storage/opened-status filter; this is what StockPolicy checks and AcquisitionList subtracts. Opened-status filters traverse contents → `located in` → container; food in no container is outside any opened-status filter rather than undefined.

---

## 10. Worked example — one braise, BFO-conformant throughout

```
TYPES (universals, in subsumption hierarchies)
  Chicken Breast (raw)     ⊑ Poultry ⊑ Fresh Meat [Perishability] ⊑ FoodObject
  Chicken Breast (braised) ⊑ Poultry ⊑ Cooked Leftover [Perishability]
  Braising                 ⊑ Wet-Heat Method ⊑ Process
  Heating                  ⊑ Capability ⊑ Function

CONCEPTS (Designative ICEs)
  Concept "chicken breast, raw"  denotes → Type Chicken Breast (raw)
      exactMatch → FDC 05062
  Identifier (GTIN 00021234500017) denotes → Type "Brand X Chicken Breast, 1 lb"

PLAN SIDE
  Step  instance_of → Braising
    has_specification → Specification #S1
        has_participation_role: input
        specifies → Type Chicken Breast (raw)
        has_specified_quantity → QuantitySpecification(500 g, status: specified)
    has_specification → Specification #S2
        has_participation_role: instrument
        specifies → Function type "Heating"      ← a Function, not an Equipment Type
        has_state_requirement → StateRequirement(cleanliness = clean)
    has_specification → Specification #S3
        has_participation_role: output
        specifies → Type Chicken Breast (braised)
        has_specified_quantity → QuantitySpecification(375 g, status: default)
                                  ← 500 g x 0.75, from has_default_yield["Braising"]

INVENTORY
  PortionOfSubstance #C88   instance_of → Chicken Breast (raw)
      bearer_of → mass Quality #Q1
          Measurement(510 g, observed, hasTime: Sunday 10:15)
          ← this IS the quantity on hand; no separate quantity Quality
      bearer_of → shelf-life Disposition
      located in → ContainerObject #T4 (instance_of Tray; opened_status: opened)

  DiscreteWholeItem #C90    instance_of → Yellow Onion       (never weighed)
      bearer_of → mass Quality #Q2
          Measurement(180 g, IMPUTED, hasTime: Sunday 10:15)
              wasDerivedFrom → QuantitySpecification
                               has_default_mass_per_unit["Yellow Onion"]
          ← without `imputed`, nothing in the model is about THIS onion's mass;
            the Type default is about nothing existing (§4.1)
  EquipmentObject #E1  instance_of → Dutch Oven
      bearer_of → Function (instance of type "Heating")  ← satisfies #S2 without
                                                            being named
      bearer_of → cleanliness Quality

EXECUTION
  Process P1  instance_of → Braising
      concretizes → the Plan            ← BFO-native; replaces PROV hadPlan
      occupies temporal region → Sunday 16:00–18:00
      has_input      → #C88             (RO)
      has_participant → #E1             (BFO; NOT has_agent — an oven acts on
                                         nothing of its own accord)
      realizes → #E1's reservation Role
      qualifiedUsage → Allocation #A1
          is about → #C88;  role: input
          fulfills → #S1
          has_actual_quantity → Measurement(510 g, observed)
      qualifiedGeneration → Allocation #A3
          is about → #C91;  role: output
          fulfills → #S3
          has_actual_quantity → Measurement(383 g, observed)

  PortionOfSubstance #C91  instance_of → Chicken Breast (braised)
      begins to exist during → P1       ← BFO-native
      bearer_of → NutrientContent (protein), described by Measurement(84 g, derived)
                  ← from the braised type's own NutrientProfiles (§8 rule 7a),
                    not from retention factors

Material accounting (§5.1): expected = 510 g × 0.75 = 383 g; actual = 383 g;
unaccounted = 0. The 127 g of moisture that left the pan needs no entity — the
yield factor already accounts for it.

--- and what happened to the onion, without mutating anything ---

  Process P0 (dicing) → Allocation(input, is about #C90, 60 g, hasTime Sunday 17:40)

  #C90's mass at Sunday 18:00, per §4.1.1:
      latest observed-or-imputed Measurement about #Q2  = 180 g (imputed, 10:15)
      minus input Allocations about #C90 after 10:15    = 60 g
      = 120 g

  No decrement relation, no mutated field, no wasRevisionOf. If the app
  materializes this it is a Measurement(120 g, derived, hasTime 18:00)
  wasDerivedFrom the imputed 180 g and the 60 g Allocation.
```

---

## 11. Domain Invariants

**Structural**
1. Every SDC `inheres in` exactly one Independent Continuant. No SDC inheres in a GDC — **BFO forbids realizables on generically dependent continuants**, so no Role, Disposition, or Function may attach to a Plan, Concept, Measurement, or any other ICE.
2. Every **Measurement** `is about` exactly one Quality or Disposition and has exactly one `hasTime`. A **QuantitySpecification** is about no existing Quality and has no time.
2a. At most one `observed` and at most one `imputed` Measurement may be about the same Quality at the same time; where both exist, `observed` governs.
2b. Every `imputed` Measurement `wasDerivedFrom` exactly one QuantitySpecification; every `derived` Measurement `wasDerivedFrom` at least one Measurement or Allocation.
3. Each of Measurement and QuantitySpecification holds exactly one of: a value, a closed range, an open-bounded range, or `unconvertible`; an open-bounded range states which bound is absent; a closed range has min ≤ max.
4. Every Allocation `is about` exactly one Independent Continuant and has exactly one `has_participation_role`.
5. Every Specification has exactly one `has_participation_role`.
6. Instrument-role Specifications and Allocations carry no quantity.
7. A MealPlanEntry has exactly one of (`references` + `has_planned_servings`) or `consumes_leftover_from`.
8. Within one lookup-bearing Type hierarchy, a Type has at most one direct parent; membership in several hierarchies is expected.
9. A Plan has at most one `wasRevisionOf` predecessor and `specializationOf` exactly one RecipeIdentity.
9a. `defines_output_type` is borne by RecipeIdentity only, never by a Plan version — a recipe edit must not change what kind of dish the recipe makes (§5.2). A recipe-defined Type is subsumed under **Prepared Dish** in the Perishability hierarchy unless the author places it otherwise.
10. `has member part` ranges over independently self-connected Objects, **alike or not**; genuinely causally-unified wholes use `has continuant part`; contents-in-a-container use `located in` (§5.4).
11. A UUID or user-QR Identifier `denotes` exactly one Entity and is unique within its scheme; a GTIN may be shared.

**Value**
12. No quantity-bearing value may be negative.
13. Cross-quantity-kind conversion requires an explicit density; without one, `unconvertible`.
14. Retention factors lie in (0, 1]. Yield factors are positive and may exceed 1 where a food absorbs water (boiled pasta ≈ 2.0) or fall well below it for trimming (whole pineapple ≈ 0.5).
14a. `unaccounted` (§5.1) is a derived diagnostic and is **never** a validity condition — no Process is rejected on its value.

**Process**
15. Summed input quantities per bearer cannot exceed that bearer's **physical** on-hand at the time of the Process, computed per §4.1.1. A violation against an `imputed` baseline is informative rather than fatal — it means the Type default was wrong for this instance, and the resolution is to record an `observed` Measurement.
16. No Allocation target may be both an input and an output of the same Process.
17. A Process cannot begin before every entity it takes as input exists.
18. `via_substitution` must reference a rule whose `is_excluded` is false.
19. A StockReconciliation produces a new `observed` Measurement at the time of the recount; it does not revise the prior one. The unexplained difference is that Measurement's value minus the value predicted for that moment by §4.1.1.

**Vocabulary**
20. `exactMatch`/`closeMatch` link Concepts across different schemes, by this application's convention.
21. `candidate_type` ranges over the **same hierarchy as the `specifies` it substitutes for** — a Food-Identity Type for a food slot. Similarity between candidates is computed over Culinary Role via `may_bear_role`, never stored (§5.3).
22. `SubstitutionRule.for_specification` references an input-role Specification only.

**Planning**
23. Total planned consumption across entries drawing on one source cannot exceed that source's surplus.
24. An entry's planned consumption cannot exceed its own planned servings.
25. **Equipment exclusivity is per Equipment Type, not universal** — a pan is exclusive-use, an oven is not. Overlapping Temporal Regions are rejected only for Types declared exclusive. *(Rev. 3's blanket version was simply false about kitchens.)*
26. `has_target_level` ≥ `has_reorder_threshold`.
27. A leftover-consuming entry cannot be scheduled before its source Process completes, nor after the leftover's effective expiration.
27a. A reservation Role on a physical portion and the `consumes_leftover_from` edge between entries are **not duplicates** — they are the plan/actual pair the model is built on, asserted at different times: the entry-to-entry link at planning, the portion-to-entry Role only once the food physically exists. Where both are present they must agree: the Role's target entry must be the one whose `consumes_leftover_from` names the entry whose Process generated that portion. (Checkable only once `targets_entry`, §7, is asserted — F15 named the invariant but not the relation it depends on; added on implementation contact.)
28. AcquisitionList counts only entries not yet `fulfilledBy` a completed Process.

**Nutrition**
29. A cooking output's NutrientContent is always `derived`.
30. A NutritionTarget and its rollup must share nutrient and quantity kind; bounds state inclusive/exclusive; daily scope states its day-boundary rule.

---

## 12. Reversibility

Most irreversibility is already implicit: a Process generating a **new instance of a new Type** (cooking) is irreversible by construction; a Process toggling a **cycling Quality** (cleanliness) is reversible by construction. The residue is one-way Quality transitions, so `is_reversible` is declared on the **Quality type**. Application-level undo is edit history, not domain semantics.

---

## 13. Deferred / out of scope

Fiat Object Part; Immaterial Entity and Site-based location; **Person/Agent** (single-user tool — note this is why no BFO agent relation is used anywhere); freezing/thawing as modeled transitions; non-linear recipe scaling; new top-level classes via ExtensionPropertyDefinition; splitting Food Identity into composition-vs-aggregation hierarchies; **MealServing** (per-serving customization — motivating scenario recorded, deferred); full OWL/DL reasoning.

**Resolved by the implementation decision (Structr, §16)**: the two questions previously held pending implementation-capability research are settled, and — importantly — settled *differently* from each other, because the two cases are not symmetric.

- **Defaults → reified** (`DefaultSpecification`, §8). The eight named relations would have lived on `InstantiationPattern`, a type with many live instances; adding a ninth would modify a populated schema type, which is the dangerous case in Structr. As data, a new kind costs nothing.
- **Constraints → shared abstract trait** (`PlanningConstraint`, with `StockPolicy` and `NutritionTarget` as concrete subtypes). Adding `BudgetConstraint` or `TimeConstraint` later means creating a *new* type inheriting an existing trait, with no instances yet — which is safe. Their attributes genuinely differ (eligibility filters vs. a time scope), so forcing them into one reified type would recreate the untyped-bag problem this model has rejected throughout. `MealPlan.has_constraint → PlanningConstraint` becomes one polymorphic declaration.

The general principle both follow: **reify what varies within a populated type; subclass what varies across types.**

---

## 14. Changes in Rev. 4

| # | Change | Reason |
|---|---|---|
| E1 | `ContainerObject has_part contents` → **`located in`** | Flour is not a continuant part of a bag. BFO has a containment relation |
| E2 | `hadMember` → BFO **`has member part`** | BFO-native membership existed; the PROV import was unnecessary |
| E3 | PROV `hadPlan` → BFO **`concretizes`** | BFO's `concretizes` declares **Process** in its domain and GDC in its range — this exact relation, already available. `correspondsToStep` retires as redundant |
| E4 | RO `has_agent` for equipment → BFO **`has participant`**; role renamed `agent` → **`instrument`** | RO's agent is the entity *causally responsible*. An oven is an instrument. With Person out of scope, the model has no agents at all |
| E5 | Measurement split into **Measurement** + **QuantitySpecification** | `is about` requires something to be about; a required quantity is about nothing existing. The old invariant was false for every prescribed value |
| E6 | NutrientContent split into **NutrientContent** (Quality) + **NutrientProfile** (Descriptive ICE) | "Per 100 g" is type-level reference data, not the magnitude of anything inhering in a particular |
| E7 | `quantity` Quality merged into **mass** on PortionOfSubstance; count moved to Object Aggregate | For a bulk portion these were one Quality under two names. A count only makes sense where a plurality exists |
| E8 | Equipment Function *facet* deleted; **Capability** types under BFO Function | The facet duplicated as a Concept what the Function already asserted |
| E9 | **Type / Concept split** (§1) | SKOS Concepts had been doing the work of BFO universals. Retires `skos:related`; moves default lookup onto native transitive subsumption |
| E10 | `has_participation_role` retained but documented as a literal enum | The name invites confusion with BFO Role; invariant 1 now states outright that no realizable may inhere in an ICE |
| — | Fourteen ICE relations declared **subproperties of `is about`** | All were specializations of one IAO relation |
| — | `skos:notation` retired in favour of **Identifier** | One mechanism for codes, per the earlier decision |
| — | Invariant 25 (equipment exclusivity) scoped per Equipment Type | The blanket rule would have rejected an oven holding two dishes — normal cooking |

## 15. Rev. 4.1 — the foundational fix

A lifecycle case study found that Rev. 4, in making `Measurement` rigorous about *being about* something, lost two abilities it previously had implicitly.

| # | Change | Reason |
|---|---|---|
| F1 | Measurement gains an **`imputed`** status | An unmeasured instance (an onweighed onion) had no object in the model about its own mass — the Type default is a QuantitySpecification, about nothing existing. Without a distinct status, a resolved default was indistinguishable from a human guess |
| F2 | Measurements are **time-indexed** (`hasTime`); a Quality's current magnitude is **computed**, not stored (§4.1.1) | Nothing said how a Process changes its source's magnitude. Quantity was a mutable field in Rev. 3; Rev. 4 made it an immutable ICE with no successor mechanism |
| F3 | `wasRevisionOf` retires from magnitude change; **stock reconciliation is a new observed Measurement**, not a revision | The earlier value was correct when made. Only genuine data-entry error is a revision |
| F4 | `wasDerivedFrom` promoted from shorthand to load-bearing for Measurement provenance | It now links imputed→specification and derived→(prior Measurement, Allocations) |
| F5 | Invariant 15 violations against an `imputed` baseline are informative, not fatal | Exceeding a defaulted quantity means the default was wrong for this instance — useful signal, not corruption |
| F6 | Material balance reframed as a **diagnostic** with an explicit `unaccounted` term; the **yield factor is authoritative** for expected mass change (§5.1) | A home kitchen is an open system. Input-minus-output demanded entities for tap water, rendered fat, and onion peel that no cook records — and it disagreed with the yield factor, with nothing designating which won |
| F7 | **`has_default_edible_fraction` retires**, absorbed into `has_default_yield` | Trimming is a transformation; its edible fraction *is* its yield factor. Two relations for one fact, and the direct cause of balance and edible-fraction requiring opposite things |
| F8 | Accumulated `unaccounted` feeds the default-verification Process | A systematically-signed residual is evidence the yield factor is wrong for that Type — the same feedback path as nutrition learning |
| F9 | **`RecipeIdentity.defines_output_type`** (§5.2); Perishability gains an explicit **Prepared Dish** branch | Every FoodObject must instantiate a Type, but a cooked dish's Type is authored by nobody. A recipe genuinely defines a kind of dish. Placing the definition on RecipeIdentity rather than on a Plan version is what stops a salt adjustment from making last week's leftovers a different food |
| F10 | `candidate_type` re-ranged to **Food-Identity Types**; similarity **computed** over Culinary Role via new `may_bear_role`; **`substitutableFor` retires** (§5.3) | Invariant 21 contradicted `specifies` outright: a Specification names Butter, so a substitute must be a food, not a role. Culinary Role is what similarity is *measured over*, not what candidates are *drawn from*. And a Wu-Palmer score is derived from hierarchy structure — storing it stored something computable |
| F11 | `specifies` may name a **Culinary Role** directly for input slots | A recipe that doesn't care can require "any baking fat" rather than naming butter and enumerating substitutes — removing the substitution question instead of answering it |
| F12 | `DiscreteFoodAggregate` → **`FoodAggregate`**; the "like items" restriction on `has member part` **dropped**; a plated meal is an aggregate (§5.4) | The restriction was mine, not BFO's — BFO requires only that members be independently self-connected. It was added to patch an earlier bug and created a new gap: a plated dinner fit no class. BFO's real criterion, causal unity, separates aggregate (plate) from unified whole (sandwich) cleanly |
| F13 | Heterogeneous mixtures need **no new class** (§5.4) | Draining is a transformation with a yield factor when the liquid is discarded, and a division into two output Allocations when it is used. Internal composition would only matter if something reasoned about it before separation, and nothing does |
| F14 | **Purchase Process** declared (§5.5); purchase date is its temporal region | Rev. 4 asserted purchase provenance came from a Process it never declared, leaving the original-expiration chain unstated. No new attribute is needed anywhere |
| F15 | Invariant 27a: reservation Role and `consumes_leftover_from` are the **plan/actual pair**, not duplicates — but must agree | On inspection this was not double-assertion: the entry-to-entry link is made at planning, the portion-to-entry Role only once the food exists. What was missing was the consistency constraint between them |

The case-study queue is now empty. Everything the spaghetti-bolognese lifecycle surfaced has been addressed, and three of the findings (F7, F10, F12) turned out to be **corrections of restrictions this model had invented for itself** rather than gaps in what it covered.

## 16. Rev. 4.2 — implementation chosen, held decisions resolved

**Implementation: Structr 6.x on Neo4j.** Not chosen for reasoning power — none is needed — but because its traits give real multiple inheritance and polymorphic targeting, its schema methods substitute credibly for SHACL, and it supplies auth/REST/admin that a triplestore would not. See the separate build sketch for the three-layer split (fixed structural traits / metamodel as data / instance data) and the specific gotchas.

| # | Change | Reason |
|---|---|---|
| G1 | Eight `has_default_*` relations → **`DefaultSpecification`** nodes with `hasKind`/`keyedBy` (§8) | The relations sat on a type with many live instances; a ninth would modify populated schema. Keyed tables become one node per cell, independently overridable |
| G2 | `StockPolicy` and `NutritionTarget` → concrete subtypes of an abstract **`PlanningConstraint`** | A new constraint type inherits an existing trait with no instances — the safe case. Their attributes genuinely differ, so one reified type would have been an untyped bag |

The principle these two resolve to, worth carrying forward: **reify what varies within a populated type; subclass what varies across types.**

## 17. Rev 4.3 — corrections found building real recipes

Rev 4.2 chose the implementation; this rev is what actually building combination recipes and a full meal-planning layer against it turned up. Two findings, both recorded rather than silently patched around, per this document's own standing practice.

| # | Change | Reason |
|---|---|---|
| H1 | §5.1's material-accounting formula clarified: apply `has_default_yield` **per input, then sum** — not one factor over the summed total | Every worked case in §5.1 had exactly one input Type, so the distinction never surfaced. A genuinely combined recipe (pasta + butter + parmesan) has no single meaningful yield — each input transforms differently. The formula's own "summed input mass" already sums before the factor; the fix is resolving that factor per input (the existing single-input mechanism, unchanged) rather than inventing a combination-level default. See §5.1.1 |
| H2 | Three relations added to §7 that were used in prose but never named: `for_type`, `for_meal_plan`, `targets_entry` | Same failure mode as the original E9 finding, independently recurring twice more. `for_type`/`for_meal_plan` are `is about` subproperties (§6) discovered missing while wiring `DefaultSpecification` and `AcquisitionList`; `targets_entry` is what invariant 27a (F15, Rev 4.1) needed all along to be checkable at all — the invariant was named four revisions ago, the relation it depends on wasn't |
| H3 | `Plan.has_recipe_yield`'s unit resolved: **servings** | Never pinned down explicitly, which blocked real per-serving nutrition scoring (whole-batch nutrition was being compared against a per-person target). Not a new ambiguity to resolve by fiat — AcquisitionList's own computation ("scaled by planned-servings ÷ recipe-yield") only makes sense if recipe-yield is already denominated in servings. The formula had already settled this; nothing had connected it to the field's own definition |
| H4 | `ContainerObject` gains **`has_opened_status`** → a Type (`Opened`/`Sealed`), and §8's `ShelfLife` compound key (`keyedBy: [Storage Condition, opened status]`) is now actually usable | §8's own worked example already keyed `ShelfLife` by `[Fridge, Opened]`/`[Fridge, Sealed]`, implying opened/sealed are Types usable in a `keyedBy` list — but no relation carried a container's actual opened state anywhere, so every `ShelfLife` default in practice had been flattened to the Storage-Condition dimension alone. Same "independent instance-level classification" shape as `has_perishability_type` (§1, Reading A) — a container's opened state is orthogonal to what kind of container it is |
| H5 | `ContainerObject` gains **`has_storage_condition`** → a Type (`Fridge`/`Freezer`/`Pantry`), closing the other half of the same compound key | The smaller sibling gap H4 left open: Storage Condition was hardcoded to "Fridge" everywhere, so `ShelfLife` had no way to distinguish freezer stock from fridge stock even after H4. Same relation shape as `has_opened_status`, same fallback reasoning (no container → assume "Fridge", the common case for an untracked portion in a home kitchen). `StockPolicy.eligible_storage_conditions` (named since Rev 4.2, never usable) now actually filters — demonstrated with real frozen stock (30 days old, 500g, correctly resolving ~150 days remaining on a 180-day freezer shelf life vs. long-expired on a 5-day fridge one, and correctly excluded from a Fridge-only policy's eligible count) |

**Standing recommendation, not yet done**: a systematic pass checking every one of the 30 invariants against whether each relation it references actually has a §7 entry. Three independent misses in one build is enough to suspect there's at least a fourth.

Not a modeling finding, but worth recording here since it was found in the same pass: the Structr implementation of `resolveDefault` (build sketch §5) doesn't actually honor its own documented signature — §8 says a `DefaultSpecification` "resolves independently by its (`hasKind`, `keyedBy`) signature," but the live `SchemaMethod` only filters by `hasKind`. The model was already correct on this point; the implementation wasn't. See the build sketch's §5 addendum.


## 18. Rev 4.4 — semantics settled while building selection, nutrition and reservation

Rev 4.3 recorded what building recipes turned up. This rev records what building the *consumers* of the model turned up: places where the model named a relation or formula but left its behaviour open, and the implementation had to pick a reading to proceed. Each row is a **resolution chosen under implementation pressure, not derived from the model** — the same status as §17, and equally open to challenge. The code that implements each is named so it can be checked against the claim.

| # | Change | Reason and status |
|---|---|---|
| J1 | **AcquisitionList's formula is read as one shared stock pool.** `net = max(0, committed demand + target level − eligible on-hand)`, with on-hand subtracted **once**, not once inside "shortfall" and again at the end | §7 reads "(inputs of not-yet-fulfilled entries…) + (StockPolicy shortfalls up to target level) − **eligible** on-hand". Taken literally that subtracts on-hand twice, because a "shortfall" is already `target − on-hand`. The reading chosen is also the physical one: buying for Monday's dinner does not also refill a standing reserve for free. **Not built:** the division by "the yield factor of any trimming/prep transformation between the purchased form and the required form" — there is no vocabulary distinguishing a Type's purchased form from its as-required form (`mealplanner/reservation.py`) |
| J2 | **StockPolicy resolution.** The governing policy for a Type is found by walking up its hierarchy; the **nearest level with an applicable policy wins**, the same rule `resolveDefault` uses (§8). A policy on an ancestor applies to a descendant **only if `includes_subtypes` is not false**; a policy on the Type itself always applies. Several policies on one Type combine **restrictively**: flags AND together, `eligible_storage_conditions` intersect, `includes_subtypes` is false if any says false, and the largest target level is used. An unset `includes_subtypes` counts as true | §7 says a policy `applies_to` a Type and has `includes_subtypes`, and nothing about which policy governs a Type when several could, or what the flag does when it is false. The implementation had been taking the first policy the graph returned. Restrictive combination is order-independent and can only shrink what counts as usable stock. **Open:** nested policies (an ancestor's and a descendant's) describe physically overlapping stock and are not reconciled; tied policies are treated as constraints on one pool, so "keep 1000 g sealed in the fridge *and* 500 g in the freezer" is not expressible (`resolve_stock_policy`) |
| J3 | **`has_planned_consumption` is servings eaten at that entry**, in the same unit as `has_planned_servings`; where absent, **one serving** is assumed | Invariant 24 compares the two, which only makes sense in a common unit. The single-user default is a stated convention, not a fact about the data: every entry that relied on it is reported to the caller. No current data sets the field, so today every entry uses the default (`mealplanner/nutrition_scope.py`) |
| J4 | **A NutritionTarget is judged at the scope it declares.** `per_meal`: one serving against the range. `daily`: the entries whose start falls on the same calendar day under the target's day-boundary rule (only "midnight" is implemented; any other rule is reported unsupported, never guessed). `weekly`: every active entry of the MealPlan. Skipped entries never count; **cooked entries do** (they were eaten). Because nutrient amounts are non-negative, a partial total only grows, so a **hard maximum is decidable while planning and a hard minimum is not** — a scope may simply be unfilled. Minimums are judged only by a report over a filled plan | `has_time_scope` existed from Rev 4.2 and nothing read it: the selector compared one meal against every target whatever its scope. `NutrientProfile` carries no unit field, so amounts are grams per 100 g by convention and a target not stated in grams is reported unsupported. **Open:** inclusive/exclusive bounds (invariant 30) are not modeled — both bounds are treated as inclusive |
| J5 | **Final vs. intermediate outputs are derived from the Plan's own structure.** An output Specification is *final* if no Step of the same Plan takes its Type as an input; otherwise it is an intermediate, which is neither eaten (nutrition) nor required from stock (a raw-input requirement is likewise one whose Type no Step of the Plan produces) | The model allows several outputs per Step and several Steps per Plan but does not say which outputs a person eats. Deriving "final" keeps it computed rather than stored. It assumes a Type identifies the material, so a Plan that consumes and produces the same Type in different roles reads as having no final output of that Type. **Open:** which outputs are *eaten* (a broth's fat, an inedible trimming) is not modeled, so an output with no NutrientProfile makes a recipe's nutrition **unknown** rather than a partial sum. The chained-Step material-accounting question left open in §5.1.1 (an intermediate's mass double-counting through its producer and its consumer) is unaffected (`candidate_outputs`) |
| J6 | **Exclusions are transitive downward through both hierarchies.** Excluding a Type bans it and every descendant; every food whose Biological Origin is the excluded Type *or any descendant of it*; and those foods' own descendants. They are **not** transitive upward: a recipe naming only a supertype ("Poultry") when one subtype is excluded is not a hard violation, since it can be made another way | Exclusion previously reached only the excluded Type and foods linked directly to it. Not banning upward is a choice; for an allergy, where a generic requirement might be met by the excluded thing, the conservative reading may be preferred (`excluded_domain_type_ids`) |

**Still open from §17:** the systematic pass checking each invariant against whether every relation it references has a §7 entry has not been done. Separately, the implementation's invariant tracker (`mealplanner/domain_invariants.py`) omitted four of the thirty invariants (2, 10, 25, 27) until a self-audit before external review — a reminder that the tracker and this document are two places that must agree.

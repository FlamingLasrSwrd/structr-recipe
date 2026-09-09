# Meal Planning Data Model — Design Document, Round 2 (for Adversarial Review)

**Purpose of this document**: this is a fresh snapshot for external adversarial review, produced after a first review cycle was completed in full (every accepted finding from that round has a corresponding change in the model below) and after an internal reconsideration pass that ran two new scenarios end-to-end and looked specifically for consolidation opportunities. It is self-contained — no prior conversation is assumed. Section 11 is where a reviewer's attention is most usefully spent: it contains findings from the internal pass that have **not yet been acted on**, unlike everything before it.

---

## 1. Problem Statement

A personal tool that generates a weekly meal plan satisfying: a difficulty ceiling matching cooking skill, nutrient targets (daily/weekly, macro and/or micro), required meal-type coverage, time budgets, pantry/fridge inventory awareness including expiration, and minimized ingredient waste across the week. This document concerns the **data model** only — entities, classes, and relations — deliberately independent of implementation technology.

## 2. Methodology

Grounded in existing formalisms rather than an ad hoc schema: **BFO** (upper ontology), **IAO/CCO** (information content entities), **RO** (relations), **PROV-O** (provenance/execution), **P-Plan** (plan structure), **SKOS** (controlled vocabulary), **OWL-Time** (temporal), **QUDT/UCUM** (quantities/units). Built breadth-first, stress-tested against concrete kitchen scenarios and a real comparable product (Grocy), then substantially revised through a full external adversarial review cycle. This document is the output of a *second* such cycle: an internal reconsideration pass, described in §11, whose findings are not yet built.

---

## 3. Class Hierarchy (current)

```
Entity
├── Continuant
│   ├── Independent Continuant
│   │   ├── Material Entity
│   │   │   ├── Object
│   │   │   │   ├── FoodObject
│   │   │   │   │   ├── DiscreteWholeItem      single naturally-bounded item
│   │   │   │   │   ├── PortionOfSubstance     separable measured quantity of a substance
│   │   │   │   │   ├── PackagedProduct        one instance per purchase/lot, never merged
│   │   │   │   │   ├── PreparedDish           single-mass cooking output
│   │   │   │   │   └── PortionedLeftover      dish portion, physically separated —
│   │   │   │   │                             §11 questions whether this is redundant
│   │   │   │   │                             with PreparedDish now that "reserved for
│   │   │   │   │                             a later meal" is a Role, not a subclass
│   │   │   │   └── EquipmentObject
│   │   │   │       ├── Cookware
│   │   │   │       ├── Utensil
│   │   │   │       └── Appliance
│   │   │   ├── Object Aggregate
│   │   │   │   ├── DiscreteFoodAggregate      hadMember → DiscreteWholeItems as stated —
│   │   │   │   │                             §11 flags this as inconsistent with the
│   │   │   │   │                             separate decision to reuse it for composite
│   │   │   │   │                             meals (PreparedDish members)
│   │   │   │   └── UtensilSet
│   │   │   └── Fiat Object Part                [deferred — empty]
│   │   └── Immaterial Entity                    [out of scope — empty; storage
│   │                                             location is free text, storage
│   │                                             *condition* is a small facet]
│   │
│   ├── Specifically Dependent Continuant
│   │   ├── Quality                              density, mass, volume, cleanliness,
│   │   │                                         color, quantity-on-hand, opened_status,
│   │   │                                         NutrientContent (for_nutrient-qualified)
│   │   └── Realizable Entity
│   │       ├── Role                             inventory allocation; equipment
│   │       │                                     scheduling; leftover reservation —
│   │       │                                     three uses of one pattern (§11: worth
│   │       │                                     naming once rather than three times)
│   │       └── Disposition
│   │           ├── (shelf-life / spoilage propensity)
│   │           └── Function                     declared, never exercised since — §11
│   │                                             flags this as dead weight or an
│   │                                             unbuilt feature, not a working part
│   │
│   └── Generically Dependent Continuant
│       └── Information Content Entity            (CCO refinement of IAO)
│           ├── Directive ICE
│           │   ├── RecipeIdentity                 enduring, named recipe (not a
│           │   │                                 vocabulary term)
│           │   ├── Plan                          one immutable version; ordered Steps
│           │   ├── InputRequirement               material a Step needs
│           │   ├── SubstitutionRule                per-Requirement acceptable/excluded
│           │   │                                 alternate, with a ratio
│           │   ├── OutputSpecification            what a Step should produce
│           │   ├── AgentRequirement                equipment a Step needs — only one
│           │   │                                 precondition field (`requires_clean`);
│           │   │                                 §11 found this too narrow
│           │   ├── Instantiation Pattern         class-level defaults — 8 named
│           │   │                                 properties now; §11 questions whether
│           │   │                                 that's still the right shape
│           │   ├── MealPlanEntry                 "cook this Plan at this time," or
│           │   │                                 "eat a prior entry's surplus"
│           │   ├── StockPolicy                   standing par-level, independent of
│           │   │                                 any Plan
│           │   ├── NutritionTarget                nutrient range over daily/weekly scope
│           │   ├── ExtensionPropertyDefinition     user-declared typed property on an
│           │   │                                 existing class/facet, not a new class
│           │   └── AcquisitionList                derived "what to buy"
│           ├── Designative ICE                   vocabulary Concepts in ConceptSchemes
│           └── Descriptive ICE
│               ├── Measurement                   value/range + unit + has_status;
│               │                                 may be unconvertible
│               ├── ExtensionPropertyValue
│               ├── PriceObservation
│               ├── InputAllocation                qualifies a Process's real input:
│               │                                 which Requirement, how much, via what
│               │                                 substitution
│               └── OutputAllocation               qualifies a Process's real output
│
└── Occurrent
    ├── Process                                   cooking, cleaning, opening, disposal,
    │                                             stock reconciliation
    ├── Process Boundary                           [placeholder — unused]
    └── Temporal Region                            OWL-Time Instant/Interval
```

Not yet in this hierarchy, per §11: a household-level `DietaryRestriction`, any difficulty representation, a grouping entity above `MealPlanEntry`, `BudgetTarget`/`TimeConstraint`.

---

## 4. Facets

| Facet | Drives | Constrained? |
|---|---|---|
| Food Identity | density/mass-per-unit/purchase-quantity/edible-fraction/nutrient-profile defaults; barcode via leaf Concepts; external `exactMatch` | yes (single-parent) |
| Perishability Class | shelf-life table (Storage Condition x opened_status) | yes |
| Storage Condition | second shelf-life key | yes (small, flat) |
| Culinary Role | substitutability scoring | yes |
| Biological Origin | allergen/dietary tagging — **not yet consulted by anything that blocks planning**, per §11 | yes |
| Equipment Type / Material | cleaning-time default; Step precondition matching | yes |
| Heat Method | default Step duration | yes |
| Nutrient | `has_default_nutrient_profile` keys; sub-nutrient rollup; external mapping | rollup-only |
| Units | Measurement's unit reference; wraps QUDT/UCUM | n/a |
| Cuisine, Meal Type | browsing/search only | no |

A Concept's primary tag lives in one facet; `skos:related` cross-links to others it participates in. Barcode-bearing leaf Concepts sit as `broader`-children within Food Identity. Splitting Food Identity into composition-vs-aggregation facets was evaluated and deliberately deferred — no concrete conflict has forced it, unlike Culinary Role.

---

## 5. Core Entities (summary — see the working model for full attribute lists)

Recipe side: `RecipeIdentity` -> `Plan` (immutable per version, `wasRevisionOf`-chained) -> `Step` -> `InputRequirement`/`OutputSpecification`/`AgentRequirement`, with `SubstitutionRule`s hanging off specific `InputRequirement`s.

Execution side: `Process` -> `InputAllocation`/`OutputAllocation` (PROV-O's qualification pattern, quantity-aware, optionally `via_substitution`), `correspondsToStep` back to the Plan side, `hadPlan` naming the exact version followed.

Inventory side: `PackagedProduct`/`DiscreteWholeItem`/`PortionOfSubstance`, one instance per purchase/lot, quantity as a Quality, `opened_status` as a Quality, expiration via a keyed Instantiation Pattern default.

Planning side: `MealPlanEntry` (fresh-cook or leftover-consuming, mutually exclusive), `StockPolicy` (reorder threshold + target level + eligibility scoping), `NutritionTarget`, `AcquisitionList` (computed netting).

Meta layer: `Instantiation Pattern` (8 default types, closed set, per-Concept), `ExtensionPropertyDefinition`/`Value` (typed user extensibility, cannot create new top-level classes).

---

## 6. Relations (by category)

**Structural/participation**: `part_of`, `has_participant`, `has_agent`/`has_input`/`has_output` (RO, Process-only).
**Allocation**: `qualifiedUsage`/`qualifiedGeneration` -> `InputAllocation`/`OutputAllocation`, `entity`, `fulfills_requirement`/`fulfills_specification`, `has_allocated_quantity`/`has_produced_quantity`, `via_substitution`.
**Dependence**: `inheres_in`/`bearer_of`, `realizes`/`realized_in`.
**Plan structure**: `isPreceededBy` (P-Plan), `has_input_requirement`/`has_output_specification`/`has_agent_requirement`, `specifies_concept`, `has_required_quantity`/`has_expected_quantity`.
**Execution/provenance**: `correspondsToStep`, `hadPlan`, `used`/`wasGeneratedBy`/`wasDerivedFrom`, `preceded_by`.
**Versioning**: `wasRevisionOf` (Measurement-correction and Plan-version — two legitimate uses, not reused for Aggregate membership), `specializationOf`.
**Vocabulary**: `inScheme`, `broader`/`narrower` (single-parent, non-transitive by SKOS's own definition), `related`, `exactMatch`/`closeMatch` (different-scheme convention), `notation` (UCUM codes and barcodes).
**Substitution**: `substitutableFor` (general, graded), `has_substitution_rule`/`for_requirement`/`candidate_concept`/`has_substitution_ratio`/`is_excluded`.
**Defaults**: `applies_within`, `has_default_quality`/`_disposition`/`_duration`/`_mass_per_unit`/`_yield`/`_purchase_quantity`/`_nutrient_profile`/`_edible_fraction`.
**Nutrition**: `for_nutrient`, `has_target_range`, `has_time_scope`.
**Extension properties**: `has_domain`, `has_value_type`, `for_definition`, `for_instance`, `has_value`.
**Planning**: `scheduledFor`, `fulfilledBy`, `is_skipped`, `is_retired`, `has_recipe_yield`, `has_planned_servings`, `has_planned_consumption`, `consumes_leftover_from`.
**Stock policy**: `applies_to`, `has_reorder_threshold`, `has_target_level`, `includes_narrower_concepts`, `eligible_storage_conditions`, `eligible_opened_statuses`.
**Temporal**: `hasBeginning`/`hasEnd`/`hasDuration`, `before`/`after`/`during`/`overlaps`.

---

## 7. Instantiation Pattern Algorithm

1. Locate the instance's Concept in the relevant facet (one `related` hop if the default lives elsewhere).
2. Walk `broader` (single-parent) until a value is found or the root is reached (-> `unconvertible`).
3. An `observed`-status Measurement on the instance always overrides an inherited `default`.
4. `has_default_disposition`/`has_default_nutrient_profile` resolve to keyed tables, not single values.
5. `has_default_yield` lands on a different target Concept than queried.
6. Cross-brand/variant rollups walk the same tree downward instead of upward.
7. `PreparedDish`/`PortionedLeftover` NutrientContent is always derived from Allocations, never looked up this way.

---

## 8. Domain Invariants (26, current — see working model for full text)

Structural/cardinality (9), value constraints (4, including edible-fraction bounds), Process/Allocation conservation (4), vocabulary/facet (3), planning/scheduling (4, including the equipment-`overlaps` check and StockPolicy's target>=threshold), nutrition (2).

---

## 9. Condensed Decision Log Since Round 1

- **Step/Process domain fix**: `Step` (an ICE) cannot carry `has_input`/`has_output` (Process-only relations) — introduced `InputRequirement`/`OutputSpecification`/`AgentRequirement`.
- **Allocation layer**: `InputAllocation`/`OutputAllocation`, built on PROV-O's `Usage`/`Generation` qualification pattern — also unified state-change/combination/division into one mechanism and gave material-balance a computed basis.
- **Nutrition**: added in full (`NutrientContent`, `Nutrient` facet, `NutritionTarget`, `has_default_nutrient_profile`) — was entirely absent despite being an original requirement.
- **Measurement `has_status`**: five values (`observed`/`specified`/`default`/`derived`/`estimated`), unambiguous for every existing Measurement.
- **Servings/scaling/planned leftovers**: `has_recipe_yield`, `has_planned_servings`/`has_planned_consumption`, `consumes_leftover_from` — makes "cook extra on purpose" an explicit planning decision with a checkable invariant.
- **Plan versioning**: `RecipeIdentity` + immutable-per-version `Plan`, `wasRevisionOf`/`specializationOf` — third legitimate use of a pattern first retired for Object Aggregates, correctly reinstated for stock reconciliation and now this.
- **StockPolicy scope**: reorder threshold vs. target level, brand-inclusion toggle, storage/opened-status eligibility; a universal (not policy-specific) rule that expired stock never counts as on-hand.
- **Substitution**: `substitutableFor` (general/candidate-discovery) vs. `SubstitutionRule` (specific/authoritative, per-`InputRequirement`) — the same default/override shape as Instantiation Pattern.
- **Typed extension properties**: `ExtensionPropertyDefinition`/`Value` — narrower than Grocy's arbitrary custom fields; extends existing classes, cannot create new ones.
- **Lifecycle states**: only two of four flagged entities needed a new field (`is_skipped`, `is_retired`); the other two were already fully computable.
- **Domain invariants**: consolidated, 26 total, most implied by prior decisions, several genuinely new (negative-quantity ban, range min<=max, equipment-overlap check, etc.).

---

## 10. Known Limitations / Deferred (deliberate)

Fiat Object Part, Immaterial Entity/Site modeling, Person/Agent, a periodic default-verification process, full OWL/DL reasoning, non-linear recipe scaling, new-top-level-class extensibility, and the Food-Identity facet split — all evaluated, all deliberately left alone pending a concrete forcing case.

---

## 11. Findings From an Internal Reconsideration Pass — Not Yet Acted On

Two scenarios were run end-to-end against the model above, generating concrete instances rather than reasoning abstractly. This section is where fresh review attention is most valuable.

### Scenario A — household with a nut allergy, Sunday batch-cooking
- **No `DietaryRestriction` entity exists.** Biological Origin lets ingredients be *tagged* allergen-relevant; nothing checks that tag against anything when a `MealPlanEntry` is created. A standing allergy currently cannot block a recipe.
- **No difficulty/skill representation exists anywhere** — neither `Plan` nor `Step` carries anything resembling it, despite being one of the five constraints in the original problem statement. Conceptually addressed once, very early (difficulty as derived from Step attributes rather than an authored scalar), never built.
- **`AgentRequirement` has exactly one precondition field** (`requires_clean`) — a Step needing a *preheated* oven has nowhere to express that.
- **`Function` is declared but exercised nowhere** — no relation, worked example, or default targets it since it was introduced. Either it should do real work (e.g., letting `AgentRequirement` accept "any tool with this Function" instead of one specific Equipment-Type) or it's dead weight.
- **Range-valued `NutritionTarget`s force both bounds** even when only one is meaningful (sodium ceiling with no floor; fiber floor with no ceiling).

### Scenario B — a dinner party, three dishes, one oven
- **Confirmed working**: the OWL-Time `overlaps` invariant genuinely detects two Processes competing for one `EquipmentObject`.
- **Found a real inconsistency, not just a gap**: `DiscreteFoodAggregate` is defined (§3/§5) with `hadMember` ranging over `DiscreteWholeItem`s only — but a prior decision explicitly reuses this class for composite meals (`PreparedDish` members). The class's own stated definition was never actually widened to match. This surfaced only by trying to instantiate the composite plate concretely.
- **No cost ceiling** — `PriceObservation`/`AcquisitionList` exist; nothing checks a total against a budget.
- **No entity groups a set of `MealPlanEntry`s as one unit** — nothing represents "Saturday's dinner party," or a week's plan, as a whole, despite the original problem being framed exactly as "a weekly meal plan."
- **Per-serving customization has no home** — one vegetarian guest wanting tofu instead of chicken in one serving isn't expressible; `SubstitutionRule` operates at the whole-recipe level.

### Consolidation / overlap tensions

1. **Instantiation Pattern's default set has grown to 8 named properties, 4 structural shapes.** Four (`_quality`, `_mass_per_unit`, `_purchase_quantity`, `_edible_fraction`) are identical in shape, differentiated only by *what* they default. This is the same tension that justified rejecting generic key:value earlier in the project — worth deciding whether 8 is still an acceptable number of named instances of one pattern, or the point to reconsider.
2. **The same tension is reappearing at the Target level.** `NutritionTarget` exists; proposed `BudgetTarget`/`TimeConstraint` would be structurally identical to it. Building more instances of this shape before resolving (1) compounds the same open question rather than settling it.
3. **`PortionedLeftover` may be fully redundant with `PreparedDish`** now that "reserved for a later meal" is a Role rather than a subclass distinction — no remaining structural difference has been found. High-confidence collapse candidate.
4. **`Role` implements the identical pattern three times** (inventory allocation, equipment scheduling, leftover reservation), explained three separate times rather than named once. Not broken — worth tidying.

### Suggestions, unranked beyond what's above

Difficulty/skill modeling; `DietaryRestriction` as a hard filter distinct from soft `SubstitutionRule`; richer `AgentRequirement` preconditions; resolving `Function` one way or the other; a grouping entity above `MealPlanEntry`; open-bounded range Measurements; fixing `DiscreteFoodAggregate`'s stated membership type; a feedback loop from repeated disposal events back into purchase-quantity/StockPolicy defaults (this reconnects the already-deferred periodic-verification-process idea to a concrete use).

---

## 12. Suggested Angles for Review

Start with §11 — it's new and nothing in it has been cross-examined yet. Beyond that: is the Instantiation-Pattern/Target-entity proliferation tension (§11, consolidation #1-2) actually a problem, or is 8+ named instances of one pattern still fine because each is genuinely independently meaningful? Is the `PortionedLeftover`/`PreparedDish` collapse (§11, #3) actually clean, or does dropping the subclass lose something not yet noticed? Does `DiscreteWholeItem`-vs-`PreparedDish` aggregation (the found inconsistency) have further knock-on effects elsewhere the fix might expose? Is there a *third* original requirement, beyond difficulty and nutrition, that hasn't yet been checked against the model?

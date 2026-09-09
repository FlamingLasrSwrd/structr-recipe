# Meal Planning Data Model — Design Document (for Adversarial Review)

**Purpose of this document**: this is being handed to another AI reviewer whose task is to critically examine the model below and find gaps, inconsistencies, or unjustified decisions. To make that review efficient, this document includes not just the final model but the reasoning, alternatives considered, and a list of issues already known and either fixed or deliberately deferred — so review effort goes toward genuinely unexamined territory rather than re-deriving ground already covered. Where a decision looks arbitrary, the reasoning section explains why; where something is missing, the deferred-issues section says so plainly rather than leaving it to be "discovered."

---

## 1. Problem Statement

The goal is a personal tool that generates a weekly meal plan satisfying several simultaneous constraints:
- difficulty ceiling (matching the cook's skill level)
- nutrient targets (daily/weekly, macro and/or micro)
- required meal-type coverage (breakfast/lunch/dinner/snack composition)
- time budgets (active vs. total, per meal and per day)
- awareness of current pantry/fridge inventory, including expiration
- minimization of ingredient waste (overlap/efficiency across the week's recipes)

A survey of existing consumer apps (KitchenPal, Cooklist, Eat This Much, PlateJoy, FoodiePrep, etc.) found each solves 2–3 of these well but none combines all of them, particularly the ingredient-use-efficiency goal, which is closer to a constraint-satisfaction/optimization problem than a recipe-lookup problem. This motivated a custom build.

**This document concerns only the data model** — the entities, classes, and relations the tool operates over — deliberately independent of implementation technology (database engine, language, framework). The optimizer/algorithm and the technology stack are separate concerns handled elsewhere; nothing here should be read as assuming or requiring a particular implementation.

---

## 2. Methodology

Rather than inventing an ad hoc schema, the model is grounded in existing formalisms, each chosen for a specific job:

| Standard | Role |
|---|---|
| **BFO** (Basic Formal Ontology) | upper-level category structure: continuant/occurrent, object/quality/role/disposition |
| **IAO** / **CCO** (Information Artifact / Common Core Ontologies) | information content entities — plans, vocabulary, measurements, as distinct from physical things |
| **RO** (OBO Relation Ontology) | standardized relations, including the agent/input/output participation pattern |
| **PROV-O** | provenance and execution — the distinction between a plan and its actual execution |
| **P-Plan** | ordered plan-step structure (extends PROV-O) |
| **SKOS** | controlled vocabulary — hierarchy and cross-vocabulary alignment |
| **OWL-Time** | temporal intervals, durations, ordering |
| **QUDT** / **UCUM** | quantities, units, and unit conversion |

Rationale: reusing established formalisms (a) provides rigor that's already been stress-tested by other domains, (b) enables real interoperability with existing food/nutrition data sources (FoodOn, USDA FoodData Central, USDA FoodKeeper), and (c) reduces the risk of building bespoke structures that don't compose with each other, since these standards were themselves designed to compose (RO and PROV-O both build on BFO; P-Plan extends PROV-O; SKOS is independent but designed to interoperate).

**Process**: the model was built breadth-first — a general class hierarchy first, checked for consistency against the standards above, then repeatedly stress-tested against concrete scenarios (a full home-kitchen walkthrough: shopping, meal planning, cooking, cleaning, leftovers, disposal) and against a real, mature comparable product (Grocy, an open-source home-inventory ERP) to surface capability gaps. Several rounds of revision followed from that testing; §8 documents the more significant ones, including at least one outright reversal.

---

## 3. Class Hierarchy

```
Entity
│
├── Continuant
│   │
│   ├── Independent Continuant
│   │   ├── Material Entity
│   │   │   ├── Object
│   │   │   │   ├── FoodObject
│   │   │   │   │   ├── DiscreteWholeItem      single naturally-bounded item
│   │   │   │   │   ├── PortionOfSubstance     separable measured quantity of a substance
│   │   │   │   │   ├── PackagedProduct        product-as-purchased; one instance per lot/batch
│   │   │   │   │   ├── PreparedDish           single-mass cooking output
│   │   │   │   │   └── PortionedLeftover      dish portion, physically separated
│   │   │   │   └── EquipmentObject
│   │   │   │       ├── Cookware
│   │   │   │       ├── Utensil
│   │   │   │       └── Appliance
│   │   │   ├── Object Aggregate
│   │   │   │   ├── DiscreteFoodAggregate      e.g. a dozen eggs, a tray of cookies
│   │   │   │   └── UtensilSet
│   │   │   └── Fiat Object Part                [deferred — see §9]
│   │   └── Immaterial Entity                    [out of scope — see §9]
│   │
│   ├── Specifically Dependent Continuant
│   │   ├── Quality                              density, mass, volume, cleanliness, color,
│   │   │                                         quantity-on-hand, opened_status
│   │   └── Realizable Entity
│   │       ├── Role                             inventory allocation; equipment scheduling
│   │       └── Disposition
│   │           ├── (shelf-life / spoilage propensity)
│   │           └── Function                     e.g. a knife's cutting function
│   │
│   └── Generically Dependent Continuant
│       └── Information Content Entity            (CCO refinement of IAO)
│           ├── Directive ICE
│           │   ├── Plan                          Recipe; ordered Steps (P-Plan)
│           │   ├── Instantiation Pattern         class-level defaults for new instances
│           │   ├── MealPlanEntry                 "cook this Plan at this time"
│           │   ├── StockPolicy                   "keep at least X on hand"
│           │   └── AcquisitionList                derived "what to buy" prescription
│           ├── Designative ICE                   vocabulary Concepts, in ConceptSchemes (facets)
│           └── Descriptive ICE
│               ├── Measurement                   value/range + unit; may be "unconvertible"
│               └── PriceObservation
│
└── Occurrent
    ├── Process                                   cooking, cleaning, opening, disposal,
    │                                             stock reconciliation
    ├── Process Boundary                           [placeholder — unused]
    └── Temporal Region                            OWL-Time Instant/Interval
```

**Placement rationale (Object / Object Aggregate / Fiat Object Part)**: an Object is a single, causally-unified whole; an Object Aggregate is a collection of independently-existing Objects treated together; a Fiat Object Part is a part of an Object demarcated by a non-physical boundary, prior to actual separation. Packaging (a bag, jar, carton) is treated as providing the physical unity for `PackagedProduct` — i.e. the package is the Object, and what it contains (whether a continuous substance or several discrete items) is secondary. Bulk/granular substances (flour, sugar, rice) are deliberately treated as `PortionOfSubstance` — a single measured "portion," not an aggregate of individual grains — purely for practicality; this is a judgment call, not a settled ontological fact (see §8, item 3).

---

## 4. Facets (Controlled Vocabulary Schemes)

**Why facets, not one vocabulary tree**: a single subsumption hierarchy encodes one specific notion of "more general than." Different lookup purposes have different, equally legitimate notions of similarity that frequently disagree — e.g. density-defaulting wants compositional similarity (flour generalizes to flour), while ingredient substitutability wants culinary-functional similarity (butter and margarine are close despite different composition). This is a known problem in classification theory (Ranganathan's faceted classification theory, developed for exactly this reason), and it isn't unique to this project — FoodOn itself, the real BFO-based food ontology referenced throughout, is organized into facets (organism parts, processing methods, quality attributes) for the same reason. The fix is not a bigger single hierarchy; it's a small number of independent, purpose-specific hierarchies (facets), each consulted by name by whichever mechanism needs it, cross-linked by an associative (non-hierarchical) relation where a term participates in more than one.

| Facet | Organizing principle | Drives | Lookup-constrained? |
|---|---|---|---|
| **Food Identity** | what the food specifically is | density, mass-per-unit, purchase-quantity defaults; primary Object tag; barcode via leaf Concepts; external `exactMatch` anchor | yes |
| **Perishability Class** | spoilage/storage behavior | shelf-life Disposition defaults (table keyed by Storage Condition × opened_status) | yes |
| **Storage Condition** | pantry / fridge / freezer | second key into the shelf-life table | yes (small, flat) |
| **Culinary Role** | function within a recipe | substitutability scoring | yes |
| **Biological Origin** | taxonomic/biological source | allergen/dietary filtering | yes |
| **Equipment Type** | what a tool is | cleaning-time default; Step precondition matching | yes |
| **Equipment Material** | what a tool is made of | modifies cleaning-time; compatible-technique constraints | yes |
| **Heat Method** | dry/wet/fat-based/no-heat | default Step duration | yes |
| **Units** | quantity kind | Measurement's unit reference; wraps QUDT/UCUM | n/a |
| Cuisine, Meal Type | browsing categories | search/filter only | no |

"Lookup-constrained" facets use single-parent `broader` (a strict tree) — required so that "nearest applicable default" is unambiguous; SKOS itself permits multiple parents, but this model deliberately restricts to a subset of what SKOS allows for facets where an unambiguous walk matters. Browsing-only facets are unconstrained.

An Object's primary tag lives in one facet (typically Food Identity or Equipment Type); it reaches other relevant facets via `skos:related`, an associative cross-link — not by being independently classified in every scheme. Food Identity can hold leaf-level Concepts for specific branded/packaged products (barcode-bearing, `broader` the generic ingredient) alongside the generic terms; aggregating across brands is a rollup query over the same tree, walked downward instead of upward — deliberately not a separate variant/parent-product relation (see §8, item 12).

---

## 5. Core Entities

| Entity | Key attributes | Notes |
|---|---|---|
| **DiscreteWholeItem** | tagged Food-Identity Concept; mass Quality | one egg, one onion |
| **PortionOfSubstance** | tagged Food-Identity Concept; mass/volume/density Qualities | one purchased lot's contents |
| **PackagedProduct** | tagged Food-Identity Concept; quantity, purchase date, expiration, `opened_status`, Storage-Condition tag | **one instance per purchase/lot** — never merged across purchases |
| **DiscreteFoodAggregate** | `hadMember` → constituent DiscreteWholeItems | identity-over-time not modeled; quantity lives on the containing PackagedProduct |
| **EquipmentObject** | Equipment-Type + Equipment-Material tags; cleanliness Quality, a Function, and (when scheduled) a Role | three simultaneous, independent states on one instance |
| **Plan (Recipe)** | ordered Steps (`isPreceededBy`); each Step has `has_agent`/`has_input`/`has_output` | Directive ICE |
| **Step** | precondition, effect, Heat-Method reference | inside a Plan |
| **Instantiation Pattern** | `applies_within` a facet; up to one default type (see §7) | attached to a Concept, consulted at instance-creation time |
| **MealPlanEntry** | Plan reference; `scheduledFor` a Temporal Region; `fulfilledBy` a Process once cooked | a prescription, not yet an occurrence |
| **StockPolicy** | `applies_to` a Food-Identity Concept; `has_minimum_level` | standing par-level, independent of any Plan |
| **AcquisitionList** | derived: recipe-driven demand + unmet StockPolicies, minus on-hand quantities | MRP-style netting; computed, not hand-maintained |
| **Measurement** | `is_about` a Quality/Disposition; single value or range; unit; may be `unconvertible` | full-rigor layer, decoupled from the Quality itself |
| **PriceObservation** | store, product-type, date, Measurement | outside the Object hierarchy — price is a transaction fact, not a property of a thing |
| **Process** | `hadPlan`; `correspondsToStep`; IOA-triad relations; `preceded_by` other Processes; occupies a Temporal Region | stock reconciliation is a distinct subtype needing none of these |

---

## 6. Relations

| Relation | Source | Domain → Range |
|---|---|---|
| `part_of` / `has_part` | BFO/RO | Independent Continuant ↔ same |
| `has_participant` / `participates_in` | RO | Process → Independent Continuant |
| `has_agent` / `has_input` / `has_output` | RO (IOA triad) | Process → Independent Continuant |
| `inheres_in` / `bearer_of` | BFO | Quality/Role/Disposition/Function ↔ Independent Continuant |
| `realizes` / `realized_in` | BFO | Role or Disposition ↔ Process |
| `isPreceededBy` | P-Plan | Step ↔ Step (within a Plan) |
| `preceded_by` / `precedes` | RO | Process ↔ Process (actual, executed order) |
| `correspondsToStep` | bespoke | Process → Step |
| `hadPlan` | PROV-O | Process → Plan |
| `used` / `wasGeneratedBy` / `wasDerivedFrom` | PROV-O | Process ↔ Continuant |
| `scheduledFor` | bespoke | MealPlanEntry → Temporal Region |
| `fulfilledBy` | bespoke | MealPlanEntry → Process |
| `applies_to` | bespoke | StockPolicy → Food-Identity Concept |
| `has_minimum_level` | bespoke | StockPolicy → Measurement |
| `wasRevisionOf` | PROV-O | Measurement (corrected) → Measurement (prior) — reconciliation only |
| `inScheme` | SKOS | Concept → ConceptScheme |
| `broader` / `narrower` | SKOS | Concept → Concept (single-parent, in lookup-bearing facets) |
| `related` | SKOS | Concept ↔ Concept (cross-facet) |
| `exactMatch` / `closeMatch` | SKOS | Concept ↔ Concept, **different schemes only** |
| `substitutableFor` | bespoke, graded | Concept ↔ Concept, same scheme (Culinary Role) |
| `notation` | SKOS | Concept → literal (UCUM code, or barcode/GTIN on a leaf Concept) |
| `applies_within` | bespoke | Instantiation Pattern → ConceptScheme |
| `has_default_quality` / `_duration` / `_mass_per_unit` / `_purchase_quantity` | bespoke | Instantiation Pattern → Measurement/Duration |
| `has_default_disposition` | bespoke | Instantiation Pattern → table of (Storage Condition, opened_status) → Measurement |
| `has_default_yield` | bespoke | Instantiation Pattern → (target Concept, Measurement) |
| `is_about` | IAO | Measurement → Quality/Disposition |
| conversion factor | QUDT | Measurement ↔ Measurement, same quantity kind |
| `hasBeginning`/`hasEnd`/`hasDuration`, `before`/`after`/`during`/`overlaps` | OWL-Time | Occurrent/Temporal Region ↔ same |

---

## 7. The Instantiation Pattern mechanism

**Problem it solves**: avoiding class explosion (e.g. not needing separate classes for red vs. white onion) while still giving new instances sensible defaults (density, shelf-life, etc.) derived from how they're classified.

**Rejected alternatives**:
- *Generic key:value pairs on a single class* — rejected because it discards the type-checking a proper ontology is meant to provide (nothing would stop "density" being attached to a Role, or holding a non-Measurement value), and because RDF/OWL already provides generic key:value at the triple level — a wrapper class for it is redundant.
- *A dedicated pattern subclass per BFO category* (`DefaultQualityPattern`, `DefaultDispositionPattern`, ...) — rejected because it reproduces the exact class-explosion problem this mechanism exists to avoid, one abstraction level up.
- *Adopted*: one `Instantiation Pattern` class with a small, closed, named set of typed properties (`has_default_quality`, `_disposition`, `_duration`, `_mass_per_unit`, `_yield`, `_purchase_quantity`), only as many as concrete need has demonstrated.

**Algorithm**:
1. Start at the instance's tagged Concept in the relevant facet (one `related` hop first if the default lives in a different facet).
2. Check for the needed property; if absent, walk `broader` (single-parent, unambiguous) and repeat.
3. Reaching the scheme root with nothing found → explicitly **undefined/unconvertible**, never guessed.
4. A directly-measured Measurement on the instance always overrides an inherited default — this is routine, expected configuration (e.g. per-product unit-conversion factors), not a rare correction path.
5. `has_default_disposition` is two-dimensional (Storage Condition × opened_status), not a single value; effective expiration once opened is `min(original_expiration, open_date + post_open_duration)`.
6. `has_default_yield` lands on a *different* target Concept than the one queried (juicing a lemon yields lemon juice, a distinct Concept).
7. A resolved Measurement may itself be range-valued (a "pinch") — a valid final answer, not an intermediate state.
8. Stock reconciliation is the sole use of `wasRevisionOf`: a correction with no required cause.
9. Cross-brand/variant aggregation walks `broader`/`narrower` *downward* from a shared ancestor — the same tree, opposite direction, no separate relation.

---

## 8. Key Design Decisions and Reasoning

This section exists specifically to give a reviewer the "why," including paths not taken, so objections already considered aren't re-raised without new grounds.

1. **BFO as upper ontology**, rather than an ad hoc schema — chosen because a real, actively-maintained food ontology (FoodOn) is already built on it, meaning terms and structure can potentially interoperate with real external data rather than being invented in isolation.

2. **Quality vs. Role vs. Disposition vs. Function are kept as genuinely distinct**, not collapsed into one generic "attribute" concept, because they behave differently: a Quality (density, cleanliness) is always present and changes via a physical Process; a Role (inventory allocation) is extrinsic, revocable, and doesn't reflect the bearer's physical structure; a Disposition (shelf-life) is grounded in physical/chemical makeup and is *realized* rather than always active; a Function (a knife's cutting capability) is a Disposition present by virtue of what the thing is, not by current use. Concretely: "diced" is a Quality change (the object's physical structure actually changed), not a Role — this was an explicit correction made mid-conversation when a Role-based framing was initially proposed for the same case.

3. **Bulk/granular substances treated as `PortionOfSubstance`, not an aggregate of grains** — a pragmatic simplification, explicitly flagged as a judgment call rather than a resolved question (real mereology would treat a pile of rice as an aggregate of discrete, non-fused grains, unlike a genuinely continuous liquid).

4. **Controlled vocabulary + Quality, not subclassing, for variant distinctions** (red vs. white onion) — avoids combinatorial class explosion; the vocabulary itself decides which distinctions matter enough to need their own term versus being left as an unmodeled Quality value.

5. **Faceted classification instead of one vocabulary tree** — see §4's reasoning. Directly motivated by a concrete conflict: the same single tree could not simultaneously serve density-defaulting (wants compositional similarity) and substitutability scoring (wants culinary-functional similarity) without one purpose degrading the other.

6. **Single-parent constraint on lookup-bearing facets only** — full SKOS permits multiple `broader` parents; this model restricts that for facets used in default-lookup specifically because "nearest wins" requires an unambiguous distance, which multiple parents (or ties) would break. Facets used only for browsing are left unconstrained, since nothing there depends on unambiguous distance.

7. **Substitutability is a bespoke relation, not SKOS `exactMatch`/`closeMatch`** — SKOS's own reference specification states its mapping properties are conventionally used only across different concept schemes, and their formal semantics (symmetric equivalence) are stronger than "usable substitute in most, not all, contexts." Reusing them would misrepresent both the convention and the semantics if the data were ever consumed by a SKOS-aware tool.

8. **Full-rigor Measurement, separate from the Quality it describes**, adopted specifically because automatic unit conversion was stated as an important requirement — a single flattened numeric-plus-unit field would not support cleanly distinguishing a directly-measured value from an inherited default, nor would it support range-valued or explicitly-unconvertible results.

9. **QUDT for conversion math, UCUM for compact notation, both wrapped as vocabulary Concepts** — rather than treating units as an ad hoc string field, units get the same controlled-vocabulary treatment as everything else, letting `notation` (a SKOS property) hold the UCUM code and `exactMatch` anchor to the QUDT URI.

10. **Object Aggregate identity-over-time — an explicit reversal worth reading in full.** Initial handling of "12 eggs, cook 3" reached for PROV-O's `Collection`/`hadMember`/`wasRevisionOf`/`specializationOf` machinery, treating each change in membership as a new immutable "collection state." This was later shown to be solving the wrong problem: the actually-common case (a second jar of paprika bought before the first is empty) doesn't need collection-identity tracking at all — it's simply two independent `PackagedProduct` instances existing concurrently, each with its own quantity Quality. The fix: **every purchased unit is its own persistent instance from creation** (batch/lot granularity), and "how much do I have" is a query (sum across instances), not a stored, identity-tracked entity. The PROV revision machinery was retired for this use — but *not* discarded entirely: it resurfaced later, correctly, for stock-reconciliation (a corrected Measurement value genuinely is a revision of a prior one). **This is flagged explicitly because it's exactly the kind of thing a reviewer should stress-test further** — it's plausible the simplification is still hiding an edge case (e.g., tracking which specific batch went into which specific meal, for a recall or contamination scenario) that hasn't been exercised yet.

11. **`opened_status` as a Quality plus a two-key shelf-life table**, rather than a single shelf-life value — motivated directly by the concrete counterexample that unopened milk lasts substantially longer than opened milk, and storage condition (fridge/freezer) compounds with that independently. Storage condition itself was deliberately kept as a *static* tag rather than modeled as a further state-transition (freezing/thawing as their own Processes) — a real capability gap relative to Grocy (which tracks four separate shelf-life countdowns: normal, post-open, post-freeze, post-thaw) that was consciously accepted rather than closed, on the reasoning that the added rigor wasn't judged worth the complexity at this stage. A reviewer may reasonably disagree with that judgment call.

12. **Multi-brand/variant stock aggregation via `broader`/`narrower` rollup, not a dedicated variant/parent-product relation** — a relation for this was initially proposed (mirroring Grocy's explicit `parent_product_id`), then retracted on the observation that it would duplicate the classification tree already in the model. Aggregation is instead a downward walk of the same single-parent tree used upward for defaults.

13. **Barcodes handled by reusing `notation` on leaf-level Food-Identity Concepts**, rather than introducing a separate "Product" entity layer between the generic ingredient and the physical instance (which is how Grocy itself is structured) — chosen to avoid adding a new class tier when the existing tree, extended one level deeper (a specific branded/packaged product as a leaf `broader` the generic ingredient), already provides the needed specificity.

14. **Stock reconciliation as a Process requiring no cause** — added after the observation that real inventory loss is often spontaneous or a miscount, not traceable to any modeled event (consumption, spoilage, disposal). Modeled via `wasRevisionOf` on the Measurement, deliberately not via the IOA-triad relations that assume an identifiable input/output/cause.

15. **Standing minimum-stock levels (`StockPolicy`) as a Directive ICE, separate from recipe-driven `AcquisitionList` demand** — added because the shopping-list logic, as originally scoped, only responded to active meal plans and had no way to represent "always keep at least 2 lb of flour on hand" independent of whether anything is currently planned to use it.

16. **Deliberately excluded**: Person/Agent (no multi-user modeling), Fiat Object Part and Immaterial Entity as populated branches, a periodic default-verification process, formal DL reasoning, and — notably — user-definable arbitrary custom fields/entities (a real, prominent feature of comparable real-world tools). The last is excluded on principle, not oversight: generic, untyped extensibility was evaluated and rejected earlier (see item 4's reasoning, and the Instantiation Pattern rejection of key:value pairs) as fundamentally in tension with the model's typed, closed-set design philosophy.

---

## 9. Known Limitations / Deferred (not yet resolved, flagged rather than hidden)

- **Fiat Object Part branch is empty.** Chopping/cutting a `DiscreteWholeItem` physically produces multiple new, separate Objects under strict BFO mereology (a cut piece is no longer part of one causally-unified whole). The model currently papers over this by treating prep-state (raw/diced/cooked) as a Quality change on one enduring Object — workable for a home-cooking tool's purposes, but not a genuine resolution of the underlying branch.
- **No modeling of economies of scale in equipment cleaning** — cleaning several items in one session very likely costs less time than the sum of each item's individual default cleaning duration, and the model has no session-level construct to capture that.
- **Perishability Class facet has no "cooked/prepared" category** distinct from raw-ingredient categories — a `PortionedLeftover`'s shelf-life doesn't sensibly inherit from what it was made of, and currently has nowhere better to draw a default from.
- **Freezing/thawing are not modeled as state-transition Processes** (see item 11 above) — storage condition is a static tag by deliberate choice, not oversight, but this is a real, named simplification relative to a comparable real product.
- **Periodic default-verification process** (aggregate-review-driven correction of Instantiation Pattern defaults) is named in the algorithm but not designed in detail.
- **No reasoner is assumed.** The model is expressed in OWL-adjacent terms throughout, but formal DL consistency-checking has not been run or verified against it — internal contradictions may exist that a reasoner would catch and this document's authors have not.
- **User-definable custom fields are out of scope by design** (see item 16) — flagged again here because it is a substantive capability gap relative to comparable tools, accepted deliberately rather than accidentally.

---

## 10. Suggested angles for review

Offered as a starting point, not a constraint on scope — anything else found is equally in-bounds:

- Does the Instantiation Pattern's closed set of default types actually cover everything the rest of the model implies it needs, or are there more lurking?
- Does the dual-purpose use of `broader`/`narrower` (upward for defaults, downward for aggregation) have failure modes when a facet's tree shape is optimized for one direction and not the other?
- Is treating prep-state as a Quality (rather than confronting Fiat Object Part) actually defensible under BFO's own semantics, or does it quietly misuse the Quality category?
- Is there a case the batch/lot-instantiation simplification (item 10 above) doesn't actually cover, particularly around tracing a specific batch through to a specific consumption event?
- Are the seven facets actually sufficient, or does the model's own logic imply others that haven't been named yet?

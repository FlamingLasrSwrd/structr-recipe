# BFO 2020 — Class and Relation Reference, with Model Mapping

Compiled from BFO 2020 (ISO/IEC 21838-2), the BFO-2020 OWL release, IAO, CCO, and RO. Domains and ranges are as BFO/IAO actually declare them. §3 maps the meal-planner model onto this and records where the two disagree.

---

## 1. Classes

### 1.1 Continuant
Persists through time, exists wholly at every moment it exists.

| Class | Elucidation | Examples | Meal-planner use |
|---|---|---|---|
| **Entity** | The root. Everything. | anything | root |
| **Continuant** | Persists, exists wholly at each moment, may change | a bag of flour, a knife, a recipe | everything except Process/Temporal Region |
| **Independent Continuant** | Does not depend on another entity for existence | an apple, a pan | FoodObject, EquipmentObject, ContainerObject |
| **Material Entity** | An independent continuant with matter | flour, an oven | all physical things |
| **Object** | Maximally self-connected, causally unified whole | one egg, one knife, a pot of soup | DiscreteWholeItem, PortionOfSubstance, ContainerObject, EquipmentObject |
| **Object Aggregate** | A collection of objects, each independently self-connected | a dozen eggs, a flock of birds | DiscreteFoodAggregate, UtensilSet |
| **Fiat Object Part** | A part demarcated by a non-physical boundary | the northern half of a state; a drumstick on an intact chicken | *deferred, empty* |
| **Immaterial Entity** | Independent continuant without matter | a cave, the hold of a ship | *out of scope* |
| **Site** | An immaterial entity that is a three-dimensional hole/cavity | Piazza San Marco; the interior of a fridge | *out of scope — location is free text* |
| **Continuant Fiat Boundary** | 0-, 1-, or 2-dimensional non-physical boundary | the Geographic North Pole; a national border | *unused* |
| **Spatial Region** | Pure space | a cubic metre of space | *unused* |

### 1.2 Specifically Dependent Continuant (SDC)
Cannot exist without one **specific** bearer. If the bearer goes, it goes.

| Class | Elucidation | Examples | Meal-planner use |
|---|---|---|---|
| **Specifically Dependent Continuant** | Depends on a specific independent continuant | the mass of the Eiffel Tower | Quality + Realizable |
| **Quality** | A characteristic fully exhibited whenever it exists — always "on" | the mass of a portion of flour; the colour of an apple; cleanliness of a pan | density, mass, volume, cleanliness, opened_status |
| **Relational Quality** | A quality depending on two or more bearers | a marriage; a debt | *unused* |
| **Realizable Entity** | A characteristic manifested only in certain processes | fragility; a doctor's role | Role, Disposition, Function |
| **Role** | Realizable, **externally grounded**, optional, changes nothing physical about the bearer | being a doctor; being reserved for Wednesday's lunch | inventory allocation, equipment scheduling, leftover reservation |
| **Disposition** | Realizable, **internally grounded** in the bearer's physical makeup | the fragility of a glass; the spoilage propensity of milk | shelf-life |
| **Function** | A disposition the bearer exists *in order to* realize | a knife's cutting function; a heart's pumping function | equipment capability |

### 1.3 Generically Dependent Continuant (GDC)
Copiable content or pattern — exists in virtue of there being at least one of possibly many copies.

| Class | Elucidation | Examples | Meal-planner use |
|---|---|---|---|
| **Generically Dependent Continuant** | The content/pattern multiple copies share | a PDF file and its copy; a protein sequence; the content of a sentence; an engineering blueprint | all ICEs |
| **Information Content Entity (IAO)** | A GDC that is *about* something | a document, a database record, a measurement datum | Plan, Specification, Measurement, Concept, Identifier |
| **Directive ICE (CCO)** | An ICE that prescribes action | a recipe, a protocol, an order | Plan, Specification, MealPlan, StockPolicy |
| **Designative ICE (CCO)** | An ICE that denotes or classifies | a name, an identifier, a taxonomy term | Concept, Identifier |
| **Descriptive ICE (CCO)** | An ICE describing a quality or state | a measurement result, a price record | Measurement, Allocation, PriceObservation |

> **Hard BFO constraint:** *"It is impossible for generically dependent continuants to be the bearer of realizable entities."* No Roles, Dispositions, or Functions may inhere in a Plan, a Concept, a Measurement, or any other ICE.

### 1.4 Occurrent
Unfolds in time; has temporal parts.

| Class | Elucidation | Examples | Meal-planner use |
|---|---|---|---|
| **Occurrent** | Happens rather than persists | a game, a cooking session | Process, Temporal Region |
| **Process** | A continuous activity with temporal parts, depending on at least one material participant | roasting a chicken; washing a pan | cooking, cleaning, opening, portioning, disposal, purchase, reconciliation |
| **Process Boundary** | Instantaneous temporal boundary of a process | the moment the oven reached 200°C | *placeholder, empty* |
| **Temporal Region** | Pure time | the year 2026; 4:00–6:00 PM Saturday | scheduling |
| **Zero-dimensional Temporal Region** | An instant | midnight | timestamps |
| **One-dimensional Temporal Region** | An interval | Saturday afternoon | Process extents |
| **Spatiotemporal Region** | Space-time | the region occupied by a game | *unused* |
| **History** | The totality of processes a material entity participates in | the history of this pan | *unused; potentially relevant* |

---

## 2. Relations, with declared domain and range

### 2.1 Dependence and inherence

| Relation | Domain | Range | Notes and examples |
|---|---|---|---|
| `specifically depends on` | SDC | Independent Continuant | the parent relation of `inheres in` |
| `inheres in` | **Specifically Dependent Continuant** | **Independent Continuant** (not a spatial region) | *the mass of this flour inheres in this flour.* Sub-property of `specifically depends on` |
| `bearer of` | Independent Continuant | SDC | inverse of `inheres in` |
| `generically depends on` | **GDC** | **Independent Continuant** | *this PDF's content generically depends on some disk* |
| `concretizes` | **SDC or Process** | **GDC** | *"The sum of patterns of ink on the pages of this copy of War and Peace concretizes the novel written by Tolstoy."* Note the **Process** in the domain — an execution can concretize a plan |
| `is concretized by` | GDC | Process **or** SDC | inverse |

### 2.2 Parthood, membership, location

| Relation | Domain | Range | Notes |
|---|---|---|---|
| `continuant part of` / `has continuant part` | Continuant | Continuant | temporalized in BFO 2020 as `_at_some_time` / `_at_all_times`; only the at-all-times form is transitive |
| `member part of` / `has member part` | Object | Object Aggregate | **BFO-native membership** — the correct relation for a dozen eggs |
| `occurrent part of` / `has occurrent part` | Occurrent | Occurrent | a sub-process of a cooking session |
| `located in` | Independent Continuant | Independent Continuant | **containment, not parthood** — flour in a bag is *located in* it, not *part of* it |

### 2.3 Participation and realization

| Relation | Domain | Range | Notes |
|---|---|---|---|
| `participates in` | IC, SDC, or GDC (not spatial region) | **Process** | |
| `has participant` | **Process** | IC, SDC, or GDC | inverse |
| `realizes` | **Process** | **Realizable Entity** | *the washing realizes the pan's cleanability* |
| `realized in` | Realizable Entity | Process | inverse |
| *(axiom)* | | | `realizes ∘ inheres in ⊑ has participant` — "bearers of realizables participate in their realization" |
| `occupies temporal region` | Process | Temporal Region | |
| `begins to exist during` / `ceases to exist during` | Continuant | Process | *this leftover began to exist during the portioning* |
| `precedes` / `preceded by` | Occurrent | Occurrent | actual temporal order |

### 2.4 Aboutness (IAO / CCO)

| Relation | Domain | Range | Notes |
|---|---|---|---|
| `is about` | **Information Content Entity** | **Entity** (unrestricted) | the single most-specialized relation in ICE modeling; NFDIcore and others routinely declare **subproperties of `is about`** for domain-specific aboutness |
| `denotes` (CCO) | Designative ICE | Entity | naming/identifying flavour of aboutness |
| `prescribed by` (CCO) | Process or Entity | Directive ICE | the published fix for relating an execution to the plan it followed, including **failed** executions |

### 2.5 RO participation refinements

| Relation | Domain | Range | Notes |
|---|---|---|---|
| `has agent` | Process | Material Entity | the entity **causally responsible** for the process occurring — canonically an organism or agent |
| `has input` | Process | Continuant | consumed |
| `has output` | Process | Continuant | produced |

---

## 3. Mapping the meal-planner model onto this — agreements and disagreements

### 3.1 Confirmed correct

| Model relation | BFO/IAO counterpart | Status |
|---|---|---|
| `inheres_in` / `bearer_of` (Quality → Object) | identical | ✅ |
| `realizes` / `realized_in` (Process ↔ Role) | identical | ✅ |
| `has_participant` (Process → Material Entity) | identical | ✅ |
| `occupies` a Temporal Region | identical | ✅ |
| Object / Object Aggregate placement | identical | ✅ |
| Quality vs Role vs Disposition vs Function distinctions | identical | ✅ |
| ICE as GDC; Directive/Designative/Descriptive split | IAO + CCO | ✅ |

### 3.2 Errors found — see the walkthrough notes for each

| # | Model relation | Declared range | Problem |
|---|---|---|---|
| E1 | `ContainerObject has_part contents` | Material Entity | **Wrong relation.** Flour is *located in* a bag, not a continuant part of it. BFO has `located in` for exactly this |
| E2 | `hadMember` (DiscreteFoodAggregate → items) | PROV-O relation | BFO already has **`has member part`**, domain Object Aggregate. Importing PROV here is unnecessary |
| E3 | `hadPlan` (Process → Plan) | PROV-O relation | BFO's **`concretizes`** already covers this — its domain explicitly includes Process, range GDC. Same relation, imported twice |
| E4 | `has_agent` (Process → EquipmentObject) | Material Entity | **Misuse.** RO's `has_agent` means the entity causally responsible. An oven is an *instrument*, not an agent. With Person out of scope, the model has no agents at all |
| E5 | `is_about` (Measurement → Quality) + invariant #2 | "exactly one Quality/Disposition" | **False for `specified`-status Measurements.** A required 500 g is about no existing Quality — nothing has that mass yet |
| E6 | `NutrientContent` (a Quality) with a per-100g Measurement | Quality | **Category conflation.** "Protein per 100 g" is type-level reference data (an ICE); "this 383 g portion holds 84 g protein" is an instance Quality. One class does both |
| E7 | `quantity` and `mass` as separate Qualities on `PortionOfSubstance` | Quality | For a bulk portion these are the **same Quality** under two names |
| E8 | Equipment Function *facet Concept* + a BFO **Function** inhering | Concept / Realizable | **Same fact, two representations**, introduced in Rev. 3 |
| E9 | "tagged with a Food-Identity Concept" | — | **Relation never named anywhere in the model.** Used constantly, defined nowhere |
| E10 | `has_participation_role` ∈ {input, output, agent} | literal enum | Name invites confusion with BFO **Role**; if ever read as one, it would put a realizable on a GDC — which BFO forbids outright |

### 3.3 The large overlap: fourteen relations are all `is about`

Walking every ICE in the model and asking "what does this point at, and why," the answer is the same fourteen times:

| Model relation | Domain (all ICEs) | Range |
|---|---|---|
| `is_about` | Measurement | Quality |
| `denotes` | Identifier | Entity |
| `entity` | Allocation | Independent Continuant |
| `fulfills` | Allocation | Specification |
| `specifies_concept` | Specification | Concept |
| `for_nutrient` | NutrientContent / NutritionTarget | Concept |
| `applies_to` | StockPolicy | Concept |
| `candidate_concept` | SubstitutionRule | Concept |
| `for_specification` | SubstitutionRule | Specification |
| `for_definition` | ExtensionPropertyValue | ExtensionPropertyDefinition |
| `for_instance` | ExtensionPropertyValue | Entity |
| `has_domain` | ExtensionPropertyDefinition | class or facet |
| `references` | MealPlanEntry | Plan |
| `covers` | MealPlan | Temporal Region |

Every one has an ICE domain and is a claim that the ICE *concerns* its range. That is precisely `iao:is about`, whose range is unrestricted `Entity`. Declaring them as **subproperties of `is about`** is the established practice — NFDIcore does exactly this, introducing subproperties of `iao:is about` to capture more nuanced relationships while keeping the general one queryable.

This does not merge them into one relation. It gives them a common parent, so "everything this Plan concerns" is one query instead of fourteen, while each keeps its own specific meaning and range.

### 3.4 The unnamed relation (E9), and why it is genuinely hard

Every physical instance in the model is "tagged with a Concept," and that relation has no name. Naming it exposes a real ambiguity:

- If a Concept is an **ICE that denotes a type**, then tagging is the inverse of `is about`, and the Concept is about the *universal*, not about each instance.
- If tagging means the instance *instantiates a universal*, that is `rdf:type`, and Concepts are not the right thing to point at, because a SKOS Concept is an information artifact, not a universal.

The model has quietly been using SKOS Concepts to do the work of BFO universals. That works because the lookup algorithms only ever traverse the Concept tree — but it means "AP Flour" is simultaneously playing two roles: a vocabulary term (an ICE) and a class of physical stuff (a universal). Resolving this is deferred, but it should be named rather than left implicit.

### 3.5 Relations correctly ranged but conceptually loose

| Relation | Note |
|---|---|
| `specifies_concept` | A Specification requires *actual flour*, not the concept of flour. The relation is shorthand for "any entity classified by this Concept" — worth stating |
| `scheduledFor` (MealPlanEntry → Temporal Region) | Correct as aboutness: a plan is *about* a time, it does not *occupy* one. Only a Process occupies |
| `correspondsToStep` | Redundant with `concretizes` if E3 is fixed: a Process concretizing a Step-level Plan fragment already says this |

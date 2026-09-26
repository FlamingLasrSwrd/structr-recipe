# Meal Planner — Structr Build Sketch

Maps the Rev. 4.1 data model onto Structr 6.x. Assumes the cheatsheet's verified findings throughout, especially the retroactive-labeling trap, the `sourceJsonName`/`targetJsonName` inversion, and trait-level `unique` being global.

---

## 1. The three layers

The single most important decision, and everything else follows from it:

| Layer | Lives as | Changes at runtime? | Why |
|---|---|---|---|
| **Structural** — BFO categories and the model's own classes | Structr **traits** (`SchemaNode` + `inheritedTraits`) | **No** | Fixed by the model. Never touched after build, so none of the schema-mutation hazards apply. Gets real inheritance and polymorphic targeting |
| **Metamodel** — domain types, vocabulary, relation hierarchy | **Data nodes** with `SUBCLASS_OF` edges | Constantly | `RecipeIdentity.defines_output_type` mints one per recipe; reclassification is routine. As schema, every one of those would be a live schema mutation and would hit the label trap |
| **Instance** — actual portions, processes, measurements | Data nodes | Constantly | ordinary application data |

The label trap is the reason for the split. A node's Neo4j label set is fixed at creation, so a type gaining a trait after instances exist strands them. The structural layer never gains traits after the fact; the metamodel layer never uses traits at all.

---

## 2. Structural traits

`isAbstract: true` unless marked concrete. `Object` is renamed `BfoObject` to avoid collision.

```
Entity
├── Continuant
│   ├── IndependentContinuant
│   │   ├── MaterialEntity
│   │   │   ├── BfoObject
│   │   │   │   ├── FoodObject
│   │   │   │   │   ├── DiscreteWholeItem      ● concrete
│   │   │   │   │   └── PortionOfSubstance     ● concrete
│   │   │   │   ├── ContainerObject            ● concrete
│   │   │   │   └── EquipmentObject            ● concrete
│   │   │   └── ObjectAggregate
│   │   │       ├── FoodAggregate              ● concrete
│   │   │       └── UtensilSet                 ● concrete
│   ├── SpecificallyDependentContinuant
│   │   ├── Quality                            ● concrete  (kind-reified, §3)
│   │   └── RealizableEntity
│   │       ├── Role                           ● concrete  (kind-reified)
│   │       └── Disposition                    ● concrete  (kind-reified)
│   │           └── Function                   ● concrete  (kind-reified)
│   └── GenericallyDependentContinuant
│       └── InformationContentEntity
│           ├── DirectiveICE
│           │   ├── RecipeIdentity             ● concrete
│           │   ├── Plan                       ● concrete
│           │   ├── Step                       ● concrete
│           │   ├── Specification              ● concrete
│           │   ├── QuantitySpecification      ● concrete
│           │   ├── StateRequirement           ● concrete
│           │   ├── SubstitutionRule           ● concrete
│           │   ├── InstantiationPattern       ● concrete
│           │   ├── DefaultSpecification       ● concrete  (kind-reified, §3)
│           │   ├── MealPlan                   ● concrete
│           │   ├── MealPlanEntry              ● concrete
│           │   ├── PlanningConstraint         (abstract trait)
│           │   │   ├── StockPolicy            ● concrete
│           │   │   └── NutritionTarget        ● concrete
│           │   ├── ExtensionPropertyDefinition ● concrete
│           │   └── AcquisitionList            ● concrete
│           ├── DesignativeICE
│           │   ├── Concept                    ● concrete
│           │   └── Identifier                 ● concrete
│           └── DescriptiveICE
│               ├── Measurement                ● concrete
│               ├── NutrientProfile            ● concrete
│               ├── Allocation                 ● concrete
│               ├── PriceObservation           ● concrete
│               └── ExtensionPropertyValue     ● concrete
└── Occurrent
    ├── Process                                ● concrete  (kind-reified)
    └── TemporalRegion                         ● concrete
```

51 types (35 concrete, 16 abstract scaffolding; `mealplanner/structural_types.py` is the canonical list and the source of that count). This is the whole schema and it should never change after build.

**Polymorphic targeting pays for itself here.** `Allocation -[ABOUT]-> Entity` and `Identifier -[DENOTES]-> Entity` are single declarations that accept anything, because every concrete type inherits `Entity`. That is exactly the model's deliberately-unrestricted range, and it works natively — provided every concrete type has its traits from creation, which the no-runtime-schema-change rule guarantees.

---

## 3. Kind reification — the pattern that keeps the schema small

Mass, density, cleanliness, and nutrient-content are **not** separate Structr types. There is one concrete `Quality` type with a `hasKind` relationship to a metamodel `DomainType`. Same for `Role`, `Disposition`, `Function`, and `Process`.

```
Quality  #q1   hasKind → DomainType "Mass"
Quality  #q2   hasKind → DomainType "NutrientContent:Protein"
Process  #p1   hasKind → DomainType "Braising"
Role     #r1   hasKind → DomainType "Reservation"
DefaultSpecification #d1  hasKind → DomainType "Yield"
                          keyedBy → DomainType "Braising"
```

This is the model's own `for_nutrient` pattern applied consistently rather than only to nutrients. It keeps a braising, a roasting, and a dicing as instances of one `Process` type rather than three schema types — which matters because Transformation Methods are user-extensible, and a new one must never require a schema change.

**The counterpart rule — subclass what varies across types.** `PlanningConstraint` is *not* kind-reified: `StockPolicy` and `NutritionTarget` have genuinely different attributes (eligibility filters vs. a time scope), so they are concrete subtypes of an abstract trait. Adding `BudgetConstraint` later creates a new type inheriting an existing trait with no instances yet — the safe schema change, per the cheatsheet. The distinction: **reify what varies within a populated type; subclass what varies across types.**

---

## 4. Metamodel node types (data, not schema)

```
DomainType              a universal, reified as data
  name                  String, unique, indexed
  isLookupBearing       Boolean   — single-parent constraint applies
  ── SUBCLASS_OF ──▶    DomainType        (0..1 per hierarchy; * across hierarchies)
  ── IN_HIERARCHY ──▶   TypeHierarchy

TypeHierarchy           "Food Identity", "Transformation Method", "Perishability", …
  name                  String, unique
  singleParent          Boolean

Concept                 vocabulary term (already a structural type, §2)
  ── DENOTES ──▶        DomainType         (0..1 — a Concept may denote nothing,
                                            e.g. a Cuisine tag)
  prefLabel, altLabels
  ── IN_SCHEME ──▶      ConceptScheme

RelationKind            ★ the relationship hierarchy, stored as data
  name                  String, unique   — matches an actual Structr relationshipType
  ── SUBCLASS_OF ──▶    RelationKind
```

### Why `RelationKind` earns its place

Structr traits are for node types; there is no relationship-type hierarchy, so the model's fourteen `is about` subproperties have no native home. Storing them as data recovers most of the value:

```
IS_ABOUT
├── DENOTES            Identifier → Entity
├── ABOUT              Allocation → Entity
├── FULFILLS           Allocation → Specification
├── SPECIFIES          Specification → Entity
├── FOR_NUTRIENT       NutrientProfile → DomainType
├── APPLIES_TO         StockPolicy → DomainType
├── CANDIDATE_TYPE     SubstitutionRule → DomainType
├── REFERENCES         MealPlanEntry → Plan
├── TARGETS_PROPERTY   StateRequirement → DomainType
└── … (the rest)
```

"Everything this Plan concerns" becomes: read the descendants of `IS_ABOUT` from the `RelationKind` tree, collect their `name` values, then one Cypher match filtered by `type(r) IN $names`. Two queries instead of one, and it is **query construction, not enforcement** — nothing stops a bad edge being written. Worth being clear-eyed that this is a convenience index over the relation vocabulary, not a semantic guarantee.

The same node type is the natural home for anything else the model knows about its own relations: inverse names, which are aboutness vs. mereology vs. participation, which ones are transitive.

---

## 5. Where the algorithms live

Structr `SchemaMethod`s on traits, which per docs run for every inheriting subtype. This is where the model's "compute, don't store" discipline lands:

| Method | On | Does |
|---|---|---|
| `resolveDefault(kind)` | `DomainType` | walk `SUBCLASS_OF*` upward, nearest wins, return the `QuantitySpecification` or nothing |
| `currentMagnitude()` | `Quality` | latest `observed`/`imputed` Measurement minus input Allocations since (§4.1.1 of the model) |
| `physicalOnHand()` / `eligibleOnHand()` | `DomainType` | rollup down `SUBCLASS_OF*`, with the eligibility filter |
| `unaccounted()` | `Process` | actual output minus (input × yield factor) |
| `netRequirements()` | `MealPlan` | the AcquisitionList computation |
| `onCreate` / `onSave` validators | various traits | the 30 domain invariants |

Heterogeneous walks (all Allocations about one bearer across every Process kind; the daily nutrient rollup) want JS mode — `find()`/`each()` work one type at a time, and merging across types needs `${{ }}` with `Structr.find`.

**Implementation note, found building this**: `currentMagnitude()`, `physicalOnHand()`/`eligibleOnHand()`, and the selector/`netRequirements()`-shaped logic ended up as plain Python over REST instead of `SchemaMethod`s as planned above. Same root cause each time: these need multi-hop traversal across several entity types plus real control flow (date comparisons, sums across a filtered collection, per-input branching) — exactly the shape that hit StructrScript's real ceiling building `resolveDefault` itself (no working recursion between `SchemaMethod`s, no infix comparison operators, `filter()`/`each()` don't compose the way you'd expect when nested). `resolveDefault(kind)` and `onCreate`/`onSave` validators stayed in StructrScript successfully — the difference is that those only ever walk *one* relationship chain at a time. Anything that needs to correlate across chains (this Allocation's Process's temporal region vs. that Measurement's time; this Plan's several inputs each resolving their own yield) is better done client-side.

**`resolveDefault` doesn't actually implement its own documented signature** (and this is now resolved in the code that matters). §8 above says a `DefaultSpecification` "resolves independently by its (`hasKind`, `keyedBy`) signature" — but the StructrScript `SchemaMethod` only filters candidates by `hasKind` and never checks `keyedBy`, so a Type carrying `Yield` defaults for two transformations returned whichever the `filter()` found first, and a caller re-checking the key afterwards could not recover the right one. It is also the unrolled depth-6 workaround described above, not an unbounded walk. **Resolution:** every code path now resolves defaults in Python through `mealplanner/defaults.py` (`resolve_default(type, kind, keys)`: nearest Type with an applicable default wins; applicable means all its keys are among the requested keys; the most keys wins, so exact beats partial beats unkeyed; equal specificity is an error), used for yields, shelf lives, densities and mass-per-unit. The `SchemaMethod` remains for the early spike scripts and is kind-only by design; nothing in `mealplanner/` calls it. This follows the same reasoning as the rest of this addendum: multi-hop logic that StructrScript can't express belongs in Python.

---

## 6. Relationship declarations — watch the inversion

Per the cheatsheet, `targetJsonName` becomes the property on the **source** type and `sourceJsonName` becomes the property on the **target**. Written correctly:

| source | rel type | target | `targetJsonName` (on source) | `sourceJsonName` (on target) |
|---|---|---|---|---|
| `Allocation` | `ABOUT` | `Entity` | `isAbout` | `allocationsAbout` |
| `Allocation` | `FULFILLS` | `Specification` | `fulfills` | `allocations` |
| `Process` | `QUALIFIED_USAGE` | `Allocation` | `allocations` | `process` |
| `Process` | `CONCRETIZES` | `Plan` | `concretizes` | `executions` |
| `Quality` | `INHERES_IN` | `IndependentContinuant` | `inheresIn` | `qualities` |
| `Measurement` | `IS_ABOUT_QUALITY` | `Quality` | `isAboutQuality` | `measurements` |
| `FoodObject` | `LOCATED_IN` | `ContainerObject` | `locatedIn` | `contents` |
| any | `HAS_KIND` | `DomainType` | `hasKind` | `instances` |
| `DomainType` | `SUBCLASS_OF` | `DomainType` | `parent` | `children` |

Write one throwaway relationship first and read the resulting property names back before building on the pattern.

---

## 7. Gotchas already known to hit this build

- **Trait-level `unique` is global across subtypes.** Do **not** put `unique` on `Identifier.identifierValue` — invariant 11 needs UUIDs unique within their scheme while GTINs are shared. Enforce in an `onCreate` method instead.
- **`Date` properties come back as real objects**, not strings — call `.getTime()`/`.toISOString()`. Relevant everywhere `hasTime` is compared.
- **New nodes default to owner-only visibility.** Every write needs an explicit `visibleToAuthenticatedUsers`.
- **Renaming a `SchemaNode` orphans its instances.** Get the 51 structural names right the first time; there is no cheap rename later.

---

## 8. Build order

1. **Structural traits only**, top-down, no properties — verify a 4-level chain reads back with correct `inheritedTraits` on every link (don't trust `name` showing up as proof).
2. **One polymorphic target** — `Allocation -[ABOUT]-> Entity`, satisfied by a `PortionOfSubstance` and an `EquipmentObject`. This is the load-bearing assumption; if it fails, the whole structural layer needs rethinking.
3. **Metamodel types** + a three-level `DomainType` chain, and `resolveDefault` walking it.
4. **One lifecycle-method invariant** end to end, to confirm the SHACL substitute is real.
5. Only then: instance data, and the first real recipe.

Steps 1–4 are the spike. If any of them behaves differently than the cheatsheet predicts, better to find out before there is data.

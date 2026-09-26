# CLAUDE.md — Meal Planner Project

Read this before touching anything else.

## What this is

A single-user meal-planning tool. It generates a weekly plan satisfying difficulty, nutrition, meal-type coverage, time budgets, inventory and expiration awareness, and minimal ingredient waste. The data model is BFO-grounded and has been through four major revisions and two external adversarial reviews. **The modeling is done; the build is not.**

## Document status — read this table first

| File | Status | Use it for |
|---|---|---|
| `data-model.md` (Rev. 4.4) | ✅ **Authoritative** | the model. If anything contradicts it, it loses |
| `structr-build-sketch.md` | ✅ **Authoritative** | how the model maps onto Structr |
| `structr-cheatsheet.md` | ✅ **Authoritative** | Structr mechanics. Empirically verified against a real instance — trust its ✅ items over the official docs |
| `bfo-reference.md` | 📖 Reference | what BFO classes and relations mean, with domains/ranges |
| `optimizer-design.md` | 📝 **Proposal, built as a first version — unreviewed** | the design of the optimizer and, in its §12, what was actually built and which of its questions were answered by default. Not authoritative: the objective in particular is a proposal, not a fact about what makes a good week |
| `design-review-document.md` | 🗄️ **Historical — do not follow** | records round-1 review findings, all since fixed |
| `design-review-document-round2.md` | 🗄️ **Historical — do not follow** | same, round 2. Its §11 "not yet acted on" items **have** since been acted on |

The two review documents describe the model *as it was before fixes*. Reading them as current guidance will reintroduce solved problems.

## Hard rules — violating these destroys data

From the cheatsheet's empirically-verified findings. These are not stylistic.

1. **Never rename a `SchemaNode`.** It orphans every existing instance — unreachable under both old and new names. Get the 51 structural type names right the first time.
2. **Never add a trait to a type that already has instances.** A node's Neo4j label set is fixed at creation; existing instances silently fail polymorphic-target lookups forever. Only fixable with direct Cypher `SET n:<Label>`.
3. **The structural trait layer is frozen after build.** Everything that varies at runtime is data — see the three-layer split in the build sketch. If a task seems to require a new structural type, stop and ask.
4. **Every write sets visibility explicitly** (`visibleToAuthenticatedUsers` or `visibleToPublicUsers`). The default is owner-only and fails silently.
5. **Check-then-create everything.** Nothing in Structr's schema API is idempotent; POSTing twice duplicates or errors.
6. **`sourceJsonName`/`targetJsonName` are inverted** from what the names suggest. Write one throwaway relationship and read the resulting property names back before building on the pattern.
7. **Never put `unique` on a trait** unless global-across-all-subtypes is genuinely wanted. It is not per-type. This specifically breaks `Identifier.identifierValue`.
8. **Don't trust a verification spike run right after a schema change** — restart the container first, then test. A stale compilation cache produces false positives, not just false negatives.

## Two principles that decide most modeling questions

- **Reify what varies within a populated type; subclass what varies across types.** Quality, Role, Process, and DefaultSpecification all take `hasKind → DomainType`. PlanningConstraint uses concrete subtypes instead, because its members' attributes genuinely differ.
- **Compute, don't store.** Current magnitudes, on-hand quantities, acquisition lists, nutrient rollups, and similarity scores are all derived at query time. If a task asks you to add a stored field for something derivable, question it.

## Deliberately out of scope — do not helpfully add these

Each was considered and declined. Adding any of them is a regression, not an improvement.

- **Person/Agent** — single-user by design. There are no agents in the model; equipment participates, it does not act.
- **Per-serving customization** (`MealServing`) — deferred with its motivating scenario recorded.
- **Freezing/thawing as modeled state transitions** — storage condition is a static tag.
- **Non-linear recipe scaling** — scaling is uniform across ingredients, knowingly.
- **Site-based location modeling** — shelf/cupboard is free text; storage *condition* is a Type.
- **New top-level classes via `ExtensionPropertyDefinition`** — it adds typed properties to existing types only.
- **OWL/DL reasoning** — BFO is design discipline here, not a runtime dependency.

## The optimizer

**Status: designed on paper and built as a first version, unreviewed.** For twenty-plus sessions there was no scoring function, no search strategy and no numeric definition of a good week, and the selector (`scripts/11c_simple_selector.py`) picks one meal for one slot, so it cannot enforce a hard nutritional minimum. `optimizer-design.md` proposes the plan-level formulation; `mealplanner/planning/` builds it (`plan_week`), with the selector's scoring shapes shared through `mealplanner/scoring.py`.

The rule stands: **do not change its objective (§4.5 of the design) or its search silently.** The weights and the weighted sum are a proposal for the owner to retune against real weeks. Its first version has no library solver, so on a full week it returns a good plan it cannot prove optimal, and says so (§12).

## Build order

Steps 1–4 are effectively a spike. Do not proceed past a failure.

1. **Structural traits only**, top-down, no properties. Verify a 4-level chain reads back with correct `inheritedTraits` on **every** link — read the literal value, don't infer from `name` appearing (it appears regardless).
2. **One polymorphic target**: `Allocation -[ABOUT]-> Entity`, satisfied by both a `PortionOfSubstance` and an `EquipmentObject`. This is the load-bearing assumption of the whole structural layer.
3. **Metamodel types** and a three-level `DomainType` chain, with `resolveDefault` walking it.
4. **One lifecycle-method invariant** end to end, confirming the SHACL substitute is real.
5. Seed vocabulary — Food Identity roots, Transformation Methods, Perishability classes, Nutrient types. Real curation work, not a formality.
6. First real recipe, first real inventory, first real cook.

## Repo conventions

- **Split the generic Structr client from the project data mapping** into separate modules. The REST mechanics don't change per project; only type names and field mappings do.
- **Schema-setup scripts idempotent from day one** — `ensure_type` / `ensure_property` / `ensure_relationship` helpers, so re-running after adding one type is free and safe.
- **Set up Deployment export to git early.** Nothing in the scripted-REST approach captures schema or page changes made through the UI.
- **The 30 domain invariants in `data-model.md` §11 are the test suite.** Expect two or three to turn out uncheckable as written — that's a finding worth recording, not a reason to skip them.

## When something doesn't fit

The model has been wrong before and been corrected many times; several fixes came from discovering that a restriction the model had invented for itself was the actual problem. If the model appears to prevent something ordinary — a normal kitchen operation that has nowhere to go — that is a genuine finding. Record it rather than working around it silently.

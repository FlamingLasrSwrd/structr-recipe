# Optimizer Design — Proposal, built as a first version (unreviewed)

**Status: a proposal, since built as a first version (§12 says what was built and where it departs from this text), and still unreviewed and not authoritative.** `CLAUDE.md` says the optimizer must not be invented silently. This is the design, written so it could be challenged; the build followed the recommendations in §10 because the owner asked for it to be built, and §12 lists each assumption so any of them can be overruled. Decisions that are the owner's to make are marked **D1–D9** and collected in §10 with a recommendation each. Where this document states a fact about the code, the file is named; where it states an expectation it has not tested, §11 says so.

It came out of a specific question: *how should a hard nutritional minimum be enforced?* The answer turned out to be that it cannot be, by anything shaped like the current selector, and that the honest fix is the thing the project has never had.

## 1. What has to be produced

Given a week of meal slots, produce a set of `MealPlanEntry`s that **satisfies every hard constraint** and, among those that do, **scores best** on the soft ones — or, when no plan can satisfy the hard constraints, **say so, name which constraints conflict, and show the closest achievable plan.**

`CLAUDE.md` names what a week must satisfy: difficulty, nutrition, meal-type coverage, time budgets, inventory and expiry awareness, and minimal ingredient waste. §3 maps each to what exists today.

## 2. Why the current selector cannot do minimums

`scripts/11c_simple_selector.py::select` picks **one meal for one slot**, given the meals already chosen. Three properties make a hard minimum unreachable for it, and only the first is fixable by tuning.

**2.1 It cannot see the rest of the day.** A scoped nutrient total only grows, so a hard *maximum* is decidable mid-plan (already over, nothing fixes it) while a hard *minimum* is not (the day may simply be unfilled). `mealplanner/nutrition_scope.py` says this and `nutrition_report()` judges minimums only after the fact.

**2.2 There is nothing to fill.** `MealPlan` holds only entries already chosen. No representation exists of how many meals a day should have, or of which slots are still open. Any "can the minimum still be reached?" check needs that number, and the model does not have it.

**2.3 A per-slot score is not a plan-level objective.** For a scoped target the selector scores `planned + this meal` against the range. Summed over slots, that judges the same daily target three times against three different running totals. A plan is judged once, on the final total.

**A worked case, run against the real scoring functions** (`time_fit_score`, `nutrition_fit_score`). One day, three slots, a hard daily protein minimum of 70 g (maximum 140 g), a 30-minute time budget, time weight 0.6, nutrition weight 0.2, no variety term. Five recipes, per serving:

| recipe | protein | minutes |
|---|---|---|
| buttered pasta | 12 g | 20 |
| veggie stir-fry | 10 g | 25 |
| omelette | 24 g | 35 |
| chicken salad | 30 g | 40 |
| braised chicken | 45 g | 90 |

The selector's ranking at each slot picks buttered pasta (0.634, 0.669, 0.703 in turn; veggie stir-fry is runner-up each time): the day totals **36 g, 34 g under the minimum**. Of the 125 possible menus, **63 are feasible**; the best of them (three omelettes, 72 g) scores 1.906 against the greedy day's 2.006. Two more facts matter for the design:

- **No single swap repairs the greedy day.** Changing one slot never reaches 70 g, so a "greedy, then repair" pass of one-slot swaps finds nothing. The fix needs a joint choice.
- **The price of feasibility is visible and small here** (0.1 of score), which is what a soft objective should be trading against a hard constraint, not silently ignoring it.

(The nutrition weight was chosen so the two days do not tie. At 0.3 they tie exactly, by coincidence of the weights, which is itself a demonstration that the score cannot see the minimum.)

## 3. What must be satisfied, and where each stands

| Goal (`CLAUDE.md`) | Today | The optimizer needs |
|---|---|---|
| Meal-type coverage | Selector filters candidates by a `meal_type` tag (`candidate_meal_types`). Nothing says which slots exist | Slots carrying a meal type (§4.2), each filled by a recipe tagged for it |
| Nutrition | Hard maximum disqualifies; minimum only scored; soft targets scored per slot | Every scoped target judged once, on the scope's final total; hard min and max both constraints |
| Time budget | Per-candidate `time_fit_score` against `MealPlan.timeBudgetMinutes` | Same per-slot term; **D5**: whether a per-day total is wanted |
| Inventory and expiry | Coverage and waste scores per candidate; `Reserved` pools the plan's own claims | Ingredient demand of the whole plan against stock **with expiry dates**, so food that expires before a slot can't feed it |
| Minimal waste | `wasteWeight` urgency term | Unused near-expiry stock and unwanted surplus as penalties |
| Difficulty | `Plan.difficultyRating` exists (`easy/medium/hard`); **nothing reads it** (REVIEW.md round 1 #15) | **D6**: authored or derived, and hard or soft |
| Leftovers | `consumesLeftoverFrom`, `hasPlannedConsumption` exist; invariants 23, 24, 27 are not built | Cook-once-eat-twice as a decision, which needs surplus accounting (§8) |

## 4. The design

### 4.1 Separate the problem from the solver

The work is two independent pieces with one interface between them:

1. **Extraction**: read the graph (through the existing engines and a `ReadCache`) and produce a plain-data `PlanningProblem`: slots, candidate recipes with their per-serving nutrient amounts, minutes, difficulty and ingredient demands, stock lots with expiry dates, the constraints and weights. Pure numbers, no Structr in it.
2. **Solving**: `PlanningProblem` in, `Solution` out (chosen recipe or leftover per slot, objective breakdown, or an infeasibility diagnosis).

This is the same split the project already uses to test itself: the arithmetic runs offline on plain data (`tests/`), and only extraction touches Structr. It also means a solver can be swapped or cross-checked without touching the model. The extraction reuses `serving_nutrient_amount`, `candidate_input_requirements`, `instance_expiration`, `resolve_stock_policy` and `net_requirements`'s pooling; it should introduce no second way of computing any of them.

### 4.2 Slots are an input, not stored data (D1)

A slot is `(start time, meal type)`. The set of slots for a week is a **call-time template** ("breakfast 08:00, lunch 12:30, dinner 18:30, seven days"), not a stored entity. Reasons: it needs no new structural type (`CLAUDE.md` hard rule 3), it is cheap to vary per week, and an already-planned `MealPlanEntry` can be presented to the solver as a **fixed** slot. The output becomes ordinary `MealPlanEntry`s, which the model already supports.

Alternative: store open slots as entries with no recipe. That would need invariant 7 (an entry references a Plan or consumes a leftover) to admit a third state, which is a model change with no other benefit. Not recommended.

### 4.3 Decisions the solver makes

For each open slot `s`:

- `x[s,r] ∈ {0,1}`: cook recipe `r` fresh at `s` (exactly one of the slot's options is chosen).
- `z[s',s] ∈ {0,1}`: slot `s'` eats leftovers of the fresh cook at `s < s'`, which must be the same recipe, complete before `s'`, and not yet expired at `s'` (invariant 27).
- Cooked servings at `s` are **derived**, not free: the servings eaten at `s` plus those drawn by the leftover slots. Ingredients scale uniformly (the model's own knowing simplification, and how reservation already scales), so cooking 2 of a 4-serving recipe uses half of it and nothing is lost to rounding to whole batches.

The eaten amount per slot defaults to one serving (J3). The size of a cook is therefore a consequence of the plan, not a stored decision, which keeps the model's compute-don't-store discipline.

### 4.4 Hard constraints

Each is linear in the decision variables, which is what makes the exact approach in §5 possible.

| # | Constraint | Form |
|---|---|---|
| H1 | Every open slot is filled, exactly once | `Σ_r x[s,r] + Σ_s0 z[s,s0] = 1` |
| H2 | The recipe carries the slot's meal type | candidates filtered up front |
| H3 | No hard `ExclusionConstraint` violated (J6, J10) | candidates filtered up front |
| H4 | **Every hard `NutritionTarget`, at its declared scope**: `min ≤ Σ_{s in scope} intake(s) ≤ max` | one inequality per (target, day) or (target, week); intake `= Σ_r amount[r,n] · servings_eaten · x[s,r]` |
| H5 | Leftover legality (source before, same recipe, before expiry) | on `z` |
| H6 | Optional, if the owner wants no shopping (**D4**): demand for each stock pool ≤ eligible stock | per pool |
| H7 | Optional (**D6**): difficulty cap per meal or day | on `x` |

**H4 is the answer to the question this document started from.** A hard minimum stops being something a greedy pass hopes for and becomes a row in the constraint set. When the set has a solution the plan meets it; when it has none, §4.7 says what to report.

### 4.5 The objective (D3): the piece that has never existed

There is no numeric definition of a good week. This section proposes one, deliberately built from what the selector already computes so that nothing about a single meal changes.

**Form.** Maximise a weighted sum of terms, each normalised to `[0,1]`, subject to §4.4. Weights are the ones the model already stores on `MealPlan` (`timeBudgetWeight` default 0.5, `varietyWeight` 0.5, `stockWeight` 0, `wasteWeight` 0) and on each `NutritionTarget.weight`. No new stored field.

| Term | Per | Definition | Reuses |
|---|---|---|---|
| Time fit | slot | 1 within budget, falling linearly to 0 at twice the budget | `time_fit_score` |
| Variety | pair of slots | nearer than 14 days apart with the same recipe costs `1 − days/14`; a recipe already used in past entries counts against the same scale (J14) | `variety_score` |
| Soft nutrition fit | (target, scope) | judged **once**, on the scope's final total, by the selector's existing shape (1 in range; falling with relative deviation) | `nutrition_fit_score` |
| Stock coverage | plan | fraction of ingredient demand met from stock rather than bought | `net_requirements` |
| Waste | cook | the selector's urgency: 1 if the soonest-expiring stock still good at the cook expires that day, falling to 0 at five days; rewards cooking what uses it (as built, §12; a penalty for stock left unused is not built) | `waste_urgency` |
| Soft exclusion | use | the constraint's weight per use of a banned type (J10) | `soft_exclusions` |

**Continuity requirement.** A one-slot problem must give the selector's winner. This is the regression test that ties the new machinery to the old (§6), and it holds only if plan-level terms reduce to the selector's when there is one slot.

**What is a proposal in all of this, not a derivation:** the choice of a weighted sum rather than a lexicographic order, the normalisation of each term, and the 14-day variety window (inherited from `VARIETY_CAP_DAYS`). They are defensible defaults, not facts about the eater's preferences, and the owner is the only one who can say a plan "feels" wrong.

### 4.6 Unknown data (D7)

The project's rule is that unknown stays unknown, never a plausible default. The optimizer inherits it, and it bites hardest here, because a hard target can now be *decided* on data that may be missing or placeholder.

Proposal: a candidate whose amount of a hard-targeted nutrient is unknown, or comes from placeholder data (REVIEW.md round 1 #24, which needs a provenance field on `NutrientProfile`), is **ineligible in any scope with a hard target on that nutrient**, and is listed in the result as "would be eligible if its nutrition were filled in". A soft target treats it as neutral, as the selector does today. This makes missing data a visible, fixable reason a recipe was skipped, never a silent pass.

### 4.7 Infeasibility is an answer

If no assignment meets every hard constraint, the solver re-runs with each hard scoped target relaxed to a penalised slack and reports:

- which hard constraints cannot hold together (the minimal set whose removal makes a plan possible);
- the closest achievable plan and its exact deficit ("best possible is 58 g against a 70 g minimum on Tuesday");
- the recipes that would close the gap per serving, from the candidate pool.

This is also the standalone "shortfall report with remedies" the owner was offered, produced as a by-product instead of being built separately.

### 4.8 Output: a proposal, then a commit

The solver returns a `Solution`; nothing is written. Committing creates `MealPlanEntry`s (with `hasPlannedServings`, `consumesLeftoverFrom`, `hasPlannedConsumption`) through the existing write-time validators. Each choice carries its reasons: the terms behind its score, the constraints that were binding, and the runner-up. Determinism matters here: ties break by recipe name so the same inputs always give the same week.

## 5. How to solve it (D2, D8)

| Approach | Handles minimums | Guarantee | Cost |
|---|---|---|---|
| A. Greedy plus look-ahead pruning | Partly: rejects a pick when the best remaining meals cannot reach the minimum | None | Small; **needs the remaining-slot count**, so it depends on §4.2 anyway |
| B. Beam search over slots in time order | Yes, with the same pruning bound | None (can miss the optimum) | Moderate; no new dependency |
| C. Exact: CP-SAT or a MILP over the §4.4 constraints | Yes, natively | **Optimal, or a proof of infeasibility**, and a gap when stopped early | A dependency (e.g. OR-tools); encoding leftovers and stock lots is the real work |
| D. Exhaustive branch-and-bound | Yes | Optimal | No dependency, but the search is exponential in slots and rests entirely on the quality of its pruning |

**As built (§12): a dependency-free exact search and a beam search, behind the interface below; the library solver of C is not installed and needs the owner's permission (D8).** **Recommendation: C behind the interface in §4.1, with a brute-force enumerator as the test oracle, and B as the no-dependency fallback if the dependency is refused.** Reasons: the constraints are all linear, so an exact solver is a natural fit; only an exact solver can *prove* a minimum unreachable, which is the thing §4.7 needs; and a brute-force oracle is affordable on small instances (a 3-slot, 5-recipe day is 125 menus, as in §2), which gives independently-worked expected values, the project's testing rule.

A sound pruning bound for approach A or B, for the record: with `k` slots left in a scope, a candidate is infeasible for a hard minimum if `planned + intake + k · (best per-serving amount among eligible candidates) < min`. It never rejects a pick that could still succeed, so it is safe, and it is weak (it ignores time, stock and variety).

**Size.** A week is on the order of 21 slots; a single user's recipe book is tens to low hundreds. That is roughly a few thousand booleans and a few dozen linear constraints. That is an *expectation*, not a measurement (§11).

## 6. How it will be verified

The project's own testing rules apply unchanged: expected values worked out independently of the code under test; test data prefixed `TEST -- `; demos self-clean; every data change through a committed script.

1. **Brute-force oracle.** For instances small enough to enumerate (≤ 6 slots × ≤ 6 recipes), the solver's optimum and its feasibility verdict must equal the enumerator's. Includes the §2 case, whose expected answer (63 of 125 feasible; three omelettes best) is already worked out.
2. **Continuity.** A one-slot problem returns the selector's winner on the existing demo data.
3. **Hard constraints are never violated** when feasible: property checks over generated instances.
4. **Infeasible instances** return a diagnosis with the exact deficit, not a plan.
5. **Unknown and placeholder data** make a recipe ineligible for hard scopes and appear in the report.
6. **Leftover cases**: a cook-once-eat-twice week beats two separate cooks on waste, and never schedules a leftover before its source or past expiry.
7. **A live demo** in the `22a`/`25a` style, self-cleaning, against real Structr; and a **scale check** recording seconds for a realistic week so the expectation in §5 is replaced by a number.

## 7. Build phases

Each phase leaves the repo working and is worth having on its own.

| Phase | Adds | Exit criterion |
|---|---|---|
| 1 | `PlanningProblem`, extraction, the brute-force oracle, **hard constraints only, no objective** | "Does a plan meeting every hard constraint exist?" answered exactly, including H4 minimums. **This alone resolves the nutritional-minimums question.** |
| 2 | The objective (§4.5) and a solver | Oracle agreement; continuity test passes |
| 3 | Leftovers and stock lots with expiry | The §6 leftover and waste cases pass; needs §8's prerequisites |
| 4 | Commit, explanations, infeasibility diagnosis, live demo, scale check | The §6 list is complete |

## 8. Prerequisites and their state

| Needed | State |
|---|---|
| Slot template (D1) | This document proposes it; nothing exists |
| Leftover surplus accounting (invariants 23, 24, 27) | Not built (`domain_invariants.py`); needed from Phase 3, not before |
| Placeholder-data provenance on `NutrientProfile` (D7) | Not built; needed for §4.6 to be more than a naming convention |
| Difficulty semantics (D6) | Undecided |
| What "no container" means (REVIEW.md round 2 #18) | Undecided; affects which stock counts as eligible |
| Stock lots with expiry as solver input | `instance_expiration` exists; extraction to be written |
| The read path being fast enough | Reduced (303 to 95 requests) but still linear in history; extraction should read once and hand plain data to the solver, not call back into Structr |

## 9. Non-goals

Everything `CLAUDE.md` lists as declined stays declined: no person or agent, no per-serving customisation, no freezing or thawing as state, no non-linear scaling, no site-based locations, no new top-level classes. In particular **no multi-person planning** and **no learning of preferences**: weights are set by the owner. The optimizer adds no structural type, and (D1) no stored property.

## 10. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D1 | Slots as a call-time template, with existing entries fixed | Yes (§4.2) |
| D2 | Exact solver (CP-SAT/MILP) behind an interface, with a brute-force oracle | Yes; adds a dependency, which is the real question (D8) |
| D3 | The objective: weighted sum of `[0,1]` terms from the selector, each scope judged once | Yes as a starting point, expecting the owner to retune weights against real weeks |
| D4 | Stock hard ("cook only from what I have") or soft (shortfall is a purchase and a penalty) | Soft by default, hard as an option per plan |
| D5 | Time budget: per meal only (today), or also a per-day total | Per meal now; per-day added when asked |
| D6 | Difficulty: authored or derived, hard or soft | Authored (`difficultyRating`), soft, with an optional hard cap |
| D7 | Unknown or placeholder nutrition for a hard-targeted nutrient makes a recipe ineligible for that scope | Yes, with a provenance field on `NutrientProfile` (a property, not a type) |
| D8 | Accept a solver dependency (OR-tools or PuLP with CBC) in a project whose only dependency is `requests` | Yes, isolated to one module and optional at import; beam search remains the fallback |
| D9 | Meal-type coverage means only "each slot holds a recipe tagged for its type" | Yes; richer coverage rules ("two vegetarian dinners") are a later constraint |

## 11. What has not been verified

(Written before the build; §12 records what the build then measured and found.)


- **Solver performance.** Measured for the dependency-free search only (§12); a library solver has not been run.
- **OR-tools availability** on the target machine and in CI. Not installed here; installing it needs a decision (D8).
- **Whether one score suits the owner.** The objective is a proposal (§4.5). The way to test it is to generate weeks from real recipes and look at them.
- **The single-slot continuity claim** rests on the plan-level terms reducing exactly to the selector's. It is the first thing Phase 2 must show, not something assumed.
- The worked example in §2 used the real `time_fit_score` and `nutrition_fit_score`; its variety, stock and waste terms were zero by construction, so it shows the minimum problem in isolation, not a full week.

## 12. As built

The first version follows Sec 7's four phases and lives in `mealplanner/planning/` (`model`, `evaluate`, `search`, `diagnose`, `extract`, `commit`, `plan`, `report`), with the selector's scoring shapes moved to `mealplanner/scoring.py` and its candidate helpers to `mealplanner/candidates.py` so both use one copy. `plan_week(client, meal_plan_id, template, now)` is the entry point. **It has not been reviewed.**

**Decisions taken by default** (the owner asked for a build and answered none of D1-D9, so each was taken as recommended; any can be reversed):

| # | What was built |
|---|---|
| D1 | Slots are a call-time `SlotSpec` list; entries already in the MealPlan become fixed slots |
| D2, D8 | An exact branch and bound and a beam search, **dependency-free**, plus a brute-force oracle used only by tests. No library solver was installed: that is a download, and needs permission. It would slot in behind `search.solve` |
| D3 | The weighted sum of §4.5, each scoped target judged once |
| D4 | Stock is soft only (coverage and waste terms); the "cook only from what I have" option is not built |
| D5 | Per-meal time budget only |
| D6 | `Plan.difficultyRating` is an optional hard cap (`max_difficulty`); a recipe with no stated difficulty is ineligible when a cap is set; there is no soft difficulty term |
| D7 | `NutrientProfile.provenance` (`placeholder` / `sourced`) was added as a property; a hard target is never decided on a figure that is unknown, placeholder or unmarked. Nothing in the repo is marked `sourced`: only a person who has checked a figure can say so |
| D9 | Meal-type coverage is "each fresh cook is tagged for its slot's meal type"; leftovers may fill any slot |

**Where the build departs from the text above**
- *Waste* is the selector's reward (urgency of the soonest-expiring stock a cook draws on), so that a one-slot problem scores exactly as the selector does; it is not the penalty on unused stock §4.5 described.
- *Batches* scale uniformly and are not rounded (§4.3, corrected above).
- A *leftover slot* scores time fit 1 (nothing to cook), counts as a use of its recipe for variety (so eating the same dish a day later is penalised by the variety weight), and is ready only after its source cook has finished (`Candidate.minutes`) and until its keeping time runs out. The keeping time is the ShelfLife default of the `Cooked Leftover` class for Fridge, Sealed, seeded as **3 days, a placeholder** (`17b`).
- *Stock*: cooks are served in time order from the lots still good when each starts, soonest-expiring first. Stock and waste are bounded by their weights during search rather than computed, because a later leftover changes how much an earlier cook must produce; they are exact in the final score.
- *Pooling* is `reservation.stock_pools`, the same pools `net_requirements` uses, including the nested-policy carve-out.

**What is verified**
- 108 offline tests over the planner and the engine changes it rests on (`tests/test_planning_*.py`): hand-worked values, including the §2 case (63 of 125 menus feasible; best score 1.7); the exact search against the brute-force oracle on 80 seeded random problems (61 feasible, 19 infeasible, 39 with hard targets, 16 with leftovers in the best plan), strict and relaxed; the partial-assignment bound checked against every prefix of sampled completions (five deliberate breakages of the bounds were each caught); and **continuity**: on a shared graph with variety, a soft and a hard-maximum target, a soft exclusion, stock coverage and expiry urgency all active, the planner's score for each recipe equals the selector's to nine places.
- `scripts/26a_planner_demo.py` against real Structr, self-cleaning, with every expected score worked out by an independent enumeration in the script: eligibility under a hard target, the best feasible day with and without leftovers (1.7 and 1.9), commit, `nutrition_report()` (which predates the planner) judging the committed day `ok` at 72 g, re-reading the entries as fixed slots, an unreachable minimum giving a proven diagnosis with the exact 5 g shortfall and writing nothing, a figure switched to placeholder being left out, an existing entry counting towards the day, and a leftover entry accepted by the write-time validators.

**Measured limits** (synthetic weeks, random recipes, hard daily protein and sodium targets, stock in ten pools; one machine)

| slots x recipes | exact search | beam, width 30 |
|---|---|---|
| 6 x 10 | proven optimal in 1.3 s | same score, 0.1 s |
| 9 x 20 | 15 s limit reached, not proven; 89,000 nodes | 0.4 s, 2.4% below the exact's best |
| 21 x 30 | 15 s limit reached, not proven | 2.3 s, 2.3% below |
| 21 x 30, leftovers | 15 s limit reached, not proven | 4.4 s, 2.3% below |
| 21 x 60, leftovers | 15 s limit reached, not proven | 6.8 s, equal to the best exact found |

So the dependency-free exact search proves a small week and cannot prove a full one: its bounds are loose (every unplaced slot is assumed to earn its full weight) and it recomputes them at each node. `plan_week` therefore defaults to `auto`: exact search under a time limit, then beam search, returning the better and **labelling the result "not proven optimal"** when it did not finish. Hard constraints are never relaxed by this: a plan that is returned meets them. What a full week does not get without a library solver is a proof of optimality or of infeasibility. The synthetic weeks are not the owner's recipe book, so these are orders of magnitude, not a promise.

**Not built:** a library solver adapter (D8); hard stock ("only cook from what I have"); a per-day time budget; a penalty for unused near-expiry stock; a soft difficulty term; a persistent "locked" flag on entries beyond what an existing entry already is; the parent link that would carry a leftover's purchase date through a division (J12).

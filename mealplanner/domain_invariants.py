"""Domain invariants (data-model.md Sec 11) implemented as onCreate
validators or schema constraints, plus notes on what's already
structurally guaranteed and what's deferred.

CLAUDE.md calls these "the test suite" and expects "two or three to
turn out uncheckable as written." What actually happened scoping this:
most of the 30 aren't uncheckable so much as UNBUILDABLE YET -- they
govern structural pieces this build hasn't touched (MealPlan,
MealPlanEntry, StockPolicy, NutritionTarget, AcquisitionList,
SubstitutionRule, Identifier's full relations, wasDerivedFrom,
currentMagnitude/physicalOnHand). Implementing those properly is a
build phase of its own, not a validator to bolt on. This module covers
what's checkable against what step 6 actually built.

STATUS KEY:
  STRUCTURAL   -- already guaranteed by the schema shape itself, no
                  code needed (verified empirically, not assumed)
  IMPLEMENTED  -- a real onCreate check or notNull constraint, below
  DEFERRED     -- needs structural pieces not yet built; noted, not
                  silently skipped
"""

# --- STRUCTURAL (no code -- verified, not assumed) --------------------
#
# 1 (partial): "No SDC inheres in a GDC" -- INHERES_IN's declared
#   target type is IndependentContinuant; Structr rejects assigning a
#   wrong-typed node id with 422 "No IndependentContinuant with UUID
#   ... found" (confirmed empirically against a GDC/RecipeIdentity id).
# 8: "At most one direct parent per hierarchy" -- SUBCLASS_OF's target
#   multiplicity is 1, making `parent` a scalar reference field. A
#   scalar field cannot hold two values; there is no operation that
#   would even express "two parents" to violate this.

# --- IMPLEMENTED -------------------------------------------------------
#
# 12: No quantity-bearing value may be negative.
#   Measurement.onCreate (see MEASUREMENT_ONCREATE below) AND
#   QuantitySpecification.onCreate for its value, minValue and maxValue --
#   the latter was missing until external review (only Measurement was
#   checked, so a target range of -10 to 50 was accepted). Guarded with
#   empty(this.value) first -- lt(null, 0) evaluates true in
#   StructrScript, which silently broke every categorical Measurement
#   (opened_status, cleanliness) before this guard was added.
#
# 3 (adapted): "exactly one of value/range/unconvertible" -- this build
#   only implements a scalar value (no range/unconvertible support --
#   that's real unbuilt machinery, not in scope here). Adapted to what
#   exists: QuantitySpecification.value is notNull (a QuantitySpec
#   without a value is meaningless in this simplified schema);
#   Measurement requires at least one of value/literalValue.
#
# 4, 5: "Every Allocation/Specification has exactly one
#   has_participation_role." -- hasParticipationRole is notNull on both.
#
# 6: "Instrument-role Specifications/Allocations carry no quantity."
#   onCreate checks on both types.
#
# 14 (partial): "Retention factors in (0,1]; yield factors positive."
#   DefaultSpecification.onCreate, branching on this.hasKind.name,
#   reading this.hasValue.value via chained relationship access.
#   (Density/MassPerUnit/PurchaseQuantity/Duration/NutrientAmount
#   defaults have no comparable documented range to check yet.)
#
# 13 (as a computation, not a validator): "Cross-quantity-kind
#   conversion requires an explicit density; without one,
#   unconvertible." mealplanner/unit_conversion.py's convert_to_grams()
#   resolves Density/MassPerUnit defaults (Sec 8) for volume/count ->
#   mass conversion and returns None (unconvertible) rather than
#   guessing when neither resolves -- wired into
#   scripts/11c_simple_selector.py's stock-coverage scoring, fixing a
#   "unit-blind" gap found by external review (it used to compare a
#   Specification's raw numeric value directly against on-hand grams
#   regardless of its declared unit). Unlike most entries in this
#   IMPLEMENTED section, this isn't an onCreate write-time check --
#   there's nothing to reject at write time, only a computation that
#   must not silently guess.
#
# 15 (as an audit, not a validator): "Summed input quantities per bearer
#   cannot exceed that bearer's physical on-hand at the time of the
#   Process." mealplanner/inventory.py's overdraws() checks it at every
#   draw's own time (so a later weighing cannot hide an earlier overdraw)
#   and find_overdraws() scans every portion; an `imputed` baseline gives an
#   informative Overdraw (fatal=False), an `observed` one a real violation,
#   as the invariant says. It is NOT a write-time check: a validator would
#   have to compute on-hand inside StructrScript, which cannot (the
#   recursive/multi-entity ceiling found while building resolveDefault), so
#   an oversized Allocation is still accepted when written and is found
#   afterwards. Proven against real Structr by scripts/15e, and offline by
#   tests/test_inventory.py.
#
# 28 (as a computation, not a validator): "AcquisitionList counts only
#   entries not yet fulfilledBy a completed Process."
#   mealplanner/reservation.py's committed_requirements() and
#   net_requirements() both filter on exactly this (plus isSkipped),
#   and are wired into scripts/11c_simple_selector.py's stock-coverage
#   scoring as the "Reserved"/"Available" tiers -- fixing a "no
#   reservation layer" gap found by external review (two candidates
#   scored in the same planning session used to both see the full
#   on-hand stock as available). net_requirements() is AcquisitionList's
#   own formula (data-model.md's Recipes/plans/policies table),
#   including a documented resolution of an ambiguity in how it reads
#   ("StockPolicy shortfalls... - eligible on-hand" would double-
#   subtract on-hand taken literally) and a documented scope cut
#   (purchased-form vs. required-form yield division, not built --
#   no vocabulary exists yet for a Type's purchased form). See that
#   module's docstring for both.
#
# 29: "A cooking output's NutrientContent is always derived."
#   Measurement.onCreate: if isAboutQuality's hasKind sits in the
#   Nutrient hierarchy AND that Quality's bearer has
#   beginsToExistDuring set (i.e. it's a cooking-process output), the
#   Measurement's status must be "derived". A non-cooking-output food's
#   nutrient content is unrestricted (can be observed/estimated).
#
# 2a: "At most one observed and one imputed Measurement about the same
#   Quality at the same time." Measurement.onCreate, using the
#   isAboutQuality.measurements reverse collection (confirmed
#   self-inclusive during onCreate -- gt(count, 1) means "more than
#   just myself", not gt(count, 0)).

MEASUREMENT_ONCREATE = (
    'if(and(not(empty(this.value)), lt(this.value, 0)), '
    'error("value", "must_not_be_negative"), '
    # A numeric value with no unit can't be used in arithmetic; the inventory
    # engine raises on one rather than guessing, so refuse it at write time.
    'if(and(not(empty(this.value)), empty(this.unit)), '
    'error("unit", "quantity_needs_a_unit"), '
    'if(and(empty(this.value), empty(this.literalValue)), '
    'error("value", "must_have_value_or_literal_value"), '
    'if(and(not(empty(this.isAboutQuality)), and('
    'equal(this.isAboutQuality.hasKind.hierarchy.name, "Nutrient"), '
    'not(empty(this.isAboutQuality.inheresIn.beginsToExistDuring)))), '
    'if(not(equal(this.status, "derived")), '
    'error("status", "cooking_output_nutrient_content_must_be_derived"), '
    'INV2A_CHECK), '
    'INV2A_CHECK))))'
).replace(
    "INV2A_CHECK",
    'if(or(equal(this.status, "observed"), equal(this.status, "imputed")), '
    'if(gt(size(filter(this.isAboutQuality.measurements, '
    'and(equal(data.status, this.status), equal(data.hasTime, this.hasTime)))), 1), '
    'error("status", "duplicate_observed_or_imputed_measurement_at_same_time"), null), '
    'null)',
)

SPECIFICATION_ONCREATE = (
    'if(and(equal(this.hasParticipationRole, "instrument"), not(empty(this.hasSpecifiedQuantity))), '
    'error("hasSpecifiedQuantity", "instrument_role_must_not_have_quantity"), null)'
)

ALLOCATION_ONCREATE = (
    'if(and(equal(this.hasParticipationRole, "instrument"), not(empty(this.hasActualQuantity))), '
    'error("hasActualQuantity", "instrument_role_must_not_have_quantity"), null)'
)

DEFAULT_SPECIFICATION_ONCREATE = (
    'if(equal(this.hasKind.name, "Yield"), '
    'if(lte(this.hasValue.value, 0), error("hasValue", "yield_factor_must_be_positive"), null), '
    'if(equal(this.hasKind.name, "RetentionFactor"), '
    'if(or(lte(this.hasValue.value, 0), gt(this.hasValue.value, 1)), '
    'error("hasValue", "retention_factor_must_be_in_0_to_1"), null), '
    'null))'
)

# Also declared notNull in mealplanner/recipe_schema.py. It used to be
# declared False there and flipped to True only by the PATCH in
# scripts/07_domain_invariants.py, so the code and the live schema
# disagreed; the drift-detecting schema helpers found it. Kept here so
# 07 stays a self-contained statement of which invariants it enforces.
NOT_NULL_PROPERTIES = [
    ("Specification", "hasParticipationRole"),
    ("Allocation", "hasParticipationRole"),
    # Invariant 2: every Measurement has exactly one hasTime. It was optional,
    # so a Measurement without one was accepted and the inventory engine then
    # silently ignored it (found by external review and by our own audit).
    ("Measurement", "hasTime"),
]

# --- IMPLEMENTED, added while building the meal-planning layer ---------
#
# 3 (extended): QuantitySpecification.value was notNull (see above list
#   -- since removed) until NutritionTarget.hasTargetRange needed real
#   range support ("may be open-bounded" is explicit in the model).
#   Replaced with an onCreate check: exactly one of (scalar value) or
#   (minValue and/or maxValue) -- not both, not neither -- plus, when
#   both bounds are present, minValue <= maxValue.
#
# 7: "A MealPlanEntry has exactly one of (references + has_planned_servings)
#   or consumes_leftover_from." MealPlanEntry.onCreate.
#
# 26: "has_target_level >= has_reorder_threshold." StockPolicy.onCreate --
#   now also requiring both to be stated in the SAME unit, because the check
#   compares bare numbers (500 g against 2 lb used to pass 500 >= 2). Originally:
#   chained property access into both QuantitySpecifications' values.
#
# 27a: see ROLE_ONCREATE below -- required naming and building a
#   relation (Role.targetsEntry) that Sec 7 never named, the third
#   independent occurrence of that pattern in this project (after the
#   original Concept/instance-tagging E9 and DefaultSpecification's
#   forType). Recorded back to data-model.md Sec 7.

QUANTITY_SPECIFICATION_ONCREATE = (
    # Invariant 12 (no negative quantity-bearing value) was only checked on
    # Measurement; a QuantitySpecification's value and either range bound
    # could be negative (found by external review).
    'if(and(not(empty(this.value)), lt(this.value, 0)), '
    'error("value", "must_not_be_negative"), '
    'if(and(not(empty(this.minValue)), lt(this.minValue, 0)), '
    'error("minValue", "must_not_be_negative"), '
    'if(and(not(empty(this.maxValue)), lt(this.maxValue, 0)), '
    'error("maxValue", "must_not_be_negative"), '
    'if(and(or(not(empty(this.value)), or(not(empty(this.minValue)), not(empty(this.maxValue)))), empty(this.unit)), '
    'error("unit", "quantity_needs_a_unit"), '
    'if(and(not(empty(this.value)), or(not(empty(this.minValue)), not(empty(this.maxValue)))), '
    'error("value", "must_not_have_both_scalar_value_and_range"), '
    'if(and(empty(this.value), and(empty(this.minValue), empty(this.maxValue))), '
    'error("value", "must_have_either_value_or_range"), '
    'if(and(not(empty(this.minValue)), not(empty(this.maxValue))), '
    'if(gt(this.minValue, this.maxValue), error("minValue", "min_must_not_exceed_max"), null), '
    'null)))))))'
)

MEAL_PLAN_ENTRY_ONCREATE = (
    'if(not(empty(this.consumesLeftoverFrom)), '
    'if(or(not(empty(this.references)), not(empty(this.hasPlannedServings))), '
    'error("consumesLeftoverFrom", "leftover_entry_must_not_also_reference_a_plan"), null), '
    'if(and(not(empty(this.references)), not(empty(this.hasPlannedServings))), null, '
    'error("references", "fresh_cook_entry_needs_both_references_and_planned_servings")))'
)

# Not one of the model's original 30 -- a consequence of adding
# strictness/weight to PlanningConstraint for the simple-path selector
# (a soft constraint with no weight can't contribute to a weighted
# score; a hard constraint doesn't need one, since it's pass/fail).
PLANNING_CONSTRAINT_ONCREATE = (
    'if(equal(this.strictness, "soft"), '
    'if(empty(this.weight), error("weight", "soft_constraint_requires_a_weight"), null), '
    'null)'
)

# 27a: "A reservation Role on a physical portion and the
#   consumes_leftover_from edge between entries... must agree: the
#   Role's target entry must be the one whose consumes_leftover_from
#   names the entry whose Process generated that portion."
#   Only checkable now that Role.targetsEntry exists (see
#   mealplanner/role_entry_schema.py -- this was the third occurrence
#   of a recurring pattern: an invariant's prose describing a relation
#   Sec 7 never actually named). Checks when both chains are already
#   resolvable; skips (does not error) when the leftover-consuming
#   entry hasn't been created yet -- same "check when possible, don't
#   block impossible orderings" reasoning as invariant 16's deferral.
ROLE_ONCREATE = (
    'if(and(equal(this.hasKind.name, "Reservation"), not(empty(this.targetsEntry))), '
    'if(and(not(empty(this.inheresIn.beginsToExistDuring)), '
    'gt(size(this.inheresIn.beginsToExistDuring.fulfillsMealPlanEntries), 0)), '
    'if(empty(this.targetsEntry.consumesLeftoverFrom), '
    'error("targetsEntry", "target_entry_must_itself_consume_a_leftover"), '
    'if(not(equal(this.targetsEntry.consumesLeftoverFrom.id, '
    'first(this.inheresIn.beginsToExistDuring.fulfillsMealPlanEntries).id)), '
    'error("targetsEntry", "reservation_role_target_disagrees_with_leftover_source"), '
    'null)), '
    'null), '
    'null)'
)

STOCK_POLICY_ONCREATE = (
    'if(and(not(empty(this.hasTargetLevel)), not(empty(this.hasReorderThreshold))), '
    # The two are compared as bare numbers, so they must be stated in the same
    # unit: 500 g against 2 lb passed `500 >= 2` (found by external review).
    # Requiring one unit is simpler and safer than re-implementing unit
    # conversion inside StructrScript.
    'if(not(equal(this.hasTargetLevel.unit, this.hasReorderThreshold.unit)), '
    'error("hasTargetLevel", "target_and_reorder_threshold_must_share_a_unit"), '
    'if(lt(this.hasTargetLevel.value, this.hasReorderThreshold.value), '
    'error("hasTargetLevel", "target_level_must_be_at_least_reorder_threshold"), null)), '
    'null)'
)

# --- DEFERRED ------------------------------------------------------------
#
# 2b, 9 (wasRevisionOf part), 11 (Identifier): need wasRevisionOf /
#   Identifier's denotes+scheme relations, not built.
# 16: "No Allocation target both input and output of the same Process."
#   Genuinely awkward as a per-Allocation onCreate check: an
#   Allocation's Process link may be set before OR after the Allocation
#   itself exists (upsert order-dependent), so onCreate can't reliably
#   see "this Process's other Allocations" yet. Better suited to an
#   onSave check on Process once all its Allocations are attached, or
#   an application-level check before committing a Process. Not
#   implemented here to avoid a fragile, order-dependent validator.
# 17: "A Process cannot begin before every input entity exists" --
#   ambiguous what "exists" means operationally (createdDate vs BFO
#   existence via beginsToExistDuring for generated entities); not
#   implemented pending that decision.
# 18: SubstitutionRule/via_substitution, not built.
# 19: StockReconciliation, not built.
# 9a, 20, 21, 22: Concept.exactMatch/closeMatch, candidate_type,
#   RecipeIdentity.defines_output_type -- none of these relations are
#   built yet.
# 23, 24: leftover-reservation surplus/planned-consumption checks
#   (MealPlanEntry.consumesLeftoverFrom, the reservation Role,
#   targetsEntry) -- genuinely separate from 28 below: computing a
#   leftover source's surplus needs to know whether that source has
#   been cooked yet (a real Allocation's output) or not
#   (expected_combination_output()'s estimate, material_accounting.py),
#   which is real, separate work. mealplanner/reservation.py's own
#   module docstring states this scope cut explicitly.
# --- Not tracked here until the self-audit before the second external
# review (they were simply missing, not judged and skipped): -------------
#
# 2 (partial, in the IMPLEMENTED sense): "Every Measurement is about
#   exactly one Quality or Disposition and has exactly one hasTime."
#   hasTime is now notNull (NOT_NULL_PROPERTIES; declared notNull in
#   recipe_schema.py). It was an optional Date, so a Measurement without a
#   time was accepted and mealplanner/inventory.py then silently ignored it
#   when choosing a baseline -- found by our own audit and again by external
#   review. "About exactly one Quality" is NOT enforced: isAboutQuality is
#   single-valued but optional (the 2a check even tests it for emptiness).
#   A Measurement also now needs a unit whenever it has a numeric value
#   (quantity_needs_a_unit), which the inventory engine relies on.
# 10: a modelling rule about has-member-part vs has-continuant-part vs
#   located-in. A convention for how to model, not a property of stored
#   data that anything could check; nothing enforces it and nothing could.
# 14a: "unaccounted is a derived diagnostic, never a validity condition."
#   Satisfied vacuously: no code rejects a Process on it. The diagnostic
#   itself is only computed in scripts/06d's sanity check, not as a
#   reusable function.
# 25: equipment exclusivity per Equipment Type -- needs an exclusivity
#   flag on Equipment Types and an overlap check across Processes'
#   temporal regions; neither is built.
# 27: a leftover-consuming entry can't be scheduled before its source
#   Process completes, nor after the leftover's effective expiration --
#   needs the same source-surplus and expiry machinery as 23/24; not built.
#
# 30 (partial): "A NutritionTarget and its rollup must share nutrient and
#   quantity kind; bounds state inclusive/exclusive; daily scope states
#   its day-boundary rule." mealplanner/nutrition_scope.py applies the
#   day-boundary and quantity-kind parts at EVALUATION time, not write
#   time: a daily target whose dayBoundaryRule isn't "midnight", or whose
#   range isn't in grams, is reported as unsupported rather than
#   evaluated. Not enforced when the target is written, and inclusive/
#   exclusive bounds aren't modeled at all (both bounds are treated as
#   inclusive). The rollup itself is now computed at each target's
#   declared scope (daily/weekly/per_meal), which is what the invariant's
#   "rollup" refers to.

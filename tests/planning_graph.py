"""A small kitchen in the in-memory graph, for testing extraction and commit.

Builders mirror the shapes the real graph has (Plan -> Step -> Specification ->
QuantitySpecification; output type -> NutrientProfile; MealPlan -> entries and
constraints), so mealplanner/planning/extract.py reads it through the same engines
it uses on Structr.
"""

from tests.fakegraph import FakeGraph, Ref, at


def add_type(g: FakeGraph, name: str, parent: str | None = None) -> str:
    g.add("DomainType", name, name, parent=Ref(parent) if parent else None, children=[], defaultSpecifications=[],
          stockPoliciesApplying=[], nutrientProfilesAbout=[], foodsOfThisOrigin=[])
    if parent:
        g.nodes[parent]["children"].append(Ref(name))
    return name


def new_kitchen() -> FakeGraph:
    g = FakeGraph()
    for name in ("Protein", "Mass"):
        add_type(g, name)
    g.add("MealPlan", "week", "the week", hasEntry=[], hasConstraint=[], timeBudgetMinutes=30.0, timeBudgetWeight=0.6,
          varietyWeight=0.0)
    return g


def add_recipe(g, name, *, output_grams, protein_per_100g, provenance, yield_servings, minutes, meal_types=("Dinner",),
               inputs=(), difficulty=None, retired=False, with_yield=True):
    """One recipe: `inputs` is [(ingredient type, grams)]; it makes `output_grams` of an output type
    that carries a protein profile of `protein_per_100g` per 100 g."""
    out = add_type(g, f"{name} (dish)")
    profile_id = f"profile {name}"
    g.add("NutrientProfile", profile_id, forNutrient=Ref("Protein"), basis="per_100g", amount=protein_per_100g,
          provenance=provenance)
    g.nodes[out]["nutrientProfilesAbout"].append(Ref(profile_id))
    for meal in meal_types:
        if meal not in g.nodes:
            g.add("Concept", meal, meal)
    g.add("RecipeIdentity", f"recipe {name}", isRetired=retired, hasMealType=[Ref(m) for m in meal_types])
    specs = []
    g.add("QuantitySpecification", f"q out {name}", value=output_grams, unit="g")
    g.add("Specification", f"out {name}", hasParticipationRole="output", specifies=Ref(out),
          hasSpecifiedQuantity=Ref(f"q out {name}"), isOptional=False)
    specs.append(Ref(f"out {name}"))
    for i, (type_name, grams) in enumerate(inputs):
        if type_name not in g.nodes:
            add_type(g, type_name)
        g.add("QuantitySpecification", f"q in{i} {name}", value=grams, unit="g")
        g.add("Specification", f"in{i} {name}", hasParticipationRole="input", specifies=Ref(type_name),
              hasSpecifiedQuantity=Ref(f"q in{i} {name}"), isOptional=False)
        specs.append(Ref(f"in{i} {name}"))
    g.add("Step", f"step {name}", hasSpecification=specs)
    fields = dict(steps=[Ref(f"step {name}")], specializationOf=Ref(f"recipe {name}"), estimatedDurationMinutes=minutes,
                  referencedByEntries=[])
    if difficulty:
        fields["difficultyRating"] = difficulty
    if with_yield:
        g.add("QuantitySpecification", f"yield {name}", value=yield_servings, unit="servings")
        fields["hasRecipeYield"] = Ref(f"yield {name}")
    g.add("Plan", name, name, **fields)
    return name


def add_target(g, name, minimum, maximum, *, scope="daily", strictness="hard", weight=0.2, unit="g"):
    g.add("QuantitySpecification", f"range {name}", minValue=minimum, maxValue=maximum, unit=unit)
    g.add("NutritionTarget", name, name, forNutrient=Ref("Protein"), hasTargetRange=Ref(f"range {name}"),
          hasTimeScope=scope, dayBoundaryRule="midnight", strictness=strictness, weight=weight)
    g.nodes["week"]["hasConstraint"].append(Ref(name))
    return name


def add_entry(g, name, plan, start_iso, *, servings=None, skipped=False, week="week", leftover_of=None):
    g.add("TemporalRegion", f"region {name}", hasBeginning=start_iso)
    fields = dict(isAbout=Ref(f"region {name}"), isSkipped=skipped, memberOf=Ref(week) if week else None)
    if leftover_of:
        fields["consumesLeftoverFrom"] = Ref(leftover_of)
    else:
        fields["references"] = Ref(plan)
        fields["hasPlannedServings"] = servings
        g.nodes[plan]["referencedByEntries"].append(Ref(name))
    g.add("MealPlanEntry", name, name, **fields)
    if week:
        g.nodes[week]["hasEntry"].append(Ref(name))
    return name


def add_portion(g, name, type_name, grams, hour_iso=None):
    if type_name not in g.nodes:
        add_type(g, type_name)
    g.add("PortionOfSubstance", name, name, instanceOf=Ref(type_name), bearerOf=[Ref(f"q {name}")], allocationsAbout=[])
    g.add("Quality", f"q {name}", hasKind=Ref("Mass"), inheresIn=Ref(name), measurements=[Ref(f"m {name}")])
    g.add("Measurement", f"m {name}", status="observed", hasTime=hour_iso or at(25, 0), value=grams, unit="g")
    return name


class Recorder:
    """Stands in for the write side of a client: upsert() records what would be written."""

    def __init__(self):
        self.writes = []

    def upsert(self, type_name, key, value, fields):
        self.writes.append((type_name, value, dict(fields)))
        return f"{type_name}:{value}"

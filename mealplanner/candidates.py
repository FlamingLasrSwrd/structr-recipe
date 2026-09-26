"""What a recipe needs, excludes and is tagged for: the candidate-side facts
both the selector (scripts/11c_simple_selector.py) and the planner
(mealplanner/planning) filter and score by.

Moved out of the selector script so a library does not import from a demo.
Behaviour is unchanged; see data-model.md Sec 18 J6 and J10 for what the
exclusion rules mean.
"""

from __future__ import annotations

from mealplanner.material_accounting import plan_specifications
from mealplanner.scoring import number
from mealplanner.typetree import subtypes_of


def banned_by(client, target_id: str) -> set[str]:
    """Every DomainType an exclusion of `target_id` bans.

    Transitive in both hierarchies. For an excluded type T:
      1. T and every DESCENDANT of T are banned (excluding Tree Nut bans
         a sub-origin such as Cashew; excluding Beef bans every kind of
         beef).
      2. Every food whose Biological Origin is T or any descendant of T
         is banned, together with that food's own descendants (a roasted
         form of an excluded nut is still that nut).
    Found by external review: this used to ban only T and foods linked
    DIRECTLY to T, so a food whose origin was a child of the excluded
    origin, or a subtype of an excluded food, slipped through -- for an
    allergy, the dangerous direction to be wrong in.

    Not banned: a type ABOVE an excluded one. A recipe that calls for
    generic "Poultry" while only chicken is excluded can be made with
    something else, so it isn't a hard violation; a recipe that names the
    excluded type itself is."""
    banned_roots = subtypes_of(client, target_id)
    banned = set(banned_roots)
    for root_id in banned_roots:
        for food in client.get_all("DomainType", root_id)["result"].get("foodsOfThisOrigin", []):
            banned |= subtypes_of(client, food["id"])
    return banned


def excluded_domain_type_ids(client) -> set[str]:
    """Every DomainType a HARD ExclusionConstraint bans."""
    excluded: set[str] = set()
    for ec in client.get_all("ExclusionConstraint")["result"]:
        if ec.get("strictness") == "hard" and ec.get("appliesTo"):
            excluded |= banned_by(client, ec["appliesTo"]["id"])
    return excluded


def soft_exclusions(client) -> list[tuple[str, float, set[str]]]:
    """(constraint name, weight, banned type ids) for every SOFT
    ExclusionConstraint. These used to do nothing at all: ExclusionConstraint
    inherits strictness and weight from PlanningConstraint, but only "hard"
    was ever read, so a soft exclusion was silently inert (found by external
    review). A soft exclusion is a preference against, not a ban: a candidate
    that needs a banned type loses `weight` from its score."""
    out = []
    for ec in client.get_all("ExclusionConstraint")["result"]:
        if ec.get("strictness") == "soft" and ec.get("appliesTo"):
            out.append((ec["name"], number(ec.get("weight"), 0.0), banned_by(client, ec["appliesTo"]["id"])))
    return out


def candidate_meal_types(client, plan: dict) -> set[str]:
    """The Concept names (e.g. {"Dinner"}) the Plan's RecipeIdentity is
    tagged with. A Plan with no specializationOf, or a RecipeIdentity
    with no tags at all, returns an empty set -- deliberately: an
    untagged recipe (a prep step, a structural test fixture) never
    matches a meal-type filter, which is what keeps it out of the
    candidate pool without needing a separate "is this a real meal"
    concept."""
    recipe_ref = plan.get("specializationOf")
    if not recipe_ref:
        return set()
    recipe = client.get_all("RecipeIdentity", recipe_ref["id"])["result"]
    return {c["name"] for c in recipe.get("hasMealType", [])}


def candidate_consumed_types(client, plan: dict) -> set[str]:
    """The DomainTypes a cook would actually use or eat, for exclusion
    purposes: the types named by INPUT and OUTPUT Specifications that are not
    optional.

    It used to be every Specification's type regardless of role. That
    rejected a recipe for an excluded INSTRUMENT (equipment isn't eaten) and
    for an OPTIONAL ingredient (it can simply be omitted), which are wrong
    the other way from the allergy bug. Outputs count because the finished
    dish is what is eaten: a recipe whose output is an excluded type makes
    it. Intermediates are included as outputs too, conservatively."""
    consumed = set()
    for spec in plan_specifications(client, plan):
        if spec.get("hasParticipationRole") == "instrument" or spec.get("isOptional"):
            continue
        if spec.get("specifies"):
            consumed.add(spec["specifies"]["id"])
    return consumed


def candidate_optional_types(client, plan: dict) -> set[str]:
    """Types the recipe lists only as optional input, for a note: a recipe
    with an excluded OPTIONAL ingredient isn't rejected, but the user should
    be told to leave it out."""
    return {
        spec["specifies"]["id"] for spec in plan_specifications(client, plan)
        if spec.get("isOptional") and spec.get("hasParticipationRole") == "input" and spec.get("specifies")
    }


def active_nutrition_targets(client, meal_plan: dict) -> list[dict]:
    return [
        client.get_all("NutritionTarget", c["id"])["result"]
        for c in meal_plan.get("hasConstraint", [])
        if c["type"] == "NutritionTarget"
    ]

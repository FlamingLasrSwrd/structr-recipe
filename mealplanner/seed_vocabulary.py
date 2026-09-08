"""Starting seed vocabulary -- build order step 5.

Scope: the bare minimum needed for ONE recipe, the model's own worked
example (data-model.md Sec 10: braising a chicken breast). Per CLAUDE.md,
this is "real curation work, not a formality" -- these are real
vocabulary entries (no TEST prefix), not spike/probe data.

Values (the 0.75 yield ratio) are PLACEHOLDERS, not sourced from
USDA/FDC yet -- flagged explicitly in each entry's name/description
rather than silently presented as verified. Real FDC sourcing is a
follow-up pass, not done here.

Multi-hierarchy resolution (see conversation record): a food type
belongs to exactly ONE DomainType-hierarchy chain (Food Identity here);
a SEPARATE Perishability classification is a distinct fact, not a
second parent of the same DomainType node ("Reading A" -- matches
data-model.md Sec 1's AP Flour example literally). Chicken Breast (raw)
and Chicken Breast (braised) each get one Food-Identity placement AND
one independent Perishability placement below.
"""

PLACEHOLDER_NOTE = "[PLACEHOLDER -- not sourced from USDA/FDC yet]"

# (hierarchy_name, single_parent)
HIERARCHIES: list[tuple[str, bool]] = [
    ("Food Identity", True),
    ("Perishability Class", True),
    ("Transformation Method", True),
    ("Capability", True),
    ("Equipment Type", True),
    ("Container Type", True),
    ("Nutrient", True),
    ("Default Kind", True),
    # Quality kinds (data-model.md Sec 2's literal examples: mass,
    # volume, density, cleanliness, opened_status). Flat for this
    # minimal pass -- no subsumption depth needed yet, just enough for
    # HAS_KIND/StateRequirement.targetsProperty to point at.
    ("Quality Kind", True),
    # Role kinds -- data-model.md Sec 2 also lists "reservation roles"
    # under Role, alongside Culinary-Role types.
    ("Role Kind", True),
]

# (name, hierarchy, parent_name_or_None, is_lookup_bearing)
DOMAIN_TYPES: list[tuple[str, str, str | None, bool]] = [
    # Food Identity
    ("Poultry", "Food Identity", None, True),
    ("Chicken Breast (raw)", "Food Identity", "Poultry", True),
    ("Chicken Breast (braised)", "Food Identity", "Poultry", True),
    # Perishability Class -- independent facts, not sub-nodes of the
    # Food Identity types above (see module docstring).
    ("Fresh Meat", "Perishability Class", None, True),
    ("Cooked Leftover", "Perishability Class", None, True),
    # Transformation Method
    ("Wet-Heat Method", "Transformation Method", None, True),
    ("Braising", "Transformation Method", "Wet-Heat Method", True),
    # Capability (BFO Function)
    ("Capability", "Capability", None, True),
    ("Heating", "Capability", "Capability", True),
    # Equipment Type
    ("Dutch Oven", "Equipment Type", None, True),
    # Container Type
    ("Tray", "Container Type", None, True),
    # Nutrient (BFO Quality)
    ("Protein", "Nutrient", None, True),
    # Default Kind -- not lookup-bearing itself (these are the kind
    # markers DefaultSpecification.hasKind points at, not something
    # subsumption-walked in their own right for this minimal set).
    ("Yield", "Default Kind", None, False),
    # The remaining Default-Kind types data-model.md Sec 8 names
    # explicitly, added for completeness while touching this area.
    ("Density", "Default Kind", None, False),
    ("MassPerUnit", "Default Kind", None, False),
    ("PurchaseQuantity", "Default Kind", None, False),
    ("Duration", "Default Kind", None, False),
    ("RetentionFactor", "Default Kind", None, False),
    ("NutrientAmount", "Default Kind", None, False),
    # Quality Kind -- same reasoning, not lookup-bearing for this pass.
    ("Mass", "Quality Kind", None, False),
    ("Cleanliness", "Quality Kind", None, False),
    ("OpenedStatus", "Quality Kind", None, False),
    ("ShelfLife", "Quality Kind", None, False),  # Disposition kind, not a Quality, but same flat pattern
    ("Reservation", "Role Kind", None, False),
]

# One real DefaultSpecification: the braising yield factor for raw
# chicken breast -> braised chicken breast, from data-model.md Sec 10's
# worked example (500g in -> 375g out = 0.75).
YIELD_DEFAULT = {
    "name": f"Braising yield factor for Chicken Breast (raw) {PLACEHOLDER_NOTE}",
    "for_type": "Chicken Breast (raw)",
    "has_kind": "Yield",
    "keyed_by": ["Braising"],
    "target_type": "Chicken Breast (braised)",
    "value": {
        # No comma in this name -- Structr's exact-match REST query on
        # `name` silently returns zero results when the value contains
        # a literal comma (confirmed empirically; see cheatsheet). That
        # broke upsert-by-name here and produced a duplicate node on
        # the second run before this was found and fixed.
        "name": f"0.75 yield ratio for Chicken Breast (raw) via Braising {PLACEHOLDER_NOTE}",
        "value": 0.75,
        "unit": "ratio",
        "status": "default",
    },
}

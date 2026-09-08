"""Breadth-test recipes -- exercising mechanisms the chicken-breast
worked example didn't touch. Everything here is exploratory, not
curated vocabulary: every DomainType and instance is name-prefixed
"TEST -- " so it's never mistaken for real seed data, per the same
convention used throughout this build. Real, permanent hierarchy
CONTAINERS (Food Identity, Transformation Method, etc.) are reused
as-is; only the member DomainTypes added here are test-marked.

Recipe 1 -- Boiled Pasta: yield FACTOR > 1 (water absorption), the
  other direction from the chicken breast's 0.75. Numbers taken
  directly from data-model.md Sec 5.1's own worked table (454g dry ->
  expected 908g -> actual 900g, unaccounted -8g -- the negative-sign
  case, untested until now).

Recipe 2 -- Diced Onion: DiscreteWholeItem, imputed Measurement via
  resolveDefault(MassPerUnit) (the "never weighed" case, F1's whole
  reason for existing -- built into the resolveDefault spike with
  probe data in step 3, but never exercised with real instance data
  until now), then a division/trimming transformation with its own
  yield factor. Numbers from data-model.md Sec 5.1's table (180g
  imputed -> 162g actual, yield 0.90, unaccounted 0).

Scenario 3 -- Culinary Role substitution (data-model.md Sec 5.3):
  Specification.specifies pointing at a Culinary Role type instead of
  a specific Food-Identity type ("any baking fat"), plus the
  may_bear_role relation (Food-Identity Type -> Culinary Role type)
  that lets similarity be computed over Culinary Role later. Structural
  proof only -- not a full recipe, since the similarity computation
  itself is query-time application logic, out of scope here.
"""

P = "TEST -- "

# ---- Recipe 1: Boiled Pasta -------------------------------------------

PASTA_HIERARCHIES = [
    ("Dry Goods", "Perishability Class"),
]

PASTA_DOMAIN_TYPES = [
    # (name, hierarchy, parent_name_or_None)
    ("Pasta (dry)", "Food Identity", None),
    ("Pasta (cooked)", "Food Identity", None),
    ("Boiling", "Transformation Method", "Wet-Heat Method"),  # real parent
]

PASTA_YIELD = {
    "for_type": "Pasta (dry)",
    "has_kind": "Yield",
    "keyed_by": ["Boiling"],
    "target_type": "Pasta (cooked)",
    "value": 2.00,
}

PASTA_INPUT_MASS_G = 454.0
PASTA_EXPECTED_OUTPUT_G = PASTA_INPUT_MASS_G * PASTA_YIELD["value"]  # 908.0
PASTA_ACTUAL_OUTPUT_G = 900.0  # data-model.md's own table value -- water loss, not full absorption

# ---- Recipe 2: Diced Onion ---------------------------------------------

ONION_HIERARCHIES = [
    ("Produce", "Perishability Class"),
    ("Mechanical Method", "Transformation Method"),
]

ONION_DOMAIN_TYPES = [
    ("Yellow Onion", "Food Identity", None),
    ("Prepared Onion", "Food Identity", None),
    ("Peeling and Dicing", "Transformation Method", "Mechanical Method"),
]

ONION_MASS_PER_UNIT = {
    "for_type": "Yellow Onion", "has_kind": "MassPerUnit", "keyed_by": [], "value": 180.0,
}
ONION_YIELD = {
    "for_type": "Yellow Onion", "has_kind": "Yield", "keyed_by": ["Peeling and Dicing"],
    "target_type": "Prepared Onion", "value": 0.90,
}
ONION_ACTUAL_OUTPUT_G = 162.0  # matches data-model.md's table exactly (180 x 0.90)

# ---- Scenario 3: Culinary Role substitution -----------------------------

# "Culinary Role" is a genuine, permanent hierarchy per Sec 3's table --
# but TEST-prefixed here anyway, per this session's explicit instruction
# to mark everything from this breadth-testing pass as test data. A real
# curation pass would create it unprefixed.
CULINARY_ROLE_HIERARCHY = f"{P}Culinary Role"

CULINARY_ROLE_TYPES = [
    # (name, parent_name_or_None) -- all within Culinary Role hierarchy
    ("Baking Fat", None),
]

# Food-Identity types that may_bear_role Baking Fat (Sec 5.3's own
# example: butter and margarine sit far apart in Food Identity, close
# together in Culinary Role).
ROLE_BEARING_FOOD_TYPES = [
    # (name, hierarchy, parent_name_or_None)
    ("Butter", "Food Identity", None),
    ("Margarine", "Food Identity", None),
]

MAY_BEAR_ROLE_LINKS = [
    ("Butter", "Baking Fat"),
    ("Margarine", "Baking Fat"),
]

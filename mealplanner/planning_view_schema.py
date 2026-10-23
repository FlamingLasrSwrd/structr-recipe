"""A narrow view of the recipes' stored figures, for the planner's read (the owner's decision,
2026-10-23: about 1,000 recipes is a reasonable home book).

  NutrientProfile view "planning": id, type, name, amount, unit, basis, provenance, source,
      forNutrient, servingOf

Planning a week reads every recipe's stored figures per serving (data-model.md J28) in one
filtered listing. At 1,001 recipes that listing was 145 s of a 228 s read: about 28,000 rows,
read in the `all` view, which resolves every relationship each row has (allocationsAbout,
grantees, identifiers, isAbout, ...). A page of 500 took 4.3 s in it, and 1.7 s in the default
view, which holds only id, type and name. This view holds what the planner reads of a stored
figure and nothing else (nutrition_scope.stored_figure). Verified on Structr 6.0.0
(2026-10-23): a SchemaView lists its own properties as `schemaProperties` and the others (built-in
and relationship properties) by name in `nonGraphProperties`; a related node of a type without
the view comes back as {id, type, name}; asking for a view a type does not have is a 404.
"""

VIEW = "planning"
TYPE = "NutrientProfile"
SCHEMA_PROPERTIES = ("amount", "unit", "basis", "provenance", "source")
OTHER_PROPERTIES = ("id", "type", "name", "forNutrient", "servingOf")

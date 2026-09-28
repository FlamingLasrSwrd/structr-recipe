"""Schema for stock instantiated from a pantry profile (data-model.md Sec 4.1, Sec 18 J26).

  Measurement -[WAS_DERIVED_FROM]-> QuantitySpecification
      PROV `wasDerivedFrom`, as Sec 4.1 uses it: an `imputed` Measurement is about
      an instance's own Quality and derived from the QuantitySpecification it
      resolved (invariant 2b: exactly one). Named by the model since Rev. 4 and
      never built, because nothing wrote imputed Measurements until the owner's
      stock on hand could be instantiated from a pantry profile. Many to one: one
      profile amount is the source of every pantry that includes it.
"""

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Measurement", "WAS_DERIVED_FROM", "QuantitySpecification", "*", "1", "imputedMeasurements", "wasDerivedFrom"),
]

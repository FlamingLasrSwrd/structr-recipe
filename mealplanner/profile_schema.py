"""Schema for instantiated profiles (mealplanner/profiles.py, data-model.md Sec 18 J22).

  NutritionTarget.source    where an instantiated target came from: the dietary
                            profile and its sources, or the owner's own override
  EquipmentObject.source    the same for a piece of the owner's equipment
  UtensilSet -[HAS_MEMBER_PART]-> EquipmentObject
                            BFO `has member part` (Sec 7), the model's relation
                            for an Object Aggregate and its members: the owner's
                            kitchen is a UtensilSet whose members are the tools
                            in it. UtensilSet has been a structural type since
                            step 1 with nothing declared on it; a tool belongs
                            to at most one set.
"""

PROPERTIES: dict[str, list[dict]] = {
    "NutritionTarget": [{"name": "source", "propertyType": "String"}],
    "EquipmentObject": [{"name": "source", "propertyType": "String"}],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("UtensilSet", "HAS_MEMBER_PART", "EquipmentObject", "1", "*", "memberOfSet", "hasMemberPart"),
]

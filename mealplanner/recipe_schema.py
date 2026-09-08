"""Schema additions for build order step 6: the plan side, real
inventory, and execution. All additive to what steps 1-4 built -- no
renames, no new traits on already-instantiated types (new relationships
are declared on ABSTRACT traits where possible, confirmed safe by an
isolated probe: a brand-new relationship with an abstract trait as its
SOURCE works for both pre-existing and freshly-created concrete
instances, since the trait itself was never newly added to those
instances -- this differs from the retroactive-labeling trap, which is
about a type GAINING a trait after having instances).

Design notes:
- INSTANCE_OF is the relation label for the model's own "instance_of a
  <Type>" wording (FoodObject, ContainerObject, EquipmentObject, Step)
  -- reused across sources, each with a distinct reverse name.
- HAS_KIND is reserved for BFO kind-reification (build-sketch Sec 3):
  Quality/Role/Disposition/Function all inherit ONE declaration on the
  shared abstract SpecificallyDependentContinuant trait (they're all
  its descendants), rather than 4 separate declarations -- a
  simplification found while scoping this, not present in the original
  spike. Process needs its own (different branch of the BFO tree).
- HAS_PERISHABILITY_TYPE is the second half of "Reading A" (see the
  conversation record / seed_vocabulary.py docstring): a food's
  Perishability classification is a fact independent of its Food
  Identity placement, not a second parent of the same DomainType node.
"""

PROPERTIES: dict[str, list[dict]] = {
    "RecipeIdentity": [
        {"name": "isRetired", "propertyType": "Boolean"},
    ],
    "Measurement": [
        # Numeric `value` already exists (step 4). `literalValue` is new
        # -- for categorical Qualities (opened_status, cleanliness) that
        # have no numeric magnitude, found necessary while trying to
        # actually build the worked example's StateRequirement(cleanliness
        # = clean) and ContainerObject.opened_status.
        {"name": "literalValue", "propertyType": "String"},
        # invariant 2 requires exactly one hasTime -- missed in step 4,
        # only surfaced now while building real Measurement instances.
        {"name": "hasTime", "propertyType": "Date", "format": "yyyy-MM-dd'T'HH:mm:ssZ"},
    ],
    "Specification": [
        {"name": "hasParticipationRole", "propertyType": "Enum", "format": "input,output,instrument"},
        {"name": "isOptional", "propertyType": "Boolean"},
    ],
    "StateRequirement": [
        {"name": "expectedValueLiteral", "propertyType": "String"},
    ],
    "Allocation": [
        {"name": "hasParticipationRole", "propertyType": "Enum", "format": "input,output,instrument"},
    ],
    "TemporalRegion": [
        {"name": "hasBeginning", "propertyType": "Date", "format": "yyyy-MM-dd'T'HH:mm:ssZ"},
        {"name": "hasEnd", "propertyType": "Date", "format": "yyyy-MM-dd'T'HH:mm:ssZ"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # -- Plan side --
    ("Plan", "SPECIALIZATION_OF", "RecipeIdentity", "*", "1", "planVersions", "specializationOf"),
    ("Plan", "HAS_STEP", "Step", "1", "*", "plan", "steps"),
    ("Plan", "HAS_RECIPE_YIELD", "QuantitySpecification", "*", "1", "recipeYieldOfPlans", "hasRecipeYield"),
    ("Step", "HAS_SPECIFICATION", "Specification", "1", "*", "step", "hasSpecification"),
    ("Specification", "HAS_STATE_REQUIREMENT", "StateRequirement", "1", "*", "specification", "hasStateRequirement"),
    ("Specification", "HAS_SPECIFIED_QUANTITY", "QuantitySpecification", "*", "1", "specificationsWithThisQuantity", "hasSpecifiedQuantity"),
    ("StateRequirement", "TARGETS_PROPERTY", "DomainType", "*", "1", "targetedByStateReqs", "targetsProperty"),
    ("StateRequirement", "EXPECTED_VALUE_QTY", "QuantitySpecification", "*", "1", "expectedValueOfStateReqs", "expectedValueQty"),
    # -- instance_of family (reused label, distinct reverse names) --
    ("FoodObject", "INSTANCE_OF", "DomainType", "*", "1", "foodInstances", "instanceOf"),
    ("ContainerObject", "INSTANCE_OF", "DomainType", "*", "1", "containerInstances", "instanceOf"),
    ("EquipmentObject", "INSTANCE_OF", "DomainType", "*", "1", "equipmentInstances", "instanceOf"),
    ("Step", "INSTANCE_OF", "DomainType", "*", "1", "stepInstances", "instanceOf"),
    ("Specification", "SPECIFIES", "DomainType", "*", "1", "specifiedBySpecs", "specifies"),
    # -- Reading A: independent Perishability classification --
    ("FoodObject", "HAS_PERISHABILITY_TYPE", "DomainType", "*", "1", "perishabilityInstances", "hasPerishabilityType"),
    # -- BFO kind-reification, one shared declaration on the abstract
    #    SDC trait covers Quality/Role/Disposition/Function --
    ("SpecificallyDependentContinuant", "HAS_KIND", "DomainType", "*", "1", "sdcInstances", "hasKind"),
    ("Process", "HAS_KIND", "DomainType", "*", "1", "processInstances", "hasKind"),
    # -- BFO-native inherence, also shared on the SDC trait --
    ("SpecificallyDependentContinuant", "INHERES_IN", "IndependentContinuant", "*", "1", "bearerOf", "inheresIn"),
    # -- Measurement is about a Quality (build-sketch Sec 6's own table) --
    ("Measurement", "IS_ABOUT_QUALITY", "Quality", "*", "1", "measurements", "isAboutQuality"),
    # -- containment, not parthood (bfo-reference.md Sec 2.2) --
    ("FoodObject", "LOCATED_IN", "ContainerObject", "*", "1", "contents", "locatedIn"),

    # -- Sec 5.3: a Food-Identity Type MAY bear a Culinary Role
    #    (possibility, not "every instance currently plays this role").
    #    Self-referential on DomainType, but a DIFFERENT relationship
    #    type than SUBCLASS_OF, so no reverse-name collision -- both
    #    "children"/"parent" (SUBCLASS_OF) and whatever this uses stay
    #    distinct because they're different relationshipType labels
    #    even though both are DomainType->DomainType.
    ("DomainType", "MAY_BEAR_ROLE", "DomainType", "*", "*", "canBeBorneBy", "mayBearRole"),

    # -- execution (Sec 10's worked example, EXECUTION block) --
    # concretizes: Process -> Plan directly (the model's fuller
    # definition targets any GDC; scoped to Plan since that's this
    # build's actual case).
    ("Process", "CONCRETIZES", "Plan", "*", "1", "executions", "concretizes"),
    ("Process", "OCCUPIES_TEMPORAL_REGION", "TemporalRegion", "*", "1", "processes", "occupiesTemporalRegion"),
    # has_input / has_participant target the polymorphic Entity root,
    # reusing the pattern step 2 already proved works (both for
    # pre-existing and fresh instances of different concrete types).
    ("Process", "HAS_INPUT", "Entity", "*", "*", "processesUsingAsInput", "hasInput"),
    ("Process", "HAS_PARTICIPANT", "Entity", "*", "*", "processesWithParticipant", "hasParticipant"),
    # realizes targets the abstract RealizableEntity trait -- same
    # target-is-abstract-trait pattern already proven safe (step 2).
    ("Process", "REALIZES", "RealizableEntity", "*", "*", "realizedByProcesses", "realizes"),
    ("Process", "QUALIFIED_USAGE", "Allocation", "1", "*", "process", "qualifiedUsage"),
    ("Process", "QUALIFIED_GENERATION", "Allocation", "1", "*", "generatingProcess", "qualifiedGeneration"),
    ("Allocation", "FULFILLS", "Specification", "*", "1", "allocations", "fulfills"),
    ("Allocation", "HAS_ACTUAL_QUANTITY", "Measurement", "*", "1", "actualQuantityOfAllocations", "hasActualQuantity"),
    # begins_to_exist_during: Continuant -> Process, scoped to FoodObject
    # as source (abstract-trait-as-source, same proven pattern).
    ("FoodObject", "BEGINS_TO_EXIST_DURING", "Process", "*", "1", "thingsBegunDuring", "beginsToExistDuring"),
]

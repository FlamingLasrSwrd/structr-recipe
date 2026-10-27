"""Schema for taking turns at a household's bookings (docs/architecture-decision.md §7a, Path S).

  Household.bookingTurn (String)
      Written first by every booking a method makes for the household (pages/common.js bookOnce),
      with a value never written before, so the write always happens: Neo4j then holds it until the
      booking commits, and a second booking for the same household waits there, then finds what the
      first made. Households do not wait on each other. It replaces, for the methods, the pages' lock
      written through Cypher, since a Cypher write made Structr answer 404 to methods called at the
      same moment (docs/structr-cheatsheet.md §3a). Written as the superuser, so members need no right
      to change their household's node. A plain property on an already-populated concrete type, the
      safe kind of addition (scoring_schema.py's notes), not a trait.
"""

PROPERTIES: dict[str, list[dict]] = {
    "Household": [
        {"name": "bookingTurn", "propertyType": "String"},
    ],
}

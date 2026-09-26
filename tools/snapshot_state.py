"""Print the graph's named entities as normalized, sorted JSON, so a build can
be checked against a known-good state.

    python3 tools/snapshot_state.py | diff - tools/expected_state.json

An empty diff means your instance holds exactly what the maintainer's does
after a full build (every script in scripts/, in numeric order). It exists
because the repo once claimed "the scripts are the reproducible source of
truth" while the working instance held about 40 entities and 40 property
values no script produced; a from-scratch rebuild diffed against it is what
found that. Now the claim is something a reviewer can test.

What is compared: every named entity, keyed "Type | name", with its
properties and its relationships (shown as <Type:name>). What is not: ids,
creation/modification stamps, ownership and visibility, and any value that
looks like a timestamp, because test data is built relative to the moment a
script ran.

expected_state.json is a golden file. If you change what a script creates,
regenerate it deliberately (`... > tools/expected_state.json`) and read the
diff in review; a failing diff is the point, not a nuisance.

Needs STRUCTR_SUPERUSER_PASSWORD in the environment; STRUCTR_URL optional.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
IGNORED = {"id", "type", "createdDate", "lastModifiedDate", "createdBy", "lastModifiedBy", "owner", "ownerId",
           "grantees", "visibleToPublicUsers", "visibleToAuthenticatedUsers", "hidden"}
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")


def normalize(value):
    if isinstance(value, dict) and "id" in value:
        return f"<{value.get('type')}:{value.get('name')}>"
    if isinstance(value, list):
        return sorted(str(normalize(v)) for v in value)
    return value


def main():
    client = StructrClient(BASE_URL, "superadmin", os.environ["STRUCTR_SUPERUSER_PASSWORD"])
    client.wait_until_ready()
    entities = {}
    for type_name in sorted(n["name"] for n in client.get("/structr/rest/SchemaNode")["result"]):
        try:
            rows = client.get_all(type_name)["result"]
        except Exception:
            continue  # abstract or unreadable types hold no instances of their own
        for row in rows:
            if not row.get("name"):
                continue
            properties = {}
            for key, value in row.items():
                if key in IGNORED or (value in (None, [], {}, False) and key != "isSkipped"):
                    continue
                if isinstance(value, str) and TIMESTAMP.match(value):
                    continue
                properties[key] = normalize(value)
            # A polymorphic query returns each entity once per supertype; the
            # entity's own concrete type is the one that identifies it.
            entities[f"{row.get('type', type_name)} | {row['name']}"] = properties
    print(json.dumps(entities, indent=1, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()

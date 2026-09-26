"""Step 0/1 verification spike.

Confirms, against THIS live instance, before any real schema is built:
  1. The client can connect and authenticate.
  2. ensure_type is idempotent (create then re-run -> created=False).
  3. The sourceJsonName/targetJsonName inversion, empirically -- don't
     assume it from the cheatsheet, read it back.
  4. Test instance data is clearly marked and cleaned up afterward --
     these are disposable probe types, not part of the real schema.

Run with: python3 scripts/00_verify_client.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)

    print("[1] Waiting for Structr to be ready...")
    client.wait_until_ready()
    print("    OK - REST API responding")

    print("[2] ensure_type idempotency check...")
    id1, created1 = client.ensure_type("ZZ_Probe_A", is_abstract=False)
    id2, created2 = client.ensure_type("ZZ_Probe_A", is_abstract=False)
    assert created1 is True, "first call should create"
    assert created2 is False, "second call should find existing, not duplicate"
    assert id1 == id2, "should return the same node id both times"
    print(f"    OK - created once (id={id1}), second call found existing")

    print("[3] Probe relationship + sourceJsonName/targetJsonName inversion check...")
    probe_b_id, _ = client.ensure_type("ZZ_Probe_B", is_abstract=False)
    rel_id, rel_created = client.ensure_relationship(
        source_id=id1,
        target_id=probe_b_id,
        relationship_type="ZZ_PROBE_REL",
        source_multiplicity="1",
        target_multiplicity="*",
        source_json_name="probeA",
        target_json_name="probeBs",
    )
    print(f"    relationship created={rel_created}")

    # Create one instance of each, clearly marked as test data, and
    # link them, then read back the actual property names Structr
    # produced.
    a_inst = client.post(
        "/structr/rest/ZZ_Probe_A",
        {"name": "TEST -- probe A instance", "visibleToAuthenticatedUsers": True},
    )["result"][0]
    b_inst = client.post(
        "/structr/rest/ZZ_Probe_B",
        {"name": "TEST -- probe B instance", "visibleToAuthenticatedUsers": True},
    )["result"][0]

    # per targetJsonName convention, "probeBs" should land on ZZ_Probe_A
    client.patch(f"/structr/rest/ZZ_Probe_A/{a_inst}", {"probeBs": [b_inst]})

    a_readback = client.get_all("ZZ_Probe_A", a_inst)["result"]
    b_readback = client.get_all("ZZ_Probe_B", b_inst)["result"]

    print(f"    ZZ_Probe_A/{{id}}/all keys touching the relationship: "
          f"probeBs={a_readback.get('probeBs')}")
    print(f"    ZZ_Probe_B/{{id}}/all keys touching the relationship: "
          f"probeA={b_readback.get('probeA')}")

    assert "probeBs" in a_readback and a_readback["probeBs"], (
        "expected targetJsonName ('probeBs') to be the collection property "
        "on the SOURCE type (ZZ_Probe_A) -- inversion did not hold as documented"
    )
    assert "probeA" in b_readback and b_readback["probeA"], (
        "expected sourceJsonName ('probeA') to be the single-reference property "
        "on the TARGET type (ZZ_Probe_B) -- inversion did not hold as documented"
    )
    print("    OK - inversion CONFIRMED on this instance: targetJsonName -> source's "
          "property, sourceJsonName -> target's property")

    print("[4] Cleaning up probe types (disposable, not part of the real schema)...")
    client.delete(f"/structr/rest/ZZ_Probe_A/{a_inst}")
    client.delete(f"/structr/rest/ZZ_Probe_B/{b_inst}")
    client.delete(f"/structr/rest/SchemaRelationshipNode/{rel_id}")
    client.delete(f"/structr/rest/SchemaNode/{id1}")
    client.delete(f"/structr/rest/SchemaNode/{probe_b_id}")
    print("    OK - probe types and instances removed")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()

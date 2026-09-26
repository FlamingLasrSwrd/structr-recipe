# Structr Cheat Sheet

Project-agnostic notes on working with [Structr](https://structr.com) (a
graph-database-backed low-code platform, REST API + StructrScript) via
scripted REST calls rather than the Schema Editor UI. Two kinds of
material here:

- **✅ Verified** — confirmed empirically against a real running instance
  (Structr 6.0.0 Community, Neo4j backend) while building the
  `kobo-nursery`/`structr-ops` project. High confidence.
- **📖 Docs** — from official documentation (docs.structr.com /
  structr.org/docs), not personally re-verified in that project. Good
  starting point, but confirm against your own instance before relying
  on it for anything load-bearing — Structr's docs site is thin in
  places and some behavior (especially edge cases) only shows up in
  practice.

Where the two conflict, trust ✅ over 📖.

---

## 1. Running an instance (Docker)

```yaml
# docker-compose.yml — minimal shape
services:
  neo4j:
    image: neo4j:latest
    environment:
      - NEO4J_AUTH=neo4j/<password>
    volumes: [neo4j-database:/data, neo4j-logs:/logs]
    networks: {structr-network: {aliases: [neo4j]}}
  structr:
    image: structr/structr:6.0.0
    depends_on: [neo4j]
    ports: ["8083:8082"]           # host:container — container always listens on 8082
    environment:
      - AGREE_TO_STRUCTR_PRIVACY_POLICY=yes   # required or Structr won't start
      - STRUCTR_superuser_password=<password>
      - STRUCTR_database_available_connections=neo4j_default
      - STRUCTR_neo4j__default_database_driver=org.structr.bolt.BoltDatabaseService
      - STRUCTR_neo4j__default_database_connection_url=bolt://neo4j:7687
      - STRUCTR_neo4j__default_database_connection_username=neo4j
      - STRUCTR_neo4j__default_database_connection_password=<password>
      - STRUCTR_nodeservice_active=neo4j_default
      - STRUCTR_application_schema_automigration=true
    volumes:
      - structr-files:/var/lib/structr/files
      - structr-repository:/var/lib/structr/repository
      - structr-logs:/var/lib/structr/logs
      - ./structr/license.key:/var/lib/structr/license.key   # empty file is fine for Community
    networks: {structr-network: {}}
```

- ✅ `docker compose down` (no `-v`) stops containers but **preserves
  named volumes** — all schema/data survives a restart. `down -v`
  destroys it. `docker compose up -d` from the same directory brings it
  back exactly as it was.
- ✅ Default UI: `http://localhost:<host-port>/structr/` (note trailing
  slash for the admin UI itself; REST/HTML app routes below don't need
  it).
- 📖 First boot can take 10–30s before the REST API responds — poll
  `GET /structr/rest/SchemaNode` with your credentials until it returns
  200 rather than assuming it's up right after `docker compose up`.
- 📖 A missing/invalid `license.key` file is fine — Structr runs in
  Community edition automatically; you don't need a real license to do
  anything described in this document.
- ✅ **The superuser account created from `STRUCTR_superuser_password`
  is named `superadmin`, not `admin`.** Confirmed on a fresh 6.0.0
  container (this document's §1 compose shape, password set via env
  var): `X-User: admin` with the correct password 401s
  ("Wrong username or password... Note: Username is case sensitive!");
  `X-User: superadmin` with the same password immediately returns 200
  against `GET /structr/rest/SchemaNode`. The container log's "Creating
  initial user..." line doesn't name it, so this isn't discoverable from
  logs — confirmed empirically by trying candidate usernames against a
  live instance (`admin`, `superadmin`, `superuser` — only `superadmin`
  worked).

---

## 2. Authentication

✅ Structr checks credentials in this order (confirmed via docs, matches
observed behavior): **session cookie → JWT in `Authorization` header →
`X-User`/`X-Password` headers → anonymous**.

For scripts (not a browser session), `X-User`/`X-Password` on every
request is simplest:

```python
session = requests.Session()
session.headers.update({
    "X-User": "admin", "X-Password": "admin",
    "Content-Type": "application/json",
})
```

✅ For a real browser session (needed for `visibleToAuthenticatedUsers`
HTML pages to render for a human visitor), the mechanism that actually
works is `POST /structr/rest/login` with a **raw JSON body**
(`{"name": ..., "password": ...}`) — this sets a session cookie the
HTML frontend then honors. Confirmed end-to-end: login → redirect →
full page loads → navigating to a different page (fresh request) still
authenticated.

- ✅ A plain HTML `<form>` submit to `/login`
  (`application/x-www-form-urlencoded` or `multipart/form-data`) gets a
  **400 "Invalid JSON, expecting object or array"** — Structr's login
  endpoint only accepts JSON. If you want a login page with a normal
  HTML form, intercept the submit with a small `fetch()` call instead
  of letting the browser submit it natively.
- ✅ **`Page.enableBasicAuth` does not gate access** on this instance
  (6.0.0 Community) — verified with `curl -v`: `Authorization: Basic
  ...` was sent preemptively and the page still 404'd regardless of
  credentials, unless the page was also `visibleToPublicUsers`. Don't
  rely on it; use real session login instead.
- ✅ **Anonymous users need an explicit `ResourceAccess` grant just to
  reach `/login` at all**, or every login attempt 401s even with fully
  correct credentials:
  ```python
  POST /structr/rest/ResourceAccess
  {"signature": "_login", "flags": 64, "visibleToPublicUsers": True}
  ```
  `flags=64` was empirically confirmed to mean "non-authenticated user
  POST" (other bit values tried had no effect until the next point was
  also fixed; not proven to be the *minimal* correct value, just a
  working one).
- ✅ **The `ResourceAccess` grant node itself must also be
  `visibleToPublicUsers`.** This is the single easiest thing to miss:
  a `ResourceAccess` grant is still a normal node subject to normal
  visibility rules. If it's invisible to an anonymous request, the
  authorization check can't see the grant exists at all, and every
  anonymous request 401s regardless of `flags` — confirmed by setting
  `flags=255` (every bit) first with zero effect, then adding
  `visibleToPublicUsers=True` and immediately getting a working login.

📖 Full permission resolution order per the docs (not independently
re-verified beyond what's above): admin bypass → visibility flags
(`visibleToPublicUsers`/`visibleToAuthenticatedUsers`) → ownership →
direct `SECURITY` relationship grants → schema-level group grants →
graph-relationship-path resolution. Stops at first match.

### Node-level visibility — the default is a trap

✅ **New nodes default to owner-only visibility.** Neither
`visibleToPublicUsers` nor `visibleToAuthenticatedUsers` is set unless
you set it explicitly. A node created this way is **invisible to
everyone but its creator** — including your own later API calls if
they authenticate as a different user, and any page's `find()` script.
The failure mode is silent: no error, the node (or the whole
collection) just doesn't show up. Always decide and set visibility
explicitly on every write:

```python
payload["visibleToAuthenticatedUsers"] = True   # or visibleToPublicUsers
```

---

## 3. Building a schema via REST (not the Schema Editor UI)

Three endpoints, always in this order: type → properties → relationships.

```python
# 1. Create a type
POST /structr/rest/SchemaNode
{"name": "Widget", "isAbstract": false}
# -> {"result": ["<schema-node-id>"]}

# 2. Add a property to it
POST /structr/rest/SchemaProperty
{"schemaNode": "<schema-node-id>", "name": "sku", "propertyType": "String",
 "unique": true, "indexed": true, "notNull": true}

# 3. Relate two types
POST /structr/rest/SchemaRelationshipNode
{"sourceId": "<TypeA-id>", "targetId": "<TypeB-id>",
 "relationshipType": "HAS_WIDGET",
 "sourceMultiplicity": "1", "targetMultiplicity": "*",
 "sourceJsonName": "typeA", "targetJsonName": "widgets"}
```

✅ **`sourceJsonName`/`targetJsonName` are inverted from what the names
suggest.** `targetJsonName` ends up as the property on the **source**
type (its way of reaching the target collection); `sourceJsonName` ends
up as the property on the **target** type (its way of reaching back to
the source). In the example above: `TypeA.widgets` (a collection) and
`TypeB.typeA` (a single reference) — read the field names backwards
from what you'd guess. This was the single most expensive gotcha in
this project; get it right the first time by writing a throwaway test
relationship and reading the actual resulting property names back
before building real relationships on top of it.

✅ **`sourceMultiplicity`/`targetMultiplicity` describe cardinality per
participant, not "how many nodes sit on each side of the arrow" the
way the field names suggest at a glance.** `targetMultiplicity` is how
many target instances one source instance may relate to — set it `"1"`
to make the source-side property (`targetJsonName`) a single reference
instead of a collection. `sourceMultiplicity` is how many source
instances may relate to one target instance — set it `"*"` when many
sources can share one target. Confirmed the hard way building
`Allocation -[ABOUT]-> Entity` (one Allocation is about exactly one
Entity; many Allocations may be about the same Entity over time): first
attempt used `sourceMultiplicity: "1", targetMultiplicity: "*"`,
which compiled fine with no error at declaration time, but writing
`{"isAbout": <id>}` to a real Allocation instance failed with
`422 "Invalid JSON input for key isAbout, expected a JSON collection"`
— the multiplicities had made `isAbout` (the property landing on the
source, per the inversion above) a collection property instead of a
single reference. Swapping to `sourceMultiplicity: "*", targetMultiplicity:
"1"` fixed it immediately, no restart needed (the relationship
declaration itself had no live data yet, so this was a clean
delete-and-recreate, not a data migration). No instances existed
before the relationship was corrected, so this cost nothing beyond one
failed write — get the direction right before any real data is
written under a new relationship, the same discipline as the JSON-name
inversion just above.

✅ `propertyType` values used successfully: `String`, `Integer`,
`Double`, `Boolean`, `Date` (needs a `format`, e.g.
`"yyyy-MM-dd'T'HH:mm:ssZ"`), `Enum` (needs a `format`, a comma-joined
string of allowed values, e.g. `"red,green,blue"`).

✅ **Everything here is idempotent-by-hand, not idempotent by default**
— POSTing the same `SchemaNode`/`SchemaProperty`/
`SchemaRelationshipNode` twice creates a duplicate (or errors, for
some). Always check-then-create in your own scripts:

```python
def ensure_type(name):
    existing = get("/structr/rest/SchemaNode", params={"name": name})
    if existing["result"]:
        return existing["result"][0]["id"], False
    created = post("/structr/rest/SchemaNode", json={"name": name})
    return created["result"][0], True
```

This makes your schema-setup script safe to re-run any time you add a
new type — re-running just skips everything that already exists and
only creates what's new. Build this once as a small reusable
`ensure_type`/`ensure_property`/`ensure_relationship` helper; every
schema change after that is just adding entries to a data table, not
writing new procedural code.

### Mutating an existing schema: renaming orphans data, changing a property's shape needs a two-step free-then-recreate

✅ **Renaming a `SchemaNode` (`PATCH /structr/rest/SchemaNode/{id}
{"name": "NewName"}`) orphans every existing instance of that type.**
Confirmed with a throwaway type: create one instance, rename the type,
then query both the old and the new name — the instance is **not**
findable under either one (`404`s by id on both). The instance still
exists somewhere in the underlying graph, but it's unreachable through
the normal type-based REST API, which is what actually matters in
practice. If you need to change what a type is *called* while it has
live data, don't rename it — create the new type, copy every instance's
fields across, repoint every relationship that referenced the old type,
then delete the old type and its now-empty instances. Tedious, but the
only path that doesn't quietly maroon real data.

✅ **A property/relationship can't be changed in place if the change
alters its "shape"** (scalar → relationship, or a relationship's target
type) — Structr won't let two different `SchemaProperty`/
`SchemaRelationshipNode` entries share one JSON name on the same type.
Trying to `ensure_relationship` a new target under a JSON name an old
relationship (or old scalar property) already occupies just fails
silently or errors — the old one has to be explicitly deleted first
(`DELETE /structr/rest/SchemaRelationshipNode/{id}` or `.../
SchemaProperty/{id}`) to free the name before the replacement can be
created. Concretely, changing "a relationship that points at type A" to
"the same-named relationship pointing at type B instead" is: (1) read
every live reference under the *old* relationship first (you'll need
this data — it's gone once you touch step 2), (2) delete the old
`SchemaRelationshipNode`, (3) create the new one under the same JSON
name, (4) write the captured references back in, now pointing at their
new-type equivalents. Doing this against a type with real live data
without capturing step 1 first is how you lose it.

✅ **Renaming just the `relationshipType` *label* — same source, same
target, same JSON names, nothing else different — orphans existing
edges too.** Easy to assume this one's safe since the "shape" (source/
target/JSON names) didn't change at all, only the label. It isn't:
confirmed with a throwaway relationship (`OLD_REL` between two test
types, one real edge), deleting that `SchemaRelationshipNode` and
recreating an identical one under `NEW_REL` — the pre-existing edge is
gone from both directions afterward, same as the `SchemaNode`-rename
case above. Any relationship-label rename with live data needs the same
read-old/delete/create-new/rewrite sequence as a full retargeting, not
just a label swap.

✅ **The one relocation that *is* safe: moving an already-correctly-named
relationship (or property) from a direct per-type declaration onto a
trait the type now inherits, with the label and JSON names both
unchanged.** This is what makes collapsing duplicate declarations onto a
shared trait viable at all. Confirmed by contrast with the rename case
above: declare `SAME_REL` directly on a concrete type, create a real
edge, delete that declaration, then declare the identical `SAME_REL`
(same label, same JSON names) on a new abstract trait the concrete type
now inherits instead — the pre-existing edge is still there, readable
through the inherited relationship. The underlying graph edge is keyed
by the `relationshipType` string itself, not by which `SchemaNode`
currently owns the declaration — so *relocating* a label is free, but
*renaming* one (even keeping everything else identical) is not.

🛑 **Changing which concrete type is the *source* of a relationship
(not just relocating the same declaration onto a trait the same type
already inherits) hits a schema-compilation-cache conflict, not covered
by any of the cases above.** Concretely: type `A` has a live relationship
`REL_NAME` to some target; you want type `B` to have that relationship
instead (a full migration, not a relocation-onto-a-shared-trait). If you
create `B`'s new `REL_NAME` declaration **before** deleting `A`'s old
one, both declarations claim the same JSON property name simultaneously
— even though they're on different source types — and every pre-existing
instance's read of that property silently returns `null` via REST,
including instances that were never touched by the migration and whose
underlying data is completely intact. Confirmed via `docker exec ...
cypher-shell` querying the graph directly (bypassing Structr's REST/
schema-compilation layer entirely): the edges themselves were untouched
the whole time — `MATCH (a)-[r:REL_NAME]->(b) RETURN count(r)` returned
the correct, unchanged count throughout. This is a read-layer/schema-
compilation-cache conflict, not data loss — but it looks exactly like
data loss if you only check via REST.
- Merely deleting the newly-created conflicting declaration again did
  **not** immediately fix it — the compiled schema stayed stale even
  after the conflict was removed.
- `docker restart` of the Structr container **did** fix it, both times
  it was hit (once on a dry run, again on the real migration run, since
  the corrected script still does remove-old-then-create-new within one
  process execution).
- **Practical upshot**: when migrating a relationship's *source type*
  (as opposed to relocating an unchanged declaration onto a newly-
  inherited trait, which is safe per the point above), do the full
  sequence strictly serially and never let old and new declarations
  exist at the same time — read every live reference under the old
  declaration first, delete the old `SchemaRelationshipNode`, create the
  new one, write the captured references back in under the new source
  type, *then* delete the old type. After a real (non-dry-run) migration
  of this shape, expect to need a container restart before trusting any
  REST read of the migrated property, and verify a spot-check reference
  actually resolves correctly post-restart before considering the
  migration done.
- 🛑 **A live spike test run *before* that restart can give a false
  positive, not just a false negative.** Confirmed the hard way: a
  quick `PATCH`-based spike (set a brand-new relationship's property on
  an existing node, read it back) appeared to succeed against a
  pre-existing instance right after a related schema change — looking
  like proof a design worked even for old data. It didn't; the instance
  was mid-way through the same stale-cache window this section
  describes, and a clean re-test via `POST` (not `PATCH`) after a
  restart, in a genuinely settled state, rejected the exact same
  instance. The gap between the two results wasn't the request verb —
  it was testing before vs. after the cache had actually settled.
  **Don't trust a verification spike run in the same breath as the
  schema change it's testing; restart first, then test, especially for
  anything touching a relationship's source type, a newly-added trait
  on an already-instantiated type, or both at once.**

### Inheritance: use `inheritedTraits`, not `extendsClass`

✅ **The real inheritance mechanism in Structr 6.x is a traits-based
multiple-inheritance model, via a field called `inheritedTraits` — not
the classic Java-style `extendsClass`.** This is an easy mistake to make
and worth flagging explicitly: `extendsClass` is accepted silently (no
error), the type gets created, but properties declared on that
"supertype" **never appear on the subtype's REST endpoint** — not in the
create payload, not in `/all`. It looks exactly like "inheritance doesn't
work," and it's tempting to conclude that and move on. It's wrong. The
correct field, confirmed live on any real `SchemaNode`'s own `/all` view
(`"inheritedTraits": [...]`) and in docs.structr.com's Data Model
chapter ("Inheritance" section — "Structr supports multiple inheritance
through traits"), is `inheritedTraits`, a **list** of trait/type names
(order matters for conflict resolution, per docs, when the same
property/method name exists on more than one listed trait):

```python
# Base ("trait") type — usually abstract
POST /structr/rest/SchemaNode  {"name": "Base", "isAbstract": true}
POST /structr/rest/SchemaProperty  {"schemaNode": base_id, "name": "sharedProp", "propertyType": "String", "unique": true}

# Subtype — inherits Base's properties AND relationships
POST /structr/rest/SchemaNode  {"name": "Sub", "inheritedTraits": ["Base"]}
# or, on an EXISTING type:
PATCH /structr/rest/SchemaNode/{sub_id}  {"inheritedTraits": ["Base"]}
```

Confirmed, with `inheritedTraits` used correctly (throwaway
`TraitBase`/`TraitSub` types, cleaned up after):

- ✅ A property declared on the trait shows up correctly on the
  subtype's create payload **and** its `/all` read-back — real
  inheritance, not just schema metadata.
- ✅ A **relationship** declared with the trait as source or target
  (`SchemaRelationshipNode.sourceId`/`targetId` pointing at the trait's
  own id) also propagates: a concrete subtype can set/read that
  relationship's property exactly as if it were declared directly.
- ⚠️ A `unique` (and/or `indexed`) constraint declared on the trait
  applies **globally across every type that inherits it**, not
  per-concrete-type. Two different subtypes cannot both use the same
  value for that property, even though they're different types — a real
  behavior change from declaring the same-named `unique` property
  separately on each type (which is scoped per-type). Confirmed with two
  sibling subtypes of one trait: the second `POST` with a duplicate value
  got a `422` with `"token": "already_taken"`, referencing the *other*
  subtype's node as the conflict. Check your existing data for
  cross-type collisions before migrating a per-type-unique property onto
  a shared trait.
- ✅ To actually collapse duplication (not just add an inherited copy
  alongside an existing direct one), remove each concrete type's own
  direct `SchemaProperty` for the now-shared field(s) — Structr lets a
  direct property silently **override** an inherited one of the same
  name (per docs), which means leaving both in place just defeats the
  point rather than erroring.
- 📖 Per docs, `Views` (see §4) are also inherited from trait to subtype
  — not independently re-verified in this project.
- ✅ **A lifecycle method (`onCreate`) declared on an ABSTRACT trait
  runs automatically for every concrete subtype that inherits it** —
  upgraded from 📖 to ✅ after direct verification (meal-planner
  project): one `onCreate` declared on the abstract `PlanningConstraint`
  trait, tested by POSTing to each of its three concrete, independently-
  declared subtypes (`StockPolicy`, `NutritionTarget`,
  `ExclusionConstraint`) — all three correctly ran the trait's
  validator and rejected the same invalid case (`422`), with zero
  method declarations on any of the concrete types themselves. Same
  propagation mechanism as trait-level properties/relationships,
  confirmed to extend to methods too.

**Takeaway:** if a "does inheritance work" test comes back negative,
suspect the field name before the platform. Verify by reading a real
existing `SchemaNode`'s own `/all` output for the actual field your
version uses, rather than assuming a name from an older version, a
different product, or general Java-ORM conventions.

### Multi-level trait chains, polymorphic targets, and the retroactive-labeling trap

✅ **Trait chains work across multiple levels.** `Leaf` inheriting `Mid`
(`inheritedTraits: ["Mid"]`), where `Mid` itself inherits `Base`
(`inheritedTraits: ["Base"]`), gets properties **and** relationships from
both `Mid` and `Base` — confirmed with a real 3-level chain (`ChainBase`
→ `ChainMid` → `ChainConcrete`), both a property declared two levels up
and a relationship declared one level up showed up correctly on the
leaf's create payload and `/all` read-back.

⚠️ **A comment saying a type "inherits" something is not the same as the
type actually having it in `inheritedTraits`.** Found the hard way: a
middle-of-the-chain abstract type was documented in a code comment as
"inherits Base," but the config line that actually set
`inheritedTraits: ["Base"]` on it was simply never written — a
copy-paste gap between the comment and the code. The bug was silent for
a long time: every leaf type under it still showed a working built-in
`name` property in spot-checks (Structr's `name` exists on every node
regardless of custom traits), so nothing looked wrong. The actual
casualties — a custom property from the missing link, and a `unique`
constraint on `name` — were invisible unless specifically checked for
(`.get("notes") is None` vs. `"notes" not in the response at all`, and
an actual duplicate-write test for the constraint). **Read the literal
`inheritedTraits` value on the real, live `SchemaNode` for every link in
a chain** — don't trust a comment, and don't trust that a spot-check of
one obviously-present field (especially a built-in like `name`) proves
the rest of the chain is wired correctly.

✅ **A missing link like this doesn't just hide a property from the
schema — it silently drops it from REST visibility on writes too, while
the underlying value still gets written correctly.** Found on a second,
independent occurrence of the same missing-link bug: a middle-of-chain
abstract type (call it `Mid`, itself meant to inherit `Base`, which
declares several properties) never actually had `inheritedTraits:
["Base"]` set, so `Mid` — and everything chained through it — had no
schema-level knowledge of `Base`'s properties at all. `POST`ing one of
those properties in the create payload anyway didn't error; the value
was silently accepted and (confirmed after the fix) genuinely persisted
to the underlying graph property — it just didn't come back via any
REST read (`/all` included) until the schema chain was fixed, because
Structr's REST serialization is schema-driven and had no property to
serialize. **The practical upshot is good news, not a data-loss
scenario:** patching the missing `inheritedTraits` link retroactively
restored every existing instance's already-written values with no
migration needed — unlike the polymorphic-target labeling issue above
(which really does leave old instances permanently unable to satisfy a
new trait relationship), a node's *properties* aren't gated by its
Neo4j label set the same way a relationship-target lookup is. Still,
don't assume this generalizes without checking: verify a known-affected
instance's value comes back correctly immediately after patching the
link, the same way this was confirmed here, before concluding "no
migration needed" applies to a different case.

✅ **A relationship can target an *abstract trait*, and any concrete type
that inherits it satisfies the relationship polymorphically** — confirmed
with two sibling subtypes of one fresh abstract trait, both successfully
filling the same relationship slot through one shared declaration.

🛑 **But this does NOT work retroactively.** If a type already has live
instances *before* it gains a new trait, those existing instances cannot
be used as the target of a relationship that polymorphically targets
that trait — only instances created *after* the trait relationship
existed can. Confirmed the hard way against real project data: a
relationship declared as `X → AbstractTrait` accepted a brand-new
instance of a type inheriting `AbstractTrait` immediately, but rejected
every already-existing instance of that same type with `"No
AbstractTrait with UUID ... found"` — reproduced identically whether the
type inherited the trait directly or through a multi-level chain, so
it's not a chain-depth issue. Root cause: **a node's Neo4j label set is
fixed at creation time**; Structr does not retroactively add a newly-
inherited trait's label to instances that already existed when the
`inheritedTraits` change was made, and the polymorphic-target lookup is
resolved by label match. Tried and confirmed **not** to fix it: a full
container restart, a `PATCH` ("touch") on the existing instance
re-setting one of its own fields, and the `rebuildIndex` and
`flushCaches` maintenance commands (`POST
/structr/rest/maintenance/<commandName>`) — both ran successfully
(`result_count: 0`, no error), but a direct Neo4j read of the old
instance's label set (`MATCH (n) WHERE n.id = '...' RETURN labels(n)`)
showed no change at all before or after: still missing the new trait's
label, while a control instance created after the trait existed had it.
`rebuildIndex` rebuilds search indexes for `indexed`/`unique` property
*values* — it has nothing to do with a node's label set, which is what
the polymorphic lookup actually keys on, so this null result matches
what the command is documented to do.

✅ **There IS a real fix, but it has to bypass Structr's REST/schema
layer entirely: add the missing label directly in Neo4j.** Structr's own
docs describe schema and data as "loosely coupled" — a schema change
(rename a property, change a type, restructure relationships) doesn't
migrate existing data, and recommend "a script that updates all affected
nodes." For a property rename that script can just go through Structr's
own REST API (copy the value from the old name to the new one). For a
*label* gained via `inheritedTraits`, it can't — a `PATCH` through the
REST API only ever touches property values, never a node's label set, so
that route (already tried above) does nothing. The label has to be set
directly against the graph: `docker exec <neo4j-container> cypher-shell
-u neo4j -p <pass> "MATCH (n) WHERE n.id = '<uuid>' SET n:<TraitLabel>
RETURN labels(n);"`. Confirmed against the same failing instance from
above: immediately after this one Cypher `SET` — **no Structr restart
needed** — the polymorphic relationship POST succeeded, the read-back
resolved the target correctly, and the instance started showing up in a
plain `GET` against the abstract trait type's own collection endpoint
too (not just the relationship — genuinely, not superficially, an
instance of the trait from Structr's perspective). This is a real,
scriptable migration path: for every old instance that needs to satisfy
a newly-added trait, run one `SET n:<TraitLabel>` per node (matched by
`id`, or in bulk via a `WHERE n:<ExistingConcreteLabel> AND NOT
n:<TraitLabel>` style query for every affected instance at once).

**Practical upshot:** two real options once you need an existing type's
old instances to satisfy a polymorphic target, not just new ones.
(1) **Fall back to one direct relationship declaration per concrete
target type** (reusing the same relationship-type label across all of
them, the same discipline as any other reused relationship) — no
maintenance step required, more declarations, application-layer-only.
(2) **Add the trait's label directly via Neo4j** (`SET n:<TraitLabel>`
per affected node, see above) and keep the single polymorphic
declaration — one write migration, then it behaves identically to a
type that had the trait from day one. Prefer (1) when the retrofit is a
one-time, small, already-decided set of target types (`Lot.LOT_OF`'s
current shape); prefer (2) when the trait is being added to a type with
a large or open-ended number of live instances and you'd rather pay a
one-time bulk migration than N schema declarations going forward. Either
way, a brand-new type gaining a trait from day one (before any instances
exist) needs neither — that case already works with zero extra effort.

🛑 **The fallback above only works if each declaration's JSON name on
the *shared* side differs too — reusing the relationship-type label is
fine, reusing the JSON property name is not.** Easy to get backwards,
because the two are independent axes and only one of them is safe to
repeat. Concretely: two different source types (`A`, `B`) each
declaring a relationship to the *same* target type `T`, both landing on
an identically-named property on `T` (say, both want `T.owner`) —
confirmed to fail even though the relationship-type label reuse itself
is the already-proven-safe pattern above, and even though this has
nothing to do with the retroactive-labeling trap (both `A` and `B` can
be brand-new types with zero pre-existing instances and it still
fails). Structr doesn't error at declaration time — both
`SchemaRelationshipNode`s create successfully — but only one of the two
ends up authoritative for reads/writes against `T.owner`; the other's
instances are rejected as targets with an error naming only the
*winning* type (`"No A with UUID ... found"` even when the id being
sent genuinely is a live `B`), which is easy to misread as "my `B` node
doesn't actually satisfy the trait" rather than "this property name is
already spoken for by a different declaration." Look closely at the
already-documented safe examples (a `Lot`-style type declaring the same
relationship label toward several different target types) and notice
they don't actually share a JSON name either — each target gets its own
distinctly-named property on the *varying* side (`lot.fertilizer`,
`lot.seed`, `lot.potSize`, ...); only the *reverse* collection name is
ever shared, and that's harmless because it lands on different node
types each time, not the same one. The real rule: a JSON property name
must be unique per concrete type, full stop, regardless of how many
different relationships or labels theoretically want to claim it — so
when using this fallback for a property that's conceptually "the same
kind of pointer" from more than one source type, give each source type
its own distinctly-named property on the target (e.g. `bearer` for one
source type, `bearerAlt` for another) and enforce "exactly one is set"
in application code, the same "exactly one of N" discipline used
elsewhere for a single source pointing at N possible target types —
just mirrored onto the axis that's varying here (N possible source
types pointing at one target).

### `Object` (and possibly other short, generic names) is silently reserved — a custom SchemaNode with that exact name gets contaminated with DOMElement/DOMNode

🛑 **Naming a custom abstract SchemaNode `Object` is not safe, even though creating it succeeds with no error or warning.** Found while importing BFO's real class hierarchy: a concrete type declaring `inheritedTraits: ["Object"]` (an abstract SchemaNode literally named `Object`, sitting in an otherwise-ordinary custom is_a chain) came back from a fresh `POST` with `isDOMNode: true` and roughly 140 extra `_html_*` properties (`_html_onclick`, `_html_style`, `_html_tabindex`, ...) — the entire DOMElement/DOMNode trait bundle Structr's own page-building system (`Page`/`DOMElement`/`Content`, see §6) uses, despite this type having nothing to do with pages. `ensure_type`'s own "does this type already exist" check found nothing under the name `Object` before creating it (it printed `[created]`, not `[exists]`), so this isn't a same-name collision with a pre-existing SchemaNode either — Structr appears to special-case the bare name `Object` internally (plausibly because every Java class implicitly extends `java.lang.Object`, and Structr's own trait-resolution machinery does some name-based matching that isn't scoped to user-defined SchemaNodes only).

✅ **Isolated by binary-searching the chain with disposable probe types, one level at a time**: a probe type declaring `inheritedTraits: ["IndependentContinuant"]` came back clean; a probe declaring `inheritedTraits: ["MaterialEntity"]` (one level further down the same chain) also came back clean; a probe declaring `inheritedTraits: ["Object"]` (one level further still) came back contaminated. Confirms the issue is keyed on the literal name `Object` specifically, not something structural about depth or the chain as a whole.

**Practical upshot:** don't name a custom SchemaNode exactly `Object` (or presumably other single-word names that might collide with a reserved Java/Structr concept — not exhaustively tested, but worth treating any bare, generic, capitalized noun as suspect and verifying with a disposable probe + a fresh instance's `/all` read-back before trusting it in a real schema, the same discipline as the `site`/existing-type-name collision case in `bfo-ontology-cheatsheet.md`, except this one collides with something inside Structr itself, not with anything the project defined). Rename and move on — verified the rename alone (no other change) produces a clean instance.

### An inherited property can't be REST-queried by value — even though it reads fine

✅ **`GET /structr/rest/{Type}?{inheritedProp}=value` returns zero
results, always, even for an exact match on a value confirmed correct
via `GET /structr/rest/{Type}/{id}/all`** — but the identical query
against a property declared *directly* on the concrete type works
normally. Confirmed live, twice, on two unrelated projects' worth of
types: a `unique`+`indexed` property declared on an abstract trait and
inherited by eight concrete subtypes, and a different `unique`+`indexed`
property inherited by nineteen. Both cases: the property is visibly
correct via the `/all` view, and completely unfindable by REST query.
The `indexed`/`unique` flags on the property's own declaration don't
matter — a directly-declared property with neither flag still queries
fine; an inherited property with both still doesn't. This looks like a
distinct limitation from the two documented above (it's about property
*searchability*, not relationship polymorphism or label backfilling),
and from the `/all`-view trap in §4 below (that one's about which
properties come back in the response at all; this one is about whether
a `?prop=value` filter matches anything, regardless of view).

**Practical upshot — this breaks upsert-by-natural-key for any type
using an inherited unique property as its lookup key**, which is a
common pattern (a trait shared by several concrete types, each still
needing "find-or-create by name/code"). Workaround, not a real fix:
fetch every instance and filter in your own code instead of asking
Structr's REST layer to filter. Two things make a naive version of this
workaround actively dangerous rather than just slow:
- **A bare, unfiltered `GET /structr/rest/{Type}` only returns what fits
  Structr's default page size** — silently incomplete for any type large
  enough to exceed it. Paginate explicitly (`_page`/`_pageSize`, see
  above) and keep fetching until a page comes back short, don't trust one
  request to mean "everything."
- **The bare collection endpoint also only returns the default view** —
  same trap as the `/all`-view section below, but easy to miss here
  specifically because a property close enough to a built-in one (e.g. a
  type's own `name`) can ride along in the default view by coincidence,
  making a spot-check look fine right up until you filter on a property
  that doesn't. Use the collection-level `/all` suffix
  (`GET /structr/rest/{Type}/all`, not just `/{Type}/{id}/all` for one
  node) so every property is actually present to filter against — and
  confirm this combines with pagination correctly before relying on it
  (it does: `GET /structr/rest/{Type}/all?_page=2&_pageSize=50` works as
  expected).

📖 **Custom-type ↔ built-in-type relationships are broken in 6.0.0
Community** — ✅ independently confirmed empirically in this project:
every attempt to relate a custom type to Structr's built-in `Image`/
`File` types failed with `"Invalid schema setup: missing
StartNode(s)/EndNode(s) property"`, across multiple relationship-shape
variants, both directions, and a full container restart. If you need
to reference an uploaded file from a custom type, don't fight this —
store the file node's `id` as a plain `String` property instead of a
real relationship (see §5).

📖 **Views** group a type's properties into named output shapes,
selectable via URL suffix (see §6). Not exercised beyond the built-in
`public`/`all` views in this project — if you're building an API for
external consumers, defining custom views (in the Schema Editor, or via
further `SchemaProperty`-adjacent endpoints not explored here) is the
documented way to control exactly what a given client sees.

---

## 3a. Custom instance methods (`SchemaMethod`) via REST

Written while building a `resolveDefault`-style method (walk a
self-referential `SUBCLASS_OF` chain upward, nearest-match wins) on the
`meal-planner` project. None of this is covered by official docs in
enough detail to skip empirical verification — every ✅ below was
confirmed live against a 6.0.0 Community instance with no pre-existing
built-in `SchemaMethod`s to learn the shape from (`GET
/structr/rest/SchemaMethod` on a fresh instance returns an empty
result, not documentation).

✅ **Creating one — minimal required fields, discovered by probing with
an empty POST:**

```python
POST /structr/rest/SchemaMethod
{"name": "resolveDefault", "schemaNode": "<DomainType-schema-node-id>"}
# name must match ^[a-z_][a-zA-Z0-9_]*$ (lowercase-start identifier) --
# confirmed via the validation error an empty POST returns.
```

Then `PATCH` the `source` field in separately — it's not required at
creation time.

✅ **`source` is plain StructrScript, with NO `${...}` wrapper** — unlike
a `Content` node's text, where `${...}` distinguishes script from
literal text, a `SchemaMethod`'s `source` field is *already* entirely
script. Wrapping it in `${...}` (or the JS-mode `${{ ... }}`) produces
a parse error (`"Unexpected character 36 ($)"`); confirmed the plain
form (`"source": "42"`) evaluates correctly (returns `42.0`) while the
`${...}`-wrapped form of the identical logic does not.

✅ **Invoke via `POST /structr/rest/{Type}/{id}/{methodName}`** (an
instance method, `isStatic: false`, the default) with a JSON body —
`200` on success regardless of what the script returns, so check the
body/log for actual success, not just the status code.

✅ **`returnRawResult: true` (a boolean field on `SchemaMethod`, default
`false`) makes the response body the bare returned value** instead of
the usual `{"result": [...], ...}` envelope — confirmed: with it
`false`, a script returning `42` produced `{"result": [], ...}`
(the scalar wasn't wrapped in the `result` array the way a normal REST
list response is); with it `true`, the same script's response body was
literally `42.0`. If a method's result looks like it's silently
vanishing, check this flag before assuming the script failed.

✅ **`if(...)`, comparisons, and `filter()`/`each()` predicates all need
StructrScript's function-call form, not infix operators.** `size(x) >
0` and `data.field == value` both fail to parse
(`"Unexpected character ... in string ..."`, logged as a
`org.structr.core.function.Functions` `WARN`, with **no error surfaced
to the REST caller** — the call returns `200` with an empty result, so
the failure is silent unless you check the container log). The working
forms, confirmed live:
  - `gt(a, b)` / `gte` / `lt` / `lte` instead of `>`/`>=`/`<`/`<=`
  - `equal(a, b)` instead of `==`, including inside a `filter()`
    predicate: `filter(collection, equal(data.someField.id, x))`

  **Practical upshot: always tail the container log
  (`docker compose logs structr --since 30s | grep -i warn`) after
  patching a method's `source` and before trusting a `200` response** —
  a syntax error in StructrScript is a silent no-op from the REST
  caller's point of view, not a REST-level error.

✅ **`this` correctly resolves to the calling instance inside a
`SchemaMethod`**, and chained relationship-property access through it
works to arbitrary depth in one script execution — confirmed
`this.parent.name` and `this.parent.parent.name` both resolved
correctly (a 2-level walk up a self-referential relationship), with no
special syntax needed beyond ordinary dot access.

🛑 **Passing a value into a *recursive* internal call
(`this.parent.someMethod(x)`, where `someMethod` is itself a custom
`SchemaMethod`) does not appear to work via any mechanism tried.**
Confirmed dead ends, each isolated with its own test:
  - `retrieve("key")` reads the **top-level REST call's own JSON body**
    correctly (`retrieve("kindId")` with body `{"kindId": "abc123"}`
    returns `"abc123"`) — but a nested call's `retrieve("kindId")`
    comes back empty even when the outer call's `retrieve("kindId")`
    was used as part of the very expression passed as the nested call's
    argument. The nested execution does not inherit the outer request's
    parameter binding.
  - `store("key", val)` in the caller, `retrieve("key")` in the callee:
    also empty. `store`/`retrieve` are **not** a shared, request-wide
    threadlocal across nested `SchemaMethod` invocations the way they
    might be assumed to be from the name — each invocation (including
    an internal one triggered by `object.method(...)` syntax) appears
    to get a fresh binding scope.
  - A declared `SchemaMethodParameter` (`POST
    /structr/rest/SchemaMethodParameter {"schemaMethod": id, "name":
    "kindId", "parameterType": "String", "index": 0}`, confirmed
    correctly linked via `SchemaMethod.parameters` afterward) does
    **not** make the parameter's name usable as a bare variable inside
    the method body either — tested both as the top-level REST-invoked
    call (bare `kindId` as the entire `source`, called with body
    `{"kindId": ...}`: empty) and as a literal positional argument in a
    nested call (`this.parent.resolveDefault("LITERAL_TEST")` with the
    callee's source being bare `kindId`: also empty, even though the
    caller unambiguously passed a real value). Whatever
    `SchemaMethodParameter` is for (plausibly OpenAPI documentation
    metadata only, given the accompanying `description`/`exampleValue`
    fields), it isn't functional argument binding for a StructrScript
    method body in this version.
  - `codeType` accepts arbitrary string values with no validation
    (`"js"`, `"text/javascript"`, `"application/javascript"` all `200`
    on write) but does **not** change the execution engine — JS
    statement syntax (`"var x = 1; return x + 1;"`) still fails with
    the exact same StructrScript tokenizer warning regardless of what
    `codeType` is set to. If `SchemaMethod` supports a real JavaScript
    execution mode in 6.0.0 Community, the trigger for it was not found
    by varying this field.

  **Practical upshot: don't design a `SchemaMethod` around recursive
  self-calls with arguments.** What *does* work, confirmed as the
  practical workaround for a bounded-depth upward walk (e.g. resolving
  a default up a type hierarchy): **unroll the walk as nested `if()`
  expressions over a chained property path** (`this`, `this.parent`,
  `this.parent.parent`, ...) within **one single script execution** —
  since `retrieve()` stays valid for the whole execution as long as no
  nested method call is involved, and chained property dereferencing
  (as opposed to a nested method *call*) is not subject to the binding
  problem above. This bounds the walkable depth to however many levels
  you unroll (6 was enough to confirm the pattern; pick a depth with
  headroom over your deepest real hierarchy, or find another mechanism
  — a Java-based `SchemaMethod`, or walking `SUBCLASS_OF*` in the
  calling application instead of in-database — if unbounded depth is a
  real requirement, which was not tested here).

✅ **Lifecycle hooks (`onCreate` etc.) are just `SchemaMethod`s with a
reserved name, and DO run automatically on every create** — confirmed
live: a `SchemaMethod` named exactly `onCreate` on a concrete type
(no special flag beyond the name) fires on every subsequent `POST` to
that type, with no separate registration step.

✅ **`error(property, token)` is the function that aborts a create/save
from inside a lifecycle method**, confirmed as the real
SHACL-substitute mechanism the build sketch's "onCreate/onSave
validators" line describes. Calling it (even unconditionally, as an
isolation probe) makes the write fail with a `422`:
```json
{"code": 422, "message": "Server-side scripting error",
 "errors": [{"token": "<your token>", "type": "<Type>", "property": "<your property>"}]}
```
Gated behind an `if(...)`, this is a real, working validator:
`if(lt(this.value, 0), error("value", "must_not_be_negative"), null)`
on `Measurement.onCreate` — confirmed to reject a negative `value`
with exactly that shape, while zero and positive values are accepted
normally (`201`). Re-verified identically after a full container
restart, per the stale-cache warning above — no difference.

🛑 **`lt(this.value, 0)` (and presumably `gt`/`lte`/`gte`) evaluates
`true` when `this.value` is absent/null, not false or an error.**
Found when a second property (`literalValue`, for categorical
Measurements with no numeric magnitude — opened_status, cleanliness)
was added alongside `value`, and every write of a Measurement carrying
only `literalValue` started failing the *same* `must_not_be_negative`
check, even though `value` was never set at all. StructrScript
apparently coerces a missing/null numeric property to something that
compares as less than zero, rather than treating the comparison as
vacuously false or erroring. **Guard any numeric-comparison validator
with an explicit `empty()` check first** if the property being
compared isn't always present:
`if(and(not(empty(this.value)), lt(this.value, 0)), error(...), null)`
— confirmed this fixes it: the negative-value case still rejects, a
literal-only Measurement (no `value` at all) is now accepted, and a
positive `value` is still accepted.

---

## 4. Data CRUD via REST

```
GET    /structr/rest/{Type}              # list (paginated)
GET    /structr/rest/{Type}/{id}         # one by internal id
POST   /structr/rest/{Type}              # create — 201, body is the new object
PATCH  /structr/rest/{Type}/{id}         # partial update of one object
PUT    /structr/rest/{Type}/{id}         # full update of one object
DELETE /structr/rest/{Type}/{id}         # delete one
DELETE /structr/rest/{Type}?filter=...   # ⚠ bulk delete — no filter = deletes ALL of that type
```

✅ **Upsert pattern** (find-by-unique-property, then create-or-patch) —
this is the workhorse for any data-sync script:

```python
def upsert(type_name, unique_prop, unique_value, fields):
    existing = get(f"/structr/rest/{type_name}", params={unique_prop: unique_value})
    payload = {k: v for k, v in fields.items() if v is not None}
    payload[unique_prop] = unique_value
    payload["visibleToAuthenticatedUsers"] = True   # don't forget — see §2
    if existing["result"]:
        node_id = existing["result"][0]["id"]
        patch(f"/structr/rest/{type_name}/{node_id}", json=payload)
        return node_id
    created = post(f"/structr/rest/{type_name}", json=payload)
    return created["result"][0]
```

Relationship properties (from §3's `targetJsonName`) are set the same
way as scalar properties — just include the related node's id as the
value: `{"widgets": widget_node_id}`.

### Query parameters (📖 per docs, spot-confirmed where noted)

| Param | Purpose | Example |
|---|---|---|
| `?prop=value` | exact match | `?sku=ABC123` |
| `?prop=a;b` | OR match | `?status=open;pending` |
| `?prop=` | find null/empty | `?sku=` |
| `?prop=[lo TO hi]` | range (numeric or date) | `?createdDate=[2026-01-01T00:00:00Z TO ]` (open-ended) |
| `_inexact=1` | substring/fuzzy match instead of exact | `?name=wid&_inexact=1` |
| `_page`, `_pageSize` | pagination — **note the leading underscore** | `?_page=2&_pageSize=50` |
| `_sort`, `_order` | sort by property, `asc`/`desc` | `?_sort=name&_order=desc` |
| `_outputNestingDepth` | JSON serialization depth (default 3) | `?_outputNestingDepth=1` |
| `_latlon`, `_distance` | spatial search | `?_latlon=48.85,2.35&_distance=10` |

🛑 **A literal comma anywhere in an exact-match `?prop=value` query value
makes it match nothing — silently, `200` with `result_count: 0`, not an
error — even though a node with that exact value genuinely exists.**
Confirmed by isolating character-by-character on a disposable probe
type: names containing parens, brackets, or a double-dash all queried
back correctly (`found_by_query=1`); the only variant that broke was
one containing a comma (`found_by_query=0`). Root cause not
investigated further (plausibly the query parser treats `,` as a
value-list/OR separator internally, similar to `;`'s documented
OR-match role, but silently produces an empty match instead of an
error when it does), but the practical effect is what matters: **this
silently breaks upsert-by-name for any value your own code generates
that might contain a comma** — confirmed the hard way when a
`DefaultSpecification`'s value name ("0.75 yield ratio**,** Chicken
Breast (raw) via Braising...") caused `upsert`'s find-then-patch-or-create
to never find the existing node, quietly creating a duplicate on every
re-run instead of erroring. **Avoid commas in any property value you
intend to query by exact match** (rephrase instead — "for X via Y"
instead of "X, via Y"), or route around it entirely with `_inexact=1`
(substring match) if a comma is unavoidable in the real data.

✅ **At the REST layer, pagination/sort param names are underscore-
prefixed — leaving off the underscore fails, not falls back to a
default.** Confirmed the hard way: `GET /structr/rest/Entry?pageSize=5`
returns `400 "Unknown search key pageSize"`; the working form is
`?_pageSize=5`. (StructrScript's `predicate.page(n, size)` is a
function call with positional arguments, not a query-string key, so
this particular gotcha is REST-API-specific.)

### Views

✅ **The default REST response only returns a handful of base
properties** (`id`, `name`, `type`, plus visibility/audit fields) —
custom properties and relationship collections you just added via
`SchemaProperty`/`SchemaRelationshipNode` are silently absent unless
you select a view that includes them. Confirmed: a fresh custom
relationship property showed up as populated via
`GET /structr/rest/{Type}/{id}/all` but was completely missing (not
`null` — just not a key in the JSON at all) via the bare
`GET /structr/rest/{Type}/{id}`. **If a property you just added looks
"empty" via the API, check the view before assuming the write failed.**

```
GET /structr/rest/{Type}              # default ("public") view
GET /structr/rest/{Type}/all          # all properties, incl. custom + relationships
GET /structr/rest/{Type}/{name}       # any named custom view you've defined
```

---

## 5. File uploads

✅ File/image upload is a **separate endpoint from the rest of the
REST API**, with different conventions:

```python
resp = session.post(
    f"{base_url}/structr/upload",
    files={"file": (filename, file_obj)},
    headers={"Content-Type": None},   # see below — critical
)
new_node_id = resp.text.strip()       # plain text, NOT json
```

- ✅ Returns the new node's id as **plain text**, not JSON — don't
  `.json()` this response.
- ✅ Structr **auto-detects `Image` vs generic `File`** from the actual
  file content/bytes, not the filename or extension.
- ✅ If your HTTP client session has a persistent
  `Content-Type: application/json` header (common if you're reusing a
  `requests.Session` for the rest of the API), **it must be overridden
  to `None` on this specific request**, or Structr rejects the body
  with `"Request does not contain multipart content"` even though it
  genuinely is valid multipart — the stale header wins over the
  correct auto-generated multipart boundary header otherwise.
- 📖 `POST /structr/rest/Image` or `/structr/rest/File` with a
  multipart body (the "obvious" REST-consistent approach) does **not**
  work — returns `400 "Invalid JSON, expecting object or array"`.
  `/structr/upload` is genuinely a different code path.
- Since custom-type↔File/Image relationships don't work (§3), reference
  the uploaded node by storing its `id` as a plain `String` property on
  your own type, and resolve it with a second `GET
  /structr/rest/File/{id}` (or `Image/{id}`) when you need the actual
  file's metadata.
- ✅ **A fresh upload defaults to owner-only visibility, same trap as
  every other node (§2)** — `POST /structr/upload` does not stamp
  `visibleToAuthenticatedUsers`/`visibleToPublicUsers` any more than a
  normal `POST` does. Confirmed live: a freshly uploaded file 404'd when
  fetched via a real session cookie (see the next point) until a
  follow-up `PATCH .../File/{id} {"visibleToAuthenticatedUsers": true}`
  was added right after the upload call. Easy to miss because the
  *upload itself* still succeeds and returns a valid id — the failure
  only shows up later, when something tries to actually render the file.
- ✅ **`GET /structr/rest/File/{id}` (or `/Image/{id}`) returns JSON
  metadata only — it does NOT serve the raw file bytes**, despite being
  the "obvious" REST-consistent guess (superseding the 📖 guess in the
  previous version of this section, which was wrong). The real
  mechanism: every File/Image node has a `path` property (e.g.
  `/._structr_uploads/photo.png`); **`GET` that `path` directly, on the
  bare host root, not under `/structr/rest/`**, and it streams the
  actual bytes with the correct `Content-Type`. Confirmed live for both
  an image (plain `200`, `Content-Type: image/png`) and a video (a
  `<video>` tag's native range request got a real `206 Partial
  Content`). Works with **either** `X-User`/`X-Password` headers **or**
  just a session cookie — meaning a plain `<img src="/._structr_uploads/
  photo.png">` in a page you built (§6) renders correctly for a
  logged-in browser session with no extra wiring, as long as the
  visibility PATCH above was done first.
- ✅ **Querying the generic `File` type by `id` also matches `Image`
  instances** (`GET /structr/rest/File?id=<id>` or, in JS scripting,
  `Structr.find('File', 'id', someId)`) — `Image` is a `File` subtype,
  so one lookup resolves either kind without needing to know upfront
  which one a given upload turned out to be. Useful specifically because
  Structr auto-detects `Image` vs. `File` from content (see above), so a
  caller storing just the `id` often doesn't know which concrete type to
  query.

---

## 6. Building frontend pages via REST (Page/DOMElement/Content)

Structr can serve real rendered HTML pages, built the same
programmatic way as data — useful for a quick internal admin/ops
dashboard without a separate frontend framework.

✅ **Structr does not auto-build an html/head/body skeleton** when you
POST a `Page` — every element is created one at a time, explicitly
linked by `parent` + `pageId`:

```python
POST /structr/rest/Page            {"name": "my-page"}              # -> page_id
POST /structr/rest/Html            {"pageId": page_id, "parent": page_id}   # -> html_id
POST /structr/rest/Body            {"pageId": page_id, "parent": html_id}   # -> body_id
POST /structr/rest/H1              {"pageId": page_id, "parent": body_id}   # -> h1_id
POST /structr/rest/Content         {"pageId": page_id, "parent": h1_id, "content": "Hello"}
```

Rendered at `/structr/html/<page name>`, **not** the bare root path
(`GET /<name>` 404s — verified).

🛑 **On this project's pinned image (`structr/structr:6.0.0`), the tag-specific
REST types in the example just above DO NOT RENDER — the whole tree from
that node down.** POSTing to `/structr/rest/Html`, `/structr/rest/Body`,
`/structr/rest/H1`, `/structr/rest/A`, etc. creates a perfectly good graph
node — correct `parent`/`pageId`, readable back via GET, shows up in the
parent's `children` — but `GET /structr/html/<page>` renders nothing for it
or anything nested under it: the response is the bare `<!DOCTYPE html>` line
and nothing else, no error anywhere (server log or response). Confirmed
after a clean `docker compose restart structr`, so not a stale-process
fluke; confirmed as both the page's root element and as a leaf several
levels deep with otherwise-generic ancestors. **What does render:** the
generic `/structr/rest/DOMElement` with an explicit `"tag"` property, for
every element, all the way down (`scripts/27_public_pages.py` does this).
This directly contradicts the next bullet's advice below for rendering
purposes — that bullet's claim about *attributes* still holds (see the
workaround it now describes).

- ✅ **Tag-specific HTML attributes need the tag-specific REST type — which
  is exactly why they can't be used for rendering (see above).**
  `_html_action`/`_html_method` (on `Form`), `_html_type`/`_html_name`/
  `_html_placeholder`/`_html_required` (on `Input`), `_html_href` (on `A`),
  etc. only exist on that tag's own schema type. POSTing to the generic
  `/structr/rest/DOMElement` with a `tag: "form"` (or `"a"`, ...) property
  and those attributes **silently drops them** — no error, the attribute
  just doesn't render (confirmed for `_html_href` on `A`). Since the
  dedicated type that *would* keep the attribute doesn't render at all,
  the practical fix for something like a link is to skip attributed
  elements entirely and write the literal tag as markup inside a `Content`
  node instead — `'<a href="/some/path">label</a>'` — which needs the next
  bullet's `contentType` fix to come out unescaped.
- 🛑 **A `Content` node's text is HTML-escaped by default.** Literal markup
  written into `content` (e.g. that `<a href=...>` workaround, or a
  hand-built `<li>` from StructrScript's `print()`) comes back as visible
  `&lt;a href=...&gt;` text, not a real tag, unless `contentType` is set to
  `"text/html"` explicitly — confirmed both for a literal string and for a
  `${each(..., print(...))}` expression's output. The next bullet's
  `text/javascript` case is the same underlying rule, one contentType over.
  The other side of the same rule: once `contentType` is `text/html`, whatever a StructrScript
  expression prints is inserted **raw**. Wrap any value someone could control (a recipe's `name`)
  in `escape_html()`, or a name like `<script>...</script>` runs in every visitor's browser.
  `scripts/27_public_pages.py` does, and its step [5] checks it against a public recipe with a
  markup name.
- ✅ **A `<script>` tag's `Content` node needs
  `"contentType": "text/javascript"` explicitly.** The default plain-
  text content type converts newlines to literal `<br>` tags — silently
  breaks JS syntax, with no error at write time; only visible as
  garbled output and a browser console error at render time.
- Every element defaults to `visibleToAuthenticatedUsers=True` unless
  you pass `visibleToPublicUsers=True` — same trap as §2, one level up.
  An invisible element just renders as nothing.

### Deleting a `Page` does not cascade-delete its element tree

✅ `DELETE /structr/rest/Page/<id>` removes the `Page` node but leaves every
`DOMElement`/`Content` that was under it, orphaned with `pageId` (and
`parent`) wiped to `null` — confirmed by re-querying `/structr/rest/DOMElement`
and `/structr/rest/Content` after deleting a page and finding the old counts
unchanged. They render nothing (no `pageId`) but stay in the graph. Delete a
page's elements explicitly before or after deleting the page itself; a script
that rebuilds a page tree by name (matched on `pageId`+`name`, as
`scripts/27_public_pages.py` does) never creates this problem because it
patches existing elements in place rather than deleting the page.

### Detail pages: URI object resolution

✅ For a page that renders one specific node (e.g. an entity detail
view), Structr has a **built-in mechanism** rather than needing a
hand-rolled `?id=...` query param + `find()` script: a path segment
after the page name is matched against a node's `id`/`name` by
default, and the matched node becomes available via the `${current}`
keyword:

```
/structr/html/<page-name>/<node id or name>
```
```html
<h1>${current.someProperty}</h1>
```

This is the documented, idiomatic pattern (docs.structr.com: "URI
Object Resolution on Detail Pages") — confirmed working. If a caller
only knows a human-facing identifier (not the internal Structr node
id — e.g. someone scanning a barcode), fall back to a query param and
resolve it explicitly:

```
${if(empty(current), first(find("Type", "humanId", request.humanId)), current)}
```

### `redirect()` does not fire reliably from a nested Content node

✅ Confirmed via `curl -i`: by the time a `Content` node several levels
deep in the DOM tree evaluates its script, the HTTP response looks
already committed — still 200, no `Location` header, regardless of
where in the tree the call was placed. A working server-side redirect
needs to run before any output starts, which wasn't achievable this
way. Workaround used successfully: skip the redirect, use a plain GET
`<form>` that lands directly on the target URL with a query param
instead of a canonical-id redirect.

---

## 7. StructrScript quick reference

Interpolated with `${...}` inside `Content` node text/attributes.

### Gotchas (✅ verified)

- **String literals must be double-quoted.** `print("<li>", data.x)`
  works; `print('<li>', data.x)` (single-quoted) **silently renders
  nothing at all** — no error, just empty output.
- **Don't chain a relationship/collection property onto an `if()`'s
  result when feeding it into `each()`.**
  `each(if(cond, a, b).items, ...)` renders nothing — even though
  `if(cond, a, b).items` evaluated alone *does* resolve to a real,
  non-empty collection (confirmed via direct interpolation: it prints
  as a Java `FilterIterable` object, not empty). Chaining a *scalar*
  property this way (`if(cond, a, b).name`) works fine — only
  collections passed to `each()` hit this. Fix: resolve the property
  *inside* each branch instead: `each(if(cond, a.items, b.items), ...)`.
- **A `print(...)` call nested as one argument *inside a larger,
  containing* `print(...)` call does not compose — the inner call's
  output escapes to the front of the whole line instead of interpolating
  at its actual argument position, silently, with no error.** Confirmed
  live with a disposable spike page:
  `${print("Before: ", if(cond, print("<a>...</a>"), print("<a>...</a>")), " :After")}`
  rendered as `<a>...</a>Before:  :After` — the inner print's HTML jumped
  to the very front, and the "Before:"/":After" text collapsed together
  with nothing in between, exactly where the `if(...)`'s result should
  have interpolated. This is a sharper variant of the `each()`-chaining
  gotcha just above — same family of "a function call's return value
  doesn't compose the way it looks like it should when nested."
  **What does work, also confirmed live**: `if(cond, "plain string",
  print(...))` — and even `if(cond, print(...), print(...))` with *every*
  branch a full `print(...)` call, no plain-string branch at all — as
  long as the `if(...)` expression is a content node's **entire, sole**
  content, not embedded as an argument inside a further outer `print()`.
  Practical upshot: if you need a conditional link/HTML fragment
  embedded in the middle of a longer line (e.g. inside an `each(...,
  print(...))` list row), you can't just drop an `if(cond, plain,
  print(link))` into the middle of that outer `print()`'s argument list
  — either give that fragment its own separate content node (fine for a
  page with a fixed layout, not fine inside a per-row list item), or
  switch that whole section to JS-mode scripting (`${{ ... }}`,
  `Structr.print`, ordinary `+` concatenation — see below), which has no
  equivalent nesting hazard since it's just building and returning a
  real string rather than relying on `print()`'s side-effecting output
  order.

### Useful keywords (📖 per docs; `current`/`data`/`request` ✅ confirmed in use)

| Keyword | Resolves to |
|---|---|
| `current` | The node matched by URI object resolution (see §6) |
| `data` | The current element inside an `each()`/`filter()` loop |
| `this` | The current object instance |
| `request` / `parameterMap` | HTTP request query/form parameters |
| `me` | The currently authenticated user |
| `now` | Current timestamp |
| `page` | The current `Page` in a rendering context |

### Useful built-in functions (📖 per docs; `find`/`each`/`print`/`if`/`size` ✅ confirmed in use)

```
find(type, key1, value1, ...)               # exact-match query, returns a collection
find(type, predicate.range(prop, lo, hi))    # range query — e.g. a date window, "this week"
find(type, predicate.sort(prop))
find(type, predicate.page(n, size))
search(type, ...)                            # like find(), but case-insensitive/inexact
size(collection)                             # length
first(collection) / last(collection)
each(collection, expression)                 # iterate — current item bound to `data`
filter(collection, expression)               # subset a collection
if(condition, thenExpr, elseExpr)
empty(value)                                 # null-or-empty check
dateFormat(date, "yyyy-MM-dd")               # (📖 not verified this session)
```

📖 The `predicate.range()`/`gt()`/`gte()`/`lt()`/`lte()` family is the
documented way to do a "this week" / "last N days" style time-windowed
query directly in StructrScript, e.g.
`size(find("Order", predicate.gte("createdDate", oneWeekAgo)))`. Not
independently verified in this project (a real dashboard's "this week"
count was left as an all-time count instead, specifically because this
wasn't confirmed before time ran out) — worth testing directly against
your instance before shipping it, but this is the documented shape to
start from.

### JavaScript scripting (`${{ ... }}`) — for what StructrScript can't do

✅ Structr also supports plain JavaScript, interpolated with `${{ ... }}`
(double braces, vs. `${...}` for StructrScript) inside the same `Content`
node text. Reached for this the first time this project needed to
**merge multiple different node types into one collection and sort it
by a shared property** — e.g. building one time-descending activity feed
across 18 different event types related to one parent node.
StructrScript's `find()`/`each()` operate on a single type at a time, and
there is no documented StructrScript-native way to union heterogeneous
collections and sort the result; plain JS trivially does both (`Array.
push`/`Array.sort`), so this is the reach-for-it case.

Verified live, all in the same session:

- **The JS-mode equivalents of `current`/`request`/`find(...)` are
  `Structr.get('current')`, `Structr.get('request')`, and
  `Structr.find(type, key, value)`** (returns a JS array; index/`.length`
  work normally). The dual "path-based id, or `?humanId=` query-param
  fallback" pattern from §6 ports over directly:
  ```js
  ${{
  var e = Structr.get('current');
  if (!e) {
      var found = Structr.find('Entry', 'entryId', Structr.get('request').entryId);
      e = found.length > 0 ? found[0] : null;
  }
  }}
  ```
- **Relationship/collection properties are accessed the same way as
  StructrScript** — both `node.someRelationship` and bracket notation
  `node['someRelationship']` work (bracket notation matters when the
  property name is only known at runtime, e.g. iterating a list of
  collection names). Standard JS array methods (`.push`, `.sort`,
  `.length`, indexing) work directly on the returned collections and on
  plain arrays built from them.
- **A Date-typed property comes through as a real object supporting
  `.getTime()`/`.toISOString()` directly — it is not a string.** Printed
  raw, it renders as Java's `Date.toString()` format ("Mon Jun 22
  12:00:00 UTC 2026"), which is a strong tell that something tried to
  treat it as a string rather than call a method on it. Don't
  string-parse it (`new Date(x.replace(...))` silently fails, no error,
  just an unusable result) — call `.getTime()` for arithmetic/sorting or
  `.toISOString()` for display directly on the property.
- **A JS block's return value is HTML-escaped by default** — the last
  expression's value becomes the block's output (same implicit-return
  behavior as StructrScript), but building an HTML string like
  `'<li>' + x + '</li>'` and returning it renders as literal
  `&lt;li&gt;...&lt;/li&gt;` text, not a real element. `Structr.print(str)`
  (equivalently `$.print(str)`) outputs raw, unescaped HTML — the JS-mode
  counterpart to StructrScript's `print()`, and required for any block
  that builds markup rather than a plain scalar value. A bare global
  `print(...)` (no `Structr.`/`$.` prefix) silently produces no output at
  all — don't confuse the two.
- **Accessing a property that doesn't exist on a given concrete type
  (e.g. reading `.pot` on a node type that has no such relationship)
  resolves to `undefined`, not an error** — safe to probe optional,
  type-specific fields directly (`ev.pot ? ev.pot.name : ''`) when
  iterating a heterogeneous collection of different concrete types
  without checking `.type` first for every property access.

📖 The `$.find()`/`$.create()`/`$.delete()` naming shown in Structr's own
docs and `Structr.find()`/`Structr.get()` used above appear to be the
same API under two different global aliases (`$` and `Structr`) — both
were seen working live via `Structr.X`; `$.X` was only spot-checked for
`print`. Reach for `Structr.X` first since that's what's actually been
exercised end-to-end here.

---

## 8. Deployment / export-import (📖, not exercised in this project)

Structr has a built-in app-as-code workflow via its Deployment panel
(Dashboard → Deployment):

1. Export the current schema+pages+data to a server-side directory
   (`/var/lib/structr/repository/<name>`, or a bind-mounted host path).
2. Commit that directory to a git repo on the host.
3. On another instance (or after a wipe), import from the same
   directory path to restore/replicate the app.

This is the mechanism for treating a Structr app as version-controlled
code rather than only living in the running database — worth setting
up early on any project past a quick prototype, since none of the
scripted-REST approach in this document captures pages/schema changes
made through the UI.

---

## 9. General approach that worked well

- **Script everything via REST, verify empirically, write down what you
  learn as you go** (comments in the client code, not just this
  document) — Structr's docs are real but thin in places, and several
  behaviors here (the json-name inversion, the view-visibility trap,
  the upload endpoint's quirks) simply aren't documented anywhere
  obvious. Empirical verification against a real running instance
  beat guessing from docs every time it was tried.
- **Make schema-setup scripts idempotent from day one** (check-then-
  create for every type/property/relationship) — schemas grow
  incrementally, and re-running the same script after adding one new
  type should be free and safe, not something you have to reason
  about by hand each time.
- **Split "generic Structr client" from "this project's data mapping"**
  into two files/modules even in a small project — the REST mechanics
  (auth, upsert, schema-management, upload) don't change per project;
  only the type names and field mappings do. Keeping them separate
  means the client can be copied wholesale into an unrelated project.
- **Keep a running "Not yet done" / gotchas doc alongside the code**
  (this file is one example) — several of the entries above
  (visibility defaults, view selection, the json-name inversion) are
  the kind of thing that's cheap to write down once and expensive to
  rediscover from scratch in a different project six months later.

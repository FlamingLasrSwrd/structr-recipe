# Structr features: what this project uses, what it could use, and what the spikes found

**Status: findings and a plan (2026-10-27); batches 1 to 4 built, 5 and 6 waiting on the owner.** A read of all of Structr's documentation
(structr.org/docs, 84 pages, written for 7.x) and of the 7.1.0 release notes, checked against the
6.0.0 this project runs: read-only probes of the development instance's schema metadata, endpoints
and image, then spike tests on throwaway stacks (`tools/spikes/`). `docs/structr-reference.md` is
the same knowledge without this project in it, for any Structr work; `docs/structr-cheatsheet.md`
remains the authority on what this project has verified.

## 1. What the project uses today

REST for everything the Python does (schema through `structr_client`'s `ensure_*` helpers, data
through upserts by name); StructrScript `onCreate` validators for the domain invariants
(`mealplanner/domain_invariants.py`); JavaScript user-defined functions for the request-time
engines (`methods/`, `docs/methods.md`); pages that are one JavaScript `Content` each, printing their
HTML (`pages/`, `docs/pages.md`); `ResourceAccess` grants, a `Group` per household, `grant()` on
private nodes, `doPrivileged`, `doInNewTransaction`, `cypher`; one custom view (`scripts/37a`);
`unique`, `indexed`, `notNull` and enum `format` on properties.

## 2. What it does not use, and what each would do here

Ranked by what it would change for this project. "6.0" says what the 6.0.0 instance showed:
**works** (spiked, behaves as documented; the catches are in section 3), **probed** (the field,
endpoint or command exists, behaviour not tested), **no** (spiked, does not work), or **7.x**
(documented for 7.x only).

| # | Feature | 6.0 | What it would do here |
|---|---|---|---|
| 1 | **Changelog**: every create, change, link and delete recorded with user, time, old and new value; `changelog(node)`, `userChangelog(user)` | works | The pantry journal and "undoing a booking" (`docs/todo.md`), and who checked or corrected what (`verification-and-sharing.md`). Stored in files, not Neo4j: needs a volume and a place in the backups |
| 2 | **Cascading delete** per relationship | works | A Specification taking its quantity, state requirements and substitution rules with it, and a Step its minutes: `recipe_import._remove_stale` deletes each by hand |
| 3 | **`onSave` validators**, with the modifications object | works | Every invariant validator is `onCreate` only, so an edit through REST or a page can break an invariant a create could not |
| 4 | **Default visibility per type** (`defaultVisibleToAuth`) | works | A safety net under hard rule 4 for the shared vocabulary types: a write that forgets the flag no longer hides the node |
| 5 | **Schema grants** (a group's rights on every node of a type) | works | Stage 5 (`architecture-decision.md` §7a): a curators group editing the shared vocabulary without a grant per node |
| 6 | **Permission propagation** along relationships | works | Stage 5: a household's data reachable through its MealPlans and entries without `ensureNode` granting each node |
| 7 | **Compound uniqueness** | works | Stage 5's MealPlan name collision across households, if the household can be part of the key |
| 8 | **`format` ranges and patterns** | works | Invariant 12 (no negative quantity) and simple patterns declared, not scripted |
| 9 | **Batch writes**: an array POST in one transaction | works | Importers write node by node, each its own transaction, so an interrupted import half-writes a recipe; and each transaction costs round trips |
| 10 | **Readiness endpoint** `/structr/health/ready` | works | A compose health check; `tools/wait_for_structr.sh` |
| 11 | **Query histogram** `/structr/histogram` | works | Where the planner's reads and the pages' renders spend their time (`docs/todo.md`: one consistent snapshot) |
| 12 | **Scheduled tasks** (CronService) | works | Nightly sweeps and checks without a host cron; runs as the superuser |
| 13 | **`sync` export of a query's subgraph** | works | A household's own data as one ZIP ("download my data", hosted), and a backup without stopping |
| 14 | **`createLabels`** | works | Hard rule 2 says a trait added to a populated type is "only fixable with direct Cypher SET n:<Label>"; this may be the supported fix |
| 15 | **Declared method parameters, the GET verb, OpenAPI** | works | The methods' hand-written argument checks; the planner contract documented for a worker or self-hosters |
| 16 | **Python inside Structr** (GraalPy, `Polyglot.eval`) | **no** | Some Python engines would run in Structr instead of being written twice (JavaScript beside Python, Path S) |
| 17 | **Event Action Mapping** | probed (the library and the element settings) | Bookings as real posts with confirmations, field errors and partial reloads, instead of GET links (`docs/todo.md`, the cheap security fixes) |
| 18 | `cache()`, `prefetch()`, `doAs()`, `schedule()` | works | Slow page reads cached; traversals prefetched; tools acting as a household member (stage 5); work after the request |
| 19 | Server-sent events to a group | 7.x docs, servlet off | The week page updating for every member when one books; "your plan is ready" from the planner |
| 20 | Self-registration, password reset, OAuth, two-factor login, HTTPS by Structr itself | 7.x docs | The hosted offering's sign-up, and HTTPS for phones (`self-hosting.md` step 4) |
| 21 | Mail in and out | 7.x docs | The week's menu mailed to members; receipt mails turned into Purchase bookings |
| 22 | `jdbc()` (SQLite) | 7.x docs | A Grocy import reading Grocy's database file (the driver JAR is a download: the owner's permission) |
| 23 | Localization, `User.locale` | probed | Pages in a member's language, for a hosted service |
| 24 | URL routes with typed parameters, shared components, repeaters | 7.x docs | Pages as structure rather than one printing script; `/week/{start}` instead of `?week=` |
| 25 | Content extraction | 7.1 only | Reading recipe-card PDFs to help re-transcribe the owner's recipes |

## 3. Spike results

Run with `bash tools/spikes/run_spikes.sh` (a throwaway stack on port 8084 with the settings in
`tools/spikes/docker-compose.spike.yml`; setup, a restart, then verify). The last run's raw results
are in `tools/spikes/last_results.json`.

Twenty-five spikes, run on 2026-10-27 against `structr/structr:6.0.0`: 21 behave as documented,
one does not (Python), three only report (the endpoints, an object parameter, `onSave` on
relationship changes). What each showed, and what it means here:

| Spike | 6.0.0 showed | For this project |
|---|---|---|
| cascade | `cascadingDeleteFlag` 1 (source to target) deletes the target with its source; 0 leaves it | Batch 2 below |
| cascade_more | A flag set on a relationship that already has edges applies to them after a restart; cascades chain; **the target is deleted even when another node still points at it**, by the same relationship type or another | `HAS_SPECIFIED_QUANTITY`, `EXPECTED_VALUE_QTY` and the step times are declared many-to-one: one quantity could be shared. The importer never shares one (each is named after its owner), but the migration must check, and refuse if any is |
| visibility | A type's `defaultVisibleToAuth` makes a node created without flags visible to every signed-in user, **but the node's stored `visibleToAuthenticatedUsers` still reads false** | Not a safety net for hard rule 4: every check that reads the flag would still call such a node hidden, and the flag would hide the slip the snapshot catches. Not adopted |
| compound | Two properties marked `unique` and `compound` refuse a repeated pair (422 `already_taken`) and accept a new one | Ready for stage 5's per-household names |
| format | `[0,100]`, `[0,100[`, `[0.0,100.0]` refuse values outside with 422 `must_be_in_range`, on Double and Integer, for creates and edits (a PATCH out of range leaves the old value); **an open end (`[0,]`) is accepted but checks nothing**; a missing value passes. **A string pattern refuses a missing value** (`must_match`) | Invariant 12 can be a format with a large upper bound, covering edits the `onCreate` validator misses; never a pattern on an optional property |
| onsave | `$.retrieve('modifications')` holds `before` and `after`; `$.error` in `onSave` refuses the edit (422, by PUT or PATCH) and nothing changes; `onSave` does not run on a create | `onSave` twins of the validators work, but see Batch 4 on the importers' two-step writes |
| onsave_links | **`onSave` runs when only a node's relationships change**: deleting the node at the other end runs it (and a failing one refuses the delete), and so does setting the link from the other end | Batch 4: a twin of a validator that reads a relationship guards that relationship on delete, so only six validators got twins |
| grant | A `SchemaGrant` (`schemaNode`, `principal`, `allowRead`, `allowWrite`, `allowDelete`, `allowAccessControl`) lets a group's members read and write every node of a type, owned by anyone, with no flags; a non-member sees none | Stage 5's curators of the shared vocabulary |
| propagation | `permissionPropagation: "Out"` with `readPropagation: "Add"` (the others `"Keep"`): a read grant on a folder lets a user read its documents, which carry no grant | Stage 5: a household's MealPlan opening its entries |
| labels | A node made before its type gained a trait lacks the trait's label and is refused as the target of a relationship to the trait; `POST /structr/rest/maintenance/createLabels {"type": ...}` adds it, and the same relationship is then accepted | Hard rule 2's "only fixable with direct Cypher" is out of date: `createLabels` is the supported fix. The rule's wording is the owner's to change (`docs/todo.md`) |
| bulk | An array POST is one transaction (one duplicate in it: 422, nothing created); a PATCH array on a collection updates many | Batch 6 |
| unknown | `STRUCTR_jsonrestservlet_unknowninput_validation_mode=reject` refuses a key the schema does not declare (422 "Rejecting input with unknown JSON key ...") and creates nothing | Batch 1: a misspelt key in a tool, or a tool run ahead of its migration, fails where it happens |
| changelog | With `STRUCTR_application_changelog_enabled` and `..._user__centric_enabled`, `$.changelog(id, false)` lists `create` and `change` entries with `prev`, `val`, `userName` and time; kept as files in `/var/lib/structr/changelog`, **which is on no volume** | Batch 1, with a volume and a place in the backups |
| cron | `STRUCTR_cronservice_tasks=<function>` and `STRUCTR_<function>_cronExpression` (six fields) run the function; it must exist when Structr starts | No task yet; a nightly check is a candidate |
| polyglot | **No.** The image carries the GraalPy jars, but `Polyglot.eval('python', ...)` answers 422 and the log says "No language for id python found. Supported languages are: [js]" | Python cannot run inside Structr 6.0 as shipped: what a request does stays JavaScript (`methods/`) and the planner stays Python outside it, as Path S has it |
| params | A `SchemaMethodParameter` of type Integer turns `"7"` into 7; `httpVerb: "GET"` takes path segments (`/structr/rest/<name>/5`) and refuses POST (405); **an undeclared argument is dropped silently** (7.1 refuses it) | Batch 5. Every method must declare every argument it reads before 7.1 |
| param_object | A JSON object passed to a declared parameter of type Map, Object or String arrives whole, as an object; the undeclared `warmUp` beside it is dropped | Batch 5: a booking method can declare one object parameter for its fields, and `warmUp` |
| evaluate | `$.evaluateScript(node, 'expression')` runs a StructrScript expression with `this` the stored node and returns its value; written as `${...}` it returns nothing | Batch 4's check of the stored data: each validator's expression, its `error(` replaced by a function that only returns, evaluated against every node of its type |
| cache | `$.cache(key, seconds, fn)` returns the first value again | A candidate for slow page reads; the key must name the household, since a cached value is shared by everyone |
| doas | `$.doAs(user, fn)` runs `fn` as that user (`$.me`, their rights), **but returns nothing**: the result must be kept in a variable outside `fn` | Tools and checks acting as a household member (stage 5) |
| schedule | `$.schedule(fn, title)` runs `fn` after the request | Work a page should not wait for |
| prefetch | `$.prefetch` exists; its gain was not measured | Measure on the planner's reads before adopting |
| sync | `maintenance/sync {"mode": "export", "file", "query"}` writes the subgraph a Cypher query returns into a ZIP | "Download my data" for a household; import not tried |
| health | `/structr/health/ready` 200 without credentials; `/structr/health` 200; `/structr/histogram` 200 from inside the container (`curl` is in the image) | Batch 1: a compose health check |
| eam | `/structr/js/frontend/frontend.js` is served and DOM elements carry `eventMapping`, `triggeredActions`, `parameterMappings`, `reloadTargets` and the notification settings; the behaviour was not exercised | Bookings as posts: a spike of its own when the pages' cheap security fixes come up |

## 4. If the project moves to 7.1

- **The tools log in as the superuser** (`mealplanner/connection.py`). In 7.1, three wrong superuser
  passwords within 15 minutes block it everywhere, and with its second factor on, header requests
  need a fresh code each. The tools should use an admin user (`docs/todo.md`).
- A fresh install needs a setup token (`STRUCTR_setup_token`): `cloud/bootstrap.sh`, the throwaway
  rebuilds and `tools/owner_stack.sh build`.
- Lower risk here: `assert()` and `sort()` changed meaning, but neither the pages nor the methods call
  them (the pages sort with JavaScript's own `Array.sort`); undeclared method parameters are refused
  only for methods that declare parameters; the session cookie becomes HttpOnly (the pages do not
  read it); virtual types are removed (not used).
- Gained: content extraction, vector search, named job queues, `/structr/rest/_serverLog`, the
  `migrate` maintenance command, `$.modifications`.

## 5. The plan

In batches, each finished and verified before the next: a numbered, idempotent migration where the
schema changes, offline tests whose expected values are worked out by hand, a deliberate break of
each to see the test notice it, a fresh rebuild ending in SNAPSHOT IDENTICAL, and the owner's steps
in `docs/todo.md`.

**Batch 1, operations: settings in `docker-compose.yml`, no schema change. Built 2026-10-27.**
- A compose health check on `/structr/health/ready` (`curl` is in the image), so `docker compose ps`
  says when Structr is ready. `tools/wait_for_structr.sh` keeps its authenticated read, which also
  proves the password. Readiness answered 503 now and then during a rebuild's schema changes, so a
  run of migrations can show the container unhealthy for a while; nothing acts on the status.
- The changelog on, with the user-centric log, on a volume of its own (`structr-changelog`) that
  `tools/backup.py` backs up with the others (`docs/backups.md`). It records from the moment it is
  on; the history before stays unknown. A full rebuild left 34 to 36 MB of it.
- Unknown input keys refused (`reject`). The rebuild is the check: every script and tool writes
  through REST, so a rebuild that ends identical shows none sends a key the schema lacks. The first
  one did not: script 04 sent `hasTime` before `recipe_schema` declares it (now it sends it only
  once declared), and the importer's demo, numbered 29b, ran today's importer long before the
  schema it writes (36a, 41a). It is now `44c`, after them. Nothing else in a build sends an unknown
  key.

**Batch 2, cascading delete (migration 44a). Built 2026-10-27.** Source-to-target on Step
`HAS_SPECIFICATION`, `HAS_WORKING_TIME` and `HAS_WAITING_TIME`; Specification
`HAS_SPECIFIED_QUANTITY`, `HAS_STATE_REQUIREMENT` and `HAS_SUBSTITUTION_RULE`; StateRequirement
`EXPECTED_VALUE_QTY` (`mealplanner/cascade_schema.py`). With the flags, the importer deletes a
stale Step or Specification and Structr deletes what it owned in the same transaction, where
`recipe_import._remove_stale` used to send a request for each. 44a first reads every node these
point at and refuses, changing nothing, if one is held by anything else (cascade_more: it would be
deleted from under the other holder). On an instance before 44a the importer still deletes each
by hand (`cascade_schema.delete_owned`): a rebuild runs 41b to 43b, which import, before 44a. The
offline graph deletes as Structr does, along the rows that carry the flag, and drops a deleted
node's relationships everywhere. `scripts/44b` checks it all on real Structr, and the snapshot
records each flag that is set.

**Batch 3, invariant 12 as `format` (migration 45a). Built 2026-10-27.** `[0,1000000000]`
(`domain_invariants.NON_NEGATIVE_FORMAT`) on the quantity-bearing values: QuantitySpecification
`value`, `minValue` and `maxValue`, and Measurement `value`. The `onCreate` validators stay; the
format adds edits, which the spike showed it refuses, keeping the old value. An open end checks
nothing, hence the large bound (the largest value a build stores is 1,000). A fresh build declares
it from the start (03a, 04, 10a, so every declaration carries it, or the schema helpers' drift
check would refuse a re-run); 45a sets it on an instance built before, after reading every stored
value and stopping if one is outside. `scripts/45b` edits each property out of range on real
Structr. Found on the way: an `onCreate` validator's error ends a request before Structr checks the
format, so a negative create is refused with the validator's token alone, and only a value past
the bound with the format's. On a throwaway made to look built before (no format, then a value
edited to -4, which the validators let through), 45a refused while that value was stored and set
all four once it was gone.

**Batch 4, `onSave` twins of six validators (migration 46a). Built 2026-10-27.** The onsave_links
spike changed the plan: Structr runs a node's `onSave` when only its relationships change too, the
node at the other end deleted or the link set from the other end, and a failing one refuses that
delete or write. A twin of a validator that reads a relationship would therefore guard it. So
twins went to the six whose result a removed link cannot turn from passing to failing, since they
read the node's own properties, or a related node behind an `empty()` guard: QuantitySpecification,
Measurement, Specification, Allocation, StockPolicy and PlanningConstraint
(`domain_invariants.ONSAVE_TWINS`). The other four stay `onCreate` only, because their twins would
refuse deletes elsewhere: MealPlanEntry (deleting a Plan an entry references), SubstitutionRule
(deleting the food a rule names), DefaultSpecification (deleting its value first, which
`lte(null, 0)` reads as zero or less: the reset script and the owner purge delete in that order) and
Role (it reads its target entry and the cook that made its bearer, which other writes set one request
at a time; not tried). Whether Structr should
guard those references on delete is a change to how deleting works, the owner's to decide
(`docs/todo.md`).

Before installing, 46a checks every stored node of the six types against its validator, since an
`onSave` refuses any edit of a node that already breaks it. A throwaway function runs each
validator through `$.evaluateScript` (the evaluate spike) with its `error(...)` calls turned into
plain strings (`domain_invariants.as_check`), and is removed again. The REST writers were read
first: the vocabulary, profile and household tools write a node's changes in one PATCH
(`Sync.ensure`); the importer's `_write` clears fields in a second request, but on these six types
a node never changes shape between the two; the week's commit writes only open slots. `scripts/46b`
edits each type out of its invariant on real Structr. To put the build's own writes through the
twins, a throwaway was also built with 46a moved to just after 10b, where the six validators first
exist: every later script ran under them, and the instance ended identical to an ordinary build's.
It showed one thing: with the twins in, a validator's error comes before the format's on an edit
too, so `scripts/45b` now accepts either token for an edit. On that instance, with all four batches in force, the pages and
methods were installed and `check_bookings.py`, `check_pages.py` and `check_instructions.py` found no
difference; `check_households.py` did too once the recipes' nutrition per serving was stored
(`calculate_recipe_nutrition.py`), which its nutrition comparison needs on any fresh build.

**Batch 5, methods:** declared parameters for every argument a method reads, GET for the read-only
ones, `includeInOpenAPI` with a tag for the planner contract. Needed before 7.1 in any case. Once a
method declares one parameter, 6.0 drops every argument it does not declare (the params spike), so
each method declares all it reads, `warmUp` included (`tools/install_methods.py`). The three booking
methods take the fields of one action among many (`bookForCaller`): either every key any action
reads is declared, or they take one declared object, for which a parameter type has to be found
first. The param_object spike found one: declared as Map (or Object, or String), an object arrives
whole. **Not built: waiting on the owner**, because it changes how every caller calls the methods
(`docs/methods.md`): a booking would move from flat keys to one object, or declare every key any
action reads, and a read method moved to GET is called with path segments instead of a POST body.
Nothing on 6.0 needs it: 6.0 passes undeclared arguments to a method that declares none, and only
7.1 refuses them. It belongs with a move to 7.1.

**Batch 6, importers in one transaction:** a recipe written as array POSTs, so an interrupted import
leaves nothing half-written, and measured against today's 8 to 19 s a recipe. **Not built: waiting on
the owner.** The importer upserts every node by name and links each to nodes made a moment before;
an array POST is one transaction (the bulk spike) but a new node in it cannot name another new node
by id. So it needs either Structr's nested objects with autocreation (`autocreationFlag`, not yet
spiked) or a redesign that reads everything first and writes the new nodes in two arrays, then the
links. Batch 2 already made a recipe's deletions one transaction each. It is worth measuring where
an import's time goes before choosing.

**Waiting on the owner, or on stage 5:** schema grants, propagation and compound uniqueness (stage
5's sharing and names); the wording of hard rule 2 now that `createLabels` works; a changelog-based
journal and undo for the pantry (`docs/todo.md`); `sync` export as "download my data"; Event Action
Mapping for bookings; a nightly scheduled check. **Not adopted:** default visibility (the stored
flag stays false, section 3) and Python inside Structr (not available on 6.0).

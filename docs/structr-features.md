# Structr features: what this project uses, what it could use, and what the spikes found

**Status: findings and a plan (2026-10-27), being built.** A read of all of Structr's documentation
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

Twenty-two spikes, run on 2026-10-27 against `structr/structr:6.0.0`: 20 behave as documented,
one does not (Python), one only reports (the endpoints). What each showed, and what it means here:

| Spike | 6.0.0 showed | For this project |
|---|---|---|
| cascade | `cascadingDeleteFlag` 1 (source to target) deletes the target with its source; 0 leaves it | Batch 2 below |
| cascade_more | A flag set on a relationship that already has edges applies to them after a restart; cascades chain; **the target is deleted even when another node still points at it**, by the same relationship type or another | `HAS_SPECIFIED_QUANTITY`, `EXPECTED_VALUE_QTY` and the step times are declared many-to-one: one quantity could be shared. The importer never shares one (each is named after its owner), but the migration must check, and refuse if any is |
| visibility | A type's `defaultVisibleToAuth` makes a node created without flags visible to every signed-in user, **but the node's stored `visibleToAuthenticatedUsers` still reads false** | Not a safety net for hard rule 4: every check that reads the flag would still call such a node hidden, and the flag would hide the slip the snapshot catches. Not adopted |
| compound | Two properties marked `unique` and `compound` refuse a repeated pair (422 `already_taken`) and accept a new one | Ready for stage 5's per-household names |
| format | `[0,100]`, `[0,100[`, `[0.0,100.0]` refuse values outside with 422 `must_be_in_range`, on Double and Integer, for creates and edits; **an open end (`[0,]`) is accepted but checks nothing**; a missing value passes. **A string pattern refuses a missing value** (`must_match`) | Invariant 12 can be a format with a large upper bound, covering edits the `onCreate` validator misses; never a pattern on an optional property |
| onsave | `$.retrieve('modifications')` holds `before` and `after`; `$.error` in `onSave` refuses the edit (422) and nothing changes | `onSave` twins of the validators work, but see Batch 4 on the importers' two-step writes |
| grant | A `SchemaGrant` (`schemaNode`, `principal`, `allowRead`, `allowWrite`, `allowDelete`, `allowAccessControl`) lets a group's members read and write every node of a type, owned by anyone, with no flags; a non-member sees none | Stage 5's curators of the shared vocabulary |
| propagation | `permissionPropagation: "Out"` with `readPropagation: "Add"` (the others `"Keep"`): a read grant on a folder lets a user read its documents, which carry no grant | Stage 5: a household's MealPlan opening its entries |
| labels | A node made before its type gained a trait lacks the trait's label and is refused as the target of a relationship to the trait; `POST /structr/rest/maintenance/createLabels {"type": ...}` adds it, and the same relationship is then accepted | Hard rule 2's "only fixable with direct Cypher" is out of date: `createLabels` is the supported fix. The rule's wording is the owner's to change (`docs/todo.md`) |
| bulk | An array POST is one transaction (one duplicate in it: 422, nothing created); a PATCH array on a collection updates many | Batch 6 |
| unknown | `STRUCTR_jsonrestservlet_unknowninput_validation_mode=reject` refuses a key the schema does not declare (422 "Rejecting input with unknown JSON key ...") and creates nothing | Batch 1: a misspelt key in a tool stops being stored silently as a stray property |
| changelog | With `STRUCTR_application_changelog_enabled` and `..._user__centric_enabled`, `$.changelog(id, false)` lists `create` and `change` entries with `prev`, `val`, `userName` and time; kept as files in `/var/lib/structr/changelog`, **which is on no volume** | Batch 1, with a volume and a place in the backups |
| cron | `STRUCTR_cronservice_tasks=<function>` and `STRUCTR_<function>_cronExpression` (six fields) run the function; it must exist when Structr starts | No task yet; a nightly check is a candidate |
| polyglot | **No.** The image carries the GraalPy jars, but `Polyglot.eval('python', ...)` answers 422 and the log says "No language for id python found. Supported languages are: [js]" | Python cannot run inside Structr 6.0 as shipped: what a request does stays JavaScript (`methods/`) and the planner stays Python outside it, as Path S has it |
| params | A `SchemaMethodParameter` of type Integer turns `"7"` into 7; `httpVerb: "GET"` takes path segments (`/structr/rest/<name>/5`) and refuses POST (405); **an undeclared argument is dropped silently** (7.1 refuses it) | Batch 5. Every method must declare every argument it reads before 7.1 |
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

**Batch 1, operations: settings in `docker-compose.yml`, no schema change.**
- A compose health check on `/structr/health/ready` (`curl` is in the image), so `docker compose ps`
  says when Structr is ready. `tools/wait_for_structr.sh` keeps its authenticated read, which also
  proves the password.
- The changelog on, with the user-centric log, on a volume of its own (`structr-changelog`) that
  `tools/backup.py` backs up with the others. It records from the moment it is on; the history
  before stays unknown.
- Unknown input keys refused (`reject`). The rebuild is the check: every script and tool writes
  through REST, so a rebuild that ends identical shows none sends a key the schema lacks.

**Batch 2, cascading delete (migration 44a).** Source-to-target on Step `HAS_SPECIFICATION`,
`HAS_WORKING_TIME` and `HAS_WAITING_TIME`; Specification `HAS_SPECIFIED_QUANTITY`,
`HAS_STATE_REQUIREMENT` and `HAS_SUBSTITUTION_RULE`; StateRequirement `EXPECTED_VALUE_QTY`. These
are what `recipe_import._remove_stale` deletes by hand, one request each; with the flags, deleting a
Step or a Specification takes its dependents in one transaction. 44a first checks that no target of
these relationships has a second incoming edge of any kind (cascade_more: a shared target would be
deleted from under its other owner) and refuses if one has. The importer then deletes Steps and
Specifications only, and refuses to run against an instance without 44a. The offline graph learns
the same flags.

**Batch 3, invariant 12 as `format`.** `[0,1000000000]` on the quantity-bearing values
(QuantitySpecification `value`, `minValue`, `maxValue`; Measurement `value`): the `onCreate`
validators stay, the format adds edits. An open end checks nothing, hence the large bound.

**Batch 4, `onSave` twins of the validators,** after a read-only check that the existing data
breaks none of them. The catch found reading the importers: `_write` upserts, then clears the
fields given as None in a second request, so a quantity going from a range to a value has both for
a moment, and a twin of QuantitySpecification's check would refuse the first request. The writers
change first (one PATCH that sets and clears), then the twins.

**Batch 5, methods:** declared parameters for every argument a method reads, GET for the read-only
ones, `includeInOpenAPI` with a tag for the planner contract. Needed before 7.1 in any case.

**Batch 6, importers in one transaction:** a recipe written as array POSTs, so an interrupted import
leaves nothing half-written, and measured against today's 8 to 19 s a recipe.

**Waiting on the owner, or on stage 5:** schema grants, propagation and compound uniqueness (stage
5's sharing and names); the wording of hard rule 2 now that `createLabels` works; a changelog-based
journal and undo for the pantry (`docs/todo.md`); `sync` export as "download my data"; Event Action
Mapping for bookings; a nightly scheduled check. **Not adopted:** default visibility (the stored
flag stays false, section 3) and Python inside Structr (not available on 6.0).

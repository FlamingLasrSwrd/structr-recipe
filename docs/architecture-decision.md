# Architecture for a self-hosted and a hosted offering: a proposal

**Status: a proposal for the owner to decide** (2026-10-26; revised the same day, after the owner
challenged two of its claims, both corrected in §9). Nothing here is started. The owner wants to offer
both a self-hosted and a centrally hosted service for many households, and chose Structr because the
model fits a graph. This document weighs the platform again against both offerings, using the design
documents, the code as it is, probes on the development instance, and the sources listed at the end.

## 1. The question that decides it

Both coherent paths keep the graph, keep Neo4j and keep the owner's data where it is (§3). They
differ on **where the domain logic lives**:

- **Path P: Python, with Neo4j directly.** One Python application owns every calculation, booking and
  permission, serves the pages and runs the planner; it talks to Neo4j through Neo4j's own driver
  (Bolt), and Structr leaves the stack.
- **Path S: Structr, used fully.** The domain logic moves into Structr's JavaScript methods, next to the
  data; the pages call them; Structr's own accounts and access control keep households apart. Python
  remains for the planner (OR-tools) and the importers.

Today's arrangement (logic in Python, reaching the data over REST, with a second copy in the pages'
JavaScript, and Structr's access control unused) is neither, and serves neither offering well.

**The recommendation: Path P,** because the planner must be Python, and the domain engines feed it:
- **The planner depends on them.** It reads stock, nutrition, defaults and exclusions through the engines in `mealplanner/`, and OR-tools has no JavaScript form. Under S the planner would need those figures from Structr in one export call, and every engine it uses would exist in JavaScript first. Under P they stay one copy, in the planner's own language.
- **The tests stay offline.** 748 tests and two mutation sweeps test the Python in seconds. Code inside Structr can only be tested against a running instance (a rebuild takes about nine and a half minutes).
- **Self-hosting is smaller and steadier.** P drops a 2 GB Java service, and with it most of the hard rules (§3).
- **The hosted service's licence is simpler.** P runs no AGPL component.

**S is the better choice if the hosted service's isolation and accounts matter more than these.**
Structr already has the accounts, sign-up, password reset, account lockout and per-household access
control that P must build, and in S the platform, not the application, enforces the boundary between
households (§5). That is a real advantage, and the main thing P gives up.

## 2. What the two offerings ask of the platform

| | Self-hosted: one household, at home | Hosted: many households, one service |
|---|---|---|
| Data | one household's, plus the shared vocabulary, profiles and public prices, shipped as files and loaded (today's importers) | the same shared data, **curated once for everyone**, and each household's private data beside it (`verification-and-sharing.md` §3.4) |
| Between households | nothing | suggestions to shared figures, seconded or disputed by people from other households, accepted by curators or by a consensus counted in households (§3.6) |
| Isolation | none needed inside one household | each household sees its own data and the shared data, and nothing of another's |
| Size | the owner's instance today: 42,386 nodes and 88,680 relationships, the vocabulary included | the vocabulary once, plus each household's recipes, plans and pantry ledger, which grows every week |
| Footprint | a small home server: today's stack needs about 3.5 GB (`docs/self-hosting.md` step 7) | a server sized to its users |
| Backups | a nightly dump with the stack stopped is acceptable | without stopping the service |
| Install, upgrade | one command each (`docs/self-hosting.md` steps 1 and 5) | the operator's routine |
| Licence | the user runs it themselves | the operator runs it as a network service for others |

**The deciding row is "between households".** Shared figures are curated for everyone, and private data
points at them constantly: a household's portions are instances of shared food Types, its recipes call
for them, its nutrition reads their shared figures, its own prices and densities override shared ones
(J27). Suggestions and consensus cross households by design. So the hosted service is one graph with
shared and private parts, not a graph per household: a database per household would copy the
vocabulary into each and could not hold a suggestion seconded by three households. Either path holds
this; they differ on who enforces the boundary.

## 3. What Structr does today, and what it could do

| What | Today | Available in Structr 6, unused or barely used |
|---|---|---|
| **Storage** | Neo4j underneath. Checked on the development instance: a portion is one Neo4j node labelled with its whole trait chain (`Entity`, `Continuant`, `IndependentContinuant`, `MaterialEntity`, `BfoObject`, `FoodObject`, `PortionOfSubstance`, and Structr's own four), with properties `id` (a UUID), `type`, `name` and audit fields; relationships are native Neo4j relationships of the model's types (`ABOUT`, `FULFILLS`, `HAS_ACTUAL_QUANTITY`). Python could read it directly: nothing to migrate | |
| **The structural schema** (54 types, build sketch §2) | traits, which are those labels; polymorphic targets (`Allocation -[ABOUT]-> Entity`) in one declaration | |
| **Validators** (the write-time invariants: 9 of the 30, README) | StructrScript lifecycle methods, written as strings by Python scripts | lifecycle methods in JavaScript |
| **The algorithms** | in Python, over REST. The build sketch planned them as Structr methods and recorded that StructrScript could not express them (no recursion between methods with arguments, no comparison operators, filters that do not nest). That was true of StructrScript; the JavaScript form of a method was never found (the cheatsheet tried `${{ }}` and `codeType`) | **methods in JavaScript**, a `{ ... }` body (Structr's own documentation). Probed 2026-10-26: a method recursing through calls with an argument works, and a method working out every portion's grams on hand (the latest weighing, less each later use, with a recursive walk up its type's hierarchy) agreed with Python's `pantry.on_hand` on all 17 portions, in 0.7 to 0.9 s warm, where Python over REST took 12.6 s for the same 17 |
| **Access to the data** | REST only: about 270 calls to six client methods (`get_all`, `get`, `post`, `patch`, `delete`, `upsert`) in 21 modules, behind an interface the 127-line `tests/fakegraph.py` imitates for 748 tests | |
| **Pages** | 1,440 lines of server-side JavaScript repeating the Python | calling methods instead of repeating them |
| **Accounts and access control** | `Person` inherits Structr's `User` and `Household` its `Group` (K1, K2), and a group grant was probed to reach a household's members and no one else (2026-09-28). Nothing else is used: every tool connects as the superuser and every page writes through `$.doPrivileged`. That was the implementation's choice, made when the owner put security out of scope (2026-10-23), not a limit of Structr | nested groups; per-endpoint permissions (`ResourceAccess`); grants per node to users and groups; ownership; **permission propagation along chosen relationships**, with hidden properties (a grant on a Household could reach its plans, stock and recipes through their relationships); sign-in, JWT tokens, sign-up and password reset endpoints; account lockout after failed sign-ins (Structr's documentation; propagation not yet probed here) |
| **Admin UI** | data and schema browsing | |

**What Structr costs, whichever way it is used:**
- **Memory:** a second Java service, capped at 2 GB, beside Neo4j's 1.5 GB.
- **Platform quirks:** `docs/structr-cheatsheet.md` is 1,385 lines of verified Structr behaviour. Six of the eight hard rules in `docs/CLAUDE.md` exist because of Structr (1, 2, 4, 6, 7, 8): renames that orphan data, a trait that cannot be added to a populated type, visibility that defaults to owner-only, inverted relationship names, a global `unique`, and a stale cache after schema changes. In Neo4j itself, adding a label to existing nodes is one statement.
- **Licence:** Structr is AGPL or GPL, or commercial. Running it as a hosted service raises the AGPL question `docs/self-hosting.md` already sends to someone qualified.
- **Vendor:** Structr GmbH and its community are small.

**What was the implementation's, not Structr's:**
- **The slowness:** the logic sits outside Structr and fetches the graph a request at a time.
- **The two copies:** Python, and the pages' JavaScript.
- **The unused access control.**
- **The race fixed today** (REVIEW.md round 3 #9): the pages wrote in the page's own transaction.

## 4. The options

| | Today | **P. Python, Neo4j directly** | **S. Structr, used fully** | C. PostgreSQL, relational | D. PostgreSQL with Apache AGE | E. Memgraph | F. An RDF store |
|---|---|---|---|---|---|---|---|
| Model fit | as now | as now: labels for traits, any node as a target, Cypher for hierarchies | as now | the 54 types become tables, "any entity" a shared entity table, hierarchies recursive queries: workable, against the model's grain | **one label per node** (an early design decision; work on several exists on a branch, in no release I could confirm), so traits become a property and polymorphic matches filters | as P: Cypher, several labels, Neo4j's protocol | BFO's native form; SPARQL, SHACL validation |
| The owner's data | stays | **stays** | **stays** | migrated | migrated | migrated | migrated |
| Where the logic lives | Python over REST, and a JavaScript copy | Python, beside the planner; offline tests kept | Structr JavaScript; tested on a live instance; the planner in Python on an exported problem | Python | Python | Python | rewritten |
| Isolation between households | none | the application's data-access layer | **Structr's access control** (grants, propagation) | row-level security | row-level security since AGE 1.7.0 (January 2026), how it applies to graph tables not checked | roles are Enterprise | rarely |
| Accounts, sign-up, reset, lockout | Structr's, unused | to build (standard libraries) | **built in** | to build | to build | to build | to build |
| Self-hosted footprint | ~3.5 GB | ~1.5 GB for Neo4j, plus the app and the worker (estimate) | ~3.5 GB, plus the worker | small | small | in memory, about the data's size | small to moderate |
| Online backups | no (Neo4j Community dumps a stopped database) | no, without Enterprise | no, without Enterprise underneath | yes | yes | replication in Community, without automatic failover | depends on the store |
| Licence | AGPL / GPL, or commercial | GPL v3 (Community); Enterprise commercial, with a startup programme | AGPL / GPL, or commercial, over GPL Neo4j | PostgreSQL (permissive) | Apache 2.0 | Business Source Licence: source available, not open source; Enterprise from $25,000 a year | Apache 2.0 / MIT |
| Maturity for this | known | widely used, single instance in Community | known, with its cheatsheet | the most | young; a Cypher subset | smaller ecosystem | not built for a booking-heavy application |

**Why not the others:**
- **C** has the best operations and the strongest isolation, but migrates the data and remodels what the graph expresses directly. It is the fallback if the hosted service's operations come to outweigh model fit.
- **D's** one label per node strikes at the structural layer, which is built on several. Revisit it if AGE gains several labels.
- **E** is P's near neighbour, and most of P's code would run on it. It is not open source, and its RAM grows with the ledger. It is worth measuring only if Neo4j's footprint proves too much for home servers.
- **F's** case was weighed when Structr was chosen (data-model §16: no accounts, REST or admin; OWL reasoning out of scope). Publishing the shared vocabulary as RDF is a later feature, not a store.

## 5. P and S side by side

| | P. Python, Neo4j directly | S. Structr, used fully |
|---|---|---|
| **Domain logic** | stays in Python (11,500 lines with the planner), one copy | moves into Structr JavaScript: the pages hold a partial port today (1,440 lines); the rest, and the importers' checks, to write |
| **Tests** | the offline suite and fake graph stay; live checks as now | the logic's tests run against a live instance; the offline suite shrinks to the planner's search |
| **The planner** | reads the graph directly, through the same engines | reads one problem a Structr method exports, so every engine it uses exists in JavaScript first |
| **Speed** | one Cypher query per need (unmeasured) | measured: a method next to the data, 0.7 s where Python over REST took 12.6 s |
| **Isolation between households** | the application's: every read and write through one data-access layer that requires a household, and tests that try to cross it. Platform-enforced only by moving to PostgreSQL later | **Structr's**: a household's data granted to its Group, propagated along its relationships, checked by the platform on every read, whatever the code asks |
| **Accounts** | to build: sign-in, sessions, sign-up, reset, lockout (standard libraries) | built in, to configure |
| **Self-hosted footprint** | about 2 GB in all (estimate) | about 3.5 GB plus the planner |
| **Hard rules** | six retire with Structr | all stay, and become promises to every install |
| **Licence for the hosted service** | GPL only (Neo4j) | the AGPL question first |
| **Vendor** | Neo4j and the Python ecosystem | Structr GmbH, small |
| **Work to get there** | the client interface over Bolt, an app, accounts | a port of the engines to JavaScript, the access-control configuration, the planner's export |

**If S were chosen,** its first stage would be the same kind of gate as P's: port one engine
(stock on hand, already shown above) and one booking to methods, configure a household's grants
with propagation, and check against Python and across two households that each sees only its own.

## 6. What P leaves open for the hosted service

- **Isolation is the application's.** Neo4j Community has one database user with every right. That is normal for a hosted service, where database users are not people, but it puts the whole boundary in code. So:
  - every query starts from the household it is for;
  - shared data is read-only to anyone who is not a curator;
  - tests try to read and book across households, and must fail.

  If an auditor or customer ever demands isolation enforced by the platform, C is the way, or S, had it been chosen.
- **Backups without stopping the service:** Neo4j Enterprise's online backup, or snapshots of the data volume. Snapshots are an engineering choice to test first.
- **No failover:** Community is one instance. Start on one server with tested restores (`docs/backups.md`), and buy clustering when users need it.
- **Support:** Community comes with none.

None of these touch the self-hosted offering, and none need a decision before the hosted service has users.

## 7. Path P, in stages

Each stage keeps the product working and ends in a check of the kind this project already uses.

1. **The client interface over Bolt.** A second implementation of the six methods the Python uses. It reads and writes the same nodes Structr made, mapping each field name to its relationship type and direction from the declarations in `mealplanner/*_schema.py`, which already hold that mapping. It renders rows as Structr does, so the domain code and the fake graph need no change. *Done when* every read the tools and `check_pages.py` make returns the same rows through Bolt as through REST, on the development instance and read-only on the owner's. Measure the speed against the JavaScript method's 0.7 s and the planner's four-minute read. **This is the gate: if Bolt cannot reproduce what Structr returns, or gains nothing, stop and decide again, with S as the alternative.**
2. **The app serves the pages,** one at a time, from the same Python the tools use; `check_pages.py` compares the old page with the new until the old one is removed.
3. **Writes go through the app:**
   - each booking runs in one Neo4j transaction, with a lock per household, so households never wait on each other;
   - the write-time validators become Python checks in that one write path, plus Neo4j's unique constraints;
   - the terminal tools write through the same path.

   `check_bookings.py` compares, as now.
4. **Accounts in the app:**
   - sign-in, sessions, form posts protected against cross-site requests, HTTPS, account lockout, password reset (`docs/self-hosting.md` step 4);
   - household membership and the curators' group read from the graph;
   - the household scope required on every query from here on.

   Household members set new passwords, unless the app learns to check Structr's stored hashes (not looked into).
5. **Structr leaves the stack:**
   - its own nodes (schema, page elements, grants) are removed, and the owner's instance is backed up first;
   - the numbered scripts' Structr schema steps give way to the Python declarations;
   - hard rules 1, 2, 4, 6, 7 and 8 retire, and rules 3 and 5 stay as discipline;
   - the model gains a revision recording the change (data-model §16 named Structr).

   *Done when* the stack is Neo4j, the app and the worker, and every check passes.
6. **The two offerings:**
   - **Self-hosted:** one compose file, a household made on first run (self-hosting step 2), backups as now.
   - **Hosted:** the same images, with sign-up, the shared/private split marked on the data (`verification-and-sharing.md` §3.4: "mechanical"), curation (§3.6), then §6's choices.

Stages 1 and 2 are worth doing even if the hosted service never comes: they remove the JavaScript
copies (round 3 #5) and the REST slowness, and they make self-hosting smaller.

## 8. Decisions for the owner

1. **Where the domain logic lives:** Python (P) or Structr's JavaScript (S). The rest follows from it.
2. **The first stage, as a spike:** P's Bolt interface, or S's one-engine, two-household gate (§5). Either can run before anything else changes, and either result can send the decision the other way.
3. **When the hosted service is near:** under P, Enterprise or the alternatives in §6; under S, the AGPL question.

## 9. Corrections (2026-10-26)

The first version of this document said two things the owner challenged, and both were wrong as stated:

- **"The calculations planned as Structr methods ended up in Python because Structr's script language could not handle multi-step traversals."** True of StructrScript only. Structr also runs methods written in JavaScript, which the project never found. Probed: recursion between calls with an argument, and a stock-on-hand method agreeing with Python on every portion, faster (§3). The build sketch's §5 note and the cheatsheet's §3a are corrected to match.
- **"Structr's per-household permissions go unused" was put as a cost of Structr.** It is the implementation's: tools connect as the superuser and pages write through `$.doPrivileged` because security was out of scope by the owner's choice. Structr's access control (§3) is a strength for the hosted service, and §1 and §5 now weigh it as one.

## Sources (checked 2026-10-26)

- Apache AGE, one label per vertex: [apache/age discussion #109](https://github.com/apache/age/discussions/109); [Label, vertex and edge redesign ideas](https://dev.to/capnspek/label-vertex-edge-redesign-ideas-51fg). Row-level security in 1.7.0: [AGE release notes](https://age.apache.org/release-notes).
- Neo4j editions: [Operations manual, introduction](https://neo4j.com/docs/operations-manual/current/introduction/) (Community a single instance; Enterprise online backup, clustering, roles); [Neo4j licensing](https://neo4j.com/licensing/) (Community GPL v3); [startup programme](https://neo4j.com/blog/were-expanding-the-neo4j-startup-program-now-more-entrepreneurs-get-neo4j-enterprise-edition-neo4j-bloom-for-free) (its current terms not confirmed).
- Memgraph: [pricing](https://memgraph.com/pricing); [clustering FAQ](https://memgraph.com/docs/clustering/faq); [high availability and licence differences](https://memgraph.com/blog/building-high-availability-in-memgraph-license-differences).
- Structr 6.0.0's own documentation, bundled in its image: "Security" (groups, resource permissions, node grants, ownership, graph-based permission resolution, lockout), "Lifecycle Methods" (a JavaScript method body in `{ ... }`), "Structr 6.x Migration Notes" (user-defined functions at `/structr/rest/<name>`).
- This project: the development instance's Neo4j, read with `cypher-shell`; two throwaway JavaScript functions on the development instance, called over REST and removed (§3); `docs/backups.md` (Community dumps a stopped database); the owner's instance's counts from its last verified backup.

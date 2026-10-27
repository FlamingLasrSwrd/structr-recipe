# Architecture for a self-hosted and a hosted offering: a proposal

**Status: a proposal for the owner to decide** (2026-10-26). Nothing here is started. The owner wants
to offer both a self-hosted and a centrally hosted service for many households, and chose Structr
because the model fits a graph. This document weighs that choice again against both offerings, using
the design documents, the code as it is, and facts checked on the development instance and at the
sources listed at the end. It recommends a path, in stages that each end in a check.

## 1. The recommendation

1. **One Python application is the backend**, the same code for both offerings: a web app that serves
   the pages and owns every calculation, booking and permission, and a worker that runs the planner.
   The JavaScript copies in `pages/` retire as the app takes each page over.
2. **Keep the graph, and keep Neo4j; drop Structr.** The app talks to Neo4j directly through its own
   driver (Bolt). The owner's data stays where it is: Structr already stores the model as ordinary
   Neo4j nodes and relationships (§3), so there is nothing to migrate, only a different way in.
3. **One database holds shared and private data**, with every household's data scoped by the app's
   data-access layer from the first line. A database per household would not fit the sharing design
   (§2).
4. **Decide the hosted service's extras when it has users:** Neo4j Enterprise (online backups,
   clustering, roles) or a tested alternative for each. The self-hosted offering needs none of them.

Why: of the options in §4, this one keeps what the model gains from a graph and the data already
held, removes what Structr costs (§3), and works for both offerings. Its known gaps are the hosted
service's operations (§5), and they can be bought or engineered later without touching the model.

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
vocabulary into each and could not hold a suggestion seconded by three households.

## 3. What Structr does for the project today

| What | How it stands | Kept without Structr by |
|---|---|---|
| **Storage** | Neo4j underneath. Checked on the development instance (2026-10-26): a portion is one Neo4j node labelled with its whole trait chain (`Entity`, `Continuant`, `IndependentContinuant`, `MaterialEntity`, `BfoObject`, `FoodObject`, `PortionOfSubstance`, and Structr's own four), with properties `id` (a UUID), `type`, `name` and audit fields; relationships are native Neo4j relationships of the model's types (`ABOUT`, `FULFILLS`, `HAS_ACTUAL_QUANTITY`) | Neo4j, as it is |
| **The structural schema** (54 types, build sketch §2) | traits, which are those labels | the labels, set by the data-access layer from `mealplanner/structural_types.py` at creation |
| **Polymorphic targets** (`Allocation -[ABOUT]-> Entity`) | one declaration | native: Neo4j relationships take any node |
| **Validators** (the write-time invariants: 9 of the 30, README) | StructrScript lifecycle methods, written as strings by Python scripts | Python checks in the one write path, and Neo4j's unique constraints (in Community) |
| **The algorithms** | planned as Structr methods (build sketch §5), built in Python instead, because StructrScript could not express multi-hop logic (the sketch's own note). Only the kind-only `resolveDefault` remains, and nothing calls it | already Python |
| **Access to the data** | REST only: about 270 calls to six client methods (`get_all`, `get`, `post`, `patch`, `delete`, `upsert`) in 21 modules, behind an interface the 127-line `tests/fakegraph.py` imitates for 748 tests | the same interface over Bolt (§6 stage 1) |
| **Pages** | 1,440 lines of server-side JavaScript repeating the Python | the app |
| **Accounts and sharing** | `Person` inherits Structr's `User` and `Household` its `Group` (K1, K2), so Structr could check grants per household. In practice it checks none: every tool connects as the superuser and every page writes through `$.doPrivileged` | the app: accounts on Person nodes, sessions, household membership read from the graph (`has member part`) |
| **Admin UI** | data and schema browsing | Neo4j Browser for reading; the app's own curator pages for shared data |

**What Structr costs:**
- **Memory:** a second Java service, capped at 2 GB, beside Neo4j's 1.5 GB.
- **Speed:** every traversal is REST requests. A small selector run made 95 (REVIEW.md round 2 #15), and reading a week over 1,001 recipes takes about four minutes (optimizer-design §12).
- **Learning its quirks:** `docs/structr-cheatsheet.md` is 1,385 lines of verified Structr behaviour. Six of the eight hard rules in `docs/CLAUDE.md` exist because of it (1, 2, 4, 6, 7, 8): renames that orphan data, a trait that cannot be added to a populated type, visibility that defaults to owner-only, inverted relationship names, a global `unique`, and a stale cache after schema changes. In Neo4j itself, adding a label to existing nodes is one statement.
- **Licence:** Structr is AGPL or GPL, or commercial. Running it as a hosted service raises the AGPL question `docs/self-hosting.md` already sends to someone qualified.
- **The race fixed today** (REVIEW.md round 3 #9) came from Structr committing a page's write after the page had answered.

## 4. The options

| | A. Structr stays | **B. Neo4j directly** | C. PostgreSQL, relational | D. PostgreSQL with Apache AGE | E. Memgraph | F. An RDF store |
|---|---|---|---|---|---|---|
| Model fit | as now | as now: labels for traits, any node as a target, Cypher for hierarchies | the 54 types become tables, "any entity" a shared entity table, hierarchies recursive queries: workable, against the model's grain | graph in Cypher, **one label per node** (an early design decision; work on several exists on a branch, in no release I could confirm), so traits become a property and polymorphic matches filters | as B: Cypher, several labels, Neo4j's protocol | BFO's native form; SPARQL, SHACL validation |
| The owner's data | stays | **stays** | migrated | migrated | migrated | migrated |
| The Python | unchanged | the client interface reimplemented once (§6) | every read rewritten as SQL, or an adapter that hides it | the interface over AGE's Cypher subset | as B | rewritten |
| Self-hosted footprint | ~3.5 GB | ~1.5 GB for Neo4j, plus the app and the worker (estimate) | small (PostgreSQL) | small | in memory, about the data's size | small to moderate |
| Online backups | no (Neo4j Community dumps a stopped database) | no, without Enterprise | yes | yes | replication in Community, without automatic failover | depends on the store |
| Isolation in the database | Structr grants, unused today | no (Community has no roles); in the app | row-level security | row-level security since AGE 1.7.0 (January 2026), how it applies to graph tables not checked | roles are Enterprise | rarely |
| Licence | AGPL / GPL, or commercial | GPL v3 (Community); Enterprise commercial, with a startup programme | PostgreSQL (permissive) | Apache 2.0 | Business Source Licence: source available, not open source; Enterprise from $25,000 a year | Apache 2.0 / MIT (Jena, Oxigraph) |
| Maturity for this | known, with its cheatsheet | widely used, single instance in Community | the most | young; a Cypher subset; follows PostgreSQL versions late | smaller ecosystem | not built for a booking-heavy application |

**Why not the others:**
- **A** keeps every cost in §3 for both offerings, and its one unique gift, grants per household, is unused and would need every tool and page rewritten to act as a user anyway.
- **C** has the best operations and the strongest isolation, but it migrates the data and remodels what the graph expresses directly. It remains the fallback if the hosted service's operations come to outweigh model fit (§5).
- **D's** one label per node strikes at the structural layer, which is built on several. Revisit it if AGE gains several labels, since PostgreSQL's operations would then come with the graph.
- **E** is the near neighbour of B, and most of B's code would run on it. It is not open source, and its in-memory design makes RAM grow with the ledger. It is worth a measurement only if Neo4j's footprint proves too much for home servers.
- **F's** case was weighed when Structr was chosen (data-model §16: no accounts, REST or admin; and OWL reasoning is out of scope). Publishing the shared vocabulary as RDF, for others to map to, is a later feature, not a store.

## 5. What B leaves open for the hosted service

- **Isolation is the app's.** Neo4j Community has one database user with every right. That is normal for a hosted service, where database users are not people, but it puts the whole boundary in code. So:
  - every read and write goes through one data-access layer that requires a household;
  - shared data is read-only to anyone who is not a curator;
  - tests try to read and book across households, and must fail.

  If an auditor or customer ever demands isolation enforced in the database, C (or D, once ready) is the way.
- **Backups without stopping the service:** Neo4j Enterprise's online backup, or snapshots of the data volume. Snapshots are an engineering choice to test before relying on them.
- **No failover:** Community is one instance. A hosted service starts on one server with tested restores (`docs/backups.md`) and buys clustering when its users need it.
- **Support:** Community comes with none.

None of these touch the self-hosted offering, and none need a decision before the hosted service has users.

## 6. The path, in stages

Each stage keeps the product working and ends in a check of the kind this project already uses.

1. **The client interface over Bolt.** A second implementation of the six methods the Python uses. It reads and writes the same nodes Structr made, mapping each field name to its relationship type and direction from the declarations in `mealplanner/*_schema.py`, which already hold that mapping. It renders rows as Structr does, so the domain code and the fake graph need no change. *Done when* every read the tools and `check_pages.py` make returns the same rows through Bolt as through REST, on the development instance and read-only on the owner's. Measure the speed (the planner's four-minute read is the case to watch). **This is the gate: if Bolt cannot reproduce what Structr returns, or gains nothing, stop here and decide again.**
2. **The app serves the pages,** one at a time, from the same Python the tools use; `check_pages.py` compares the old page with the new until the old one is removed.
3. **Writes go through the app:**
   - each booking runs in one Neo4j transaction, with a lock per household, so households never wait on each other;
   - the write-time validators become Python checks in that one write path, plus Neo4j's unique constraints;
   - the terminal tools write through the same path, closing the gap the pages' lock leaves.

   `check_bookings.py` compares, as now.
4. **Accounts in the app:**
   - sign-in, sessions, form posts protected against cross-site requests, and HTTPS (`docs/self-hosting.md` step 4);
   - a Person's password hash stored by the app; household members set new passwords, unless the app learns to check Structr's stored hashes (not looked into);
   - household membership and the curators' group read from the graph;
   - the household scope required on every query from here on.
5. **Structr leaves the stack:**
   - its own nodes (schema, page elements, grants) are removed, and the owner's instance is backed up first;
   - the numbered scripts' Structr schema steps give way to the Python declarations;
   - hard rules 1, 2, 4, 6, 7 and 8 retire with it, and rules 3 and 5 stay as discipline;
   - the model gains a revision recording the change (data-model §16 named Structr).

   *Done when* the stack is Neo4j, the app and the worker, and every check passes.
6. **The two offerings:**
   - **Self-hosted:** one compose file, a household made on first run (self-hosting step 2), backups as now.
   - **Hosted:** the same images, with sign-up, the shared/private split marked on the data (`verification-and-sharing.md` §3.4: "mechanical") and curation (§3.6). Then §5's choices.

Stages 1 and 2 are worth doing even if the hosted service never comes: they remove the JavaScript
copies (round 3 #5) and the REST slowness, and they make self-hosting smaller.

## 7. Decisions for the owner

1. Whether to take this path (B), or keep Structr (A), or go to PostgreSQL (C).
2. If B: whether to start with stage 1 as a spike, before anything else changes.
3. When the hosted service is near: Enterprise, or the alternatives in §5, for backups, failover and support.

## Sources (checked 2026-10-26)

- Apache AGE, one label per vertex: [apache/age discussion #109](https://github.com/apache/age/discussions/109); [Label, vertex and edge redesign ideas](https://dev.to/capnspek/label-vertex-edge-redesign-ideas-51fg). Row-level security in 1.7.0: [AGE release notes](https://age.apache.org/release-notes).
- Neo4j editions: [Operations manual, introduction](https://neo4j.com/docs/operations-manual/current/introduction/) (Community a single instance; Enterprise online backup, clustering, roles); [Neo4j licensing](https://neo4j.com/licensing/) (Community GPL v3); [startup programme](https://neo4j.com/blog/were-expanding-the-neo4j-startup-program-now-more-entrepreneurs-get-neo4j-enterprise-edition-neo4j-bloom-for-free) (its current terms not confirmed).
- Memgraph: [pricing](https://memgraph.com/pricing); [clustering FAQ](https://memgraph.com/docs/clustering/faq); [high availability and licence differences](https://memgraph.com/blog/building-high-availability-in-memgraph-license-differences).
- This project: the development instance's Neo4j, read with `cypher-shell` (labels, properties and relationship types above); `docs/backups.md` (Community dumps a stopped database); the owner's instance's counts from its last verified backup.

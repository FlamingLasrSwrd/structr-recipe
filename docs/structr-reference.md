# Structr reference for AI assistants

A working reference to [Structr](https://structr.com), the graph-database application platform
(Neo4j underneath, REST API, server-side scripting, server-rendered pages), written for an AI
assistant that has to build or change a Structr application through its REST API and scripts. It
is about Structr only, not any one application, and it is written in its own words: it summarises,
it does not reproduce, the official documentation at structr.org/docs.

Every statement carries a marker saying how far it can be trusted:

| Marker | Meaning |
|---|---|
| **[V6]** | Verified by running it against a real Structr 6.0.0 Community instance (Neo4j 5, Docker). Trust it for 6.0 |
| **[P6]** | Present in 6.0.0: the field, endpoint or command exists there (read from the instance's schema metadata or OpenAPI document), but its behaviour was not exercised |
| **[D7]** | From the documentation, which describes 7.x (7.0 and 7.1). Not verified; may be absent from or differ in 6.x |
| **[7.1]** | Introduced or changed in 7.1 (from its release notes) |

**On 7.1.0 (2026-10-27):** the spikes behind the [V6] markers were run again on 7.1.0, and so was a
whole application built through REST that relies on many other [V6] items (schema setup and
relationship naming, lifecycle validators, grants to groups, pages built from elements, methods).
Everything held except what section 13 lists under "7.1.0, verified". Items not exercised that way
(file uploads, for one) are still 6.0 findings.

Where a [V6] finding contradicts the documentation, the [V6] finding wins for 6.0. Before relying
on a [D7] or [P6] item for anything that writes data, try it on a disposable instance first: a
small probe that creates throwaway types, checks one behaviour and deletes them is cheap, and
Structr has many behaviours that only show in practice.

Contents: 1 Mental model - 2 Running an instance - 3 Authentication - 4 Authorization - 5 Schema
through REST - 6 Scripting and methods - 7 Transactions and concurrency - 8 REST data access -
9 Pages - 10 Files - 11 Background work and integrations - 12 Operations - 13 Versions -
14 Patterns - 15 Probing checklist.

---

## 1. Mental model

- **Everything is a node or a relationship in one graph**, including the schema itself
  (`SchemaNode`, `SchemaProperty`, `SchemaRelationshipNode`, `SchemaMethod`, `SchemaView`,
  `SchemaGrant`), pages (`Page`, DOM elements, `Content`, `Template`), files (`File`, `Folder`,
  `Image`), users and groups (`User`, `Group`), and security settings (`ResourceAccess`). Changing
  the schema is writing data; it takes effect at once, without a deployment step.
- **The schema and the data are loosely coupled.** Renaming or deleting a type, property or
  relationship does not migrate existing data: old nodes keep their old property names and labels,
  and can become unreachable (section 5.6). Migrating data is the application's job.
- **Types are built from traits.** Every node type is a composition of traits, with multiple
  inheritance through `inheritedTraits` (an ordered list of type names). Built-in behaviour (users,
  files, pages, mail) comes as traits too.
- **Three ways in, one engine:** the REST API (`/structr/rest/...`), scripts (StructrScript or
  JavaScript, in methods and pages), and server-rendered pages (`/structr/html/<page>` or
  `/<page>`). All of them run with the permissions of the current user, in a transaction.
- **A request is a transaction.** Everything a REST request, a page render or a method call writes
  commits together or not at all (section 7).
- **Server-side by design.** Pages are rendered on the server; the client is thin. Interactivity
  comes from small built-in mechanisms (partial reloads, Event Action Mapping) rather than a
  client framework.

---

## 2. Running an instance

### 2.1 Docker

- The image is `structr/structr:<version>`; it listens on 8082 inside the container. Neo4j runs
  as a separate container reached over Bolt. **[V6]**
- `AGREE_TO_STRUCTR_PRIVACY_POLICY=yes` must be set or the container does not start. **[V6]**
- **Settings as environment variables:** `structr.conf` keys map to `STRUCTR_<key>` with every
  `.` turned into `_` and every original `_` doubled (`application.heap.max_size` becomes
  `STRUCTR_application_heap_max__size`). Environment variables override `structr.conf`. **[V6]**
  for the database connection keys; **[D7]** as a general rule.
- A typical database connection (6.0) is configured with `STRUCTR_database_available_connections`,
  `STRUCTR_<conn>_database_driver=org.structr.bolt.BoltDatabaseService`,
  `STRUCTR_<conn>_database_connection_url=bolt://<host>:7687`, the username and password keys,
  and `STRUCTR_nodeservice_active=<conn>`. **[V6]**
- Named volumes for `/var/lib/structr/files` (file contents), the logs and any deployment
  repository survive `docker compose down`; `down -v` destroys them, and with them every file's
  content. **[V6]**
- The 6.0.0 image runs GraalVM CE 25 and ships the JavaScript **and Python** language jars
  (`js-language`, `python-language`, `polyglot` under `/var/lib/structr/lib`). **[P6]**
- Tags **[D7]**: an exact `MAJOR.MINOR.PATCH` never moves; `MAJOR.MINOR` follows patch releases;
  `MAJOR` follows feature releases; `latest` crosses major versions (avoid outside evaluation).
- **[7.1]** A fresh installation asks for a one-time setup token printed in the log ("Initial
  setup: ..."); automated installs preset it with `setup.token` (`STRUCTR_setup_token`).
  Installations that already have a superuser password are not affected.

### 2.2 Readiness and memory

- `GET /structr/health/ready` answers 200 once the instance serves requests and 503 while it
  starts, shuts down or deploys; it needs no credentials. `GET /structr/health` returns memory,
  thread, cache and response-time figures as JSON, in full only to whitelisted addresses
  (`healthcheckservlet.whitelist`, default loopback). **[V6]** (`/structr/health/ready` answers 200
  without credentials; `/structr/health` and `/structr/histogram` answer 200 from inside the
  container). Readiness is the right target for a container health check.
- The first start can take tens of seconds; poll readiness rather than sleeping.
- **Each schema change (including creating, changing or deleting a method) recompiles and
  reloads the schema, and the JVM's memory grows with every reload.** Dozens of reloads in one
  run can exhaust a 2 GB container. Restart after heavy schema churn. **[V6]**

### 2.3 Accounts at start

- The superuser defined by `superuser.password` (env `STRUCTR_superuser_password`) is named
  **`superadmin`** by default (`superuser.username`), not `admin`. **[V6]**
- The superuser is not stored in the database. It works with `X-User`/`X-Password` headers and the
  configuration interface (`/structr/config`), but **cannot log in to pages** through the login
  endpoint (401 "login with superuser not supported"). **[V6]** **[V7.1]**
- An initial admin user (`initialuser.name`, default `admin`/`admin`) is created when Structr
  first connects to an empty database (`initialuser.create`). **[D7]** **[V7.1]**: a fresh 7.1.0
  database had `admin` with the password `admin` and `isAdmin: true`, and it logged in with
  headers. Delete it, or change its password, before anything else reaches the instance.
  `STRUCTR_initialuser_create=false` stops a new database from getting it (a fresh 7.1.0 database
  then had no user). **[V7.1]**
- **[7.1]** Without a second factor, three failed superuser logins within 15 minutes (counted
  across the configuration interface, headers and Basic auth together) block the superuser
  everywhere for 15 minutes, even with the right password (`configservlet.login.maxattempts`,
  `configservlet.login.lockout.seconds`). With `superuser.twofactor.enabled`, superuser requests
  over HTTP need a fresh TOTP code in `X-TwoFactor-Code`, one per request. Scripts and
  integrations should therefore authenticate as an admin user, not the superuser.

---

## 3. Authentication

### 3.1 Order of checks

A request's user is taken from the first of these that applies **[D7]** (consistent with
**[V6]** observations): an OAuth login flow; the session cookie (skipped when an `Authorization`
header is present); a JWT in `Authorization: Bearer ...`; a session id in `X-StructrSessionToken`;
`X-User` + `X-Password` headers. Otherwise the request is anonymous.

### 3.2 Header authentication

- `X-User`/`X-Password` on every request is the simplest way for scripts: no session, nothing to
  expire. Every such request is a login attempt and counts towards the account lockout
  (`security.passwordpolicy.maxfailedattempts`, default 4), so a client must stop on a 401 rather
  than retry. Use HTTPS beyond localhost. **[V6]** (mechanism) / **[D7]** (lockout detail) /
  **[V7.1]** (more than four wrong passwords in a row refuse even the right one until
  `passwordAttempts` is set back to 0; a right one before that resets the count)
- **[V7.1]** For a user stored in the database it is slow: each request checks the password against
  its Argon2id hash (`security.passwordhash.memory` 64 MB, `.iterations` 3 by default), about 0.4 s
  a request where the superuser's took 15 ms. A script making many requests should log in once and
  send the session's id in `X-StructrSessionToken` (3.3), which brought it back to 11-15 ms.
- Prefer a dedicated service user holding only what it needs over an admin account; a script that
  changes the schema needs an admin, and with `skipSecurityRelationships` it owns nothing it makes
  (4.3).

### 3.3 Sessions for browsers

- `POST /structr/rest/login` with a JSON body `{"name": ..., "password": ...}` (or `eMail`)
  sets the `JSESSIONID` cookie. **It accepts JSON only**: a native HTML form post
  (form-urlencoded or multipart) gets 400 "Invalid JSON". Submit login forms with `fetch()`, or
  use Event Action Mapping's sign-in action. **[V6]**
- Anonymous users need a `ResourceAccess` grant with signature `_login` allowing POST for
  non-authenticated users, **and that grant node must itself be `visibleToPublicUsers`**, or every
  login is a 401 regardless of flags. `_logout` likewise for authenticated users. **[V6]**
- An admin can log in without the `_login` grant by sending its `X-User`/`X-Password` headers on the
  login request as well as the JSON body. **[V7.1]**
- `POST /structr/rest/logout` ends the session, **but only when the session arrives as the
  `JSESSIONID` cookie**: with `X-StructrSessionToken` alone it answered 200 and the session stayed
  open. **[V7.1]** Each session is also stored as a `SessionDataNode`, which the logout leaves
  behind; an admin can delete its own (`GET /structr/rest/SessionDataNode?sessionId=<the cookie's
  value before its dot>`, then delete it) while the session still works. **[V7.1]**
- Cookie flags **[D7]**: `httpservice.cookies.secure` (default true: on a plain-HTTP installation
  sessions will not stick unless it is turned off), `httpservice.cookies.samesite` (default Lax),
  `httpservice.cookies.httponly` (default true from 7.1). **[V7.1]** the login's cookie over plain
  HTTP came marked `Secure; HttpOnly; SameSite=Lax`, so a client must send it back itself.
- `Page.enableBasicAuth` did not gate access on 6.0.0. **[V6]**

### 3.4 Tokens, external identities, second factors

- **JWT** **[D7]**: configure `security.jwt.secrettype` (`secret` with `security.jwt.secret` of at
  least 32 characters, `keypair` with a keystore, or `jwks` for an external provider) and grant
  POST on `_token`. `POST /structr/rest/token` with credentials returns an access token and a
  refresh token (also set as HttpOnly cookies); refresh with the `Refresh-Token` header. A refresh
  token works once; logout revokes all of a user's tokens. Scripts can mint tokens with
  `createAccessToken(user)` / `createAccessAndRefreshToken(user)`.
- **External JWKS** **[D7]**: validates tokens from Entra ID, Keycloak, Auth0 and others
  (`security.jwks.provider`, mandatory `security.jwks.audience`, optional claim mappings to admin
  and groups). The resulting principal is temporary, not stored.
- **OAuth login** **[D7]**: built-in providers auth0, azure, keycloak, google, facebook, github,
  linkedin (`oauth.servers`, `oauth.<provider>.client_id/client_secret`, tenant or server
  settings); users start at `/oauth/<provider>/login`; `jsonrestservlet.user.autocreate=true`
  creates users; an `onOAuthLogin` method on the user type can map provider groups to Structr
  groups.
- **TOTP two-factor login** **[D7]**: `security.twofactorauthentication.level` 0 (off), 1
  (per user, `isTwoFactorUser`) or 2 (everyone). The login answers 202 with a temporary token and,
  on first enrolment, a QR code in response headers; the client posts the token and code back.
  Optional device trust cookies. Wrong codes count as failed logins.
- **Self-registration and password reset** **[D7]**: double opt-in by e-mail
  (`POST /structr/rest/registration` with `eMail`, `_registration` grant,
  `jsonrestservlet.user.autocreate`), and `POST /structr/rest/reset-password` (`_resetPassword`
  grant, `jsonrestservlet.user.autologin`). The mails come from `MailTemplate` nodes named
  `CONFIRM_REGISTRATION_*` and `RESET_PASSWORD_*`; SMTP must be configured. Both endpoints are
  rate-limited per address and per e-mail.

---

## 4. Authorization

### 4.1 The decision chain

For a non-admin user Structr grants an operation on a node at the first of these that allows it
**[D7]**: admin flag (bypasses everything) - schema-based permission for one of the user's groups
on the node's type - ownership (`OWNS`) - a direct grant (`SECURITY` relationship to the user) -
the same for each group the user belongs to, nested groups included - permission propagated along
relationships. The visibility flags are evaluated separately and grant read access before this
chain.

Permissions are `read`, `write`, `delete` and `accessControl`.

### 4.2 Visibility flags: the default is owner-only

- `visibleToPublicUsers` and `visibleToAuthenticatedUsers` each grant read access to one
  audience; neither implies the other. **[V6]**
- **A node created without them is visible only to its owner** (and admins). The failure is
  silent: other users' queries simply do not return it. Set the flags on every write, or give the
  type default visibility (below). **[V6]**
- A type can default them: `SchemaNode.defaultVisibleToPublic` and
  `SchemaNode.defaultVisibleToAuth`. **[V6]** (`defaultVisibleToAuth`): a node of such a type
  created without the flag is visible to every signed-in user, **but its stored
  `visibleToAuthenticatedUsers` still reads `false`**. The default is applied when access is
  decided, not written to the node, so a check that reads the flag will report such nodes as
  hidden. Judge visibility by what a user can see, and keep setting the flag explicitly where
  other code reads it.

### 4.3 Ownership and grants

- A non-admin user who creates a node owns it (full rights). A node created by an anonymous request
  has no owner. `skipSecurityRelationships=true` on a user stops `OWNS`/`SECURITY` being created
  for what they create (faster bulk creation; the application must then grant access itself).
  **[V6]** (ownership) / **[D7]** (skip flag; **[7.1]** only admins may set it)
- In scripts: `grant(principal, node, "read, write")`, `revoke(...)`, `copyPermissions(from, to)`,
  `isAllowed(principal, node, perms)`, `addToGroup`, `removeFromGroup`, `isInGroup`.
  `grant` to a `Group` shares with its members. **[V6]** (grant to a group)
- Every node has a read-only `grantees` property (principals with a direct grant). **[P6]** (exists)
  `getDirectAccessEntries(node)` / `getEffectiveAccessEntries(node)` list who has what and why
  (owner, direct, schema, group). **[D7]**
- What a user creates is theirs alone until granted: sharing with a group needs a grant on every
  create (in the tool that writes, or an `onCreate` method). **[V6]**

### 4.4 Schema-based permissions

- A `SchemaGrant` gives a group read/write/delete/accessControl on **every instance of a type**,
  without per-node grants; the documentation calls it the efficient choice when all instances of a
  type share one access rule. `SchemaNode.schemaGrants` lists them. **[V6]**: create one with
  `POST /structr/rest/SchemaGrant {"schemaNode": <type id>, "principal": <group id>, "allowRead":
  true, "allowWrite": true, "allowDelete": false, "allowAccessControl": false}`; after a restart a
  member of the group reads and writes every node of the type (including nodes owned by others and
  created without visibility flags) and a non-member sees none of them.

### 4.5 Permission propagation along relationships

- Each `SchemaRelationshipNode` has `permissionPropagation` (none, source to target, target to
  source, both) and per-permission rules `readPropagation`, `writePropagation`,
  `deletePropagation`, `accessControlPropagation` (add, keep, remove), plus properties to hide
  from users who gained access this way. A user with access to one end then gains access to the
  other without a grant on it. Only relationships configured this way are followed. **[V6]**: the
  values are strings, e.g. `permissionPropagation: "Out"` (source to target), `readPropagation:
  "Add"`, and `"Keep"` for the others; a user granted read on a container then reads its related
  items, which carry no grant of their own, and a user without the container's grant does not.
- Use it where access naturally follows ownership of a parent (a container's items, a group's
  documents). It is followed at read time, so adding it to a populated relationship needs no data
  migration (still restart before checking, hard rule of 5.6).

### 4.6 Elevated and borrowed rights in scripts

- `doPrivileged(() => ...)` runs code as the superuser; `callPrivileged(name, args)` calls a
  user-defined function that way; `findPrivileged`, `setPrivileged` for single operations;
  `doAs(user, () => ...)` runs code as another user. **[V6]** (`doPrivileged`, `doAs`) / **[D7]**
  (others). Inside `doAs`, `$.me` is that user and reads are filtered by their rights. **`doAs`
  does not return the function's value** (it returns nothing): assign the result to a variable
  declared outside the function.
- **An object keeps the rights of the context that loaded it.** Writing, inside `doPrivileged`, to
  a node loaded outside it is refused. Pass ids across the boundary and load again inside. **[V6]**
- `cypher(query, params)` is not filtered by access control: a non-admin can read anything through
  it. Never use it for reads a user should not see. Returning nodes (not plain properties) lets
  Structr filter them. **[V6]** (unfiltered) / **[D7]** (node filtering)

### 4.7 Resource access (REST endpoints)

- Non-admin and anonymous requests need a `ResourceAccess` grant per endpoint signature and HTTP
  method, separately for authenticated and public users; **the grant node must be visible to the
  caller**. Without it: 401, and the log says "Found no resource access permission for ...
  signature '...'". **[V6]**
- Signatures **[D7]**: the type (`Project`), `Project/_id` for an entity, `Project/_Info` for a
  view (capitalised, leading underscore), `Project/_id/tasks` for a related collection, and a
  method by its name (`Project/_id/doUpdate`; a user-defined function by its bare name). `flags`
  is a bitmask; 255 grants every method to both audiences. **[V6]** (types, entities, function
  names, flags 255)
- Several grants may share a signature, each visible to different users or groups (read-only for
  members, more for administrators). **[D7]**
- CORS is configured per path (accepted origins, methods, headers, credentials, max age) in the
  Security area or the `access.control.*` settings. **[D7]**

---

## 5. Schema through REST

### 5.1 The three schema endpoints

Create, in this order: types, then properties, then relationships. **[V6]**

```
POST /structr/rest/SchemaNode            {"name": "Project", "isAbstract": false, "inheritedTraits": ["Base"]}
POST /structr/rest/SchemaProperty        {"schemaNode": "<type id>", "name": "code", "propertyType": "String",
                                          "unique": true, "indexed": true, "notNull": true}
POST /structr/rest/SchemaRelationshipNode {"sourceId": "<Project id>", "targetId": "<Task id>",
                                          "relationshipType": "PROJECT_HAS_TASK",
                                          "sourceMultiplicity": "1", "targetMultiplicity": "*",
                                          "sourceJsonName": "project", "targetJsonName": "tasks"}
```

- **Nothing is idempotent.** Posting the same schema object twice duplicates it or fails. Always
  look up first and create only what is missing; keep the schema as data tables fed to small
  `ensure_type` / `ensure_property` / `ensure_relationship` helpers, so re-running is safe. **[V6]**
- A relationship to a built-in type (such as `User`) uses `targetType: "User"` instead of a
  `targetId`, since built-in types are not `SchemaNode`s. **[V6]**

### 5.2 Relationship naming: read it backwards

- **`targetJsonName` becomes the property on the source type; `sourceJsonName` the property on the
  target type.** In the example, `Project.tasks` and `Task.project`. Create one throwaway
  relationship and read the property names back before building on the pattern. **[V6]**
- **Multiplicity is per participant:** `targetMultiplicity` is how many targets one source may
  have ("1" makes the source's property a single reference), `sourceMultiplicity` how many sources
  one target may have. A wrong guess compiles silently and fails at the first write ("expected a
  JSON collection"). **[V6]**
- Give every relationship a specific type name (`PROJECT_HAS_TASK`, not `HAS`); reusing one label
  across many type pairs forces filtering by target type. A JSON property name must be unique per
  concrete type, across all relationships that land on it. **[V6]**

### 5.3 Property types and flags

- Types **[V6]** unless marked: `String`, `Integer`, `Long`, `Double`, `Boolean`, `Date` (give a
  `format` such as `yyyy-MM-dd'T'HH:mm:ssZ`), `Enum` (`format` is the comma-joined allowed values,
  no spaces), arrays (`String[]` and so on), and **[D7]** `Count`, `Join`, `Notion` (a related
  node's property exposed as one's own), `Function` (read and write scripts, with a type hint for
  indexing), `Cypher` (read-only computed), `Encrypted` (AES, key in `structr.conf`),
  `ZonedDateTime`, `Thumbnail`, `Byte[]`, and `Double[]` with a vector index (**[7.1]**).
- Flags on `SchemaProperty`: `unique`, `indexed` (also speeds uniqueness checks; index anything
  you query or keep unique), `notNull`, **`compound`** (uniqueness of the combination of all
  properties of the type that carry it), `defaultValue`, `format`, `fulltext`. **[V6]** (unique,
  indexed, notNull, compound, format) / **[P6]** (defaultValue) / **[D7]** (fulltext)
- **Compound uniqueness [V6]**: mark two properties `unique` and `compound`; a second node with
  the same pair is refused with 422 (token `already_taken`), a node differing in either is
  accepted.
- `format` by type: a date pattern for dates, the allowed values for enums, **a regular
  expression for strings, and an interval for numbers**. **[V6]** on 6.0.0:
  - Numeric intervals: `[0,100]` (both ends inclusive), `[0,100[` (100 excluded), and `[0.0,100.0]`
    work on `Double` and `Integer`; a value outside is refused with 422, token `must_be_in_range`,
    the interval as the detail. **An open end (`[0,]`) is accepted when declared but checks
    nothing**: use a large bound instead. A node without the property passes.
  - **A string `format` (regular expression) refuses a missing value** (422, token `must_match`):
    it makes the property effectively required. Do not put one on an optional property.
  - A format replaces a hand-written validator for simple ranges and patterns, and it applies to
    every write, create and update alike.
  - **An `error()` in a lifecycle method ends the request before property validation** **[V6]**: a
    create that both an `onCreate` validator and a `format` refuse answers 422 "Server-side scripting
    error" with the validator's token alone. Check for either token when both may apply.
- A default value is stored when a node is created without the property; nodes that existed before
  the default was added show it on read but are not found by a search for it until the value is
  stored (`rebuildIndex` stores it for indexed properties). **[D7]**
- Boolean and Function properties are "passively indexed": their computed value is written at the
  end of each transaction so Cypher can find it. A Function property's read script must return the
  same value for every user, since whoever triggers the write decides what is stored. **[D7]**

### 5.4 Relationship options

On `SchemaRelationshipNode` **[P6]** (fields exist; behaviour **[D7]**) unless marked:

- `cascadingDeleteFlag`, an integer: 0 none, 1 source to target, 2 target to source, 3 always, 4
  constraint-based (delete the other side when it would otherwise violate a constraint such as
  notNull). **[V6]** (0 and 1): with 1, deleting the source deletes the target; with 0 the target
  stays. Deletion respects the deleting user's rights. Lets a parent's deletion take its
  dependents with it. **[V6]** also: a flag set on a relationship that already has edges applies
  to them after a restart; cascades chain (a deleted child's own flagged relationships cascade in
  turn); and **the target is deleted even when other nodes still point at it**, through the same
  relationship type or another. Turn it on only where every target belongs to exactly one source,
  and check the existing data for shared targets first. Changing the flag is a schema change:
  restart before trusting it. The
  request header `Structr-Cascading-Delete` and the functions `enableCascadingDelete()` /
  `disableCascadingDelete()` affect it per request. **[D7]**
- `autocreationFlag`: whether a nested JSON object in a write creates the related node when it
  does not exist (matched on a unique property). Makes Structr accept documents (section 8.4).
- The permission propagation fields of section 4.5, and `changelogDisabled`, `includeInOpenAPI`.

### 5.5 Type options

On `SchemaNode`: `isAbstract`, `inheritedTraits`, `defaultVisibleToPublic`/`defaultVisibleToAuth`,
`changelogDisabled`, `defaultSortKey`/`defaultSortOrder`, `includeInOpenAPI` with `tags`,
`summary`, `description`, and `schemaGrants`. **[P6]**

### 5.6 Changing a live schema: what destroys data

- **Renaming a `SchemaNode` orphans every existing instance**: found under neither the old nor the
  new name. To rename a type with data: create the new type, copy instances across, repoint
  relationships, delete the old. **[V6]**
- **Renaming a relationship type label orphans its existing edges**, even with everything else
  unchanged, because edges are keyed by the label. Moving an unchanged declaration (same label,
  same JSON names) onto a trait the type inherits is safe. **[V6]**
- **A property or relationship cannot change shape in place** (scalar to relationship, or a new
  target type under the same JSON name): two declarations may not share a JSON name on one type.
  Read the old data, delete the old declaration, create the new, write the data back. **[V6]**
- **Changing which type is a relationship's source while the old declaration still exists**
  leaves reads of the property returning null (the edges are intact; the compiled schema is stale)
  until the container restarts. Never let old and new declarations coexist; restart and verify a
  sample afterwards. **[V6]**
- Maintenance commands that help **[P6]**: `changeNodePropertyKey` (move values from one key to
  another), `fixNodeProperties` (convert values stored with a wrong type after a type change),
  `setNodeProperties` (set values, including `newType`, on all nodes of a type),
  `copyRelationshipProperties`, `setUuid`, `rebuildIndex`. The full list on 6.0.0:
  `changeNodePropertyKey`, `clearDatabase`, `copyRelationshipProperties`, `createLabels`, `deploy`,
  `deployData`, `directFileImport`, `fixNodeProperties`, `flushCaches`, `letsencrypt`,
  `rebuildIndex`, `setNodeProperties`, `setRelationshipProperties`, `setUuid`, `sync`. **[V6]**
- **Don't trust a check made right after a schema change.** A stale compilation cache produced
  both false negatives and false positives; restart the container, then test. **[V6]**

### 5.7 Traits and labels

- **Inheritance is `inheritedTraits`** (a list; order resolves conflicts). The older
  `extendsClass` is accepted silently and does nothing useful. **[V6]**
- Properties, relationships and lifecycle methods declared on a trait (abstract or not) apply to
  every type that inherits it, through multi-level chains; read the literal `inheritedTraits` of
  each link, since one missing link silently drops everything above it. **[V6]**
- **`unique` on a trait is global across all inheriting types**, not per type. **[V6]**
- **A property inherited from a trait cannot be found by value through REST** (`?prop=value`
  returns nothing) though it reads correctly; filter in your own code, reading every page. **[V6]**
- A relationship may target an abstract trait; any inheriting type satisfies it. **But a node's
  Neo4j labels are fixed at creation**: nodes that existed before their type gained a trait lack
  its label and are refused as targets of relationships to that trait ("No <Trait> with UUID ...
  found"). Restart, touching the node, `rebuildIndex` and `flushCaches` do not help; adding the
  label in Cypher (`MATCH (n {id: $id}) SET n:<Trait>`) does, immediately. **[V6]**
- **The supported fix is the maintenance command `createLabels`** **[V6]**:
  `POST /structr/rest/maintenance/createLabels {"type": "<Type>"}` rewrites the labels of every
  node of that type from its current hierarchy. After it, an old node that was refused as a
  relationship target is accepted. (Optional `removeUnused` also drops labels the type no longer
  has **[D7]**.) Run it after any change to a populated type's traits, then restart and verify.
- Do not name a custom type `Object`: it silently picks up the DOM element trait bundle (about 140
  `_html_*` properties). Treat other bare generic names with suspicion. **[V6]**

### 5.8 Views

- The default (`public`) view returns little (`id`, `type`, `name`); custom properties and
  relationships are absent (not null: absent) unless a view includes them. Read with
  `/structr/rest/<Type>/all` (or `/<id>/all`) when you need everything; `all` limits nested
  objects to id, type and name. **[V6]**
- Custom views (`SchemaView`) are separate endpoints: `/structr/rest/<Type>/<view>`. Define one
  per consumer to keep responses small. Views are inherited. **[V6]** (custom view) / **[D7]**
  (inheritance)

---

## 6. Scripting and methods

### 6.1 Two languages

- **StructrScript**: a small functional expression language. In page content it is written
  `${...}`; in a method's `source` it is written bare. Strings must be double-quoted (single
  quotes render nothing); comparisons are functions (`equal`, `gt`, `lt`, `and`, `not`), never
  infix operators. **A syntax error is silent to the caller**: a 200 with an empty result and a
  warning in the server log. **[V6]**
- **JavaScript (GraalJS)**: in page content `${{ ... }}`; in a method, a `source` that is one bare
  `{ ... }` block (not `${{ }}`, and the method's `codeType` does not matter). The API is the `$`
  object (`$.find`, `$.create`, `$.delete`, `$.me`, `$.this`, `$.request`, `$.print`; `Structr.`
  is an alias). Variables must be declared (strict mode). **[V6]**
- Other GraalVM languages: `application.scripting.polyglot.access` (default ALL in 7.x) allows
  calls such as `Polyglot.eval('python', ...)` from JavaScript. **[D7]** **On 6.0.0 it does not
  work as shipped [V6]**: the image carries the GraalPy jars (`python-language-*.jar` under
  `/var/lib/structr/lib`), but a call answers 422 "Server-side scripting error" and the server log
  says "No language for id python found. Supported languages are: [js]". Treat other languages as
  unavailable on 6.0 unless you find the setting that loads them.

### 6.2 StructrScript traps **[V6]**

- `lt(this.value, 0)` (and the other comparisons) is **true when the value is null**. Guard numeric
  checks: `if(and(not(empty(this.value)), lt(this.value, 0)), error("value", "negative"), null)`.
- `each(if(c, a, b).items, ...)` renders nothing; put the property inside each branch.
- A `print()` nested inside another `print()`'s arguments outputs out of order; give the fragment
  its own content element, or use JavaScript.
- A StructrScript method calling another method cannot pass it arguments through
  `retrieve`/`store` or declared parameters; unroll a bounded walk as nested expressions over a
  property path instead, or use JavaScript, where `$.otherMethod({ ... })` passes arguments and
  recursion works.

### 6.3 JavaScript traps **[V6]**

- A block's return value is HTML-escaped when rendered; output markup with `$.print(...)`. A bare
  global `print()` outputs nothing.
- Date properties are objects (`getTime()`, `toISOString()`), not strings.
- A relationship property is a node or an array; a missing property is `undefined`, not an error.
- `Intl.DateTimeFormat` with a `timeZone` works.

### 6.4 Kinds of methods

| Kind | Where | Called as |
|---|---|---|
| User-defined function (global) | `SchemaMethod` without a `schemaNode` | `POST /structr/rest/<name>`, `$.<name>({...})` **[V6]** |
| Instance method | `SchemaMethod` on a type | `POST /structr/rest/<Type>/<id>/<name>`, `node.<name>({...})` **[V6]** |
| Static method | on a type, `isStatic: true` | `/structr/rest/<Type>/<name>`, `$.<Type>.<name>()` **[P6]** (exists) |
| Method on the current user | on the user type | `/structr/rest/me/<name>` **[D7]** |
| Service class | a type holding only methods | as static methods **[D7]** |

- Names match `^[a-z_][a-zA-Z0-9_]*$`. Create the method, then set `source`. **[V6]**
- `returnRawResult: true` returns the bare value instead of the `{"result": ...}` envelope.
  **[V6]**
- Options on `SchemaMethod` **[P6]** unless marked: `httpVerb` (which HTTP method calls it; POST
  by default, GET for read-only methods), `wrapJsInMain` (wrap in a function so `return` works;
  off allows `import`), `isStatic`, `includeInOpenAPI`, `summary`, `description`, and `parameters`
  (`SchemaMethodParameter` nodes: `schemaMethod`, `name`, `parameterType`, `index`).
- Declared parameters **[V6]** (6.0.0): create
  `POST /structr/rest/SchemaMethodParameter {"schemaMethod": <method id>, "name": "count",
  "parameterType": "Integer", "index": 0}`; a call passing `"7"` then sees the number 7 in
  `$.args.count`. With `httpVerb: "GET"`, path segments map to the parameters by position
  (`GET /structr/rest/<name>/5`), and a POST to it answers 405. **On 6.0 an undeclared argument is
  silently dropped** (it is absent from `$.args`); **[7.1]** refuses it with 422 unless "allow
  unknown parameters" is set, and Event Action Mapping drops it with a warning. Types: Integer,
  Long, Double, Float, Date **[D7]** (Integer **[V6]**). A JSON object passed to a parameter
  declared `Map`, `Object` or `String` arrives whole, as an object **[V6]**. On 6.0, declared
  parameters were **not** usable as bare variables in a StructrScript body. **[V6]**
- Arguments arrive as `$.args` (aliases `$.arguments`, `$.methodParameters`) or
  `retrieve("name")`; query-string values as `$.request.<name>`. **[V6]** (`$.methodParameters`,
  `$.request`)
- Methods are inherited; an override replaces the parent's, which it can call as
  `$.<ParentType>.<name>()`. **[D7]**

### 6.5 Method lifecycle facts **[V6]**

- A method needs no restart: new, changed and deleted methods take effect at once.
- **A brand-new method called by several clients at once, before its first call finishes, answers
  some of them 404** ("Cannot resolve URL path"). Call each new or changed method once before
  real traffic.
- **While one method's transaction writes through `$.cypher`, other methods called at that moment
  answer 404**; Cypher reads do not cause it. Use ordinary property writes (which Neo4j locks just
  the same) for locks and counters.
- Each method change reloads the schema; see section 2.2 on memory.

### 6.6 Lifecycle methods

- Methods named `onCreate`, `onSave`, `onDelete` run inside the transaction before validation;
  `afterCreate`, `afterSave`, `afterDelete` run after the commit, in a transaction of their own
  (the place for e-mails and other side effects). `onNodeCreation` runs at low-level creation,
  before `onCreate`. **[V6]** (`onCreate`, `onSave`) / **[D7]** (the rest)
- A lifecycle method on a trait runs for every inheriting type; all levels of the hierarchy run,
  unlike ordinary methods. **[V6]**
- Several of one kind may coexist with suffixes (`onCreate01`, `onCreateCheck`). **[D7]**
- If an object is created and modified in one transaction only `onCreate` runs; created and
  deleted, none. In `onDelete` the node is already gone (`this` fails); use the modifications.
  **[D7]**
- In `onSave`, the changes are available: `before` and `after` (changed local properties),
  `added` and `removed` (relationships, by id): `$.retrieve('modifications')` (**[7.1]** also
  `$.modifications`). **[V6]** (6.0.0: `before`/`after` hold the old and new values of a changed
  property; `$.error(...)` in `onSave` refuses the edit with 422 and the stored value is
  unchanged, by PUT or PATCH; `onSave` does not run on a create). An `onCreate`-only validator misses
  later edits; give it an `onSave` twin that runs the same check.
- **`onSave` also runs when only a node's relationships change** **[V6]**: when the node at the
  other end is deleted, and when the link is set from the other end. If it then fails, that delete
  or that write is refused. So a twin of a validator that reads a relationship makes Structr guard
  the relationship: deleting what it names is refused while the node needs it. That may be wanted
  (referential integrity) or may break deletes elsewhere; decide per validator, and remember
  StructrScript's null comparisons (6.2): `lte(this.x.value, 0)` is true once `x` is gone.
- Other callbacks **[D7]**: `onUpload`/`onDownload` on files, `onOAuthLogin` on users, and
  user-defined functions named `onStructrLogin`, `onStructrLogout`, `onAcmeChallenge`,
  `afterAcmeChallenge`.

### 6.7 Errors

- `error(property, token[, message])` (`$.error`) marks the transaction failed; the request
  answers 422 with `{"errors": [{"type", "property", "token"}]}`. **[V6]**
- `assert(condition, status, message)`: **[7.1]** aborts on anything but the boolean `true`
  (before, a null condition or missing argument let the request through). Compare explicitly
  (`$.me != null`).
- `getErrors()`, `hasError()`, `clearError(token)`, `clearErrors()`; `rollbackTransaction()`.
  **[D7]**

### 6.8 Useful built-in functions (beyond the obvious) **[D7]** unless marked

- Database: `find(type, {k: v}, predicate...)` **[V6]**, `search` (inexact), `getOrCreate`,
  `createOrUpdate` (match on a unique property), `createRelationship`, `incoming`/`outgoing`,
  `getRelationships`, `addLabels`/`removeLabels`, `instantiate`, `searchFulltext(index, query)`
  (index `<Type>_<prop>_fulltext`), `cypher` **[V6]**.
- Predicates (`$.predicate.*` in JavaScript, bare in StructrScript): `equals`, `contains`,
  `startsWith`, `endsWith`, `empty`, `range`, `gt`/`gte`/`lt`/`lte`, `and`/`or`/`not`, `sort`,
  `page`, `withinDistance`. **[7.1]**: `sort('key', 'desc')` really sorts descending and
  `sort(list, true)` sorts by name descending; both sorted ascending before.
- Caching: `cache(key, seconds, () => value)` **[V6]** (a second call within the time returns
  the first value without running the function), `getCacheValue`, `hasCacheValue`,
  `invalidateCacheValue`. `applicationStore*` (instance-wide key/value), `requestStore*`
  (per request), `store`/`retrieve`. A cached value is shared by every user: never cache a read
  whose result depends on who asks under a key that does not name them.
- Background: `schedule(fn, title)` queues work outside the request **[V6]** (the request returns
  at once; the function's writes appear shortly after) (**[7.1]** named queues:
  `schedule(fn, {queue: 'name'})`, returns the job id), `jobInfo`, `jobList`.
- Prefetching graph data before a traversal: `prefetch('(:A)-[]->(:B)', ['REL'])`,
  `prefetch2(cypher, outKeys, inKeys)`. **[P6]** (exists on 6.0.0; the gain not measured)
- Data formats: `toJson`/`fromJson`, `toCsv`/`fromCsv`, `fromXml`/`xpath`, `toExcel`/`fromExcel`,
  `barcode(type, data)` (QR and other codes as images), `createZip`, `unarchive`.
- Security: `confirmationKey()`, `hmac()`, `encrypt`/`decrypt`, `login(user, password)`.
- Introspection: `typeInfo`, `propertyInfo`, `enumInfo`, `ancestorTypes`, `inheritingTypes`,
  `functionInfo`, `structrEnv`, `systemInfo`.
- Change history: `changelog(node, resolve, filters)` and `userChangelog(user, ...)` (section 12.5).
- Misc: `dateAdd`, `dateFormat`, `parseDate`, `weekDays`, `localize`, `setLocale`, `translate`
  (DeepL or Google key), `timer`, `evaluateScript`, `getenv`, `serverlog`.
- `$.evaluateScript(node, 'expression')` **[V6]** evaluates a StructrScript expression written bare
  (not `${...}`, which returns nothing) with `this` the given node, and returns its value: a way to
  run a stored validator's logic against existing data. Replace a validator's `error(` first:
  `error()` marks the running transaction failed (6.7).

---

## 7. Transactions and concurrency

- Each REST request, page render and method call runs in one top-level transaction: all or
  nothing. Reads see the transaction's own writes and nothing uncommitted from others. **[V6]**
- **A page's writes commit after the page has answered** (a few hundred milliseconds later): a
  validation failure at commit comes after the browser was told it worked. **[V6]**
- **Two concurrent requests do not see each other's uncommitted writes**, so find-then-create in
  each makes duplicates. Neo4j's locks serialise transactions that write the same node (setting a
  property on a shared node, or relating to it waits for the other's commit). **[V6]**
- **A read repeated in one transaction answers as it did the first time**, even after waiting for
  another transaction's lock: take the lock before any read that the write depends on. **[V6]**
- A lock that works: an ordinary property write on a shared node at the start of the transaction
  (for example a counter on a parent object). `MERGE` through Cypher without a uniqueness
  constraint is not safe under concurrency; Structr's own `unique` validation is. **[V6]**
- `doInNewTransaction(worker, onError)` runs `worker` in a transaction of its own and commits it
  before returning; a thrown error rolls it back and reaches `onError`. Returning `true` from the
  worker repeats it (batch processing). Inside `doPrivileged` it runs as the superuser. **[V6]**
  (commit, rollback) / **[D7]** (repeat on `true`)
- **[D7]** When the database terminates a transaction to resolve a deadlock, Structr repeats it,
  up to ten times, for REST requests, imports, uploads, scheduled tasks and `schedule()` jobs.
  The repeat reruns `onCreate`/`onSave`; side effects outside the database belong in the `after*`
  methods. **[7.1]** repeats instead of committing retryable failures, which also prevents
  duplicate to-one relationships under concurrency.
- Each transaction costs database round trips (one to begin, two to commit); many small
  transactions are slow against a remote database. Batch writes (section 8.4). **[D7]**

---

## 8. REST data access

### 8.1 Endpoints **[V6]**

```
GET    /structr/rest/<Type>[/<view>]          collection
GET    /structr/rest/<Type>/<id>[/<view>]     one object
POST   /structr/rest/<Type>                   create (201, result: [new id]); an array creates many
PUT    /structr/rest/<Type>/<id>              update (only the given keys)
PATCH  /structr/rest/<Type>                   with an array of {id, ...}: bulk update [D7]
DELETE /structr/rest/<Type>/<id>              delete one
DELETE /structr/rest/<Type>?<filter>          delete everything the filter matches (no filter: all,
                                              including subtypes; add type=<Type> to spare them)
POST   /structr/rest/<Type>/<id>/<method>     call an instance method
```

`PATCH /structr/rest/<Type>/<id>` works for partial updates of one object. **[V6]**

### 8.2 Query parameters

| Parameter | Effect |
|---|---|
| `?prop=value` | exact match (on directly declared properties, section 5.7) **[V6]** |
| `?prop=a;b` | either value **[D7]** |
| `?prop=` | null or empty **[D7]** |
| `?prop=[]` | has any value (local properties only) **[D7]** |
| `?prop=[lo TO hi]` | range; either end may be empty, the spaces are required **[D7]** |
| `_inexact=1` | case-insensitive "contains" **[D7]** |
| `_page`, `_pageSize` | pagination; the underscore is required (`pageSize` is a 400) **[V6]** |
| `_sort`, `_order` | repeatable; sorts on indexed properties of the listed type **[D7]** |
| `_outputNestingDepth` | depth of nested objects (default 3) **[D7]** |
| `_latlon`, `_distance` | distance search on latitude/longitude **[D7]** |
| `_locale`, `_filename`, `_as-data-url` | locale override; download name; file as a data URL **[D7]** |

- **A comma in an exact-match value matches nothing, silently** (200, no results). Avoid commas
  in values you look up by exact match, such as natural-key names. **[V6]**
- **Do not trust `result_count`/`page_count` to be present**: with a smaller `_pageSize` on a
  large collection they were missing. Read pages until one comes back short. A filtered `/all`
  read pages correctly. **[V6]**
- An unfiltered collection read is capped by a soft limit (10,000 by default) unless paged.
  **[D7]**

### 8.3 Responses and errors

- Successful collection reads return `{"result": [...], "result_count", "page_count",
  "query_time", ...}`; creates return the new ids. **[V6]**
- Errors: `{"code", "message", "errors": [{"type", "property", "token", "details"}]}`. Tokens
  include `must_not_be_empty`, `already_taken` (uniqueness). 401: not authenticated or no resource
  access grant; 403: no permission; 404: missing or invisible (Structr does not distinguish);
  422: validation; 500: see the server log. **[V6]**
- Viewing a REST URL in a browser renders navigable HTML (Accept: text/html). **[D7]**

### 8.4 Writing documents and batches

- Input looks like output. Relationship properties take ids (`"project": "<id>"`, `"tasks":
  ["<id>", ...]`), stub objects with an id, or **stub objects matched on a unique property**
  (`{"name": "Task 1"}`); with `autocreationFlag` set on the relationship, a stub that matches
  nothing is created. Assigning a to-many property replaces the set. **[V6]** (ids) / **[D7]**
  (stubs, autocreation)
- **An array in one POST creates all its objects in one transaction**: all or none, and far fewer
  round trips than one request per object. **[V6]**: one invalid object in the array (a duplicate
  of a unique value) answers 422 and creates none of the others. PATCH on the collection with an
  array of objects carrying ids updates many in one transaction. **[V6]**
- Request headers that change writes **[D7]**: `Structr-Return-Details-For-Created-Objects`,
  `Structr-Cascading-Delete`, `Structr-Force-Merge-Of-Nested-Properties`.
- `jsonrestservlet.unknowninput.validation.mode` (`accept`, `ignore`, `reject`, with `warn`
  variants) decides what happens to keys the schema does not know; `reject` turns a typo or a
  write that runs ahead of its schema migration into an error. **[V6]** (`reject`, set as the
  environment variable `STRUCTR_jsonrestservlet_unknowninput_validation_mode=reject`: a POST with
  an unknown key answers 422 "Rejecting input with unknown JSON key ..." and creates nothing).
  It applies to REST writes, so every client of the instance must send only declared keys.

### 8.5 System endpoints

`/structr/rest/me` (current user), `/structr/rest/login`, `logout`, `token`, `registration`,
`reset-password`, `/structr/rest/maintenance/<command>`, `/structr/openapi` (OpenAPI 3.0.2; per
tag `/structr/openapi/<tag>.json`), `/structr/upload`, `/structr/health[/ready]`,
`/structr/histogram`, `/structr/metrics`, `/structr/EventSource`, and **[7.1]**
`/structr/rest/_serverLog` (admin only; `lines`, `level`, `filter`, `since` for cheap polling).
**[V6]** for health, health/ready and histogram (answering 200 from inside the container; the
histogram is whitelisted to loopback) / **[P6]** for openapi; metrics and EventSource are servlets
switched off by default (404 on 6.0.0), and `_serverLog` is 404 on 6.0.0.

---

## 9. Pages

### 9.1 Building pages through REST **[V6]**

- A `Page` gets no skeleton: create every element yourself (`Html`, `Head`, `Body`, `Div`, ...,
  `Content`), each with `parent` and `pageId`. **Every element must state its `tag`** in 6.0;
  without it the page renders only `<!DOCTYPE html>`.
- Post each element to its tag's own type (`/structr/rest/Form`, `/Input`, `/A`): tag-specific
  attributes (`_html_action`, `_html_name`, ...) are silently dropped on the generic `DOMElement`.
- An element is a node: posted without visibility flags it is owner-only, and renders for no one
  else. Set the flags on every element. **[V7.1]**
- A `Content` holding JavaScript for a `<script>` needs `contentType: "text/javascript"`;
  plain text turns newlines into `<br>`.
- **Deleting a `Page` leaves its elements** (as `DOMNode`s); delete them first
  (`GET /structr/rest/DOMNode?pageId=<id>`).
- A page renders at `/structr/html/<name>` (the bare `/<name>` was a 404 on 6.0.0; the
  documentation describes `/<name>`).
- A whole page can be one `Content` (or `Template`) whose JavaScript builds the HTML with
  `$.print`: one node to install, the logic in a file under version control. Pages and
  methods can share code by concatenating the same library files into both.
- `redirect()` from a nested content element did not redirect (the response was already
  committed).

### 9.2 Page features **[D7]** unless marked

- **URL object resolution:** `/<page>/<uuid>` makes that object `current` **[V6]**;
  `htmlservlet.resolveproperties` adds other attributes (names, slugs) for resolution.
- **URL routes** on a page: path templates with typed parameters
  (`/project/{lang}/{name}`: String, Base64UrlString, Integer, Long, Double, Float, Date with a
  format, Boolean, Node with a type filter), required or optional, defaults; parameters appear as
  variables. **[7.1]** a Node parameter can set `current`.
- **Repeaters** on any element: a function query, Cypher query or flow plus a data key; the
  element renders once per result. **Show and hide conditions** decide rendering per element (not
  a security mechanism). Visibility and grants on elements also decide what renders.
- **Templates** render their children only where `render(children)` says; `include(name)` and
  `includeChild(name)` pull in other elements; **shared components** are referenced, not copied,
  so one change updates every page. Markdown and AsciiDoc content types are converted to HTML.
- **Load/update modes** per element: eager, after the page loads, delayed, when visible, or
  periodically refreshed. **Partials**: `GET /<element uuid>[/<object uuid>]` renders one element.
- A page's **content type** can be `application/json`, XML or binary: a page can be an API
  endpoint. `showOnErrorCodes` makes a page the 404 (or other) page; the visible page with the
  lowest `position` is the start page.
- **Translations**: `localize(key, domain)` looks up `Localization` nodes (key, domain, locale,
  text), falling back from full locale to language and to a fallback locale; the locale comes
  from the `locale` request parameter, the user's `locale`, a cookie, the browser, then the JVM.
- **Sites** bind pages to a hostname and port: one instance serves several applications. Pages
  without a site are served on every host no site claims.
- `?_edit=1` renders a page with its expressions and Structr attributes intact, for copying into a
  widget; `data-structr-meta-<attribute>` HTML attributes set Structr attributes (repeater query,
  data key, conditions, event mappings) when HTML is imported.

### 9.3 Event Action Mapping **[D7]**

Declarative wiring of DOM events to server actions, on any element, with the page including
`/structr/js/frontend/frontend.js`. **[P6]** (6.0.0 serves the script, and DOM elements carry
`eventMapping`, `triggeredActions`, `parameterMappings`, `reloadTargets`,
`successNotificationActions`, `failureActions` and related keys; the behaviour below was not
exercised):

- Actions: create, update or delete an object; call a method (an instance by
  `${current.id}`, a static one by type name, or a user-defined function; parameters arrive as
  `$.arguments`); run a flow; sign in, sign out, sign up, reset password; next or previous page.
- Parameters: bound to an input (repeater-aware), a constant (`json(...)`), an expression
  evaluated at render time, or the page-number request parameter.
- A confirmation dialog; notifications (alert, an inline message with `{status}`, `{message}`,
  `{result.x}`, and for validation errors a red border and `data-error` on the offending input);
  follow-ups (reload the page, refresh sections by CSS id, show or hide sections, navigate to a
  URL with `{result.id}`, raise a custom DOM event).
- Debounce with `data-structr-options='{"delay": 300}'`; HTML5 validation attributes are honoured;
  the triggering element carries `structr-action-running` while the action runs.
- Relationship fields: `<select>` (or `<select multiple>`) of ids; the "selected values
  expression" on `<option>` pre-selects; the submitted set replaces the relationship.

### 9.4 7.x-only page features [7.1]

Data-driven components (tables, lists, forms bound to a data source with configured fields,
render templates, URL-held paging, filtering and selection channels), the default widget set
(Tailwind page template, components, login forms), and BPMN process control (start a process,
claim and complete user tasks from page elements, visibility by process state, timers, signed
task links).

---

## 10. Files

- **Upload with `POST /structr/upload`** (multipart, field `file`, optional `parent` folder id or
  `uploadFolderPath`); it answers the new id as plain text, not JSON. A session-wide
  `Content-Type: application/json` header must be removed for this request. Posting multipart to
  `/structr/rest/File` does not work. Structr detects `Image` from the content. **[V6]**
- **An upload is owner-only** like any node: set visibility afterwards. **[V6]**
- `GET /structr/rest/File/<id>` returns metadata; the bytes are served at the file's `path`
  (`/<folder>/<name>`) on the host root, with range requests for media. Querying `File` also finds
  `Image`s. **[V6]**
- Custom types could not be related to the built-in `File`/`Image` types in 6.0.0 ("missing
  StartNode(s)/EndNode(s)"); store the file's id as a string. **[V6]**
- **[D7]**: `isTemplate` files evaluate `${...}` when served (dynamic CSS, an `.ics` or CSV
  generated on request); storage backends per folder (local, S3-compatible, in-memory); mounted
  server directories kept in sync (watch, rescan interval, direction, what to do when a file
  vanishes); per-user home directories; automatic checksums (xxHash, optionally crc32, md5, sha1,
  sha512); image thumbnails and EXIF metadata; CSV and XML import wizards; `getContent` /
  `setContent`; **[7.1]** `minify()`, content extraction (text of a thousand file types into
  searchable chunks, OCR with Tesseract), and untrusted files (not uploaded by an admin in a
  browser) delivered sandboxed.

---

## 11. Background work and integrations

### 11.1 Scheduled tasks **[D7]** unless marked

- **[V6]** in Docker: `STRUCTR_cronservice_tasks=myTask` and `STRUCTR_myTask_cronExpression=*/5 * *
  * * *` (the setting names, with dots as underscores) run the user-defined function `myTask`
  every five seconds; the function must exist when the service starts (otherwise the log says it
  was not found). With several tasks the list is space-separated **[D7]**.
- `CronService.tasks` lists method names (user-defined functions, or `Type.method` for static and
  service-class methods); each needs `<name>.cronExpression` with **six fields, seconds first**
  (`0 0 3 * * *` is 03:00 daily). Steps, lists and ranges, but no names (`MON`), no `?`, `L`, `W`
  or `#`, no ranges with steps. The service reads its configuration at start; restart it (or
  Structr) after a change.
- Tasks run as the superuser, unaffected by permissions, with no `this` and no request; a missed
  time is skipped, not caught up; a task still running when its next time comes is skipped unless
  `CronService.allowparallelexecution`. Log inside the task to see it ran.
- `schedule(fn)` queues work for later from any script; the Job Queue area lists it.

### 11.2 Mail **[D7]**

- Sending: `sendPlaintextMail(from, fromName, to, toName, subject, text)`,
  `sendHtmlMail(..., html, text, [files])`, or the builder (`mailBegin`, `mailAddTo`/`Cc`/`Bcc`,
  `mailAddAttachment`, `mailSend`, `mailHasError`, `mailGetError`); several SMTP configurations by
  prefix (`mailSelectConfig`); `mailSaveOutgoingMessage(true)` keeps a copy as `EMailMessage`.
  Providers usually require the sender to match the SMTP account.
- Receiving: a `Mailbox` (imaps or pop3, folders) stores new messages as `EMailMessage` with
  attachments as files when `fetchMails()` is called; **[7.1]** nothing fetches automatically any
  more, so call it from a scheduled task. `overrideMailEntityType` plus an `onCreate` on that type
  processes incoming mail.

### 11.3 Push and messaging **[D7]**

- **Server-sent events**: enable the `EventSourceServlet` in the servlet list (through the
  configuration interface: setting `httpservice.servlets` in `structr.conf` replaces the whole
  default list), grant GET on `_eventSource`; browsers open `new EventSource('/structr/EventSource',
  {withCredentials: true})`; scripts call `broadcastEvent(type, message, authenticated, anonymous)`
  or `sendEvent(type, message, userOrGroupOrList)`.
- **Message brokers**: `MQTTClient`, `KafkaClient`, `PulsarClient` objects hold connections;
  `MessageSubscriber` objects (topic or `*`, callback script) process messages with `$.topic` and
  `$.message`; `sendMessage({topic, message})` sends after the commit. Incoming processing is at
  least once: make callbacks idempotent.
- `XMPPClient` for chat notifications and bots; `DataFeed` for RSS/Atom.

### 11.4 Outbound calls and other systems **[D7]**

- `$.GET/HEAD/POST/PUT/PATCH/DELETE/FETCH(url, [body], [contentType], [options])` return
  `{status, headers, body}`; options include `headers`, `timeout`, `parseResponse`, `selector`
  (CSS selector on HTML), `binaryResponse`, `username`/`password`/`preemptive`. **[7.0]** changed
  the signatures (options object) and made an unreachable host return `status: 0` instead of
  throwing. Requests to internal network addresses are refused unless SSRF protection is off;
  `application.httphelper.urlwhitelist` restricts targets.
- `jdbc(url, sql, [user, password])` against any database whose JDBC driver JAR is in Structr's
  `lib` directory (SQLite included); `mongodb(url, db, collection)` with `bson()`.
- `exec(key, [args])` / `execBinary(...)` run only scripts registered by key in `structr.conf`
  and placed in the scripts folder.
- Geocoding (`geocode`, distance search) and geometry functions (module).

---

## 12. Operations

### 12.1 Maintenance commands

`POST /structr/rest/maintenance/<command>` with a JSON body (admin), or `maintenance(name, {...})`
in a script. Present in 6.0.0 **[P6]** (`createLabels` and `sync` **[V6]**): `changeNodePropertyKey`, `clearDatabase` (everything,
irreversibly), `copyRelationshipProperties`, `createLabels`, `deploy`, `deployData`,
`directFileImport`, `fixNodeProperties`, `flushCaches`, `letsencrypt`, `rebuildIndex`,
`setNodeProperties`, `setRelationshipProperties`, `setUuid`, `sync`. **[D7]** also
`maintenanceMode` (enable/disable), `migrate` (dry-run or apply the startup migrations),
`prefetchStatistics`, `detachedNodes`.

### 12.2 Deployment (application as code) **[D7]**

- `deploy` with `mode: export` writes the application (schema and methods, pages, shared
  components, templates, files marked `includeInFrontendExport`, mail templates, widgets,
  localizations, sites, resource access grants, schema grants, CORS settings, URL routes) to a
  directory as text files suitable for version control; `mode: import` replaces the application
  (not users or data) with a directory's contents; `extendExistingApp` merges instead.
  `pre-deploy.conf` / `post-deploy.conf` in the directory run before and after import (write them
  idempotently, with `getOrCreate`).
- `deployData` exports or imports chosen types' data; import runs without validation or lifecycle
  methods; rebuild indexes afterwards.
- `sync` with `mode: export` and a `file` path writes the whole graph, **or the subgraph a Cypher
  `query` returns**, with file contents, into one ZIP; `exportDb` leaves file contents out;
  `import` adds a ZIP's content (it does not clear first). A way to move or back up a subset
  without stopping anything. **[V6]** (export with a `query`: `POST
  /structr/rest/maintenance/sync {"mode": "export", "file": "/tmp/x.zip", "query": "MATCH (n:<Type>)
  RETURN n"}` writes the ZIP inside the container; import not exercised.)

### 12.3 Backups **[D7]**

A full backup is the Neo4j data together with Structr's files directory, `structr.conf`,
certificates and scripts, taken with both stopped (or a VM snapshot). An application export and a
`sync` export complement it; neither replaces it.

### 12.4 Monitoring and debugging

- Health endpoints (section 2.2); `/structr/histogram?sort=avg&top=100` lists every database
  statement with its count and total, average, minimum and maximum time (whitelisted:
  `histogramservlet.whitelist`) **[V6]** (from inside the container); Prometheus metrics at `/structr/metrics` once the
  `MetricsServlet` is enabled; `/structr/rest/stats` request counts. **[D7]**
- Logging **[D7]**: `log.level` (immediate), `logback-include.xml` for per-package levels,
  `log.cypher.debug`, `log.querytime.threshold` (slow queries, default 3000 ms),
  `log.callback.threshold`, `log.requests`; `$.log(...)`. Always read the server log after a
  script change, since StructrScript errors are silent to the caller. **[V6]** (silence)
- `?logPermissionResolution=true` on a request logs how each object's access was decided.
  **[D7]**
- `application.scripting.debugger=true` exposes a Chrome DevTools URL; a `debugger;` statement
  pauses there. **[D7]**
- The dashboard's event log records authentication, REST, cron, scripting errors, denied resource
  access and transactions with timing breakdowns. **[D7]**

### 12.5 Change history (changelog) **[V6]** unless marked

- `application.changelog.enabled` records, for every node, creations, deletions, links, unlinks
  and property changes (with previous and new values, user and time);
  `application.changelog.user_centric.enabled` records the same per user. Read with
  `changelog(node, resolve, {verb, key, timeFrom, ...})` and `userChangelog(user, ...)`.
- In Docker: `STRUCTR_application_changelog_enabled=true` and
  `STRUCTR_application_changelog_user__centric_enabled=true` (an underscore inside a setting's
  name is doubled). `$.changelog(id, false)` then returns entries with `verb` (`create`, `change`,
  ...), `key`, `prev`, `val`, `time`, `userId` and `userName`.
- **It is stored in files** (`changelog.path`; in the Docker image `/var/lib/structr/changelog`,
  directories `n/` for nodes and `r/` for relationships), not in the database, and that path is not
  on one of the image's volumes: mount one, and back it up with the instance. It records only
  writes made while enabled. It adds overhead to every write; exclude types with
  `changelogDisabled` (a `SchemaNode` field **[P6]**).

### 12.6 Maintenance mode and upgrades **[D7]**

- Maintenance mode shows a maintenance page on the normal ports while the admin interface and
  services move to other ports (8182 by default for HTTP).
- Minor versions migrate automatically at start; read the release and upgrade notes before a
  major version, back up first, and test the upgrade on a copy. **[7.x]**
  `application.migration.mode` (`apply`, `dry-run` which stops after reporting, `off`).

### 12.7 Settings worth knowing **[D7]**

`application.instance.name` / `application.instance.stage` (shown in the admin UI; tell
instances apart), `application.timezone`, `application.heap.min_size`/`max_size`,
`application.session.timeout`, `application.root.path` (behind a path-prefixing proxy),
`httpservice.gzip.enabled`, `httpservice.force.https`, `application.https.enabled` with a
keystore (Structr terminates TLS itself; the `letsencrypt` command fills the keystore),
`httpservice.ratelimiting.*` (off by default), `security.passwordpolicy.*`,
`htmlservlet.customresponseheaders` (HSTS), `uploadservlet.maxfilesize`,
`application.filesystem.enabled`.

---

## 13. Versions

- **6.0 relative to 5.x** **[D7]**: global methods are called as `$.name()` and
  `/structr/rest/name` (no `globalSchemaMethods`), `_loose` became `_inexact`, `$.GET` returns an
  object with `.body`, `extendsClass` became `inheritedTraits`, JavaScript runs in strict mode and
  returns its last value, custom indexes are dropped on upgrade, uploads default to
  `/._structr_uploads`, repeaters cannot use REST queries.
- **7.0** **[D7]**: outbound HTTP signatures (one trailing options object; failures return status
  0), binary POST responses are streams, `pdf()` renders inside the JVM and returns a File,
  GraalVM 25 required for the Debian package.
- **7.1** (release notes): content extraction replaces the text-search module (`$.documents.*`);
  vector search; named job queues; superuser second factor and lockout; setup token; HttpOnly
  session cookie by default; untrusted files sandboxed; URL routes set `current`; `minify()`;
  `_serverLog`; stricter `assert()`; changed sort semantics; undeclared method parameters refused;
  mailboxes no longer fetched automatically; virtual types and the api-builder module removed;
  only admins set `skipSecurityRelationships`.

- **7.1.0, verified** **[V7.1]** (2026-10-27, the same probes as the [V6] items):
  - A method that declares parameters refuses an undeclared argument with 422 "Unknown parameter(s)
    ... Enable 'Allow unknown parameters' to accept other parameters". A method that declares none
    still receives everything.
  - `application.schema.automigration` is gone (a warning at start): `application.migration.mode`
    (`dry-run`, `apply`, `off`) replaces it and **defaults to `apply`**, so an instance upgrades its
    database when it first starts on 7.1, whatever it had before. Use `dry-run` to see what would
    change, and keep a backup: only a backup goes back.
  - A fresh Docker install started with `STRUCTR_superuser_password` (and the privacy agreement)
    needed no setup token, and `X-User`/`X-Password` header requests worked unchanged.
  - **Permission propagation is not safe to rely on**: on a relationship with
    `permissionPropagation: "Out"` and `readPropagation: "Add"`, a read grant on the source to one
    user also let a second signed-in user, who had no grant, read the source and its targets.
    Plain grants to a user or a group reached only them.
  - Unchanged: cascading delete (including shared targets), formats (including the open-end and
    pattern catches, and an edit refused), `onSave` with modifications and on relationship
    changes, schema grants, `createLabels`, array POST, unknown-input `reject`, the changelog
    (still in `/var/lib/structr/changelog`), cron by environment, `cache`, `doAs` (its return
    value not tried again), `schedule`, `sync`, `evaluateScript`, health and histogram, the Event
    Action Mapping library, and default visibility's stored flag. Python still does not run.
  - A full application build was identical to its 6.0 build, node for node.
- **7.1.0, verified** **[V7.1]** (2026-10-31, a fresh development instance):
  - An admin `User` (`isAdmin`) does through REST all a build script needs of the superuser:
    schema changes, methods, maintenance commands, and reading owner-only nodes of others. With
    `skipSecurityRelationships` what it creates has no owner and no grants; without it, every node
    it creates gets both.
  - A `User` refuses even its right password after more than four wrong ones in a row (four
    then the right one worked; six did not), until `passwordAttempts` is set back to 0. The
    superuser is unaffected.
  - Header authentication as a stored user costs about 0.4 s a request (its Argon2id hash,
    `security.passwordhash.*`), against 15 ms for the superuser. A session costs one login
    (`POST /structr/rest/login`; an admin sending its headers needs no `_login` grant) and then
    11-15 ms a request with `X-StructrSessionToken`. Logout ends the session only when it carries
    the `JSESSIONID` cookie; with the token header alone it answers 200 and ends nothing.
  - Each session is stored as a `SessionDataNode`, which a logout leaves behind; none were swept
    within 48 minutes of the session timeout. An admin may delete them through REST.
  - `/structr/health/ready` answers through the published port without credentials.
  - A fresh database gets the initial user `admin` / `admin` with `isAdmin: true`, and it logs in.
  - The superuser still cannot log in to pages ("Login with superuser not supported"), even with its
    headers on the login request; an admin can (3.3).
  - A page element posted without visibility flags is owner-only, like any node.

Check the running version on the dashboard ("About Structr") or the server log's "Started
Structr" line.

---

## 14. Patterns that work

- **Idempotent schema setup:** declare types, properties and relationships as data; a helper
  looks each up by name (and, for relationships, by source, target and type) and creates only
  what is missing. Re-run freely.
- **Upsert by natural key:** find by a unique, directly declared, comma-free property; patch if
  found, create otherwise; set visibility every time. Better still, `createOrUpdate` in a script
  or a batch POST of stubs.
- **Validators as lifecycle methods:** `onCreate` and an `onSave` twin for edits, calling
  `error(...)` when an invariant fails; guard every numeric comparison with `empty()`. Simple
  ranges can be a numeric `format` instead; a string pattern `format` also makes the property
  required.
- **Dependents deleted with their parent:** `cascadingDeleteFlag` on the parent-to-child
  relationship instead of deleting each child by hand.
- **After changing a populated type's traits:** `createLabels` for that type, restart, verify.
- **Sharing within a group:** private nodes (no visibility flags), granted to the group on create;
  or a schema grant when every node of a type is shared the same way; or permission propagation
  from a shared parent (not on 7.1.0, where it let in a user without a grant: section 13).
- **Server-side logic callable from pages and from outside:** JavaScript user-defined functions in
  files, installed by a tool that sets `source`, warms each up once, and leaves others alone.
- **A lock for read-modify-write:** write a property on a shared node first, then read, then write.
- **Long jobs:** batch with `doInNewTransaction`, or `schedule()`; never one giant transaction.
- **Reproducible instances:** every schema and data change through a versioned, idempotent script,
  so an instance can be rebuilt and compared against a recorded snapshot.

---

## 15. Probing checklist

Before relying on a behaviour not marked [V6]:

1. Use a disposable instance (fresh containers, a throwaway database), never a live one.
2. Create uniquely named throwaway types; set every flag explicitly.
3. **Restart Structr after the schema changes**, then test.
4. Test both the accepted and the refused case, and read the server log after each.
5. Read results back through the view you need (`/all`), checking literal values, not
   impressions.
6. Delete what the probe created; tear the instance down.
7. Record the result with the version it was run on.

# Releasing the planner as a self-hosted project

**Status: a plan, not started** (written 2026-10-24 at the owner's request: "Write the doc but don't
work on it now"). Nothing here is built. It records what releasing this project for other people to
run at home would take, in the order it would be done, and the decisions that are the owner's.

## Where it stands

- **What runs:** three pieces on one machine. Neo4j holds the graph; Structr (6.0.0, the stock
  image) serves the REST API and the pages (`pages/`, server-side JavaScript); the planner and every
  tool are Python on the host (`tools/`, `mealplanner/`), talking to Structr over REST. The optional
  CP-SAT solver (OR-tools) lives in a virtualenv. Structr's container has no Python.
- **How a week is made:** the owner edits `private/week.toml` and runs `tools/plan_week.py` in a
  terminal; the proposal is a JSON file beside it (`private/week.proposal.json`) until `--commit`.
- **How an instance is made:** a full build (48 numbered scripts in `scripts/`, demos included), then
  `tools/make_owner_instance.py` strips the demos and marks the instance as the owner's
  (`tools/owner_stack.sh build`). Schema changes since then are idempotent scripts (`30a` to `38a`)
  run by hand on the owner's instance, then Structr restarted (CLAUDE.md hard rule 8).
- **Security:** none to speak of, by the owner's choice for a machine behind a firewall (2026-10-23):
  pages write as the superuser for anyone signed in (`$.doPrivileged`), writes travel as plain links
  (`?do=...`), the sign-in page is public, and Structr's admin UI shares the port. Two things the
  firewall does not cover (found 2026-10-26):
  - **The whole home network reaches it, not only this machine.** `docker-compose.yml` publishes
    Structr's port on every interface (`"8085:8082"`, not `"127.0.0.1:8085:8082"`), so any device on
    the network reaches the sign-in page and the REST API, where the superuser password opens
    everything. Neo4j is not published.
  - **A page on another site can book through a signed-in browser.** A booking is a link, and the page
    accepts any hex token: it is not tied to the session. Visiting a page on the internet while signed
    in could send the browser to such a link, and browsers' default cookie rule (SameSite=Lax) sends
    the session cookie with that kind of navigation, unless Structr sets a stricter one (not checked).
    The browser is inside the firewall, so the firewall does not help. A purchase needs no node id to
    forge; the other bookings need one.

  Passwords cross the network unencrypted (HTTP), and backups are plain archives that include
  `private/`.
- **Backup:** `tools/backup.py` (2026-10-26, `docs/backups.md`): a dump at every stop of the owner's
  stack, checked by restoring it into a throwaway stack; built for this machine's stack names and paths.
- **Tests:** offline, run locally; GitHub runs nothing (the owner's choice, 2026-10-24).

## Licences and content

| Piece | Licence | What it means here |
|---|---|---|
| This repository | MIT (`LICENSE`) | the owner's to choose again before a release |
| Structr | dual: AGPL v3 or later and GPL v3 or later, or a commercial licence from Structr GmbH ([github.com/structr/structr](https://github.com/structr/structr)) | used unmodified, as the published image, through its API; whether shipping MIT pages and scripts that Structr runs raises any AGPL question should be checked by someone qualified before release |
| Neo4j Community | GPL v3 | used unmodified, as the published image |
| USDA FoodData Central subsets (`data/fdc/`) | public domain (US government work) | credited in each file |
| USDA FoodKeeper (`data/foodkeeper/`) | CC0 | credited, with the checksum of the download |
| USDA retention factors (`data/retention/`) | public domain | credited |
| BLS and ERS prices (`data/prices/`) | public domain | credited |

**Recipes:** the owner's recipes (HelloFresh, EveryPlate and others) are in the git-ignored
`private/recipes/` and have never been committed (checked 2026-10-24, with `.env`); they must not
ship. A release needs a handful of original sample recipes, written for it, so a new install has a
week to plan. `structr/license.key` is an empty placeholder that Structr's community setup expects.

## Steps, in order

Each step says what is done when it is done.

1. **A clean install path.** One command that brings up the stack and builds an instance with the
   schema, the vocabulary, the profiles and the pages, and no demos, instead of building the demos
   and stripping them. *Done when* a fresh machine reaches a signed-in, empty week page with one
   command, and `tools/snapshot_state.py` matches a golden file for the empty install.
2. **A first-run setup.** The household, each person's targets from a dietary profile, the kitchen
   and the pantry, now made by `tools/instantiate_household.py` and `tools/instantiate_profile.py`
   from TOML files in `private/`, made from pages instead. *Done when* a new user can do it without a
   terminal.
3. **The planner in the stack.** A third container with Python, OR-tools and the planner, watching
   the graph for a request to plan a week and writing the proposal back; a page to start it, follow
   it (a run takes about five minutes), read the proposal and commit it. The week file's settings
   (start, meals, eaters, portions, prep sessions, the repeat tolerance, the cooking-time weight,
   the stock and waste weights) move onto that page, kept on the week's MealPlan, and the proposal
   moves from a file into the graph. *Done when* a week is planned and committed from the browser.
   (Alternatives weighed on 2026-10-24: a planner web service the page calls, Python inside
   Structr's container, a JavaScript port, a scheduled run. The watcher needs no open port and no
   credentials between services, and a long run holds no request open.)
4. **Security.** In order of cost:
   - *Cheap, and worth it even behind a firewall:* Structr's port bound to the machine
     (`127.0.0.1:`) unless other devices are meant to reach it; bookings as form posts carrying a
     token tied to the session and checked, in place of links with any token; HTTPS (a reverse proxy)
     once phones connect.
   - *With a planner or backend service (step 3; the next section):* the service not published,
     reachable only from Structr on the stack's own network; calls to it proven to come from Structr
     (a shared secret); its own Structr account with only the grants it needs, never the superuser;
     and whether a person may make a booking checked there, once, instead of in Python and in the
     pages' JavaScript.
   - *Before anyone outside the household uses it:* per-household permissions in place of
     `$.doPrivileged` for everyone (Structr's own grants, with a Household as the Group, or the
     service's check); rate limits on signing in; an audit trail (the pantry journal, `docs/todo.md`);
     Structr's admin UI and Neo4j not reachable from outside; a superuser password chosen at install,
     never a default; backups encrypted and copied off the machine.

   *Done when* a household member can do what the pages offer and nothing else, a page on another
   site cannot make the browser book anything, and a device on the network that is not signed in can
   reach nothing but the sign-in page.
5. **Upgrades.** A runner that applies the pending schema scripts in order, records which ran, and
   restarts Structr, so an upgrade is: pull the new version, run one command. "Never rename a
   SchemaNode" and "never add a trait to a populated type" (CLAUDE.md hard rules 1 and 2) become
   compatibility promises to every install. *Done when* an instance built by the previous release
   upgrades with one command and passes `tools/check_pages.py`.
6. **Backup and restore.** Built for the owner's instance on 2026-10-26 (`tools/backup.py`,
   `docs/backups.md`): a dump at every stop, checked by restoring it into a throwaway stack and
   comparing every page with Python. A release needs it to take its stack names, ports and paths from
   the install, and to offer a schedule for a stack that stays up. *Done when* a restore of last
   night's dump on a clean machine passes `tools/check_pages.py`.
7. **Sizing.** The stack needs about 3.5 GB (Neo4j 1.5 GB, Structr 2 GB, measured for about 1,000
   recipes, 2026-10-23); the planner container adds a few hundred MB while it runs. Documented, with
   the compose caps as defaults.
8. **Documents.** An install guide, a user guide (the weekly cycle: ask for recipes, plan, shop,
   cook, change the menu as the week goes), the data sources and their credits, and how to add a
   recipe (`docs/recipe-format.md` is written for this repository's owner).
9. **Release mechanics.** Version tags, a changelog, and container images published for the planner
   (and, if any is needed, the pages). With no CI on GitHub, a local release check runs before each
   tag: the offline tests with and without the solver, `tools/check_names.py`, and a fresh install
   compared with its golden file.

## How the pages would reach a Python service (2026-10-26)

Over HTTP, from the page's server-side JavaScript, with Structr's `$.POST` (or `$.GET`): not with
`exec()`. `exec()` starts a new process in Structr's own container for each call, to run a shell
script registered in `structr.conf`; a service is a program of its own, always running, in its own
container, which Structr calls as it would any web API. What follows is from Structr 6's bundled
documentation; nothing in this project has called out over HTTP yet.

A booking would read (in `pages/common.js`):

```js
$.addHeader("Content-Type", "application/json");
$.addHeader("X-Planner-Key", plannerKey);          // the shared secret, kept out of the page code
const reply = $.POST("http://planner:8000/bookings/buy",
  JSON.stringify({person: $.me.id, food: r.food, amount: r.amount, unit: r.unit, token: token}),
  "application/json", null, null, null, {timeout: 20});
if (reply.status !== 200) problem = "the planner did not answer: " + reply.status;
else booking = reply.body;                          // parsed JSON: what it booked, its notes
```

The service, a small Python web application, checks the secret, checks that the person may make the
booking, runs `mealplanner.pantry.buy(...)` against Structr's REST API with an account of its own, and
answers with what it booked; the page draws it as it does now. The Python is then the one copy.

- **Set a timeout.** `$.POST` takes one (`{timeout: seconds}`) and has none by default; `$.GET` takes
  none at all. Without one, a service that hangs hangs the page.
- **The call carries no user.** It is made by the Structr server, not as whoever is signed in, so the
  page says who is asking, and the service must believe only Structr (the next section).
- **Outgoing calls go anywhere by default.** Structr 6 can restrict them to listed addresses
  (`application.httphelper.urlwhitelist` in `structr.conf`): the service's, and nothing else.
- **The service is not published.** In the compose file it is `planner` on the stack's own network, so
  only Structr reaches `http://planner:8000`.
- **Call first, then read.** The service's writes commit before it answers; the page reads after the
  call, since a read repeated within one transaction answers as it did the first time
  (`docs/structr-cheatsheet.md`).
- **Speed is not measured.** A call goes page, service, Structr's REST and back: fine for a booking. A
  page that reads much (nutrition) would likely be slower than its JavaScript is now, unless the
  service keeps what it read.
- **One queue for every booking.** The service can take bookings one at a time in its own process; with
  the terminal tools sent through it too, the gap the pages' lock leaves (`docs/pages.md`) closes.

Two ways in which Structr never calls Python: the browser talks to the service directly (it serves the
pages or an API, and Structr is only the database; the service then needs its own sign-in and its own
check against cross-site requests), or the watcher of step 3 (a page writes "plan this week" into the
graph, the planner container notices, plans and writes the proposal back), which suits a run of
minutes that should not hold a page open, and is too slow for a button press. `exec()` suits an
occasional job only: it needs Python, the repository and OR-tools inside Structr's container, and
starts a Python process for every call.

## Security of the backend choices (2026-10-26)

The third review's #5 (`REVIEW.md`) asks for one backend in place of the pages' JavaScript copies of
the Python. Every way of doing that adds the same kind of risk: something that holds standing
credentials and acts for someone. Where it runs, and what it can reach, decides what a bug or a misuse
can do.

| Choice | What it adds | What contains it |
|---|---|---|
| **The logic in Structr's JavaScript** (schema methods the tools call) | No new service. But while writes run as the superuser, every method must code its own permission checks | Structr's per-node permissions, with a Household as a Group: the most native way to keep households apart, once writes stop running as the superuser |
| **A Python service the pages call** (`$.GET`/`$.POST` from the page, server to server) | A second network service. Reachable by anyone, and trusting a "this is person X" claim, it lets anyone act as anyone | Not published: on the stack's own network, called by Structr only, each call proven by a shared secret; its own Structr account, limited to what it needs; the one place a booking's permission is checked |
| **A planner worker or watcher** (step 3) | Runs unattended with standing credentials: a job could act on a request nobody was allowed to make, and solves can exhaust CPU and memory | Each request records who asked, checked when it runs; one solve at a time with a time limit; any queue kept off the network. Watching the graph needs no open port |
| **Reading Neo4j directly** (Bolt, for speed) | Neo4j Community has one login with every right, and no read-only roles as far as known: its credentials pass every Structr permission and validator | Bolt only on the stack's own network, never published; reads only, every write through Structr |
| **`exec()` from Structr** (a registered script, run per request) | Shell commands started by web requests: anything from the request in their arguments is an injection risk; Python inside Structr's image | Structr runs only scripts registered in `structr.conf` and quotes their arguments; pass ids only, never free text; better from a scheduled job than from a page |
| **Structr's CronService or `schedule()`** | Runs as an admin, so no permission check applies | Fine for a fixed job; never on parameters a user gave without checking them |

## Decisions for the owner

- The licence for this repository, and whether to get the AGPL question answered first.
- Whether a release is one household per install (as the model is built today, data-model.md §19)
  or several households on one server, which would need the sharing design of
  `docs/verification-and-sharing.md` built out.
- Where releases are published, under what name, and whether to accept outside contributions.
- Whether to keep "no GitHub CI" for the released project.

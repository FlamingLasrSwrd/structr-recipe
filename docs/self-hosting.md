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
  (`?do=...`), the sign-in page is public, and Structr's admin UI shares the port.
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
4. **Security.** Per-user permissions in place of `$.doPrivileged` for everyone; writes as form
   posts carrying a check against cross-site requests; HTTPS through a reverse proxy, with Structr's
   admin UI and Neo4j not reachable from outside; a superuser password chosen at install, never a
   default. *Done when* a household member can do what the pages offer and nothing else, and a
   page on another site cannot make the browser book anything.
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

## Decisions for the owner

- The licence for this repository, and whether to get the AGPL question answered first.
- Whether a release is one household per install (as the model is built today, data-model.md §19)
  or several households on one server, which would need the sharing design of
  `docs/verification-and-sharing.md` built out.
- Where releases are published, under what name, and whether to accept outside contributions.
- Whether to keep "no GitHub CI" for the released project.

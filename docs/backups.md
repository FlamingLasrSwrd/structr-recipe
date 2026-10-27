# Backups of the owner's instance

Built 2026-10-26 at the owner's request ("Yes, build a backup system"). The owner's instance holds
what nothing in the repository can rebuild: committed weeks, pantry bookings, recipes asked for,
menu changes, the household and its targets. `tools/backup.py` backs it up, checks a backup by
restoring it somewhere harmless, and puts one back.

## When a backup is made

**Every time the owner's stack is stopped**: `tools/owner_stack.sh stop` backs it up as it stops it.
The end of a working session is when the data has changed, and Neo4j Community can dump a stopped
database only, so the stack must stop for the dump anyway. A stack already stopped is not backed up
again. `NO_BACKUP=1 tools/owner_stack.sh stop` stops it without one.

At any other time:

```bash
python3 tools/backup.py now       # stops the stack for about a minute, then starts it again if it ran
```

## What a backup holds

A folder in `~/mealplanner-backups` (or `BACKUP_DIR`), named by when it was made
(`2026-10-26_133432`):

| File | What |
|---|---|
| `neo4j.dump` | the graph, by `neo4j-admin database dump` (40 MB on 2026-10-26, from a 614 MB store) |
| `structr-files.tar.gz`, `structr-repository.tar.gz` | Structr's two data volumes (empty today; kept in case) |
| `structr-changelog.tar.gz` | Structr's changelog: who created and changed what, and when, with the old and new values (2026-10-27, `docker-compose.yml`). Backups made before have none |
| `private.tar.gz` | the repository's git-ignored `private/`: recipe files, week files, household, prices |
| `manifest.json` | when, the two images, the repository's commit, the graph's node and relationship counts, each file's size and sha256, and every check made of it since |

`.env` is **not** copied: it holds the passwords, and a restore uses the repository's own.

The newest 14 are kept (`BACKUP_KEEP`). A backup is written as `.partial-<name>` and renamed only when
complete, so a folder with a plain name is a whole backup; a failed one leaves nothing behind.

**The folder is on the same disk as the instance.** A failed disk takes both. Copy the folder
elsewhere from time to time (an external drive, another machine), or point `BACKUP_DIR` at one.

## Checking a backup

```bash
python3 tools/backup.py list              # what is kept, and whether each was checked
python3 tools/backup.py verify            # the newest; or name one
```

`verify` restores the backup into a throwaway stack (`mealplanner-verify`, port 8086), counts its
nodes and relationships against the manifest, runs `tools/check_pages.py` against it (every page
against what the Python tools work out), and removes the throwaway, volumes and all. It refuses while
another stack runs (two do not fit in 8 GB), and records the result in the manifest. It checks the
files' checksums first, so a damaged backup is caught before anything is started.

**Checked 2026-10-26:** the first backup (42,386 nodes, 88,680 relationships) restored with the same
counts, and every page gave 0 differences: the week of 26 Oct (21 meals, 448 target groups, 84 foods
to buy), 53 recipes, 43 pantry portions. It took 6.5 minutes, most of it Structr starting and the
page check.

## Putting a backup back

```bash
python3 tools/backup.py restore 2026-10-26_133432
```

This replaces everything in the owner's instance, so it asks for the backup's name to be typed
first, and before changing anything it backs up what is there now (`<time>-before-restore`), so a
restore can itself be undone. It then stops the stack, loads the graph and the Structr volumes,
starts the stack and counts the graph against the manifest. The backup's `private/` is unpacked
beside yours as `private.restored-<name>/`, not over it: copy from it what you need.

## How it works, and what to keep in mind

- Every Docker command is in `tools/backup.py`'s `run`, and the tests (`tests/test_backup.py`) fake it:
  the order (count, stop, dump), what is written, what is kept, that a failed backup leaves nothing,
  that a check removes only the throwaway, and that a restore does nothing until its name is typed.
- The images are read from `docker-compose.yml`, so the dump and load use the stack's own Neo4j.
- The counts are asked inside the Neo4j container with the password it was started with; no password
  is put on this machine's command line.
- `down -v` is only ever run on the throwaway project. Never run it on `mealplanner-owner`.
- A stack left running for days is backed up only when it stops; run `backup.py now` in between.
- **A backup is put back under the Structr that `docker-compose.yml` names.** Since 2026-10-27 that is
  7.1.0, which upgrades a database made by 6.0 when it starts (`application.migration.mode`, `apply` by
  default). So a backup made before the upgrade, restored now, comes back upgraded; to have it on 6.0
  again, set the image line back to `structr/structr:6.0.0` first. Each manifest records the images it
  was made with.
- The changelog lives in files, not in the graph, so it is backed up as a volume. A restore puts back
  the changelog the backup holds; restoring a backup made before the changelog leaves the changelog
  as it is, which then also lists the writes the restore undid.
- Avoid starting a backup or a check at about 10:00, when the daily Timeshift snapshot fills the disk.

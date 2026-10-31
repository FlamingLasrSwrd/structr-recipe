"""Back up the owner's instance, check a backup, or put one back (docs/backups.md).

    python3 tools/backup.py now              back it up; the stack is stopped for the dump and started again if it ran
    python3 tools/backup.py list             the backups kept, newest first
    python3 tools/backup.py verify [NAME]    restore NAME (default: the newest) into a throwaway stack, count it against
                                             the backup, check its pages against Python, and remove the throwaway
    python3 tools/backup.py restore NAME     put NAME back into the owner's instance, after backing up what is there;
                                             asks you to type NAME first

tools/owner_stack.sh stop runs `now --leave-stopped` (NO_BACKUP=1 skips it): the end of a working session is
when the data has changed, and the stack is being stopped anyway. Neo4j Community dumps a stopped database
only, so a backup always stops the stack for the half minute the dump takes.

A backup is a folder in BACKUP_DIR (default ~/mealplanner-backups) named by when it was made:
    neo4j.dump                    the graph (neo4j-admin database dump)
    structr-files.tar.gz          Structr's data volumes
    structr-repository.tar.gz
    structr-changelog.tar.gz      who changed what and when (docker-compose.yml); not in backups made before it
    private.tar.gz                the repository's git-ignored private/ (recipes, week files, household, prices)
    manifest.json                 when, the images, the repository's commit, the graph's node and relationship
                                  counts, each file's size and sha256, and every verification since
.env is not copied: it holds passwords, and a restore uses the one in the repository. The newest BACKUP_KEEP
(default 14) are kept. A backup is written as .partial-NAME and renamed when complete, so a folder with a
name is a whole backup.

Never run against anything but the owner's stack (mealplanner-owner) and the throwaway (mealplanner-verify);
`down -v` is only ever run on the throwaway.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWNER = "mealplanner-owner"
VERIFY = "mealplanner-verify"            # the throwaway a backup is checked in; never the owner's
VERIFY_PORT = 8086
OWNER_PORT = 8085
VOLUMES = ("structr-files", "structr-repository", "structr-changelog")
NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(-[a-z-]+)?$")
WAIT_S = 240


class BackupError(RuntimeError):
    pass


def run(args: list, *, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Every docker and helper command goes through here (tests replace it)."""
    result = subprocess.run(args, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise BackupError(f"{' '.join(args[:4])}... failed: {(result.stderr or result.stdout).strip()[-600:]}")
    return result


def load_env() -> dict:
    """KEY=VALUE lines of the repository's .env, which compose needs to start a stack. Never printed."""
    path = REPO / ".env"
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def image(service: str) -> str:
    """The image docker-compose.yml names for a service, so the tools match the stack's versions."""
    text = (REPO / "docker-compose.yml").read_text()
    block = text.split(f"\n  {service}:\n", 1)[1]
    return re.search(r"image:\s*(\S+)", block).group(1)


def compose(project: str, *args, port: int | None = None, check: bool = True) -> subprocess.CompletedProcess:
    env = {**load_env(), "STRUCTR_PORT": str(port)} if port else load_env()
    return run(["docker", "compose", "-p", project, *args], env=env, check=check)


def running(project: str) -> list[str]:
    out = run(["docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Names}}"]).stdout
    return [n for n in out.split() if n]


def other_stacks(*mine: str) -> list[str]:
    """Running Structr or Neo4j containers of any project but these: two stacks do not fit in 8 GB."""
    out = run(["docker", "ps", "--format", "{{.Names}}"]).stdout.split()
    return [n for n in out if re.search("structr|neo4j", n, re.I) and not any(n.startswith(f"{p}-") for p in mine)]


def counts(project: str, wait_s: float = WAIT_S) -> tuple[int, int]:
    """(nodes, relationships) in the project's running graph, asked inside its Neo4j container with the
    password the container was started with, so none is passed on this machine's command line."""
    query = "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() RETURN nodes, count(r) AS relationships"
    shell = f'cypher-shell -u neo4j -p "${{NEO4J_AUTH#neo4j/}}" --format plain "{query}"'
    deadline = time.monotonic() + wait_s
    while True:
        got = run(["docker", "exec", f"{project}-neo4j-1", "sh", "-c", shell], check=False)
        if got.returncode == 0:
            return parse_counts(got.stdout)
        if time.monotonic() > deadline:
            raise BackupError(f"{project}'s Neo4j did not answer in {wait_s:g} s: {got.stderr.strip()[-300:]}")
        time.sleep(3)


def parse_counts(text: str) -> tuple[int, int]:
    rows = [line for line in text.strip().splitlines() if line.strip()]
    nodes, relationships = (int(x.strip()) for x in rows[-1].split(","))
    return nodes, relationships


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR") or Path.home() / "mealplanner-backups")


def backups() -> list[Path]:
    """The complete backups, newest first."""
    root = backup_dir()
    found = [p for p in root.iterdir() if p.is_dir() and NAME.match(p.name) and (p / "manifest.json").exists()] if root.exists() else []
    return sorted(found, key=lambda p: p.name, reverse=True)


def to_remove(names: list[str], keep: int) -> list[str]:
    """The backups beyond the newest `keep`, oldest last. Names sort by time."""
    return sorted(names, reverse=True)[keep:]


def owned_by_me(folder: Path, *files: str) -> None:
    """Files the containers wrote as their own users, handed to this machine's user."""
    uid, gid = os.getuid(), os.getgid()
    run(["docker", "run", "--rm", "--entrypoint", "chown", "-v", f"{folder}:/out", image("neo4j"), f"{uid}:{gid}",
         *[f"/out/{f}" for f in files]])


def dump(project: str, folder: Path) -> None:
    folder.chmod(0o777)                   # neo4j-admin writes as the image's own user
    try:
        run(["docker", "run", "--rm", "-v", f"{project}_neo4j-database:/data", "-v", f"{folder}:/backups", image("neo4j"),
             "neo4j-admin", "database", "dump", "neo4j", "--to-path=/backups", "--overwrite-destination=true"])
        owned_by_me(folder, "neo4j.dump")
    finally:
        folder.chmod(0o755)


def archive_volume(project: str, volume: str, folder: Path) -> None:
    """The volume as a .tar.gz in the folder; nothing if the stack has never made it, since `docker run -v`
    would make it: an empty volume Compose did not create warns at every start (structr-changelog,
    2026-10-27, which the first backup after it was added to docker-compose.yml made)."""
    if run(["docker", "volume", "inspect", f"{project}_{volume}"], check=False).returncode != 0:
        return
    folder.chmod(0o777)
    try:
        run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{project}_{volume}:/v:ro", "-v", f"{folder}:/out",
             image("neo4j"), "-c", f"tar czf /out/{volume}.tar.gz -C /v . && chown {os.getuid()}:{os.getgid()} /out/{volume}.tar.gz"])
    finally:
        folder.chmod(0o755)


def load(project: str, folder: Path) -> None:
    run(["docker", "run", "--rm", "-v", f"{project}_neo4j-database:/data", "-v", f"{folder}:/backups:ro", image("neo4j"),
         "neo4j-admin", "database", "load", "neo4j", "--from-path=/backups", "--overwrite-destination=true"])


def restore_volume(project: str, volume: str, folder: Path) -> None:
    run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{project}_{volume}:/v", "-v", f"{folder}:/in:ro",
         image("neo4j"), "-c", f"find /v -mindepth 1 -delete && tar xzf /in/{volume}.tar.gz -C /v"])


def git_commit() -> str | None:
    got = run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=False)
    return got.stdout.strip() or None


def write_manifest(folder: Path, data: dict) -> None:
    (folder / "manifest.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def read_manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text())


def now(*, leave_stopped: bool = False, label: str = "", force: bool = False) -> Path | None:
    """Back up the owner's instance. leave_stopped: called by owner_stack.sh stop, so the stack stays
    stopped, and a stack already stopped has nothing new to back up (unless `force`)."""
    was_running = bool(running(OWNER))
    if leave_stopped and not was_running and not force:
        print("the owner's stack is not running: nothing new to back up")
        return None
    started = time.monotonic()
    root = backup_dir()
    root.mkdir(parents=True, exist_ok=True)
    while True:                           # names are to the second: one made within it waits for the next
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        if not any(p.name.removeprefix(".partial-").startswith(stamp) for p in root.iterdir()):
            break
        time.sleep(0.2)
    name = stamp + (f"-{label}" if label else "")
    partial = root / f".partial-{name}"
    partial.mkdir()
    try:
        tally = None
        if was_running:
            tally = counts(OWNER)
        elif not other_stacks(OWNER):
            compose(OWNER, "up", "-d", "neo4j", port=OWNER_PORT)       # Neo4j alone, to count what is backed up
            tally = counts(OWNER)
        else:
            print(f"note: another stack is running ({', '.join(other_stacks(OWNER))}), so the graph is not counted")
        compose(OWNER, "stop")
        dump(OWNER, partial)
        for volume in VOLUMES:
            archive_volume(OWNER, volume, partial)
        if (REPO / "private").is_dir():
            run(["tar", "czf", str(partial / "private.tar.gz"), "-C", str(REPO), "private"])
        files = {f.name: {"bytes": f.stat().st_size, "sha256": sha256(f)} for f in sorted(partial.iterdir())}
        write_manifest(partial, {
            "name": name, "created": datetime.now().astimezone().isoformat(timespec="seconds"), "instance": OWNER,
            "images": {"neo4j": image("neo4j"), "structr": image("structr")}, "commit": git_commit(),
            "counts": None if tally is None else {"nodes": tally[0], "relationships": tally[1]},
            "files": files, "verified": []})
        partial.rename(root / name)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    finally:
        if was_running and not leave_stopped:
            run(["bash", str(REPO / "tools" / "owner_stack.sh"), "up"], check=False)
    folder = root / name
    size = sum(f.stat().st_size for f in folder.iterdir())
    print(f"backed up to {folder}: {size / 1e6:.1f} MB"
          + (f", {tally[0]:,} nodes and {tally[1]:,} relationships" if tally else "") + f", in {time.monotonic() - started:.0f} s")
    keep = int(os.environ.get("BACKUP_KEEP", "14"))
    for old in to_remove([p.name for p in backups()], keep):
        shutil.rmtree(root / old)
        print(f"removed {old}, beyond the newest {keep}")
    return folder


def show() -> None:
    found = backups()
    if not found:
        print(f"no backups in {backup_dir()}")
    for folder in found:
        m = read_manifest(folder)
        size = sum(f["bytes"] for f in m["files"].values())
        c = m.get("counts")
        checks = m.get("verified") or []
        last = checks[-1] if checks else None
        print(f"{folder.name}  {size / 1e6:6.1f} MB  " + (f"{c['nodes']:,} nodes, {c['relationships']:,} relationships" if c else "not counted")
              + ("  verified " + last["at"][:16] + (" OK" if last["ok"] else " FAILED") if last else "  not verified"))


def chosen(name: str | None) -> Path:
    found = backups()
    if not found:
        raise BackupError(f"no backups in {backup_dir()}")
    if name is None:
        return found[0]
    for folder in found:
        if folder.name == name:
            return folder
    raise BackupError(f"no backup named {name!r} in {backup_dir()} (python3 tools/backup.py list)")


def intact(folder: Path) -> None:
    """Every file the manifest lists, of the size and checksum it says."""
    for fname, meta in read_manifest(folder)["files"].items():
        path = folder / fname
        if not path.exists() or path.stat().st_size != meta["bytes"] or sha256(path) != meta["sha256"]:
            raise BackupError(f"{folder.name}/{fname} is missing or changed since the backup")


def put_back(project: str, folder: Path) -> None:
    load(project, folder)
    for volume in VOLUMES:
        if (folder / f"{volume}.tar.gz").exists():
            restore_volume(project, volume, folder)


def tools_account(port: int) -> None:
    """Make the account every tool logs in as on the instance at `port`, or bring it into line with .env
    (tools/create_tools_user.py). A backup made before the account existed (2026-10-31) does not hold it,
    and one made since may hold another password."""
    run([sys.executable, str(REPO / "tools" / "create_tools_user.py")],
        env={**load_env(), "STRUCTR_URL": f"http://localhost:{port}"})


def install_code(port: int) -> None:
    """The repository's pages and methods on the instance at `port`. A backup holds those of when it was
    made, and check_pages compares what they show with today's Python, so an older page differs though the
    data is sound (2026-10-31: 896 differences, every one the nutrition page's new mark for estimates)."""
    env = {**load_env(), "STRUCTR_URL": f"http://localhost:{port}"}
    for tool in ("install_pages.py", "install_methods.py"):
        run([sys.executable, str(REPO / "tools" / tool)], env=env)


def verify(name: str | None) -> bool:
    folder = chosen(name)
    intact(folder)
    others = other_stacks()
    if others:
        raise BackupError(f"stop the running stacks first ({', '.join(others)}): two do not fit in 8 GB")
    manifest = read_manifest(folder)
    result = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "ok": False}
    assert VERIFY != OWNER
    try:
        compose(VERIFY, "up", "--no-start", port=VERIFY_PORT)
        put_back(VERIFY, folder)
        compose(VERIFY, "start", port=VERIFY_PORT)
        nodes, relationships = counts(VERIFY)
        result.update(nodes=nodes, relationships=relationships)
        expected = manifest.get("counts")
        result["counts_match"] = expected is None or (expected["nodes"], expected["relationships"]) == (nodes, relationships)
        url = f"http://localhost:{VERIFY_PORT}"
        run(["bash", str(REPO / "tools" / "wait_for_structr.sh"), str(WAIT_S)], env={**load_env(), "STRUCTR_URL": url})
        tools_account(VERIFY_PORT)            # after the count: neither is part of what was backed up
        install_code(VERIFY_PORT)
        pages = run([sys.executable, str(REPO / "tools" / "check_pages.py")], env={**load_env(), "STRUCTR_URL": url}, check=False)
        result["pages"] = (pages.stdout.strip().splitlines() or ["(nothing printed)"])[-1]
        result["ok"] = bool(result["counts_match"] and pages.returncode == 0)
    except BackupError as exc:
        result["problem"] = str(exc)
    finally:
        compose(VERIFY, "down", "-v", port=VERIFY_PORT, check=False)       # the throwaway only
        manifest.setdefault("verified", []).append(result)
        write_manifest(folder, manifest)
    c = manifest.get("counts")
    print(f"{folder.name}: " + ("OK" if result["ok"] else "FAILED")
          + (f"; restored {result['nodes']:,} nodes and {result['relationships']:,} relationships"
             + (f" (backed up: {c['nodes']:,} and {c['relationships']:,})" if c else " (not counted when backed up)")
             if "nodes" in result else "")
          + (f"; pages: {result['pages']}" if "pages" in result else "") + (f"; {result['problem']}" if "problem" in result else ""))
    return result["ok"]


def restore(name: str, answer=input) -> None:
    folder = chosen(name)
    intact(folder)
    others = other_stacks(OWNER)
    if others:
        raise BackupError(f"stop the other running stacks first ({', '.join(others)})")
    typed = answer(f"This replaces everything in the owner's instance with {folder.name}. Type {folder.name} to go on: ")
    if typed.strip() != folder.name:
        raise BackupError("not confirmed: nothing was changed")
    safety = now(leave_stopped=True, label="before-restore", force=True)
    print(f"what was there is kept as {safety.name}")
    compose(OWNER, "stop")
    put_back(OWNER, folder)
    if (folder / "private.tar.gz").exists():
        target = REPO / f"private.restored-{folder.name}"
        target.mkdir(exist_ok=False)
        run(["tar", "xzf", str(folder / "private.tar.gz"), "-C", str(target)])
        print(f"its private/ is in {target}, beside yours, which was left alone: copy what you need from it")
    run(["bash", str(REPO / "tools" / "owner_stack.sh"), "up"])
    nodes, relationships = counts(OWNER)
    c = read_manifest(folder).get("counts")
    print(f"restored {folder.name}: {nodes:,} nodes and {relationships:,} relationships"
          + (f" (backed up: {c['nodes']:,} and {c['relationships']:,})" if c else ""))
    try:
        tools_account(OWNER_PORT)
    except BackupError as exc:                # the data is back all the same: say what is left to do
        print(f"the tools' account could not be made ({exc}): until tools/create_tools_user.py has run, every tool answers 401")
    print("its pages and methods are those of when it was made: tools/install_pages.py and tools/install_methods.py "
          "bring them up to the repository's")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p_now = sub.add_parser("now", help="back up the owner's instance")
    p_now.add_argument("--leave-stopped", action="store_true", help="leave the stack stopped (owner_stack.sh stop)")
    sub.add_parser("list", help="the backups kept, newest first")
    p_verify = sub.add_parser("verify", help="restore a backup into a throwaway stack and check it")
    p_verify.add_argument("name", nargs="?")
    p_restore = sub.add_parser("restore", help="put a backup back into the owner's instance")
    p_restore.add_argument("name")
    args = parser.parse_args(argv)
    try:
        if args.action == "now":
            now(leave_stopped=args.leave_stopped)
        elif args.action == "list":
            show()
        elif args.action == "verify":
            return 0 if verify(args.name) else 1
        else:
            restore(args.name)
    except BackupError as exc:
        print(f"problem: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

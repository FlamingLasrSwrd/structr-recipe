"""Install the meal planner's Structr methods (methods/; docs/architecture-decision.md, Path S).

    python3 tools/install_methods.py            # install, or replace, every method
    python3 tools/install_methods.py --remove   # remove every method this installs

Each methods/<name>.js is the body of one user-defined function: called over REST as
POST /structr/rest/<name> with a JSON body of its arguments ($.methodParameters), and from a page or
another method as $.<name>({...}). It runs as whoever calls it, so Structr's access control applies.
Its source is the engine code in pages/lib/ (every file, in name order) and then the file, in one block,
{ ... }, the form Structr runs as JavaScript (docs/structr-cheatsheet.md §3a): a method uses the engine
code the pages use, not a copy. pages/common.js, the pages' own shell, is not part of it.

Every method begins by answering a call whose arguments are {"warmUp": true} with nothing, and this
tool makes that call after installing or replacing one: a method called by several people at once
before its first call has finished answers some of them 404 (docs/structr-cheatsheet.md §3a).

The source's second line names the file it came from. That is how this tool knows its own methods
(it never touches another, such as the validators) and how tools/snapshot_state.py leaves them out:
they are code, like the pages, not instance state. Each run replaces each method whole and removes
those whose file is gone. Needs STRUCTR_TOOLS_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METHODS_DIR = os.path.join(ROOT, "methods")
LIB = os.path.join(ROOT, "pages", "lib")
MARK = "// installed by tools/install_methods.py from "      # tools/snapshot_state.py looks for this
WARM_UP = "if (($.methodParameters || {}).warmUp === true) return null;"
NAME = re.compile(r"^[a-z][a-zA-Z0-9]*$")                    # a Structr method name (cheatsheet §3a), no underscores


class MethodError(RuntimeError):
    pass


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def engine() -> str:
    """Every pages/lib/*.js, in name order, as tools/install_pages.py puts them before a page."""
    return "\n".join(read(os.path.join(LIB, f)) for f in sorted(os.listdir(LIB)) if f.endswith(".js"))


def methods() -> dict[str, str]:
    """name: source, for every methods/<name>.js."""
    common = engine()
    out = {}
    for fname in sorted(os.listdir(METHODS_DIR)):
        if not fname.endswith(".js"):
            continue
        name = fname[:-3]
        if not NAME.match(name):
            raise MethodError(f"methods/{fname}: a method's name starts with a small letter and has letters and digits only")
        out[name] = "{\n" + MARK + f"methods/{fname}\n" + WARM_UP + "\n" + common + "\n" + read(os.path.join(METHODS_DIR, fname)) + "\n}"
    return out


def functions(client) -> list[dict]:
    """The user-defined functions: SchemaMethods that belong to no type."""
    return [m for m in client.get("/structr/rest/SchemaMethod")["result"] if not m.get("schemaNode")]


def mine(method: dict) -> bool:
    """Installed by this tool: its source's second line names its file."""
    lines = (method.get("source") or "").split("\n", 2)
    return len(lines) > 1 and lines[1].startswith(MARK)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--remove", action="store_true", help="remove every method this installs")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # methods hold no data; what they write is the caller's to write
    client.wait_until_ready()
    wanted = {} if args.remove else methods()
    existing = functions(client)
    for m in existing:
        if mine(m) and m["name"] not in wanted:
            client.delete(f"/structr/rest/SchemaMethod/{m['id']}")
            print(f"{m['name']}: removed")
    for name, source in wanted.items():
        same = [m for m in existing if m["name"] == name]
        if same and not all(mine(m) for m in same):
            raise MethodError(f"{name}: a function of that name exists that this tool did not install; it is left alone")
        if len(same) > 1:
            for m in same[1:]:
                client.delete(f"/structr/rest/SchemaMethod/{m['id']}")
        if not same:
            client.post("/structr/rest/SchemaMethod", {"name": name, "source": source})
            print(f"{name}: installed at /structr/rest/{name}")
        elif same[0].get("source") != source:
            client.patch(f"/structr/rest/SchemaMethod/{same[0]['id']}", {"source": source})
            print(f"{name}: replaced")
        else:
            print(f"{name}: unchanged")
            continue
        client.post(f"/structr/rest/{name}", {"warmUp": True})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MethodError as exc:
        print(f"problem: {exc}")
        sys.exit(1)

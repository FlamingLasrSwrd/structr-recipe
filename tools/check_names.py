"""A small stand-in for pyflakes (not installed here): report names that are
used but never bound anywhere in a file, and imports that are never used.

Scope-insensitive on purpose: a name counts as bound if ANY scope in the file
binds it. That misses some real mistakes but has no false alarms about
comprehension or closure scoping, and it catches the failure this project has
actually had: a helper deleted or renamed while something still calls it.

Run from the repo root: python3 tools/check_names.py
Exit status is 1 if anything is reported. An import can be exempted with
`# noqa` on its line (used for deliberate re-exports).
"""

import ast
import builtins
import glob
import sys

BUILTINS = set(dir(builtins)) | {"__file__", "__name__"}
PATTERNS = ["scripts/*.py", "mealplanner/*.py", "mealplanner/*/*.py", "structr_client/*.py", "tools/*.py", "tests/*.py"]


def check(path: str) -> tuple[list[str], list[str]]:
    src = open(path).read()
    tree = ast.parse(src)
    bound, loaded, imported = set(), set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            if not isinstance(node, ast.ClassDef):
                a = node.args
                for arg in a.args + a.kwonlyargs + a.posonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                    bound.add(arg.arg)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for arg in a.args + a.kwonlyargs + a.posonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                bound.add(arg.arg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                bound.add(name)
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                bound.add(name)
                imported[name] = node.lineno
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    lines = src.splitlines()
    exported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            exported |= {e.value for e in ast.walk(node.value) if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    undefined = sorted(loaded - bound - BUILTINS)
    unused = sorted(n for n, ln in imported.items()
                    if n not in loaded and n != "annotations" and n not in exported and "noqa" not in lines[ln - 1])
    return undefined, unused


def main() -> int:
    problems = 0
    for path in sorted({p for pattern in PATTERNS for p in glob.glob(pattern)}):
        undefined, unused = check(path)
        if undefined or unused:
            problems += 1
            print(f"{path}: undefined={undefined} unused_imports={unused}")
    print(f"checked; files with findings: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

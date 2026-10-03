"""Static check: every ``self.<name>`` in the app must actually exist.

v4.1.1 shipped a log line that read ``self.sdk`` inside ``TimelineExtractor``
(the attribute lives on ``GeminiClient``), so every real job died instantly with::

    FAILED: 'TimelineExtractor' object has no attribute 'sdk'

Demo mode returns before that line, so the HTTP smoke test never reached it.
This catches the whole class of bug: an attribute read that no ``__init__``,
method, property, class attribute or base class ever defines.

Run:  .venv/bin/python tests/test_self_attrs.py
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = [
    "app.py",
    "recapstudio/ai.py",
    "recapstudio/jobs.py",
    "recapstudio/render.py",
    "recapstudio/media.py",
    "recapstudio/pipeline.py",
    "recapstudio/tts.py",
    "recapstudio/subtitles.py",
    "recapstudio/util.py",
    "recapstudio/uploads.py",
    "recapstudio/keys.py",
    "recapstudio/config.py",
]

#: names a class may legitimately pick up at runtime (none right now)
ALLOW: set[tuple[str, str]] = set()


def assigned_names(node: ast.ClassDef) -> set[str]:
    """Names a class defines: class-body fields (dataclasses) + ``self.x = …``."""
    found: set[str] = set()
    # dataclass style fields: "index: int" / "text: str = ''" in the class body
    for stmt in node.body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
            targets = [stmt.target]
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = list(getattr(stmt, "targets", []) or [stmt.target])
        for target in targets:
            if isinstance(target, ast.Name):
                found.add(target.id)
    for child in ast.walk(node):
        targets: list[ast.expr] = []
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
            targets = [child.target]
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            targets = [child.target]
        elif isinstance(child, ast.withitem) and child.optional_vars is not None:
            targets = [child.optional_vars]
        elif isinstance(child, ast.ExceptHandler) and child.name:
            found.add(child.name)  # not self.x, harmless
        for target in targets:
            for sub in ast.walk(target):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"):
                    found.add(sub.attr)
        # dynamic assignment: setattr(self, "x", …) / self.__dict__["x"] = …
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id == "setattr" and len(child.args) >= 2
                and isinstance(child.args[0], ast.Name) and child.args[0].id == "self"
                and isinstance(child.args[1], ast.Constant)):
            found.add(str(child.args[1].value))
    return found


def scan_source(source: str, runtime) -> list[tuple[str, str, int]]:
    """Return ``(class, attribute, line)`` for reads of undefined attributes."""
    tree = ast.parse(source)
    problems: list[tuple[str, str, int]] = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        defined = assigned_names(cls)
        runtime_cls = getattr(runtime, cls.name, None) if runtime else None
        for node in ast.walk(cls):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                continue
            attr = node.attr
            if attr in defined or (cls.name, attr) in ALLOW:
                continue
            if runtime_cls is not None and hasattr(runtime_cls, attr):
                continue  # method / property / class attribute
            if runtime_cls is not None and any(hasattr(base, attr) for base in runtime_cls.__mro__[1:]):
                continue
            problems.append((cls.name, attr, node.lineno))
    return problems


def scan(path: Path, module_name: str) -> list[tuple[str, str, int]]:
    try:
        runtime = importlib.import_module(module_name)
    except Exception:
        runtime = None
    return scan_source(path.read_text(encoding="utf-8"), runtime)


def main() -> int:
    print("── scanner self-test (the v4.1.1 regression) ──────────────")
    broken = """
class Extractor:
    def __init__(self):
        self.client = None

    def run(self):
        return getattr(self.sdk, "__version__", "?")
"""
    found = scan_source(broken, runtime=None)
    ok = len(found) == 1 and found[0][1] == "sdk"
    print(f"  [{'PASS' if ok else 'FAIL'}] undefined self.sdk is detected — {found}")
    if not ok:
        return 1

    total = 0
    for rel in MODULES:
        path = ROOT / rel
        if not path.exists():
            print(f"  [SKIP] {rel} (missing)")
            continue
        module_name = rel[:-3].replace("/", ".") if rel.endswith(".py") else rel
        problems = scan(path, module_name)
        seen: set[tuple[str, str]] = set()
        for cls, attr, line in problems:
            if (cls, attr) in seen:
                continue
            seen.add((cls, attr))
            total += 1
            print(f"  [FAIL] {rel}:{line} — {cls}.self.{attr} is never defined")
    print()
    if total:
        print(f"{total} undefined self attribute(s)")
        return 1
    print(f"OK — no undefined self attributes across {len(MODULES)} modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

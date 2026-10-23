"""L7 · "No model after the gate": the post-gate import graph is clean.

Project rule (SPEC §11): everything that runs after the approval gate — compiler,
simulator, resolver, job schemas, scan, replay, grid, materials — must never import
an AI provider. Enforced two ways, both hermetic:

  1. Static: walk the transitive import graph of every post-gate module (AST import
     walk over the local sources in this directory) and reject any source that
     mentions a forbidden provider name.
  2. Live: import every post-gate module for real and assert none of the modules that
     *newly* appeared in ``sys.modules`` belongs to a forbidden provider package.
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent

POST_GATE = [
    "compiler", "compiler2", "simulator", "gcode_scan", "materials",
    "grid", "replay", "resolver", "jobspec", "jobspec2",
    # L3 kernel client + bridge ride behind the gate too (deterministic, offline, kernel-facing):
    # the guard applies to them exactly as to the compiler/simulator surface above.
    "l3_client", "l3_bridge",
]

FORBIDDEN = ("openai", "anthropic", "transformers", "torch", "ollama", "langchain")

# word-boundared so e.g. 'tortoise' does not trip on 'torch'
_FORBIDDEN_RE = re.compile(r"\b(?:%s)\b" % "|".join(FORBIDDEN))


def _local_imports(source: str) -> list[str]:
    """Names of top-level / in-function imports in one source file."""
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def transitive_local_files(start: str) -> list[Path]:
    """The post-gate module's source plus every local (same-directory) module it
    transitively imports."""
    seen: dict[str, Path] = {}
    stack = [start]
    while stack:
        name = stack.pop()
        top = name.split(".")[0]
        if top in seen:
            continue
        f = CORE / (top + ".py")
        if not f.exists():
            continue                       # stdlib / third-party: not scanned (asserted live instead)
        seen[top] = f
        stack.extend(n for n in _local_imports(f.read_text())
                     if (CORE / (n.split(".")[0] + ".py")).exists())
    return list(seen.values())


def test_static_import_graph_is_clean():
    violations = []
    for name in POST_GATE:
        for f in transitive_local_files(name):
            if m := _FORBIDDEN_RE.search(f.read_text()):
                violations.append("%s → %s: %r" % (name, f.name, m.group(0)))
    assert not violations, "AI provider reference in post-gate code:\n" + "\n".join(violations)


def test_live_imports_do_not_load_forbidden_providers():
    before = set(sys.modules)
    for name in POST_GATE:
        importlib.import_module(name)     # importing is itself the assertion: the gate must work offline, model-free
    new = set(sys.modules) - before
    bad = [m for m in sorted(new)
           for f in FORBIDDEN if m == f or m.startswith(f + ".")]
    assert not bad, "post-gate import pulled in AI provider modules: %s" % bad

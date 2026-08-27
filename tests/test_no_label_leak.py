"""BUILD GATE — no agent/envelope/executor module may import ground truth.

AST-walks `src/agent`, `src/envelope`, and `src/executor` and fails on any
import of `src.simulator.latent`. Walking the AST (rather than just checking
what a test happens to exercise) catches dead code too — an unused import is
still evidence someone reached for the ground-truth module where they
shouldn't have.
"""

import ast
from pathlib import Path

_FORBIDDEN_MODULES = {"src.simulator.latent", "simulator.latent"}
_WATCHED_PACKAGES = ["src/agent", "src/envelope", "src/executor"]


def _imported_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_agent_envelope_or_executor_module_imports_latent_ground_truth():
    violations: list[str] = []
    for package in _WATCHED_PACKAGES:
        for path in Path(package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _imported_module_names(tree) & _FORBIDDEN_MODULES:
                violations.append(str(path))

    assert not violations, f"latent ground truth imported by: {violations}"

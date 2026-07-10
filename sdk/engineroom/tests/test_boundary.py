"""Decoupling boundary (ADR-0021): the chessroom package must not depend on any
server code. A static AST scan of every module asserts no ``engine_room`` import —
the contract is the wire protocol (PROTOCOL.md), never shared server code."""

from __future__ import annotations

import ast
import pathlib

_PKG = pathlib.Path(__file__).resolve().parent.parent / "src" / "chessroom"


def _imported_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module)
    return names


def test_no_server_imports_anywhere_in_the_package():
    offenders: dict[str, set[str]] = {}
    for py in _PKG.rglob("*.py"):
        bad = {n for n in _imported_names(py) if n.split(".")[0] == "engine_room"}
        if bad:
            offenders[py.name] = bad
    assert not offenders, f"SDK must not import server code: {offenders}"


def test_only_public_runtime_deps():
    # The SDK's third-party runtime imports are limited to its declared deps.
    allowed = {"chess", "websockets", "asyncio", "json", "os", "argparse", "random",
               "ast", "pathlib", "dataclasses", "typing", "__future__"}
    seen: set[str] = set()
    for py in _PKG.rglob("*.py"):
        for name in _imported_names(py):
            top = name.split(".")[0]
            if not top.startswith("chessroom"):
                seen.add(top)
    unexpected = seen - allowed
    assert not unexpected, f"unexpected imports: {unexpected}"

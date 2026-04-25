from __future__ import annotations

import ast
from pathlib import Path


def test_api_and_messaging_do_not_import_provider_common() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "providers" / "common").exists()
    offenders = _imports_matching(
        [repo_root / "api", repo_root / "messaging"],
        forbidden_prefixes=("providers.common",),
    )

    assert offenders == []


def test_provider_adapters_do_not_import_runtime_layers() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders = _imports_matching(
        [repo_root / "providers"],
        forbidden_prefixes=("api.", "messaging.", "cli."),
    )

    assert offenders == []


def test_architecture_doc_names_enforced_boundaries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / "PLAN.md").read_text(encoding="utf-8")

    assert "core/anthropic/" in text
    assert "api/runtime.py" in text
    assert "import-boundary" in text or "Provider adapters may depend" in text


def _imports_matching(
    roots: list[Path], *, forbidden_prefixes: tuple[str, ...]
) -> list[str]:
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            rel = path.relative_to(root.parent)
            offenders.extend(
                f"{rel}: {imported}"
                for imported in _imports_from(path)
                if imported in forbidden_prefixes
                or imported.startswith(forbidden_prefixes)
            )
    return sorted(offenders)


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports

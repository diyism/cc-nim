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


def test_removed_openrouter_rollback_transport_stays_removed() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert not (repo_root / "providers" / "open_router" / "chat_request.py").exists()
    assert _text_occurrences(repo_root, "OpenRouter" + "ChatProvider") == []
    assert _text_occurrences(repo_root, "OPENROUTER" + "_TRANSPORT") == []


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


def _text_occurrences(repo_root: Path, needle: str) -> list[str]:
    searchable_paths = [
        repo_root / "api",
        repo_root / "cli",
        repo_root / "config",
        repo_root / "core",
        repo_root / "messaging",
        repo_root / "providers",
        repo_root / "smoke",
        repo_root / "tests",
        repo_root / ".env.example",
        repo_root / "AGENTS.md",
        repo_root / "PLAN.md",
        repo_root / "README.md",
        repo_root / "pyproject.toml",
    ]
    occurrences: list[str] = []
    for root in searchable_paths:
        paths = root.rglob("*") if root.is_dir() else (root,)
        for path in paths:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if needle in text:
                occurrences.append(str(path.relative_to(repo_root)))
    return sorted(occurrences)

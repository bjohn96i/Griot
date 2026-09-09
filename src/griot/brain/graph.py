"""The vault's link graph.

Nodes are notes; edges are wikilinks resolved by basename, the way Obsidian
resolves them. Unresolved targets are kept as phantom nodes (paths[i] is None)
because a note you have linked but not yet written is part of the graph's
shape — but only after an artifact filter, since not every unresolved target
is a note anyone means to write.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".trash", ".obsidian", ".space", "node_modules"}
LINK = re.compile(r"\[\[([^\]|#\n]+)")
FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
ILLEGAL = set('\\/:*?"<>|')
EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


@dataclass(frozen=True)
class Graph:
    names: list[str]
    paths: list[str | None]
    edges: list[tuple[int, int]]
    degree: list[int]
    by_path: dict[str, int]
    adjacency: list[list[int]]
    fingerprint: str

    @property
    def n(self) -> int:
        return len(self.names)


def strip_fences(text: str) -> str:
    """Drop fenced code blocks so `[[...]]` inside them is not a link.

    An unclosed fence is treated as literal text rather than swallowing the
    rest of the file: a note in the wild has an odd fence count, and dropping
    its tail loses real links.
    """
    out: list[str] = []
    pending: list[str] | None = None
    for line in text.splitlines():
        if FENCE.match(line):
            pending = [] if pending is None else None
            continue
        (out if pending is None else pending).append(line)
    if pending is not None:
        out.extend(pending)          # never closed — keep the lines
    return "\n".join(out)


def is_artifact(target: str) -> bool:
    """True for unresolved targets that are parse noise or attachments."""
    if not target or target.isdigit():
        return True
    if any(c in ILLEGAL for c in target):
        return True
    match = EXTENSION.search(target)
    return bool(match) and match.group(0).lower() != ".md"


def _normalise(target: str) -> str:
    target = target.strip().rstrip("\\").strip()
    target = target.split("/")[-1]
    return target[:-3] if target.lower().endswith(".md") else target


def fingerprint(vault_path: Path) -> str:
    """Cheap change detector: note count, newest mtime, and a digest of the
    relative paths. The digest is what catches a rename — on macOS that leaves
    both the count and the newest mtime untouched.
    """
    root = Path(vault_path)
    names: list[str] = []
    newest = 0.0
    for path in _walk(root):
        names.append(str(path.relative_to(root)))
        newest = max(newest, path.stat().st_mtime)
    names.sort()
    digest = hashlib.sha1("\n".join(names).encode()).hexdigest()[:12]
    return f"{len(names)}:{newest:.0f}:{digest}"


def _walk(vault_path: Path):
    for path in vault_path.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def build_graph(vault_path: Path) -> Graph:
    vault_path = Path(vault_path)
    real: dict[str, Path] = {}
    for path in _walk(vault_path):
        real.setdefault(path.stem, path)

    names = list(real)
    index = {name: i for i, name in enumerate(names)}
    paths: list[str | None] = [str(real[name].resolve()) for name in names]
    pairs: set[tuple[int, int]] = set()

    for name in list(names):
        source = index[name]
        try:
            text = real[name].read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in LINK.findall(strip_fences(text)):
            target = _normalise(raw)
            if target not in index:
                if is_artifact(target):
                    continue
                index[target] = len(names)
                names.append(target)
                paths.append(None)
            other = index[target]
            if other != source:
                pairs.add((min(source, other), max(source, other)))

    edges = sorted(pairs)
    adjacency: list[list[int]] = [[] for _ in names]
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    return Graph(
        names=names,
        paths=paths,
        edges=edges,
        degree=[len(nbrs) for nbrs in adjacency],
        by_path={p: i for i, p in enumerate(paths) if p is not None},
        adjacency=adjacency,
        fingerprint=fingerprint(vault_path),
    )


def load_or_build(vault_path: Path, cache_path: Path) -> Graph:
    """Return the cached graph when the vault is unchanged, else rebuild it."""
    current = fingerprint(Path(vault_path))
    try:
        blob = json.loads(Path(cache_path).read_text())
        if blob.get("fingerprint") == current:
            return Graph(
                names=blob["names"],
                paths=blob["paths"],
                edges=[tuple(e) for e in blob["edges"]],
                degree=blob["degree"],
                by_path=blob["by_path"],
                adjacency=blob["adjacency"],
                fingerprint=current,
            )
    except (OSError, ValueError, KeyError):
        pass
    graph = build_graph(vault_path)
    cache = Path(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "fingerprint": graph.fingerprint, "names": graph.names, "paths": graph.paths,
        "edges": [list(e) for e in graph.edges], "degree": graph.degree,
        "by_path": graph.by_path, "adjacency": graph.adjacency,
    }))
    return graph

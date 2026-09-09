"""The vault's link graph.

Nodes are notes; edges are wikilinks resolved by basename, the way Obsidian
resolves them. Unresolved targets are kept as phantom nodes (paths[i] is None)
because a note you have linked but not yet written is part of the graph's
shape — but only after an artifact filter, since not every unresolved target
is a note anyone means to write.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".trash", ".obsidian", ".space", "node_modules"}
LINK = re.compile(r"\[\[([^\]|#]+)")
FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
ILLEGAL = set('\\/:*?"<>|')


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
    """Drop fenced code blocks so `[[...]]` inside them is not a link."""
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def is_artifact(target: str) -> bool:
    """True for unresolved targets that are parse noise, not intended notes."""
    if not target or target.isdigit():
        return True
    if any(c in ILLEGAL for c in target):
        return True
    suffix = Path(target).suffix
    return bool(suffix) and suffix.lower() != ".md"


def _normalise(target: str) -> str:
    target = target.strip().split("/")[-1]
    return target[:-3] if target.lower().endswith(".md") else target


def fingerprint(vault_path: Path) -> str:
    """Cheap change detector: note count plus the newest mtime."""
    count, newest = 0, 0.0
    for path in _walk(vault_path):
        count += 1
        newest = max(newest, path.stat().st_mtime)
    return f"{count}:{newest:.0f}"


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
                if target not in real and is_artifact(target):
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

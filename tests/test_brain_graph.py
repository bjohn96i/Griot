"""Vault -> graph. Phantom nodes are kept; parse artifacts are not."""
from griot.brain import graph as g


def vault(tmp_path, files: dict[str, str]):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


def test_resolved_links_become_edges(tmp_path):
    v = vault(tmp_path, {"A.md": "see [[B]]", "B.md": "see [[A]]"})
    graph = g.build_graph(v)
    assert set(graph.names) == {"A", "B"}
    a, b = graph.names.index("A"), graph.names.index("B")
    assert graph.edges == [tuple(sorted((a, b)))], "reciprocal links are one edge"


def test_unresolved_targets_become_phantom_nodes(tmp_path):
    v = vault(tmp_path, {"A.md": "see [[Not Written Yet]]"})
    graph = g.build_graph(v)
    i = graph.names.index("Not Written Yet")
    assert graph.paths[i] is None, "phantom nodes carry no file"
    assert graph.paths[graph.names.index("A")] is not None
    assert len(graph.edges) == 1


def test_orphans_are_kept(tmp_path):
    v = vault(tmp_path, {"A.md": "no links here"})
    graph = g.build_graph(v)
    assert graph.names == ["A"]
    assert graph.degree == [0]


def test_links_inside_code_fences_are_ignored(tmp_path):
    v = vault(tmp_path, {"A.md": "```\n[[not a link]]\n```\nreal [[B]]"})
    graph = g.build_graph(v)
    assert "not a link" not in graph.names
    assert "B" in graph.names


def test_artifact_targets_are_filtered(tmp_path):
    v = vault(tmp_path, {"A.md": "[[1]] [[Projects.base]] [[bad\\\\name]] [[Real Note]]"})
    graph = g.build_graph(v)
    assert "1" not in graph.names, "purely numeric"
    assert "Projects.base" not in graph.names, "non-.md extension"
    assert not any("\\\\" in n for n in graph.names), "illegal filename character"
    assert "Real Note" in graph.names


def test_md_extension_on_a_target_is_allowed(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B.md]]", "B.md": "hi"})
    graph = g.build_graph(v)
    assert graph.names.count("B") == 1, "B.md and B are the same node"


def test_hidden_and_trash_directories_are_skipped(tmp_path):
    v = vault(tmp_path, {"A.md": "x", ".trash/Old.md": "y", ".obsidian/Z.md": "z"})
    assert g.build_graph(v).names == ["A"]


def test_self_links_do_not_create_an_edge(tmp_path):
    v = vault(tmp_path, {"A.md": "[[A]]"})
    assert g.build_graph(v).edges == []


def test_adjacency_and_degree_agree_with_edges(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B]] [[C]]", "B.md": "", "C.md": ""})
    graph = g.build_graph(v)
    a = graph.names.index("A")
    assert graph.degree[a] == 2
    assert sorted(graph.adjacency[a]) == sorted(
        [graph.names.index("B"), graph.names.index("C")])


def test_by_path_maps_absolute_paths_to_indices(tmp_path):
    v = vault(tmp_path, {"A.md": ""})
    graph = g.build_graph(v)
    assert graph.by_path[str((v / "A.md").resolve())] == graph.names.index("A")


def test_cache_is_reused_until_the_vault_changes(tmp_path):
    v = vault(tmp_path, {"A.md": "[[B]]", "B.md": ""})
    cache = tmp_path / "graph.json"
    first = g.load_or_build(v, cache)
    assert cache.exists()
    again = g.load_or_build(v, cache)
    assert again.fingerprint == first.fingerprint
    assert again.names == first.names

    (v / "C.md").write_text("[[A]]")
    after = g.load_or_build(v, cache)
    assert after.fingerprint != first.fingerprint
    assert "C" in after.names

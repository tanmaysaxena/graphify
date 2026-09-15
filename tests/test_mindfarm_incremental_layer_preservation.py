"""Reproduction test for the mindfarm fork's watch._rebuild_code() patch.

Root cause 1b (PD36 in the consuming repo, prj-mindfarm): the incremental
branch (changed_paths is not None -- what both `graphify update <path>` and
the post-commit hook use) folded "file was re-extracted but still exists"
and "file was deleted" into one evict_sources set, and dropped every node
for any file in it, AST or semantic. Since this AST-only rebuild never
re-provides a file's semantic layer, that silently destroyed semantic nodes
(rationale, cross-references, etc.) for any file whose code changed, with
nothing in the same pass able to restore them.
"""
from __future__ import annotations

import json

from graphify.watch import _rebuild_code


def test_incremental_rebuild_preserves_semantic_nodes_for_a_changed_file(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    (corpus / "utils.py").write_text("def format_date(): pass\n", encoding="utf-8")

    # Establish a baseline graph via a full rebuild.
    assert _rebuild_code(corpus, acquire_lock=False) is True
    graph_path = corpus / "graphify-out" / "graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))

    # Inject a synthetic semantic node for auth.py -- simulating output from a
    # prior semantic extraction pass, which _rebuild_code (AST-only) never
    # produces itself but must not destroy either.
    semantic_node = {
        "id": "auth_rationale_1",
        "label": "Login must check rate limits",
        "source_file": "auth.py",
        "file_type": "rationale",
        # deliberately no "_origin" key -- this is what marks a semantic node
    }
    data["nodes"].append(semantic_node)
    graph_path.write_text(json.dumps(data), encoding="utf-8")

    # Change auth.py's code (still exists, still tracked) and re-run an
    # INCREMENTAL rebuild scoped to just that file -- exactly what the
    # post-commit hook and `graphify update <path>` do on an ordinary commit.
    (corpus / "auth.py").write_text(
        "def login(): pass\ndef refresh_token(): pass\n", encoding="utf-8"
    )
    assert _rebuild_code(corpus, changed_paths=[corpus / "auth.py"], acquire_lock=False) is True

    after = json.loads(graph_path.read_text(encoding="utf-8"))
    node_ids_after = {n["id"] for n in after["nodes"]}

    assert "auth_rationale_1" in node_ids_after, (
        "semantic node for the re-extracted-but-still-existing file was "
        "silently dropped by the incremental AST-only rebuild"
    )
    # And the AST layer genuinely did refresh: the new symbol is present.
    labels_after = {n.get("label") for n in after["nodes"]}
    assert "refresh_token()" in labels_after


def test_incremental_rebuild_still_evicts_semantic_nodes_for_a_deleted_file(tmp_path):
    """The fix must not become a blanket 'never evict semantic nodes' —
    a file that's genuinely gone still loses everything, deliberately."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    (corpus / "utils.py").write_text("def format_date(): pass\n", encoding="utf-8")

    assert _rebuild_code(corpus, acquire_lock=False) is True
    graph_path = corpus / "graphify-out" / "graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    data["nodes"].append({
        "id": "utils_rationale_1",
        "label": "Dates are always UTC",
        "source_file": "utils.py",
        "file_type": "rationale",
    })
    graph_path.write_text(json.dumps(data), encoding="utf-8")

    (corpus / "utils.py").unlink()
    assert _rebuild_code(corpus, acquire_lock=False) is True  # full rebuild — reconciles deletions

    after = json.loads(graph_path.read_text(encoding="utf-8"))
    node_ids_after = {n["id"] for n in after["nodes"]}
    assert "utils_rationale_1" not in node_ids_after, (
        "semantic node for a genuinely deleted file must still be evicted"
    )

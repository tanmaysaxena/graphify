"""Reproduction tests for the mindfarm fork's build_merge() patches.

Root cause 1a (PD32 in the consuming repo, prj-mindfarm): build_merge()'s
_kept() closure dropped every existing node/edge for a touched source_file
regardless of _origin, so a semantic-only update silently destroyed that
file's AST layer (and an AST-only update would silently destroy the
semantic layer, mirrored by the watch.py-side test in
test_mindfarm_incremental_layer_preservation.py).

Root cause 1c: neither of graphify's original shrink guards is unconditional
— the build_merge() one is skipped whenever dedup=True (the default), and
export.to_json()'s is skipped by force=True. This adds a third, unconditional
per-(source_file, _origin) guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphify.build import build_merge


def _write_graph(path: Path, nodes: list[dict], edges: list[dict] | None = None) -> None:
    path.write_text(json.dumps({"nodes": nodes, "links": edges or []}), encoding="utf-8")


class TestLayerPreservationOnMerge:
    def test_semantic_only_update_preserves_existing_ast_layer(self, tmp_path):
        """The exact PD32 shape: a doc file has both an AST heading node and a
        semantic node. An update that only re-provides the semantic node for
        that file must not drop the AST node."""
        graph_path = tmp_path / "graph.json"
        _write_graph(
            graph_path,
            nodes=[
                {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
                {"id": "readme_rationale_1", "label": "Why this exists", "source_file": "README.md",
                 "file_type": "rationale"},  # no _origin -- semantic node
                {"id": "unrelated", "label": "Unrelated", "source_file": "other.md",
                 "file_type": "document", "_origin": "ast"},
            ],
        )
        new_chunks = [{
            "nodes": [
                {"id": "readme_rationale_1", "label": "Why this exists (updated)",
                 "source_file": "README.md", "file_type": "rationale"},
            ],
            "edges": [],
        }]

        G = build_merge(new_chunks, graph_path=graph_path, dedup=False)

        assert "doc_readme" in G.nodes, "AST node for the touched file was dropped by a semantic-only update"
        assert G.nodes["doc_readme"].get("_origin") == "ast"
        assert "readme_rationale_1" in G.nodes
        assert G.nodes["readme_rationale_1"]["label"] == "Why this exists (updated)"
        assert "unrelated" in G.nodes

    def test_ast_only_update_preserves_existing_semantic_layer(self, tmp_path):
        """Mirror image: an AST-only re-extraction (no _origin key absent --
        new nodes ARE _origin=='ast') must not drop the file's semantic nodes."""
        graph_path = tmp_path / "graph.json"
        _write_graph(
            graph_path,
            nodes=[
                {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
                {"id": "readme_rationale_1", "label": "Why this exists", "source_file": "README.md",
                 "file_type": "rationale"},
            ],
        )
        new_chunks = [{
            "nodes": [
                {"id": "doc_readme", "label": "README.md (re-extracted)", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
            ],
            "edges": [],
        }]

        G = build_merge(new_chunks, graph_path=graph_path, dedup=False)

        assert "readme_rationale_1" in G.nodes, "semantic node for the touched file was dropped by an AST-only update"
        assert "doc_readme" in G.nodes
        assert G.nodes["doc_readme"]["label"] == "README.md (re-extracted)"

    def test_edges_between_preserved_same_layer_nodes_survive(self, tmp_path):
        """An edge connecting two preserved semantic nodes (same layer, file
        untouched by this update's own layer) survives the merge."""
        graph_path = tmp_path / "graph.json"
        _write_graph(
            graph_path,
            nodes=[
                {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
                {"id": "rationale_a", "label": "A", "source_file": "README.md", "file_type": "rationale"},
                {"id": "rationale_b", "label": "B", "source_file": "README.md", "file_type": "rationale"},
            ],
            edges=[
                {"source": "rationale_a", "target": "rationale_b", "relation": "relates_to",
                 "source_file": "README.md"},
            ],
        )
        new_chunks = [{
            "nodes": [
                {"id": "doc_readme", "label": "README.md (re-extracted)", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
            ],
            "edges": [],
        }]

        G = build_merge(new_chunks, graph_path=graph_path, dedup=False)
        assert G.has_edge("rationale_a", "rationale_b"), "edge between two preserved semantic nodes was dropped"

    def test_genuinely_deleted_file_still_evicted(self, tmp_path):
        """A file that's actually gone (its own layer wiped by design via
        prune_sources) is still fully removed -- the new guard must not block
        a legitimate deletion."""
        graph_path = tmp_path / "graph.json"
        _write_graph(
            graph_path,
            nodes=[
                {"id": "doc_old", "label": "old.md", "source_file": "old.md",
                 "file_type": "document", "_origin": "ast"},
                {"id": "old_rationale", "label": "old rationale", "source_file": "old.md",
                 "file_type": "rationale"},
            ],
        )
        G = build_merge([], graph_path=graph_path, prune_sources=["old.md"], dedup=False)
        assert "doc_old" not in G.nodes
        assert "old_rationale" not in G.nodes


class TestUnconditionalShrinkGuard:
    def test_shrink_guard_fires_on_partial_layer_loss_for_a_surviving_file(self, tmp_path):
        """The guard's actual purpose: a file that's still present in the new
        set (so it's NOT a legitimate full removal) but has lost one whole
        (source_file, _origin) layer -- proving the guard is a real,
        independent safety net distinct from 1a's node-level _kept() fix,
        exactly as graphify's own two ORIGINAL guards (whole-graph-total only,
        and skippable via dedup=True / force=True) would miss this."""
        from graphify import build as build_mod

        existing = [
            {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
             "file_type": "document", "_origin": "ast"},
            {"id": "readme_rationale", "label": "Why", "source_file": "README.md",
             "file_type": "rationale"},
        ]
        # README.md is still present in the new set (via its semantic node),
        # so this is NOT a legitimate full-file removal -- but its AST layer
        # is gone. A whole-graph node-count guard could easily miss this if
        # enough unrelated nodes were added elsewhere to offset the loss.
        new_graph_nodes = [
            {"id": "readme_rationale", "label": "Why", "source_file": "README.md",
             "file_type": "rationale"},
            {"id": "unrelated_new_1", "label": "x", "source_file": "new.md",
             "file_type": "document", "_origin": "ast"},
            {"id": "unrelated_new_2", "label": "y", "source_file": "new.md",
             "file_type": "rationale"},
        ]
        with pytest.raises(ValueError, match="silently drop"):
            build_mod._check_per_file_layer_shrink(existing, new_graph_nodes, context="(test)")

    def test_shrink_guard_allows_legitimate_full_file_removal(self, tmp_path):
        from graphify import build as build_mod
        existing = [
            {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
             "file_type": "document", "_origin": "ast"},
        ]
        # File is entirely gone from the new set -- legitimate, no exception.
        build_mod._check_per_file_layer_shrink(existing, [], context="(test)")

    def test_shrink_guard_allows_unrelated_growth(self, tmp_path):
        from graphify import build as build_mod
        existing = [
            {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
             "file_type": "document", "_origin": "ast"},
        ]
        new_graph_nodes = existing + [
            {"id": "doc_new", "label": "new.md", "source_file": "new.md",
             "file_type": "document", "_origin": "ast"},
        ]
        build_mod._check_per_file_layer_shrink(existing, new_graph_nodes, context="(test)")


class TestIdDisambiguationAcrossMerges:
    def test_two_files_with_same_anchor_id_disambiguated_on_merge(self, tmp_path):
        """Root cause 2 (PD37): a bare file-anchor id collision across two
        genuinely different files (this repo's cross-skill duplication shape)
        must be disambiguated even when the two files were extracted in
        SEPARATE extract() calls merged together here -- not just when a
        single extract() call sees both."""
        from graphify.build import build

        # Two AST-origin file anchors from different files, same bare id
        # (both would compute "config" via _file_node_id — same stem, one
        # parent-dir level, in different directories).
        extraction_a = {
            "nodes": [
                {"id": "config", "label": "config.py", "source_file": "pkg_a/config.py",
                 "file_type": "code", "_origin": "ast"},
            ],
            "edges": [],
        }
        extraction_b = {
            "nodes": [
                {"id": "config", "label": "config.py", "source_file": "pkg_b/config.py",
                 "file_type": "code", "_origin": "ast"},
            ],
            "edges": [],
        }
        G = build([extraction_a, extraction_b], dedup=False, root=str(tmp_path))
        node_ids = set(G.nodes)
        assert len(node_ids) == 2, f"expected 2 distinguishable nodes after disambiguation, got {node_ids}"
        assert "config" not in node_ids or len(node_ids) == 2  # at most one keeps the bare id

    def test_semantic_cross_reference_to_file_anchor_not_disturbed(self, tmp_path):
        """The legitimate case this patch must NOT touch: a semantic node
        intentionally sharing a file's own canonical anchor id as a
        cross-reference (graphify's own documented convention). Only
        _origin=='ast' nodes are disambiguated, so this must survive
        untouched."""
        from graphify.build import build

        extraction = {
            "nodes": [
                {"id": "readme", "label": "README.md", "source_file": "README.md",
                 "file_type": "document", "_origin": "ast"},
                # A semantic node from a DIFFERENT file, intentionally reusing
                # README's own canonical id as a cross-reference.
                {"id": "readme", "label": "See README", "source_file": "docs/other.md",
                 "file_type": "concept"},
            ],
            "edges": [],
        }
        G = build([extraction], dedup=False, root=str(tmp_path))
        assert "readme" in G.nodes, "legitimate cross-reference id was disturbed by the disambiguation patch"

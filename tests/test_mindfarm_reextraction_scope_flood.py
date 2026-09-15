"""Reproduction tests for the mindfarm fork's reextraction-scope-flood guard.

Root cause "root-drift-floods-scope" (PD41/PD48 in the consuming repo,
prj-mindfarm): a stale or root-mismatched manifest.json made
detect_incremental() fall into its "unknown format, re-extract to be safe"
fallback for nearly the whole corpus (213 of ~230 files, when only a
handful had actually changed). That flood fed build_merge()'s default
dedup=True corpus-wide fuzzy-dedup pass, which silently collapsed 78
unrelated nodes as false-positive duplicates. Neither of graphify's own
shrink guards is a safety net for this: the inline one is unconditionally
skipped whenever dedup=True (the exact path that ran), and
_check_per_file_layer_shrink (root cause 1c, see
test_mindfarm_layer_preservation.py) only catches a file's layer dropping
to *zero*, not a partial loss where some of a file's nodes survive while
others are silently merged away.

The consuming repo's own scripts/check_dedup_scope_safety.py already
guards this shape, but only as a manual, operator-scoped, mid-session gate
(it needs an explicit --scope and ephemeral before/after snapshots — see
that script's own docstring for why it can't be a CI check). This guard is
the automatic, no-manual-step counterpart: it fires on the flood ratio
itself, before dedup ever runs, with no operator action required — and an
explicit `allow_reextraction_flood=True` escape hatch for the rare
genuinely-intended full-corpus case, mirroring that script's own
explicit-scope-widening principle rather than a silent bypass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphify.build import build_merge


def _write_graph(path: Path, nodes: list[dict], edges: list[dict] | None = None) -> None:
    path.write_text(json.dumps({"nodes": nodes, "links": edges or []}), encoding="utf-8")


def _corpus(n: int) -> list[dict]:
    """n existing files, one AST node each — comfortably above
    min_existing_files (20) so the ratio check is meaningful."""
    return [
        {"id": f"doc_{i}", "label": f"file_{i}.md", "source_file": f"file_{i}.md",
         "file_type": "document", "_origin": "ast"}
        for i in range(n)
    ]


def _reextract(indices: range) -> list[dict]:
    return [{
        "nodes": [
            {"id": f"doc_{i}", "label": f"file_{i}.md (re-extracted)",
             "source_file": f"file_{i}.md", "file_type": "document", "_origin": "ast"}
            for i in indices
        ],
        "edges": [],
    }]


class TestReextractionScopeFlood:
    def test_flood_with_dedup_refuses_to_merge(self, tmp_path):
        """The exact PD41 shape: a large fraction of the existing corpus
        shows up in one merge call's new_chunks, with dedup enabled."""
        graph_path = tmp_path / "graph.json"
        _write_graph(graph_path, _corpus(24))
        new_chunks = _reextract(range(13))  # 13/24 = 54% >= 50% threshold

        with pytest.raises(ValueError, match="reextraction|refusing to proceed"):
            build_merge(new_chunks, graph_path=graph_path, dedup=True)

    def test_flood_with_explicit_allow_flag_proceeds(self, tmp_path):
        """The escape hatch: an operator who really means a full-corpus
        re-extraction can say so explicitly."""
        graph_path = tmp_path / "graph.json"
        _write_graph(graph_path, _corpus(24))
        new_chunks = _reextract(range(13))

        G = build_merge(
            new_chunks, graph_path=graph_path, dedup=True,
            allow_reextraction_flood=True,
        )
        assert "doc_0" in G.nodes
        assert G.nodes["doc_0"]["label"] == "file_0.md (re-extracted)"

    def test_narrow_update_below_threshold_not_flagged(self, tmp_path):
        """A normal incremental update — a couple of files out of a large
        corpus — must not be affected by this guard at all."""
        graph_path = tmp_path / "graph.json"
        _write_graph(graph_path, _corpus(24))
        new_chunks = _reextract(range(2))  # 2/24 ≈ 8%, well below threshold

        G = build_merge(new_chunks, graph_path=graph_path, dedup=True)
        assert "doc_0" in G.nodes

    def test_small_corpus_below_minimum_not_flagged(self, tmp_path):
        """A small repo where every file legitimately gets touched in one
        pass (first run, small backfill) shouldn't trip a ratio-based guard
        meant for large-corpus flood detection."""
        graph_path = tmp_path / "graph.json"
        _write_graph(graph_path, _corpus(5))
        new_chunks = _reextract(range(5))  # 100%, but corpus is tiny

        G = build_merge(new_chunks, graph_path=graph_path, dedup=True)
        assert "doc_0" in G.nodes

    def test_flood_without_dedup_not_flagged(self, tmp_path):
        """The guard is specifically about protecting the corpus-wide fuzzy
        dedup pass from running over a flooded scope — with dedup disabled
        there's no false-positive-collapse risk for this guard to prevent."""
        graph_path = tmp_path / "graph.json"
        _write_graph(graph_path, _corpus(24))
        new_chunks = _reextract(range(13))

        G = build_merge(new_chunks, graph_path=graph_path, dedup=False)
        assert "doc_0" in G.nodes

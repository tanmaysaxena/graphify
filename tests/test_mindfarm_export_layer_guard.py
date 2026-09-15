"""Reproduction test for the mindfarm fork's export.to_json() patch.

Root cause 1c (PD32/PD36/PD41 in the consuming repo, prj-mindfarm):
export.to_json()'s original whole-graph shrink guard is skippable via
force=True, a flag callers legitimately pass after a refactor that deletes
real code -- but that same force=True also silently waived protection
against an UNRELATED file's layer disappearing in the same write. This adds
a second, unconditional per-(source_file, _origin) guard.
"""
from __future__ import annotations

import json

import networkx as nx
import pytest

from graphify.export import to_json


def _graph_from_nodes(nodes: list[dict]) -> nx.Graph:
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
    return G


class TestExportPerLayerGuard:
    def test_force_true_no_longer_bypasses_per_layer_guard(self, tmp_path):
        output_path = tmp_path / "graph.json"
        existing_nodes = [
            {"id": "doc_readme", "label": "README.md", "source_file": "README.md",
             "file_type": "document", "_origin": "ast"},
            {"id": "readme_rationale", "label": "Why", "source_file": "README.md",
             "file_type": "rationale"},
        ]
        output_path.write_text(json.dumps({"nodes": existing_nodes, "links": []}), encoding="utf-8")

        # New graph: README.md is still present (via its semantic node,
        # `readme_rationale`) so this is not a legitimate full-file removal,
        # but its AST layer is gone. Overall node count is unchanged (one
        # unrelated node added to offset the one lost) -- exactly the shape
        # the ORIGINAL whole-graph guard (bypassed by force=True anyway)
        # would miss even without force.
        new_nodes = [
            {"id": "readme_rationale", "label": "Why", "source_file": "README.md",
             "file_type": "rationale"},
            {"id": "doc_new", "label": "new.md", "source_file": "new.md",
             "file_type": "document", "_origin": "ast"},
        ]
        G = _graph_from_nodes(new_nodes)

        with pytest.raises(ValueError, match="silently drop"):
            to_json(G, communities={}, output_path=str(output_path), force=True)

        # And the file on disk must be untouched -- refusing means refusing,
        # not writing a partially-corrupted graph before raising.
        on_disk = json.loads(output_path.read_text(encoding="utf-8"))
        assert on_disk["nodes"] == existing_nodes

    def test_legitimate_full_file_removal_still_allowed_under_force(self, tmp_path):
        output_path = tmp_path / "graph.json"
        existing_nodes = [
            {"id": "doc_old", "label": "old.md", "source_file": "old.md",
             "file_type": "document", "_origin": "ast"},
        ]
        output_path.write_text(json.dumps({"nodes": existing_nodes, "links": []}), encoding="utf-8")

        # old.md genuinely deleted -- absent entirely from the new graph.
        new_nodes = [
            {"id": "doc_new", "label": "new.md", "source_file": "new.md",
             "file_type": "document", "_origin": "ast"},
        ]
        G = _graph_from_nodes(new_nodes)
        assert to_json(G, communities={}, output_path=str(output_path), force=True) is True

    def test_no_existing_file_writes_normally(self, tmp_path):
        output_path = tmp_path / "graph.json"
        G = _graph_from_nodes([
            {"id": "doc_new", "label": "new.md", "source_file": "new.md",
             "file_type": "document", "_origin": "ast"},
        ])
        assert to_json(G, communities={}, output_path=str(output_path)) is True

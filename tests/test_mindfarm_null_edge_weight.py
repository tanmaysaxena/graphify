"""mindfarm fork: an edge with "weight": null must not crash clustering.

An LLM-extracted semantic cache entry carried four `references` edges with
"weight": null; once merged, every rebuild failed inside Louvain with
`unsupported operand type(s) for +: 'int' and 'NoneType'`.
"""
from graphify.build import build_from_json
from graphify.cluster import cluster


def _extraction(weight):
    nodes = [{"id": n, "label": n, "file_type": "document", "source_file": "doc.md"} for n in "abc"]
    edges = [
        {"source": "a", "target": "b", "relation": "references", "confidence": "EXTRACTED",
         "source_file": "doc.md", "weight": weight},
        {"source": "b", "target": "c", "relation": "references", "confidence": "EXTRACTED",
         "source_file": "doc.md", "weight": 1.0},
    ]
    return {"nodes": nodes, "edges": edges}


def test_null_weight_defaults_to_one_and_clusters():
    G = build_from_json(_extraction(None))
    assert G.edges["a", "b"]["weight"] == 1.0
    assert cluster(G)  # previously raised TypeError


def test_non_numeric_weight_defaults_to_one():
    G = build_from_json(_extraction("high"))
    assert G.edges["a", "b"]["weight"] == 1.0


def test_numeric_weight_is_kept():
    G = build_from_json(_extraction(0.5))
    assert G.edges["a", "b"]["weight"] == 0.5

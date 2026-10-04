"""The agent diagram is generated from the built graph, and can't drift from it (SPEC-delivery,
"Diagrams"; T44)."""

import pytest

from backend.agents.graph import NODES
from scripts import gen_agent_diagram
from scripts.gen_agent_diagram import EDGES, OUTPUT, render


def test_the_committed_diagram_matches_the_graph() -> None:
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "docs/diagrams/agent-flow.md is out of date: uv run python -m scripts.gen_agent_diagram"
    )


def test_every_node_is_in_the_diagram_with_its_kind() -> None:
    text = render()

    for name in NODES:
        assert f"    {name}" in text
    assert "triage<br/>jev" in text
    assert "draft<br/>llm" in text
    assert "identify_fee<br/>rule + jev" in text


def test_a_new_node_without_a_description_stops_the_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gen_agent_diagram, "NODES", {**NODES, "audit": NODES["finalize"]})

    with pytest.raises(SystemExit, match="audit"):
        render()


def test_a_conditional_edge_without_a_label_stops_the_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    labels = dict(EDGES)
    del labels[("triage", "finalize")]
    monkeypatch.setattr(gen_agent_diagram, "EDGES", labels)

    with pytest.raises(SystemExit, match="triage -> finalize"):
        render()

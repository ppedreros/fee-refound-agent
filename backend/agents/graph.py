"""The agent flow as a LangGraph StateGraph (D6; SPEC-agent, "Flow").

Triage first, then the three reads in parallel, joined at identify_fee. The graph only reads and
ends at finalize: the refund is `POST /cases/{id}/decision`, which the graph cannot reach.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents import nodes
from backend.agents.deps import AgentDeps
from backend.agents.state import GraphState
from backend.agents.steps import NodeFn, as_node

NODES: dict[str, NodeFn] = {
    "load_conversation": nodes.load_conversation,
    "triage": nodes.triage,
    "load_accounts": nodes.load_accounts,
    "load_transactions": nodes.load_transactions,
    "load_refund_history": nodes.load_refund_history,
    "identify_fee": nodes.identify_fee,
    "run_checks": nodes.run_checks,
    "decide": nodes.decide_case,
    "find_policy": nodes.find_policy,
    "draft": nodes.draft,
    "finalize": nodes.finalize,
}


def build_graph() -> Any:
    graph = StateGraph(GraphState, context_schema=AgentDeps)
    for name, node in NODES.items():
        graph.add_node(name, as_node(name, node))

    graph.add_edge(START, "load_conversation")
    graph.add_conditional_edges(
        "load_conversation", nodes.after_load_conversation, ["triage", "finalize"]
    )
    graph.add_conditional_edges("triage", nodes.after_triage, [*nodes.READS, "finalize"])
    graph.add_edge(nodes.READS, "identify_fee")
    graph.add_conditional_edges(
        "identify_fee", nodes.after_identify_fee, ["run_checks", "finalize"]
    )
    graph.add_edge("run_checks", "decide")
    graph.add_edge("decide", "find_policy")
    graph.add_conditional_edges("find_policy", nodes.after_find_policy, ["draft", "finalize"])
    graph.add_edge("draft", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()

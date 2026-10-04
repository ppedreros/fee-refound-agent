"""Writes `docs/diagrams/agent-flow.md` from the code (SPEC-delivery, "Diagrams"):

    uv run python -m scripts.gen_agent_diagram          # write the file
    uv run python -m scripts.gen_agent_diagram --check  # exit 1 if the file is out of date

The edges come from the compiled graph, the prompt versions from the nodes, and the timeouts and
retries from `backend/core/config/`. What a node is and does is described here, once per node: a
node without a description, or a description without a node, stops the script. A test runs the
check, so the diagram and the code can't drift.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.agents import nodes
from backend.agents.graph import NODES, build_graph
from backend.agents.runner import FALLBACK_RESERVE_S, RUN_TIMEOUT_S
from backend.providers.config import CallPolicy, providers_config
from backend.tools.queries import TOOL_RETRIES, TOOL_TIMEOUT_S

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "diagrams" / "agent-flow.md"
PROMPTS = "../../backend/agents/prompts"  # from docs/diagrams/

KINDS = {
    "tool": "Tool: reads the database as agent_reader",
    "jev": "Jev: a typed classification",
    "llm": "LLM: Sol writes text",
    "rule": "Rule: deterministic code",
}


@dataclass(frozen=True)
class Node:
    kind: str
    does: str
    tools: str = ""
    prompt: str = ""  # a prompt version; its file is linked
    fails: str = ""
    also: str = ""  # another kind the node calls on, shown in its box ("rule + jev")


def describe() -> dict[str, Node]:
    reads = "`data_timeout`: Luis decides, with what was read"
    return {
        "load_conversation": Node(
            "tool",
            "Reads the conversation since the last staff reply, sanitises and masks it",
            "get_conversation, get_member_profile, list_account_numbers, get_last_known_language",
            fails=reads,
        ),
        "triage": Node(
            "jev",
            "Intent, language, tone, manipulation and multiple requests, in one call",
            prompt=nodes.TRIAGE_PROMPT,
            fails="Luna answers instead (a note); if Luna fails too, `classifier_down`, and the "
            "message is treated as a possible fee request",
        ),
        "load_accounts": Node(
            "tool", "Sub-accounts, balances and standing", "list_member_accounts", fails=reads
        ),
        "load_transactions": Node(
            "tool",
            f"The last {nodes.TRANSACTIONS_LOOKBACK_DAYS} days, in posting order",
            "list_transactions",
            fails=reads,
        ),
        "load_refund_history": Node(
            "tool",
            f"Fee refunds of the last {nodes.REFUNDS_LOOKBACK_DAYS} days, the core's and ours",
            "list_fee_refunds, list_our_refunds",
            fails=reads,
        ),
        "identify_fee": Node(
            "rule",
            "The fee the message is about: the only one, the one Luis picked, or Jev's choice "
            "between two",
            prompt=nodes.FEE_PROMPT,
            also="jev",
            fails="`fee_ambiguous`: Luis picks the fee and the case is checked again; no fee "
            "is `fee_not_found`",
        ),
        "run_checks": Node(
            "rule",
            "The policy rules: same-day deposit, yearly limit, standing, already refunded, "
            "balances that add up",
        ),
        "decide": Node(
            "rule", "Refund or not, the amount, and whether the case is clear (shadow mode)"
        ),
        "find_policy": Node(
            "tool",
            "Full-text search for the clauses, then Jev confirms the one behind the decision",
            "search_clauses",
            prompt=nodes.CLAUSE_PROMPT,
            also="jev",
            fails="The deciding rule's own clause is quoted (never changes the outcome)",
        ),
        "draft": Node(
            "llm",
            "The reply, from the facts only (never the member's text), then a deterministic "
            "post-check",
            prompt=nodes.DRAFT_PROMPT,
            fails=f"Asked again once ({nodes.DRAFT_TRIES} tries); then the template and "
            "`drafter_down`",
        ),
        "finalize": Node("rule", "The status Luis sees, with every reason, and the result"),
    }


# Labels for the graph's conditional edges: (from, to) -> the condition.
EDGES = {
    ("load_conversation", "triage"): "a member message",
    ("load_conversation", "finalize"): "no message",
    ("triage", "load_accounts"): "about a fee",
    ("triage", "load_transactions"): "about a fee",
    ("triage", "load_refund_history"): "about a fee",
    ("triage", "finalize"): "not about a fee",
    ("identify_fee", "run_checks"): "a fee",
    ("identify_fee", "finalize"): "none, or two",
    ("find_policy", "draft"): "a reply to send",
    ("find_policy", "finalize"): "no reply: no outcome, over the limit, another topic",
}

SHAPES = {
    "tool": '[("{text}")]',
    "jev": '{{{{"{text}"}}}}',
    "llm": '(["{text}"])',
    "rule": '["{text}"]',
}


def render() -> str:
    described = describe()
    if set(described) != set(NODES):
        raise SystemExit(
            f"Describe exactly the graph's nodes: {sorted(set(NODES) ^ set(described))}"
        )
    graph = build_graph().get_graph()
    lines = ["flowchart TD", '    __start__(["Start"])', '    __end__(["Luis decides"])']
    for name, node in described.items():
        kind = f"{node.kind} + {node.also}" if node.also else node.kind
        label = f"{name}<br/>{kind}"
        lines.append(f"    {name}{SHAPES[node.kind].format(text=label)}:::{node.kind}")
    for edge in sorted(
        graph.edges,
        key=lambda e: (list(NODES).index(e.source) if e.source in NODES else -1, e.target),
    ):
        if edge.conditional:
            condition = EDGES.get((edge.source, edge.target))
            if condition is None:
                raise SystemExit(f"Label the conditional edge {edge.source} -> {edge.target}")
            lines.append(f'    {edge.source} -. "{condition}" .-> {edge.target}')
        else:
            lines.append(f"    {edge.source} --> {edge.target}")
    lines += [
        "    classDef tool fill:#EFEEED,stroke:#5f5b56,color:#001D3D",
        "    classDef jev fill:#FFFFFF,stroke:#DC634B,stroke-width:2px,color:#001D3D",
        "    classDef llm fill:#FFFFFF,stroke:#001D3D,stroke-width:2px,color:#001D3D",
        "    classDef rule fill:#001D3D,stroke:#001D3D,color:#FFFFFF",
    ]
    unused = set(EDGES) - {(e.source, e.target) for e in graph.edges}
    if unused:
        raise SystemExit(f"These labelled edges are not in the graph: {sorted(unused)}")

    config = providers_config()
    rows = []
    for name, node in described.items():
        prompt = _prompt_link(node.prompt) if node.prompt else "—"
        kind = f"{node.kind} + {node.also}" if node.also else node.kind
        rows.append(
            f"| `{name}` | {kind} | {node.does} | {prompt} | {node.tools or '—'} "
            f"| {node.fails or '—'} |"
        )
    return "\n".join(
        [
            "# Agent flow",
            "",
            "<!-- Generated by `uv run python -m scripts.gen_agent_diagram` from the built graph,",
            "the nodes' prompt versions and backend/core/config/. Edit the script, not this file:",
            "a test fails when the two disagree. -->",
            "",
            "Sequential, with one parallel fan-out (the three reads, joined at `identify_fee`).",
            "Every path ends at `finalize`, and then with Luis: the graph only reads, and the",
            "refund is his `POST /cases/{id}/decision`, which the graph can't reach.",
            "",
            "```mermaid",
            *lines,
            "```",
            "",
            "Shapes: " + " · ".join(f"**{kind}**: {text}" for kind, text in KINDS.items()) + ".",
            "Dotted edges are conditions.",
            "",
            "## Nodes",
            "",
            "| Node | Kind | What it does | Prompt | Tool calls | When it fails |",
            "|---|---|---|---|---|---|",
            *rows,
            "",
            "## Prompts",
            "",
            f"- {_prompt_link(nodes.TRIAGE_PROMPT)}: one Jev request with five typed questions "
            "about the masked message.",
            f"- {_prompt_link(nodes.FEE_PROMPT)}: which of two fees the message means; the "
            "options are the fees, each named by the payment before it.",
            f"- {_prompt_link(nodes.CLAUSE_PROMPT)}: which searched clause is the rule behind "
            "the decision, given the case facts.",
            f"- {_prompt_link(nodes.DRAFT_PROMPT)}: Sol's system prompt for the reply; it gets "
            "the outcome and facts, never the member's text.",
            "",
            "## Fallback chains",
            "",
            f"- **Jev** ({config.jev.model}): {_policy(config.jev.policy)}. Triage then goes to "
            f"**Luna** ({config.luna.model}): {_policy(config.luna.policy)}. If both fail: "
            "`classifier_down`. The fee and clause choices use Jev alone: a choice needs its "
            "calibrated confidence.",
            f"- **Sol** ({config.sol.model}): {_policy(config.sol.policy)}, then the template "
            "and `drafter_down`.",
            f"- **Reads**: {TOOL_TIMEOUT_S:g} s each, {TOOL_RETRIES} retry, then `data_timeout`.",
            f"- **The run**: {RUN_TIMEOUT_S:g} s in all. Every model call ends "
            f"{FALLBACK_RESERVE_S:g} s before that, so its fallback still fits.",
            "",
            "## Handoffs to Luis",
            "",
            "- **Every case.** The flow prepares and recommends; Luis approves, edits, rejects or "
            "replies only. Auto-approve exists in shadow mode only (off).",
            "- **Needs your call.** Any doubt or failure: unclear intent, a fee question, two "
            "possible fees (he picks one, and the case is checked again with it), no fee, "
            "manipulation, more than one request, an unsupported language, a classifier, read "
            "or drafter failure, or balances that don't add up.",
            "- **Needs supervisor approval.** A refund above his limit: no reply is drafted.",
            "- **Not about a fee.** The early exit after triage: he answers it himself.",
            "",
        ]
    )


def _prompt_link(version: str) -> str:
    suffix = ".md" if version.startswith("draft") else ".yaml"
    return f"[`{version}`]({PROMPTS}/{version}{suffix})"


def _policy(policy: CallPolicy) -> str:
    return (
        f"{policy.timeout_s:g} s, {policy.retries} retries with backoff "
        f"{policy.backoff_base_s:g} to {policy.backoff_cap_s:g} s"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m scripts.gen_agent_diagram")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            sys.exit(f"{OUTPUT.relative_to(ROOT)} is out of date: run scripts.gen_agent_diagram")
        print("The agent diagram matches the graph.")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

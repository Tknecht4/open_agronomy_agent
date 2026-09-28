"""Question-owned METHOD tasks must not inherit incidental topic words."""

from __future__ import annotations

import pytest

from agronomy_agent.decision_contract import build_decision_contract, obligation_coverage
from agronomy_agent.method_context import method_fit_reason, method_task_frame, requested_methods
from agronomy_agent.router import classify_query
from agronomy_agent.agent import load_agent_resources


@pytest.mark.parametrize(("question", "expected"), [
    ("Please do not omit a cash plan for October receipts and November loan bills.", {"cash_flow"}),
    ("Why does a memo titled 'no partial budget' use that phrase? Give its filing year.", set()),
    ("For a Maine farm, compare a partial budget and crop enterprise budget in one explanation.", {"partial_budget", "enterprise_budget"}),
    ("The bulletin lists GDD; can you locate its DOI?", set()),
    ("Prepare a monthly cash schedule; the crop enterprise budget was last year's attachment.", {"cash_flow"}),
    ("From dated current assets and liabilities, assess liquidity.", {"liquidity"}),
    ("When do loan bills fall due before grain sale?", set()),
    ("Set the right seed rate for my field.", set()),
    ("How is the seeding rate calculated from germination and target stand?", {"seed_mass"}),
    ("Use manure analyses to plan inputs, but do not choose a fertilizer application rate.", {"nutrient_plan_inputs"}),
    ("Don't skip the partial budget when comparing a machine switch.", {"partial_budget"}),
    ("Describe soil texture; the sample label reads 'cash flow'.", set()),
    ("Can this business afford debt?", set()),
    ("Explain a cash schedule and current ratio separately.", {"cash_flow", "liquidity"}),
    ("No cash plan please, only compute working capital.", {"liquidity"}),
    ("Explain liquidity, not cash flow.", {"liquidity"}),
    ("Do not omit a cash plan and do not calculate growing degree days.", {"cash_flow"}),
    ("What is the address of the cash-flow workshop?", set()),
    ("Which publisher printed the enterprise-budget handbook?", set()),
    ("Explain cash flow with no numbers.", {"cash_flow"}),
    ("Avoid mentioning liquidity and explain cash flow.", {"cash_flow"}),
    ("Ignore the cash plan and explain working capital.", {"liquidity"}),
    ("Explain why cash flow is not liquidity.", {"cash_flow", "liquidity"}),
    ("Explain why liquidity does not imply cash flow.", {"cash_flow", "liquidity"}),
])
def test_method_tasks_require_an_operation_in_scope(question: str, expected: set[str]) -> None:
    assert set(requested_methods(question)) == expected
    for task in method_task_frame(question):
        assert question[task.span[0]:task.span[1]] == task.text
        assert task.disposition in {"requested", "background", "negated", "unresolved"}


def test_frame_retains_background_negation_and_unresolved_spans() -> None:
    question = "The guide mentions cash flow. Do not draft a cash plan; can you help with a farm budget?"
    tasks = method_task_frame(question)
    assert [(task.method_id, task.disposition) for task in tasks] == [
        ("cash_flow", "background"), ("cash_flow", "negated")
    ]
    assert requested_methods(question) == ()
    vague = method_task_frame("What is the right seed rate for this field?")
    assert [(task.method_id, task.disposition) for task in vague] == [("seed_mass", "unresolved")]
    quoted = method_task_frame("Who published 'no partial budget'?")
    assert [(task.method_id, task.disposition, task.text) for task in quoted] == [
        ("partial_budget", "background", "partial budget")
    ]


def test_method_obligation_and_card_fit_use_the_same_requested_projection() -> None:
    resources = load_agent_resources("configs/rag_production_foundations_method_candidate.yaml")
    docs = {}
    for method_id in ("enterprise_budget", "cash_flow", "liquidity"):
        docs[f"method_{method_id}"] = next(
            doc for doc in resources.retriever.search(method_id.replace("_", " "), top_k=20)
            if doc.doc_id == f"method_{method_id}"
        )
    for question, expected in (
        ("For our Alberta operation, compare a crop enterprise budget with a monthly cash schedule.", {"enterprise_budget", "cash_flow"}),
        ("For our Alberta operation, the enterprise budget is attached. Prepare a monthly cash schedule.", {"cash_flow"}),
        ("For our Alberta operation, no cash plan please; assess the current ratio.", {"liquidity"}),
    ):
        contract = build_decision_contract(question, classify_query(question), method_context_enabled=True)
        obligations = {row.key.removeprefix("method:") for row in contract.evidence_obligations if row.key.startswith("method:")}
        matched = {method_id for method_id in ("enterprise_budget", "cash_flow", "liquidity")
                   if method_fit_reason(docs[f"method_{method_id}"], question, "canada") == "method_context_match"}
        assert obligations == matched == expected
        for method_id in matched:
            assert f"method:{method_id}" in obligation_coverage(docs[f"method_{method_id}"], contract)

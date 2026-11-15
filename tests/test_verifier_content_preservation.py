"""Keep useful requested content while editing concrete unsupported claims."""
import pytest

from agronomy_agent.answer_verifier import assess_claim_risk, verify_answer


ROOT_QUESTION = "My corn roots are swollen. What should I inspect today?"
ROOT_METHOD = (
    "Dig plants with their roots intact and compare affected plants with nearby healthy plants. "
    "Look for the shape and attachment of swellings, lesions, rot, or discoloration. "
    "Record crop stage and the field pattern. The cause remains uncertain; ask a diagnostic lab "
    "how to package representative roots if inspection does not resolve it."
)


class Editor:
    def __init__(self, answer=None):
        self.answer = answer
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        assert self.answer is not None, "Correct complete methods should not need an editor"
        return self.answer


@pytest.mark.parametrize("issuance", [
    "Report issued: 2030-06-21.",
    "The laboratory report was issued on 2030-06-21.",
    "The report has been issued on 2030-06-21.",
])
def test_supplied_date_roles_survive_equivalent_report_event_prose(issuance):
    question = (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report "
        "issued 2030-06-21. Which sampling date should I compare across seasons, and "
        "how should I preserve the other dates?"
    )
    draft = (
        "Use the sample collection date, 2030-06-14, for sampling-date comparisons. "
        "Analysis date: 2030-06-19. " + issuance +
        " Keep the three events separately linked to the sample and original report."
    )
    editor = Editor()
    result = verify_answer(draft, question=question, evidence_text="", question_type="field_data",
                           risk_level="low", editor=editor, review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft
    assert not result.fallback_applied and editor.calls == 0


@pytest.mark.parametrize("inspection", [
    "Look for lesions, rot, or discoloration.",
    "Compare the roots, looking for damaged attachments, rot, and discoloration.",
    "Inspect the roots for rot.",
])
def test_generic_decay_in_an_inspection_list_is_not_a_named_disease(inspection):
    draft = ROOT_METHOD.replace("Look for the shape and attachment of swellings, lesions, rot, or discoloration.", inspection)
    editor = Editor()
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=editor, review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft
    assert not result.draft_assessment.unsupported_named_conditions and editor.calls == 0


@pytest.mark.parametrize("claim", [
    "The swollen roots show rot, so that is the cause.",
    "Look for rot, which is confirmed.",
    "Look for damaged attachments, rot, which explains the swelling.",
    "Check the roots for rot, identified on every affected plant.",
    "Look for rot, or discoloration that explains the swelling.",
    "Look for root rot.",
    "Look for bacterial rot.",
    "Look for soft rot.",
    "Look for lesions, rot, or discoloration. The diagnosis is root rot.",
])
def test_inspection_context_does_not_license_disease_names_or_confirmed_findings(claim):
    assessment = assess_claim_risk(claim, question=ROOT_QUESTION, evidence_text="",
                                  question_type="plant_health", risk_level="high")
    assert assessment.unsupported_named_conditions


def test_generic_decay_exception_does_not_apply_to_other_tasks():
    assessment = assess_claim_risk("Look for rot.", question="What should I inspect on grain leaves?",
                                  evidence_text="", question_type="plant_health", risk_level="high")
    assert assessment.unsupported_named_conditions


@pytest.mark.parametrize("draft_missing_records", [False, True])
def test_claim_editor_cannot_trade_previously_present_required_content_for_a_repair(draft_missing_records):
    from agronomy_agent.answer_verifier import _rewrite_rejection_reasons
    draft = ROOT_METHOD + " Inspect for root rot."
    if draft_missing_records:
        draft = draft.replace("Record crop stage and the field pattern. ", "")
    rewrite = (
        "Dig plants with their roots intact and compare affected plants with nearby healthy plants. "
        "Record crop stage and the field pattern. The cause remains uncertain; ask a diagnostic lab "
        "how to package representative roots if inspection does not resolve it."
    )
    before = assess_claim_risk(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health", risk_level="high")
    after = assess_claim_risk(rewrite, question=ROOT_QUESTION, evidence_text="", question_type="plant_health", risk_level="high")
    reasons = _rewrite_rejection_reasons(draft=draft, rewrite=rewrite, draft_assessment=before,
        rewrite_assessment=after, question=ROOT_QUESTION, question_type="plant_health", evidence_handshake=None)
    assert "decision_content_lost:root_structure" in reasons


def test_editor_can_remove_an_unsupported_disease_name_without_losing_requested_help():
    draft = ROOT_METHOD + " Inspect for root rot."
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(ROOT_METHOD), review_mode="risk_conditioned_selective_v3")
    assert result.rewrite_accepted and result.answer == ROOT_METHOD


def test_public_verification_rejects_an_editor_that_drops_concrete_root_inspection():
    draft = ROOT_METHOD + " Inspect for root rot."
    rewrite = ROOT_METHOD.replace("Look for the shape and attachment of swellings, lesions, rot, or discoloration. ", "")
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(rewrite), review_mode="risk_conditioned_selective_v3")
    assert not result.rewrite_accepted
    assert "decision_content_lost:root_structure" in result.rejection_reasons
    assert "discoloration" in result.answer


@pytest.mark.parametrize("question,draft", [
    (ROOT_QUESTION, ROOT_METHOD),
    (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report issued "
        "2030-06-21. Which sampling date should I compare across seasons, and how should I preserve the other dates?",
        "Use the sample collection date, 2030-06-14, for sampling-date comparisons. Analysis date: "
        "2030-06-19. Report issued: 2030-06-21. Keep the three events separately linked to the sample and original report.",
    ),
])
def test_complete_method_survives_the_persisted_production_path(tmp_path, monkeypatch, question, draft):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = "imposed_complete_method_fixture"
        intervention_profile = "balanced"
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return draft

        def close(self):
            pass

    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args, **kwargs: backend)
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    try:
        session = store.create_session("Complete method preservation", {}, {})
        request = AgentExecutionRequest(store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=200,
            generation_backend=backend)
        result = chat_service.execute_agent_request(request)
        assert result.answer == draft
        assert store.get_turn(result.turn["turn_id"])["answer"] == draft
        assert len(result.stage_receipts) == 17 and backend.calls == 1
    finally:
        store._conn.close()

from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import assess_claim_risk, _looks_incomplete, verify_answer
from agronomy_agent.quantity_claims import unsupported_quantities


@pytest.mark.parametrize(('source', 'answer', 'unsupported'), [
    ('Mass: 120 kg.', 'Mass: 20 kg.', True),
    ('Mass: 120 kg.', 'Mass: 120 kg.', False),
    ('Mass: 20 kg.', 'Rate: 20 kg/ha.', True),
    ('Mass: 1,200 kilograms.', 'Mass: 1200 kg.', False),
    ('Temperature: -5 C.', 'Temperature: 5 C.', True),
    ('Depth: 2 to 4 inches.', 'Depth: 2–4 inches.', False),
    ('Mass: 120 kg.', '20 kg is an error; the source records 120 kg.', False),
    ('Mass: 120 kg.', 'The mass is not less than 20 kg.', True),
])
def test_quantities_are_complete_values_with_units(source, answer, unsupported):
    assert bool(unsupported_quantities(answer, question='Read the record.', evidence=source)) is unsupported


@pytest.mark.parametrize(('answer', 'unsupported'), [
    ('The total is 300 kg because 12 × 25 = 300.', False),
    ('The total is 25 kg because 12 bags weigh 25 kg each.', True),
    ('The total is 250 kg because 12 × 25 = 250.', True),
    ('The total is 300 lb.', True),
    ('The total is 300 kg. Apply 300 kg/ha.', True),
    ('12 × 12 = 300.', True),
])
def test_total_relation_requires_grounded_operands_and_units(answer, unsupported):
    values = unsupported_quantities(answer, question='What is the total mass of 12 bags weighing 25 kg each?',
                                   evidence='There are 12 bags and each bag weighs 25 kg.')
    assert bool(values) is unsupported


def test_unseen_container_values_and_conflicting_premises():
    q = 'What is the total weight of 7 boxes weighing 2.5 pounds each?'
    assert not unsupported_quantities('The total weight is 17.5 lb.', question=q, evidence='')
    assert unsupported_quantities('The total weight is 17.5 lb.', question=q, evidence='There are 9 boxes.')


def test_arithmetic_does_not_grant_action_permission():
    assessment = assess_claim_risk('The total is 300 kg. You can spray now because it is dry.',
        question='What is the total mass of 12 bags weighing 25 kg each?',
        question_type='product_label', risk_level='high')
    assert 'unsupported_regulated_permission' in assessment.reasons


@pytest.mark.parametrize(('answer', 'incomplete'), [
    ('The total is 300.', False), ('12 × 25 = 300.', False),
    ('First item.\n2.', True), ('1)', True), ('Next steps:\n-', True),
])
def test_terminal_number_is_not_a_dangling_list(answer, incomplete):
    assert _looks_incomplete(answer) is incomplete


@pytest.mark.parametrize(('source', 'answer', 'unsupported'), [
    ('Gray leaf spot was ruled out by the laboratory.', 'The diagnosis is not gray leaf spot; the cause remains unknown.', False),
    ('Gray leaf spot was not ruled out by the laboratory.', 'The diagnosis is not gray leaf spot.', True),
    ('Gray leaf spot may be ruled out after testing.', 'The diagnosis is not gray leaf spot.', True),
    ('Rust was ruled out by the laboratory.', 'The diagnosis is not gray leaf spot.', True),
    ('Gray leaf spot is possible.', 'The diagnosis is gray leaf spot.', True),
    ('The source mentions *Cercospora zeae*.', 'The diagnosis is *Cercospora zeae*.', True),
])
def test_diagnosis_polarity_needs_source_support(source, answer, unsupported):
    assessment = assess_claim_risk(answer, question='What does this note establish?', evidence_text=source)
    assert ('unsupported_diagnostic_certainty' in assessment.reasons) is unsupported


def test_changed_safe_claim_does_not_inherit_another_claims_trigger():
    from agronomy_agent.answer_verifier import AnswerVerificationResult
    draft = 'The shipment mass is 120 kg. You can spray now because it is dry.'
    assessment = assess_claim_risk(draft, question='Read the shipment note.', evidence_text='Mass: 120 kg.')
    record = AnswerVerificationResult(answer='Check the label.', triggered=True, rewrite_accepted=True,
        draft_assessment=assessment, draft_output=draft).as_record()
    ledger = record['claim_edit_ledger']
    assert ledger['schema_version'].endswith('.v2')
    assert ledger['changed_claims'][0]['defect_ids'] == []
    assert ledger['changed_claims'][1]['defect_ids'] == ['verifier_defect::unsupported_regulated_permission']
    assert ledger['all_changed_claims_have_localized_trigger'] is False
    assert ledger['replacement_has_named_defect'] is True  # Answer-level trigger only.
    assert ledger['changed_claims'][1]['evidence_scope'] == 'answer_review_context_not_claim_support'


def test_count_and_mass_of_different_containers_are_not_joined():
    assert unsupported_quantities('The total mass is 300 kg.',
        question='What is the total mass of 12 bags?', evidence='Each box weighs 25 kg.')


@pytest.mark.parametrize('answer', ['20kg/acre', '20 kg/acre', '20 kPa', '20abc'])
def test_unit_suffix_cannot_fall_back_to_supported_bare_magnitude(answer):
    assert unsupported_quantities(answer, question='', evidence='Mass: 20 kg.')


@pytest.mark.parametrize('answer', ['.5 kg/ha', '-.5 cm', '0.5 kg/ha'])
def test_decimal_without_integer_part_is_not_silently_omitted(answer):
    assert unsupported_quantities(answer, question='Read the record.', evidence='')


@pytest.mark.parametrize('unit', ['hectares', 'gallons', 'millilitres'])
def test_mass_is_not_support_for_area_or_volume(unit):
    assert unsupported_quantities(f'20 {unit}', question='Read the record.', evidence='20 kg')


def test_equal_counts_in_distinct_groups_are_not_deduplicated():
    assert unsupported_quantities('The total mass is 300 kg.', question=(
        'What is the total mass of 12 bags of barley and 12 bags of wheat? Each bag weighs 25 kg.'), evidence='')


@pytest.mark.parametrize('source', [
    'There is no evidence that gray leaf spot was ruled out by the laboratory.',
    'Whether gray leaf spot was ruled out by the laboratory is unknown.',
    'Gray leaf spot was ruled out by the laboratory?',
    'Gray leaf spot was ruled out by the laboratory is an unverified claim.',
])
def test_uncertain_exclusion_is_not_an_affirmative_lab_result(source):
    assessment = assess_claim_risk('The diagnosis is not gray leaf spot.',
        question='What does this note establish?', evidence_text=source)
    assert 'unsupported_diagnostic_certainty' in assessment.reasons


def test_derivation_does_not_join_unbound_groups_across_question_and_evidence():
    assert unsupported_quantities('The total mass is 300 kg.',
        question='What is the total mass of 12 bags of barley?',
        evidence='12 bags of wheat weigh 25 kg each.')


@pytest.mark.parametrize('evidence', [
    'Gray leaf spot was ruled out by the laboratory. A later test confirmed gray leaf spot.',
    'Gray leaf spot was ruled out by the laboratory. That exclusion was overturned.',
])
def test_later_contradiction_does_not_license_exclusion(evidence):
    assessment = assess_claim_risk('The diagnosis is not gray leaf spot.',
        question='What does this note establish?', evidence_text=evidence)
    assert 'unsupported_diagnostic_certainty' in assessment.reasons


@pytest.mark.parametrize('quantity', ['twenty', 'twenty-five', 'one hundred and twenty', 'minus twenty'])
def test_spelling_a_quantity_does_not_evade_numeric_review(quantity):
    assessment = assess_claim_risk(f'The shipment mass is {quantity} kg.',
        question='What shipment mass is recorded?', evidence_text='The shipment mass is 120 kg.')
    assert 'unsupported_numeric_specificity' in assessment.reasons


def test_editor_cannot_clear_numeric_defect_by_spelling_unsupported_value():
    from agronomy_agent.answer_verifier import verify_answer
    class Editor:
        def generate(self, _messages):
            return 'The mismatch is that the shipment mass is twenty kg.'
    result = verify_answer('The shipment mass is 20 kg.',
        question='Spot the mismatch in this shipment note and state the source value.',
        evidence_text='The shipment mass is 120 kg.', question_type='conceptual', risk_level='low',
        editor=Editor(), review_mode='risk_conditioned_selective_v3')
    assert not result.rewrite_accepted
    assert result.rewrite_assessment is not None
    assert 'unsupported_numeric_specificity' in result.rewrite_assessment.reasons
    assert 'twenty kg' not in result.answer


@pytest.mark.parametrize(('source', 'answer'), [
    ('The shipment mass is one hundred and twenty kg.', 'The shipment mass is twenty kg.'),
    ('The change is minus twenty kg.', 'The change is twenty kg.'),
    ('The shipment mass is twenty kg.', 'The rate is twenty kg/ha.'),
    ('The shipment mass is twenty kg.', 'The rate is twenty kg per hectare.'),
])
def test_spelled_quantities_match_whole_phrase_sign_and_rate(source, answer):
    assessment = assess_claim_risk(answer, question='Read the record.', evidence_text=source)
    assert 'unsupported_numeric_specificity' in assessment.reasons


def test_exact_spelled_quantity_is_preserved():
    assessment = assess_claim_risk('The shipment mass is one hundred and twenty kg.',
        question='Read the record.', evidence_text='The shipment mass is one hundred and twenty kg.')
    assert not assessment.unsupported_numbers


class _PreservationEditor:
    """Project-authored offline editor; it never loads or calls a model."""

    max_tokens = 1024

    def __init__(self, answer, *, fail=False):
        self.answer = answer
        self.fail = fail
        self.messages = None

    def count_prompt_tokens(self, messages):
        return sum(len(item['content'].split()) + 4 for item in messages)

    def generate(self, messages):
        self.messages = messages
        if self.fail:
            raise RuntimeError('synthetic editor failure')
        return self.answer


_RECORD = ('Harbor Lab reports soil nitrate of 13 mg/kg on a dry-soil basis '
           'at a sampling depth of 10–25 cm. Sampling date and local calibration are unknown.')
_REQUEST = ('Read the soil nitrate record, preserve its reported value, unit, basis, sampling depth '
            'and lab attribution, and explain the uncertainty from the missing date and calibration. '
            'Do not recommend an application rate.')
_SAFE_ANSWER = _RECORD + ' This record alone cannot determine an application rate.'


def _preservation_result(draft, editor, **kwargs):
    mode = kwargs.pop('review_mode', 'risk_conditioned_selective_v3')
    return verify_answer(draft, question=_REQUEST, evidence_text=_SAFE_ANSWER,
                         question_type='conceptual', risk_level='high', editor=editor,
                         review_mode=mode, editor_max_tokens=1024, **kwargs)


def test_editor_observation_captures_return_before_selection():
    events = []
    editor = _PreservationEditor(_SAFE_ANSWER + ' Apply 99 kg/ha immediately.')
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.', editor,
                                  editor_observation_hook=events.append)
    assert [event['state'] for event in events] == ['dispatch_intent', 'returned']
    assert events[-1]['raw_output'] == editor.answer
    assert not result.rewrite_accepted
    assert result.as_record()['editor_observation']['state'] == 'returned'


class _ObservedEditor(_PreservationEditor):
    def __init__(self, answer, error=None):
        super().__init__(answer)
        self.calls = 0
        self.error = error
        self.max_tokens = 220
        self.last_generation_stats = {'finish_reason': 'length', 'generation_tokens': 99}
        self.generation_stats_call_id = 0

    def generate(self, messages):
        self.calls += 1
        self.messages = messages
        if self.error is not None:
            raise self.error
        self.generation_stats_call_id += 1
        self.last_generation_stats = {'finish_reason': 'stop', 'generation_tokens': 7,
                                      'generation_stats_call_id': self.generation_stats_call_id}
        return self.answer


@pytest.mark.parametrize('kind', ['accepted', 'rejected', 'unchanged', 'empty', 'failure', 'cancel', 'no_call'])
def test_editor_observation_lifecycle_retains_each_actual_boundary(kind):
    from agronomy_agent.execution_core import stable_sha256
    from agronomy_agent.answer_verifier import validate_editor_observation
    draft = _SAFE_ANSWER + ' Apply 71 kg/ha immediately.'
    answer = {'rejected': _SAFE_ANSWER + ' Apply 99 kg/ha immediately.', 'unchanged': draft, 'empty': ''}.get(kind, ' \n' + _SAFE_ANSWER + '\n ')
    error = KeyboardInterrupt('Synthetic cancel') if kind == 'cancel' else RuntimeError('Synthetic failure') if kind == 'failure' else None
    editor = _ObservedEditor(answer, error)
    events = []
    if kind == 'cancel':
        with pytest.raises(KeyboardInterrupt) as caught:
            _preservation_result(draft, editor, editor_observation_hook=events.append)
        assert caught.value is error
    else:
        result = _preservation_result(_SAFE_ANSWER if kind == 'no_call' else draft, editor,
                                      editor_observation_hook=events.append)
        assert 'raw_output' not in result.as_record()['editor_observation']
        assert 'prompt_messages' not in result.as_record()['editor_observation']
    expected = ['no_call'] if kind == 'no_call' else ['dispatch_intent', 'failed_unknown' if error else 'returned']
    assert [event['state'] for event in events] == expected
    assert editor.calls == (0 if kind == 'no_call' else 1)
    for event in events: validate_editor_observation(event)
    if kind == 'no_call': assert events[0]['call_invoked'] is False
    elif error:
        assert events[-1]['call_invoked'] is None and events[-1]['model_identity'] is None
        assert events[-1]['generation_stats'] is None
    else:
        assert events[-1]['raw_output'] == answer
        assert events[-1]['raw_output_sha256'] == stable_sha256(answer)
        assert events[-1]['normalized_output_sha256'] == stable_sha256(answer.strip())
        assert events[-1]['generation_stats']['generation_tokens'] == 7
        assert events[-1]['identity_status'] == 'unknown'  # An arbitrary fake cannot qualify native identity.


@pytest.mark.parametrize('state', ['dispatch_intent', 'returned', 'failed_unknown'])
def test_editor_observation_checkpoint_errors_never_become_successful_provider_fallback(state):
    original = KeyboardInterrupt('Synthetic original cancellation') if state == 'failed_unknown' else None
    editor = _ObservedEditor(_SAFE_ANSWER, original)
    events = []
    def fail(event):
        events.append(event)
        if event['state'] == state: raise OSError('Synthetic checkpoint failure')
    expected = KeyboardInterrupt if original else OSError
    with pytest.raises(expected) as caught:
        _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.', editor, editor_observation_hook=fail)
    if original: assert caught.value is original
    assert editor.calls == (0 if state == 'dispatch_intent' else 1)
    assert events[-1]['state'] == state


def test_editor_observation_is_detached_and_default_record_is_unchanged():
    from agronomy_agent.answer_verifier import validate_editor_observation
    draft = _SAFE_ANSWER + ' Apply 71 kg/ha immediately.'
    a = _preservation_result(draft, _ObservedEditor(_SAFE_ANSWER))
    b = _preservation_result(draft, _ObservedEditor(_SAFE_ANSWER), editor_observation_hook=None)
    assert a.as_record() == b.as_record() and 'editor_observation' not in a.as_record()
    editor = _ObservedEditor(_SAFE_ANSWER)
    def mutate(event):
        event['prompt_messages'].clear()
        if event['generation_stats'] is not None: event['generation_stats']['finish_reason'] = 'length'
        event['receipt_sha256'] = 'wrong'
    result = _preservation_result(draft, editor, editor_observation_hook=mutate)
    record = validate_editor_observation(result.as_record()['editor_observation'])
    assert record['generation_stats']['finish_reason'] == 'stop'
    assert editor.last_generation_stats['finish_reason'] == 'stop'


def test_editor_observation_return_precedes_downstream_assessment_error(monkeypatch):
    import agronomy_agent.answer_verifier as verifier
    editor, events = _ObservedEditor(_SAFE_ANSWER), []
    def fail(**_kwargs): raise ValueError('Synthetic post-return assessment failure')
    monkeypatch.setattr(verifier, '_rewrite_rejection_reasons', fail)
    with pytest.raises(ValueError, match='post-return'):
        _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.', editor, editor_observation_hook=events.append)
    assert editor.calls == 1 and events[-1]['state'] == 'returned'


@pytest.mark.parametrize('ceiling', [None, 512])
@pytest.mark.parametrize('mode', ['risk_gated', 'risk_conditioned_selective_v3'])
def test_editor_word_ceiling_preserves_supported_record_on_accepted_rewrite(ceiling, mode):
    editor = _PreservationEditor(_SAFE_ANSWER)
    draft = _SAFE_ANSWER + ' Apply 71 kg/ha immediately.'
    result = _preservation_result(draft, editor, editor_max_words=ceiling, review_mode=mode)
    assert result.rewrite_accepted
    assert result.answer == _SAFE_ANSWER
    assert '71 kg/ha' not in result.answer
    expected = ceiling if ceiling is not None else max(60, min(160, len(draft.split()) + 40))
    assert f'in at most {expected} words.' in editor.messages[-1]['content']
    assert result.editor_context_budget['reserved_output_tokens'] == 1024
    assert result.editor_context_budget['editor_max_words'] == expected


def test_editor_word_ceiling_none_preserves_legacy_prompt_bytes():
    draft = _SAFE_ANSWER + ' Apply 71 kg/ha immediately.'
    omitted, explicit = _PreservationEditor(_SAFE_ANSWER), _PreservationEditor(_SAFE_ANSWER)
    _preservation_result(draft, omitted)
    _preservation_result(draft, explicit, editor_max_words=None)
    assert omitted.messages == explicit.messages


@pytest.mark.parametrize('value', [True, False, 0, -1, 1.5, '512', float('nan'), float('inf'), 4097])
def test_invalid_editor_word_ceiling_refuses_even_an_unreviewed_answer(value):
    editor = _PreservationEditor('Unused.')
    with pytest.raises(ValueError, match='max_words'):
        verify_answer('A benign conceptual answer.', question='Explain crop rotation.',
                      evidence_text='', question_type='conceptual', risk_level='low',
                      editor=editor, editor_max_words=value,
                      review_mode='risk_conditioned_selective_v3')
    assert editor.messages is None


def test_rejected_editor_attempt_retains_supported_record_not_unsupported_rate():
    editor = _PreservationEditor(_SAFE_ANSWER + ' Apply 99 kg/ha immediately.')
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.', editor, editor_max_words=512)
    assert not result.rewrite_accepted
    assert result.editor_output == editor.answer
    assert _RECORD in result.answer
    assert '99 kg/ha' not in result.answer
    assert '71 kg/ha' not in result.answer


def test_editor_error_fallback_retains_supported_record_and_requested_boundary():
    editor = _PreservationEditor('Unused.', fail=True)
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.', editor, editor_max_words=512)
    assert not result.rewrite_accepted
    assert 'editor_error' in result.rejection_reasons
    assert _RECORD in result.answer
    assert 'application rate' in result.answer
    assert result.editor_output is None
    assert '71 kg/ha' not in result.answer


@pytest.mark.parametrize('fail', [False, True])
def test_preservation_never_copies_unsupported_or_irrelevant_distractors(fail):
    relevant = _SAFE_ANSWER
    distractor = 'The unrelated shipment mass is 46 kg.'
    draft = relevant + ' ' + distractor + ' Apply 71 kg/ha immediately.'
    editor = _PreservationEditor(relevant + ' Apply 99 kg/ha immediately.', fail=fail)
    result = verify_answer(draft, question=_REQUEST, evidence_text=relevant + ' ' + distractor,
                           question_type='conceptual', risk_level='high', editor=editor,
                           editor_max_words=512)
    assert _RECORD in result.answer
    assert '46 kg' not in result.answer
    assert '71 kg/ha' not in result.answer and '99 kg/ha' not in result.answer


@pytest.mark.parametrize('ceiling', [1, 4096])
def test_editor_word_ceiling_valid_boundaries(ceiling):
    editor = _PreservationEditor(_SAFE_ANSWER)
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.',
                                  editor, editor_max_words=ceiling)
    assert result.rewrite_accepted
    assert f'in at most {ceiling} words.' in editor.messages[-1]['content']
    # A word instruction is not a character slicer or a claim that an editor
    # obeyed the instruction; provider termination is a separate observation.
    assert result.answer == _SAFE_ANSWER


@pytest.mark.parametrize('ceiling', [None, 512])
@pytest.mark.parametrize('fail', [False, True])
@pytest.mark.parametrize('wrapped', [
    'This claim is false: ' + _RECORD,
    'Rejected training example, not an observed lab record: "' + _RECORD + '"',
    'Hypothetical example only, not a measured lab result: ' + _RECORD,
    'This claim is false. ' + _RECORD,
    _RECORD + ' The preceding claim is incorrect.',
])
def test_literal_recovery_refuses_wrapped_or_rejected_claims(wrapped, fail, ceiling):
    editor = _PreservationEditor(_SAFE_ANSWER + ' Apply 99 kg/ha immediately.', fail=fail)
    result = verify_answer(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.',
                           question=_REQUEST, evidence_text=wrapped,
                           question_type='conceptual', risk_level='high', editor=editor,
                           editor_max_words=ceiling)
    assert not result.rewrite_accepted
    assert '13 mg/kg' not in result.answer
    assert 'Harbor Lab reports' not in result.answer
    assert '71 kg/ha' not in result.answer and '99 kg/ha' not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
@pytest.mark.parametrize('fail', [False, True])
def test_selected_record_recovery_excludes_other_record_on_the_same_topic(ceiling, fail):
    alpha = 'Field Alpha soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    bravo = 'Field Bravo soil nitrate record reports 46 mg/kg on a dry-soil basis.'
    evidence = alpha + ' ' + bravo
    question = ('Read only Field Alpha soil nitrate record and preserve its value, unit and basis. '
                'Do not include Field Bravo and do not recommend a rate.')
    editor = _PreservationEditor(evidence + ' Apply 99 kg/ha immediately.', fail=fail)
    result = verify_answer(evidence + ' Apply 71 kg/ha immediately.', question=question,
                           evidence_text=evidence, question_type='conceptual', risk_level='high',
                           editor=editor, editor_max_words=ceiling)
    assert not result.rewrite_accepted
    assert alpha in result.answer
    assert 'Field Bravo' not in result.answer and '46 mg/kg' not in result.answer
    assert '71 kg/ha' not in result.answer and '99 kg/ha' not in result.answer


def test_multiple_unselected_same_topic_records_refuse_literal_recovery():
    evidence = ('Field Alpha soil nitrate record reports 13 mg/kg on a dry-soil basis. '
                'Field Bravo soil nitrate record reports 46 mg/kg on a dry-soil basis.')
    result = verify_answer(evidence + ' Apply 71 kg/ha immediately.',
                           question=_REQUEST, evidence_text=evidence,
                           question_type='conceptual', risk_level='high',
                           editor=_PreservationEditor('Unused.', fail=True), editor_max_words=512)
    assert '13 mg/kg' not in result.answer and '46 mg/kg' not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
def test_lossy_otherwise_safe_editor_cannot_drop_explicitly_requested_record(ceiling):
    lossy = ('Sampling date and local calibration are unknown. '
             'The available evidence cannot determine an application rate.')
    editor = _PreservationEditor(lossy)
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.',
                                  editor, editor_max_words=ceiling)
    assert editor.messages is not None and result.editor_output == lossy
    assert result.rewrite_assessment is not None
    assert not result.rewrite_assessment.unsupported_numbers  # Safe quantity omission is still a loss.
    assert not result.rewrite_accepted
    assert 'requested_record_not_preserved:value_unit_or_depth' in result.rejection_reasons
    assert _RECORD in result.answer
    assert 'application rate' in result.answer and '71 kg/ha' not in result.answer


def test_supported_record_rewrite_can_paraphrase_without_verbatim_draft():
    paraphrase = ('According to Harbor Lab, soil nitrate is 13 mg/kg on a dry-soil basis, '
                  'from a sampling depth of 10 to 25 cm. Sampling date and local calibration '
                  'are unknown. This record alone cannot determine an application rate.')
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.',
                                  _PreservationEditor(paraphrase), editor_max_words=512)
    assert result.rewrite_accepted and result.answer == paraphrase
    assert _RECORD not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
def test_otherwise_safe_editor_cannot_add_an_excluded_same_topic_record(ceiling):
    alpha = 'Field Alpha soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    bravo = 'Field Bravo soil nitrate record reports 46 mg/kg on a dry-soil basis.'
    evidence = alpha + ' ' + bravo
    editor = _PreservationEditor(evidence)
    result = verify_answer(evidence + ' Apply 71 kg/ha immediately.',
                           question=('Read only Field Alpha soil nitrate record and preserve its value, unit and basis. '
                                     'Do not include Field Bravo and do not recommend a rate.'),
                           evidence_text=evidence, question_type='conceptual', risk_level='high',
                           editor=editor, editor_max_words=ceiling)
    assert result.editor_output == evidence
    assert result.rewrite_assessment is not None and not result.rewrite_assessment.unsupported_numbers
    assert not result.rewrite_accepted
    assert 'requested_record_not_preserved:unrequested_record' in result.rejection_reasons
    assert alpha in result.answer and 'Field Bravo' not in result.answer and '46 mg/kg' not in result.answer


@pytest.mark.parametrize(('loss', 'replacement'), [
    ('basis', _SAFE_ANSWER.replace(' on a dry-soil basis', '')),
    ('value_unit_or_depth', _SAFE_ANSWER.replace(' at a sampling depth of 10–25 cm', '')),
    ('attribution', _SAFE_ANSWER.replace('Harbor Lab reports soil nitrate of', 'The record reports soil nitrate of')),
    ('date_uncertainty', _SAFE_ANSWER.replace('Sampling date and local calibration are unknown.', 'Local calibration is unknown.')),
])
def test_requested_record_labels_cannot_be_lost_while_other_facts_survive(loss, replacement):
    result = _preservation_result(_SAFE_ANSWER + ' Apply 71 kg/ha immediately.',
                                  _PreservationEditor(replacement), editor_max_words=512)
    assert not result.rewrite_accepted
    assert f'requested_record_not_preserved:{loss}' in result.rejection_reasons
    assert _RECORD in result.answer and '71 kg/ha' not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
@pytest.mark.parametrize('lowercase', [False, True])
@pytest.mark.parametrize('evidence_scope', ['both', 'excluded_only'])
@pytest.mark.parametrize('draft_scope', ['both', 'excluded_only'])
def test_same_prefix_multiword_record_names_cannot_confer_identity(
    ceiling, lowercase, evidence_scope, draft_scope,
):
    selected = 'Field North Pasture soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    excluded = 'Field North Ridge soil nitrate record reports 46 mg/kg on a dry-soil basis.'
    question = ('Read only Field North Pasture soil nitrate record and preserve its value, unit and basis. '
                'Do not include Field North Ridge and do not recommend a rate.')
    evidence = selected + ' ' + excluded if evidence_scope == 'both' else excluded
    draft = selected + ' ' + excluded if draft_scope == 'both' else excluded
    if lowercase:
        question, evidence, draft = question.lower(), evidence.lower(), draft.lower()
    editor = _PreservationEditor('Unused.', fail=True)
    result = verify_answer(draft + ' Apply 71 kg/ha immediately.', question=question,
                           evidence_text=evidence, question_type='conceptual', risk_level='high',
                           editor=editor, editor_max_words=ceiling)
    assert editor.messages is not None and 'editor_error' in result.rejection_reasons
    # Multiword names are unbound in this deliberately narrow contract. Neither
    # apparent first-token uniqueness nor an excluded-only source grants identity.
    assert '46 mg/kg' not in result.answer and 'north ridge' not in result.answer.lower()
    assert '13 mg/kg' not in result.answer
    assert '71 kg/ha' not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
def test_lowercase_single_field_identity_remains_supported(ceiling):
    record = 'field alpha soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    result = verify_answer(record + ' Apply 71 kg/ha immediately.',
                           question=('Read only field alpha soil nitrate record and preserve its value, unit and basis. '
                                     'Do not recommend a rate.'), evidence_text=record,
                           question_type='conceptual', risk_level='high',
                           editor=_PreservationEditor('Unused.', fail=True), editor_max_words=ceiling)
    assert record in result.answer and '71 kg/ha' not in result.answer


def test_rewrite_cannot_extend_selected_single_field_id_with_another_word():
    record = 'Field Alpha soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    rewrite = 'Field Alpha Pasture soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    result = verify_answer(record + ' Apply 71 kg/ha immediately.',
                           question=('Read only Field Alpha soil nitrate record and preserve its value, unit and basis. '
                                     'Do not recommend a rate.'), evidence_text=record,
                           question_type='conceptual', risk_level='high',
                           editor=_PreservationEditor(rewrite), editor_max_words=512)
    assert not result.rewrite_accepted
    assert 'requested_record_not_preserved:ambiguous_record_identity' in result.rejection_reasons
    assert record in result.answer and 'Alpha Pasture' not in result.answer


@pytest.mark.parametrize('ceiling', [None, 512])
@pytest.mark.parametrize('source_scope', ['both', 'excluded_only'])
@pytest.mark.parametrize(('ascii_id', 'confusable_id'), [
    ('K', 'K'), ('AK', 'AK'), ('I', 'İ'), ('I', 'ı'), ('S', 'ſ'), ('K', 'Κ'), ('K', 'К'),
])
def test_raw_nonascii_field_id_cannot_alias_selected_ascii_id(ascii_id, confusable_id, source_scope, ceiling):
    selected = f'Field {ascii_id} soil nitrate record reports 13 mg/kg on a dry-soil basis.'
    excluded = f'Field {confusable_id} soil nitrate record reports 46 mg/kg on a dry-soil basis.'
    evidence = selected + ' ' + excluded if source_scope == 'both' else excluded
    result = verify_answer(excluded + ' Apply 71 kg/ha immediately.',
                           question=(f'Read only Field {ascii_id} soil nitrate record and preserve its value, unit and basis. '
                                     f'Do not include Field {confusable_id} and do not recommend a rate.'),
                           evidence_text=evidence, question_type='conceptual', risk_level='high',
                           editor=_PreservationEditor('Unused.', fail=True), editor_max_words=ceiling)
    assert 'editor_error' in result.rejection_reasons
    assert '46 mg/kg' not in result.answer and '71 kg/ha' not in result.answer


@pytest.mark.parametrize('field_id', ['K', 'k', 'AK', 'Plot_K', 'Plot-K'])
def test_ascii_identity_does_not_reject_unicode_ranges_or_other_prose(field_id):
    record = (f'Field {field_id} soil nitrate record reports 13 mg/kg on a dry-soil basis '
              'at a sampling depth of 10–25 cm.')
    uncertainty = 'Sampling date and local calibration are unknown.'
    evidence = record + ' ' + uncertainty + ' The lab calls this café-series sampling.'
    result = verify_answer(record + ' ' + uncertainty + ' Apply 71 kg/ha immediately.',
                           question=(f'Read only Field {field_id} soil nitrate record and preserve its value, unit, basis and sampling depth. '
                                     'Explain the uncertainty from the missing date and calibration. Do not recommend a rate.'),
                           evidence_text=evidence, question_type='conceptual', risk_level='high',
                           editor=_PreservationEditor('Unused.', fail=True), editor_max_words=512)
    assert 'editor_error' in result.rejection_reasons
    assert record in result.answer and uncertainty in result.answer
    assert '10–25 cm' in result.answer and '71 kg/ha' not in result.answer


@pytest.mark.parametrize("kind", ["provider", "keyboard", "system_exit"])
def test_editor_observation_closeout_failure_preserves_original_cause_and_control(kind):
    from agronomy_agent.release_eval_executor import exception_evidence
    original = {"provider": RuntimeError, "keyboard": KeyboardInterrupt, "system_exit": SystemExit}[kind]("Synthetic provider fault")
    leaf = ValueError("Synthetic original leaf")
    original.__cause__ = leaf
    editor = _ObservedEditor("Unused synthetic output.", error=original)
    events = []
    def sink(record):
        events.append(record)
        if record["state"] == "failed_unknown":
            raise OSError("Synthetic editor checkpoint failure")
    with pytest.raises(type(original)) as caught:
        _preservation_result(_SAFE_ANSWER + " Apply 71 kg/ha immediately.", editor,
                             editor_observation_hook=sink)
    assert caught.value is original and original.__cause__ is leaf
    assert editor.calls == 1 and [event["state"] for event in events] == ["dispatch_intent", "failed_unknown"]
    retained = exception_evidence(original)
    assert any(node["message"] == "Synthetic original leaf" and node["path"].endswith(".cause") for node in retained["nodes"])
    assert any(node["type"] == "OSError" and node["path"].endswith(".editor_observer") for node in retained["nodes"])


def test_canonical_provider_observation_does_not_become_native_identity():
    from agronomy_agent.answer_verifier import _EditorObservation
    import hashlib
    class Editor:
        generation_stats_call_id=0;last_generation_stats=None;model_id="synthetic-luna";max_tokens=220
    editor=Editor();events=[];observer=_EditorObservation(editor,events.append)
    observer.enter([{"role":"user","content":"synthetic"}],{})
    editor.generation_stats_call_id=1
    editor.last_generation_stats={"generation_stats_call_id":1,"backend":"codex_app_server_chatgpt_auth",
        "app_server_receipt":{"selected_model":"synthetic-luna","output_sha256":hashlib.sha256(b"safe").hexdigest()}}
    observer.returned("safe")
    assert events[-1]["identity_status"]=="unknown" and events[-1]["model_identity"] is None
    assert events[-1]["provider_observation"]["scope"]=="explicit_thread_selection_not_weights_identity"

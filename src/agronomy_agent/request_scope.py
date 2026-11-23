"""Shared detection of operational directives in otherwise benign requests."""
from __future__ import annotations

import json
import re
from agronomy_agent.arithmetic_input_roles import (
    ARITHMETIC_INPUT_ROLE_PATTERN, MONEY_FLOW_ROLE_PATTERN,
    BALANCE_SHEET_ROLE_PATTERN, YIELD_ROLE, AREA_UNIT_PATTERN,
    YIELD_UNIT_PATTERN,
    SEED_TARGET_ROLE,
)
from agronomy_agent.supplied_numeric_inputs import NUMBER, unit_owned_area_mass_total
from agronomy_agent.supplied_depletion_request import supplied_depletion_request

FIELD_ACTION_PATTERN = (
    # Treating a field is an operation; treating measurements as equivalent
    # is a comparison whose validity remains the evidence check's concern.
    r"(?:treat(?!\s+(?:(?:these|those|the)\s+)?(?:measurements?|values?|results?|counts?|units?|estimates?)"
    r"\s+as\s+(?:the\s+)?(?:same|equivalent|interchangeable)\b)|"
    r"apply|spray|irrigate|fertilize|drain|mow|drive|graze|sell|buy|till|cultivate|prune|operate|enter|thin|reseed|mix|increase|decrease|reduce|raise|"
    r"lower(?!\s+cap\b)|spread(?!\s+rate\b)|water(?!\s+(?:storage|depth|content|potential|balance|capacity|volume|needed|deficit)\b)|"
    r"harvest(?!\s+index\b)|plant(?![-\s]+(?:population|density|available)\b)|seed(?![-\s]+(?:rate|mass|count|cost|tkw|quality|germination)\b)|"
    r"feed(?!\s+(?:conversion|intake|mass|rate|cost)\b)|récoltez|semez|plantez|fauchez|conduisez|pâturez|nourrissez)"
)


def information_request_kind(text: str) -> str | None:
    """Own a complete explanation, record method or pre-decision checklist.

    This describes the work requested, not its agronomic topic or the truth of
    an answer. In particular, an interval comparison is not harvest permission,
    and recording observations is not diagnosing the crop. Unconsumed requests
    retain ordinary decision handling. Output evidence/authority checks still
    apply even when the user only requested information.
    """
    text = ' '.join(text.casefold().split())
    text = re.sub(r"\bvs\.(?=\s)", 'versus', text)
    from agronomy_agent.map_component_interpretation import is_map_component_explanation_question
    if is_map_component_explanation_question(text):
        return None  # Supplied mapped attributes have an existing source-bound owner.
    text = re.sub(r"^(?:please\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?", '', text)
    # A training/purpose wrapper is context, never a waiver of later actions.
    text = re.sub(r"^for (?:a |the )?(?:[a-z-]+\s+){0,3}(?:training|checklist|notebook),\s*", '', text)
    # A closed declined-prescription sentence is a constraint on the output,
    # not a request for a rate. Keep every other sentence for scope checking.
    text = re.sub(r"(?:^|(?<=[.!?;]))\s*(?:avoid prescribing|do not prescribe|do not recommend) "
        r"a (?:(?:universal|field|application|amendment)\s+)*rate[.!?;]*(?=\s|$)", '', text)
    # A nominal process subject in a declarative premise is not an imperative.
    text = re.sub(r"(^|[.!?;]\s*)spray drift(?=(?:\s+(?:and|or)\s+[a-z-]+(?: [a-z-]+){0,3})?"
        r"\s+(?:crosses|moves|occurs|affects|is|are)\b)", r'\1drift', text)
    if re.search(r"\b(?:then|also)\b", text) or has_action_directive(text):
        return None
    record = r"(?:my|the) (?:(?:dated|saved) )?(?:scouting (?:observations?|notes?|records?)|field (?:notes?|records?))"
    if re.fullmatch(
        rf"(?:use {record} to (?:summarize|summarise) what i saw|"
        rf"(?:summarize|summarise) {record})"
        r"(?:,? (?:and )?where and when i saw it)?"
        r"(?:,? and what remains unknown)?[.!?]*", text,
    ):
        return "field_record_summary"
    normal = r"(?:(?:an?|the) )?(?:seasonal |long[- ]term )?climate normals?"
    forecast = (r"(?:(?:an?|the) )?(?:next week['’]s |short[- ]term )?"
                r"(?:weather )?forecasts?(?: for next week)?")
    if re.fullmatch(
        rf"(?:compare|contrast|distinguish) (?:{normal} (?:with|and|from|against) {forecast}|"
        rf"{forecast} (?:with|and|from|against) {normal})"
        r"(?: (?:in|for) (?:seasonal planning|planting advice))?[.!?]*", text,
    ):
        return "explanation"
    if re.search(r"\b(?:today|tomorrow|tonight|currently|now|how much|how many)\b", text):
        return None
    # These are requested commitments, including embedded ones after 'explain'
    # or 'tell me'. Do not mistake an explanation prefix for their authority.
    if re.search(
        r"\b(?:diagnose|prescribe|recommend|authorize|approve|choose|select|tell|"
        r"apply|spray|irrigate|fertilize|harvest|graze|enter|mix|till|drive)\b|"
        r"\b(?:safe|legal|permitted|allowed|registered|best|appropriate|required|suitable|optimal|recommended)\b",
        re.sub(r"\btank[- ]mix\b", 'tank mixture', text),
    ):
        return None
    # A request may cite a conceptual framework as the explanation's lens.
    # Only consume the nominal lens; arbitrary 'use ...' instructions do not
    # acquire this scope.
    text = re.sub(r"^use (?:the |a |an )?(?:[a-z-]+\s+){1,6}to explain\b", 'explain', text)
    clauses = [part.strip() for part in re.split(
        r"[!?;]|\.(?=\s|$)|,\s*(?=(?:does|which|what)\b)|,?\s+and\s+(?=(?:explain|describe|define|compare|contrast|distinguish|does)\b)", text,
    ) if part.strip()]
    kinds: list[str] = []
    contextual = False
    for index, clause in enumerate(clauses):
        # Declarative context may precede, but cannot follow, the owned task.
        if not kinds and index < len(clauses) - 1 and re.fullmatch(
            r"(?:(?:an?|the)\s+)?[a-z][a-z -]{0,90}\s+"
            r"(?:is|are|was|were|has|have|points?|veers?|shows?|reports?|says?|crosses|handles|intersects)\s+[^!?;]+", clause,
        ) and not re.search(r"\b(?:should|must|please|to|whether)\b", clause):
            contextual = True
            continue
        if re.fullmatch(
            r"(?:for (?:an? |the )?[a-z][a-z0-9 .-]{0,110} comparison,\s*)?"
            r"(?:retrieve|find|summarize|summarise) (?:the )?(?:(?:analogue|regional|source|published) )?"
            r"(?:context|evidence|information) (?:for|about|on) [a-z0-9][a-z0-9 -]{0,100}", clause,
        ) and not re.search(r"\b(?:and|or|then|also|should|must|can|could|please|to)\b", clause):
            kinds.append('source_context')
            continue
        source_subject = re.search(r"\b(?:map|survey|classification|dataset|layer|grid|inventory)\b", text)
        inference = re.fullmatch(r"does (?:that|this|it) (?:prove|guarantee|confirm|establish) (.+)", clause)
        if source_subject and inference:
            proposition = re.sub(r"(?:[a-z-]+ ){1,3}and (?:[a-z-]+ ){1,3}(?=(?:conditions|properties)\b)",
                'named ', inference[1])
            if not has_unqualified_followup('Explain ' + proposition):
                kinds.append('source_context')
                continue
        if source_subject and re.fullmatch(r"does (?:this|that|the) (?:product|dataset|survey|map|layer) "
                r"(?:cover|include) (?:all of|the whole of|all) [a-z][a-z -]{0,60}", clause):
            if not re.search(r"\b(?:and|or|then|also|should|must|can|could|to|my|our|your)\b", clause):
                kinds.append('source_context')
                continue
        if re.fullmatch(r"which (?:[a-z-]+ )?records and (?:the )?retention period (?:are|is) relevant", clause):
            kinds.append('regulatory_information')
            continue
        if re.fullmatch(r"(?:which|what) (?:evidence|source|record) should (?:control|govern|inform) "
                r"(?:the )?(?:field|reported|measured) (?:result|estimate|value)", clause):
            kinds.append('source_context')
            continue
        if re.fullmatch(r"which (?:design|experimental|statistical) assumption is (?:challenged|violated|tested)", clause):
            kinds.append('study_design')
            continue
        records = re.match(r"(?:which|what) records (?:let|help|allow) (?:an? |the )?"
            r"(?:adviser|advisor|grower|scout) (?:distinguish|compare|reconcile|trace|verify|check)\s+", clause)
        if records and not has_unqualified_followup('Explain ' + clause[records.end():]):
            kinds.append('record_method')
            continue
        study = re.fullmatch(
            r"why (?:might|would|should|can|could)\s+(.+?)\s+be\s+"
            r"(?:tested|studied|compared|measured|evaluated)\s+(.+)", clause,
        )
        if study:
            if contextual or re.search(
                r"\b(?:my|our|your|i|we|you|me|this|these|those|then|also|to|should|must|please)\b", ' '.join(study.groups()),
            ) or has_unqualified_followup('Explain ' + study[2]):
                return None
            kinds.append('study_design')
            continue
        if re.search(r"\b(?:rates?|doses?|dosage)\b", clause):
            return None  # Other quantity teaching has its complete typed scope.
        if re.search(
            r"\b(?:interval|phi|rei|label|registration|buffer(?: zone)?)\s+(?:for|of|on|in|with)\b", clause,
        ):
            return None  # An exact applicable restriction needs its own authority.
        # A document's delivery location qualifies the reader, not an action
        # or the meaning of its term. Consume only this complete nominal tail;
        # a later permission or prescription still fails whole-request checks.
        document_meaning = re.fullmatch(
            r"what does ([a-z-]+(?: [a-z-]+){0,5}) mean (?:on|in) (?:an?|the) "
            r"(?:document|label|record|report) (?:sent|addressed|provided) to "
            r"(?:my|our|the) (?:[a-z-]+ ){0,3}(?:farm|field|office)", clause,
        )
        if document_meaning:
            clause = 'define ' + document_meaning[1]
        meaning = re.fullmatch(r"what does ([a-z-]+(?: [a-z-]+){0,11}) (?:mean|do|regulate|stand for)", clause)
        definition = re.fullmatch(r"what (?:is|are) (.+)", clause)
        if meaning or definition:
            clause = 'define ' + (meaning or definition)[1]
        embedded = re.fullmatch(r"(?:explain|describe) what ([a-z-]+(?: [a-z-]+){0,11}) (?:is|means)", clause)
        if embedded:
            clause = 'define ' + embedded[1]
        definition_head = re.match(r"(?:define|explain|describe)\s+(.+)", clause)
        restriction = r"(?:phi|rei|buffer zones?|(?:pre[- ]?harvest|restricted[- ]?entry) interval)"
        if definition_head and re.search(rf"\b{restriction}$", definition_head[1]) and not re.fullmatch(
            rf"(?:(?:an?|the)\s+)?{restriction}", definition_head[1],
        ):
            return None
        if re.search(
            r"\bthe\s+(?:pesticide|herbicide|fungicide|insecticide|product|treatment|tank[- ]mix)\s+(?:for|on|in|that)\b", clause,
        ):
            return None
        comparison = re.fullmatch(
            r"(?:(?:compare|contrast|distinguish)\s+|(?:explain|describe) (?:the )?differences? between )"
            r"(.+?)\s+(?:from|with|and|versus|vs\.?)\s+(.+)", clause)
        if comparison:
            # Nominal concept operands, not selection/ranking of treatments.
            forbidden = r"\b(?:products?|treatments?|varieties|options?|rates?|doses?|programs?|using|based|to|that|which|whether|if|when|is|are|can|should|must|and|or|my|our|your|i|we|you|me|needed|need|responsible)\b"
            operands = [re.sub(r"\b[a-z-]+ or [a-z-]+ (?=(?:concepts?|traits?|properties|processes?|intervals?|thresholds?|levels?)\b)",
                'coordinated', operand) for operand in comparison.groups()]
            if not contextual and all(re.fullmatch(r"(?:an? |the )?[a-z-]+(?: [a-z-]+){0,9}", operand)
                   and not re.search(forbidden, operand) for operand in operands):
                kinds.append('explanation')
                continue
            return None
        implication = re.fullmatch(r"what does ([a-z-]+(?: [a-z-]+){0,6}) imply for (.+)", clause)
        if implication:
            clause = 'explain ' + implication[1] + ' ' + implication[2]
        if re.match(r"(?:explain|describe|define)\s+", clause):
            if contextual or re.search(
                r"\b(?:my|our|your|i|we|you|me|needed|need|responsible)\b|"
                r"\b(?:this|these|that|those)\s+(?:field|farm|crop|plants?|roots?|leaves|lesions?|symptoms?|sample|test)\b", clause,
            ):
                return None
            if re.search(r"\b(?:how to|whether|to\s+(?!explain\b)|should|must|please)\b", clause) or re.match(
                r"(?:explain|describe)\s+(?:which|what|when)\b", clause,
            ):
                return None
            # 'between X and Y' owns a nominal pair; a later command remains.
            scoped = re.sub(r"\bbetween [a-z-]+ and [a-z-]+\b", 'between the subjects', clause)
            if has_unqualified_followup(scoped):
                return None
            kinds.append('explanation')
            continue
        record_head = re.match(
            r"how (?:should|can|would) (?:i|we|an? (?:adviser|advisor|scout|grower)) "
            r"(?:organize|organise|store|record|document)\s+", clause)
        checklist_head = re.match(
            r"(?:what (?:should|must) (?:an? |the )?(?:adviser|advisor|scout|grower) (?:assess|check|record|consider)|"
            r"what (?:observations|records|information|factors|checks) should (?:an? |the )?(?:adviser|advisor|scout|grower) (?:record|assess|check|consider))\s*", clause)
        if record_head or checklist_head:
            head = record_head or checklist_head
            remainder = clause[head.end():]
            if (not remainder or re.search(r"\b(?:to|can|could|should|must|would|please|whether)\b", remainder)
                    or has_unqualified_followup('Explain ' + remainder)):
                return None
            if record_head and not re.search(r"\b(?:observations?|records?|dates?|notes?|scouting|samples?|results?)\b", remainder):
                return None
            if checklist_head and re.search(r"\b(?:spill|poison\w*|exposure|emergency|injured|injury)\b", text):
                return None  # Acute incidents retain their response obligations.
            kinds.append('record_method' if record_head else 'evidence_assessment')
            continue
        return None
    kind = kinds[0] if kinds and len(set(kinds)) == 1 else None
    causal = re.match(r"(?:explain|describe) (?:why|how)\b", text)
    concept = (causal or re.search(r"\b(?:concepts?|meanings?|definitions?|differences?|relationships?|roles?|mechanisms?|process(?:es)?|methods?|models?|influences?|effects?)\b", text)
        or re.fullmatch(r"(?:explain|describe) what .+ (?:is|means)[.!?]*", text))
    forecast_read = (re.match(
        r"(?:explain|describe)\b|what (?:is|are) "
        r"(?:(?:the|this|that)\b|(?:this|next) (?:week|month)['’]s (?:weather )?forecasts?\b)", text)
        and re.search(r"\bforecasts?\b", text) and not concept)
    forecast_reference = (re.search(r"\b(?:the|this|that)\s+(?:weather\s+)?forecast\b", text)
        and not re.fullmatch(r"define (?:(?:an?|the) )?(?:weather )?forecasts?[.!?]*", text))
    current_data = re.search(
        r"\b(?:current|latest|recent|local)\b[^.!?;]{0,60}\b"
        r"(?:forecasts?|weather|conditions|observations|measurements|prices|markets?|alerts?|reports?|labels?|requirements)\b", text,
    )
    if kind == 'explanation' and (current_data or forecast_read or forecast_reference):
        return 'source_context'  # Describing current data still requires its source.
    return kind


def proposition_assertion_status(prefix: str, suffix: str = '') -> str:
    """Classify adjacent assertion scope without certifying a fact as true."""
    if re.search(
        r"\b(?:(?:(?:it is |is )?(?:false|incorrect|untrue|not true)(?: to (?:say|claim|state|suggest))?|"
        r"not the case) that|(?:does not|doesn['’]t) (?:mean|establish|confirm|demonstrate|prove|show|support)(?: that)?|"
        r"(?:cannot|can['’]t|do not|don['’]t|never) (?:assume|say|confirm)(?: that)?)\s+(?:the\s+)?$",
        prefix, re.I,
    ) or re.match(r"\s*(?:(?:products?|estimates?|measurements?|data)\s+)?[\"'’”]?\s*(?:is|was)\s+(?:false|incorrect|untrue)\b", suffix, re.I):
        return 'negated'
    if re.search(r"\b(?:unknown|unclear|uncertain|unconfirmed|unverified|not (?:known|clear|established|confirmed))\s+"
            r"(?:whether|if|that)\s+(?:the\s+)?$|\b(?:whether|if|assuming|supposing|suppose(?: that)?)\s+$", prefix, re.I):
        return 'unknown'
    if re.search(r"\b(?:does|do|can|could|may|might|would|should|must|is|are|is it true that|is it the case that)\s+$", prefix, re.I) or re.match(r"\s*(?:data\s*)?\?", suffix):
        return 'questioned'
    return 'asserted'


def has_action_directive(text: str) -> bool:
    # An embedded request for instructions remains an operational request
    # even when its action verb is unfamiliar to the domain vocabulary.
    if re.search(r"\b(?:with|including|plus|along with|as well as)\s+(?:(?:an?|the|detailed|practical|step[- ]by[- ]step)\s+)*"
            r"(?:instructions|directions|steps|an? action plan)\b", text, re.I):
        return True
    start = r"(?:^|[.!?;,]\s*|\b(?:and|also|then)\s+)"
    pattern = (start + r"(?:please\s+)?(?:(?P<verb>" + FIELD_ACTION_PATTERN +
        r"|proceed|go ahead|carry out|execute|perform|implement|undertake|turn|begin|commence)\b|"
        r"(?:give|provide|write|show|develop|create|design)\b[^.!?;]{0,55}\b(?:instructions|directions|steps|plan)\b)")
    for match in re.finditer(pattern, text, re.I):
        if (match['verb'] and match['verb'].lower() == 'lower'
                and _closed_nominal_budget_data_clause(text, match.start('verb'))):
            continue
        # In a single finite causal question, "How can X supply ... and
        # increase Y?" shares the auxiliary and subject. Exempt only that
        # weak predicate span; later commands must still be inspected.
        prefix = text[:match.start()]
        if (match['verb'] and match['verb'].lower() in {'increase', 'decrease', 'reduce', 'raise', 'lower'}
                and re.match(r'(?:and|also)\s+(?!please\b)', match.group(), re.I)
                and re.match(r'^\s*(?:how|why)\s+(?:can|could|do|does)\b', prefix, re.I)
                and not re.search(r'[.!?;,]|\bthen\b', prefix, re.I)):
            continue
        return True
    return False


def _closed_nominal_budget_data_clause(text: str, start: int) -> bool:
    """Distinguish one quantified budget input from an instruction to lower.

    This exception needs an explicit arithmetic task and one complete money
    value with an area basis. Modifiers, extra quantities and other work stay
    subject to the ordinary action checks.
    """
    if not re.search(r"\b(?:calculate|compute|work out)\b", text, re.I):
        return False
    if not re.search(r"\b(?:partial[- ]budget|net change)\b", text, re.I):
        return False
    clause = re.split(r"[!?;]|\.(?=\s|$)|,\s*(?!\d)|\b(?:and|then|also)\b", text[start:], maxsplit=1, flags=re.I)[0].strip()
    return bool(re.fullmatch(
        rf"lower\s+costs?\s+(?:(?:is|are|was|were|of)\s+|[:=]\s*)?"
        rf"(?:CAD|USD|\$)\s*{NUMBER}\s*(?:/|per\s+){AREA_UNIT_PATTERN}",
        clause, re.I,
    ))


def explicitly_unspecified_management_task(text: str) -> bool:
    """A deictic frequency question explicitly says its activity is unknown.

    This only selects a clarification obligation. It grants no operation,
    quantity or product-authority exception, and consumes the whole request.
    """
    return bool(re.fullmatch(
        r"\s*(?:how often|when) should (?:I|we) do (?:it|that)(?: then)?[?!.]\s*"
        r"(?:this is (?:the|a) [a-z -]{1,80}field from before,? but )?"
        r"(?:I|we) (?:still )?(?:have not|haven['’]t) (?:said|specified|identified) "
        r"(?:which|the) (?:(?:crop|soil),?\s*(?:or\s+)?)?(?:(?:crop|soil),?\s*(?:or\s+)?)?"
        r"(?:job|task|operation)(?: (?:I|we) mean)?[.!?]*\s*", text, re.I))


def analytical_request_kind(text: str) -> str | None:
    """Own a whole analytical task without turning its topic into an action.

    Heads describe an analysis; objects establish its measurement, sampling,
    comparison, economic or forecast role. Context must be declarative and
    every requested clause must be owned. This selects content only: it is
    neither evidence of a field condition nor authority for an operation.
    """
    text = ' '.join(text.casefold().split())
    if has_action_directive(text):
        return None
    # Preserve unknown action/permission clauses even inside a method request.
    if re.search(
        r"\b(?:apply|spray|fertilize|irrigate|prescribe|recommend|authorize|approve|"
        r"permitted|registered|legal|shorten|lengthen|tighten|increase the rate|set the rate)\b|"
        r"\b(?:be|is|are|should be|can be)\s+(?:applied|sprayed|used|mixed)\b|"
        r"\b(?:what|which)\s+(?:product|dose|application rate)\b", text,
    ):
        return None
    clauses = [part.strip() for part in re.split(
        r"[!?;]|\.(?=\s|$)|,\s*(?=(?:what|which|how|should|can)\b)", text,
    ) if part.strip()]
    kinds = []
    requested = False
    for clause in clauses:
        clause = re.sub(r"^(?:please\s+)?(?:(?:can|could) you\s+)?", "", clause)
        kind = None
        head = None
        if re.match(r"how (?:would|could|can|should) (?:i|we|you|one) (?:estimate|measure|sample|count)\b", clause):
            head = re.match(
                r"how (?:would|could|can|should) (?:i|we|you|one) (?:estimate|measure|sample|count)\s+"
                r"(?:(?:an?|the)\s+)?(?:(?!(?:in|across|from|without|using|with|over|of|at|between|to|for)\b)[a-z-]+\s+){0,3}"
                r"(?:population|density|stand|incidence|severity|counts?|samples?)"
                r"(?=$|\s+(?:in|across|from|without|using|with|over|of|at|between)\b)", clause)
            if head:
                kind = "sampling_design"
        elif re.match(r"how (?:do|can|could|would|should) (?:i|we|you|one) compare\b", clause):
            head = re.match(
                r"how (?:do|can|could|would|should) (?:i|we|you|one) compare\s+"
                r"(?:(?:these|those|the)\s+)?"
                r"(?:(?!(?:and|or|to|for|with|between|across|in|from)\b)[a-z-]+\s+){0,4}"
                r"(?:measurements?|readings?|observations?|counts?|results?|values?)\b", clause)
            if head and (not clause[head.end():].strip()
                         or re.match(r"\s+(?:between|across|in|from|with)\b", clause[head.end():])):
                kind = "measurement_comparison_method"
        elif re.match(r"can\b", clause):
            head = re.match(r"can\s+([^!?;]+?)\s+be\s+(?:directly\s+)?(?:compared|interpreted|averaged|combined|regarded|treated)\b", clause)
            if head and re.search(r"\b(?:concentrations?|measurements?|values?|samples?|counts?|results?|estimates?)\b", head[1]):
                if not re.search(r"\b(?:i|we|you|me|that|which|who|whether|if|when|because|is|are|has|have|show|shows|can|could|may|should|must|would|please|choose|select|set|use|start|stop|change|make|give|tell|then|also)\b", head[1]):
                    kind = "measurement_interpretation"
        elif re.match(r"(?:what|which) (?:additional )?(?:evidence|observations|information|records|checks|factors|data)\b", clause):
            head = re.match(r"(?:what|which) (?:additional )?(?:evidence|observations|information|records|checks|factors|data)\b", clause)
            # An inquiry about an inference's evidential basis is analytical.
            # Evidence needed for an actual irrigation, containment or other
            # field decision still belongs to that domain's complete method.
            if re.match(r"\s+(?:determines?|explains?|constrains?|affects?)\s+"
                    r"(?:[a-z-]+\s+){0,3}(?:risk|inference|interpretation|uncertainty)\s+"
                    r"(?:beyond|from|given)\b", clause[head.end():]):
                kind = "evidence_method"
        elif re.match(r"what should (?:the |an? )?(?:efficacy|response|comparator|comparison|statistical) analysis (?:account for|consider|include)\b", clause):
            head = re.match(r"what should (?:the |an? )?(?:efficacy|response|comparator|comparison|statistical) analysis (?:account for|consider|include)\b", clause)
            kind = "response_analysis"
        elif re.match(r"what should (?:an? |the )?(?:defensible |reliable |supported )?(?:diagnosis|identification) (?:request|require|document|establish)\b", clause):
            head = re.match(r"what should (?:an? |the )?(?:defensible |reliable |supported )?(?:diagnosis|identification) (?:request|require|document|establish)\b", clause)
            kind = "diagnostic_evidence"
        elif re.match(r"what does (?:this|that) (?:show|mean|imply)\b", clause):
            head = re.match(r"what does (?:this|that) (?:show|mean|imply)\b", clause)
            if re.search(r"\b(?:economic\w*|profit\w*|marginal|returns?)\b", text):
                kind = "economic_interpretation"
        elif re.match(r"(?:explain|describe) (?:an? |the )?(?:defensible |appropriate |decision )*(?:interpretation|meaning)\b", clause):
            head = re.match(r"(?:explain|describe) (?:an? |the )?(?:defensible |appropriate |decision )*(?:interpretation|meaning)\b", clause)
            if re.search(r"\b(?:forecasts?|probability|chance|predictions?)\b", text):
                kind = "forecast_interpretation"
        elif re.match(r"should (?:an? |the )?model (?:book|count|record|treat|include)\b", clause):
            head = re.match(r"should (?:an? |the )?model (?:book|count|record|treat|include)\b", clause)
            if re.search(r"\b(?:forecast\w*|predict\w*|observ\w*|received|measur\w*)\b", text):
                kind = "forecast_bookkeeping"
        if kind and head:
            # The matched analytical predicate owns its subject. A coordinated
            # measurement subject can contain depths/units; inspect everything
            # after that predicate for independent requests and decision modals.
            remainder = clause[head.end():]
            if kind in {'response_analysis', 'diagnostic_evidence'} and remainder.strip():
                return None
            if kind == 'measurement_interpretation' and remainder.strip() and not re.fullmatch(
                r"\s*(?:as\s+(?:(?:an?|the)\s+)?"
                r"(?:(?:seasonal|temporal|measured|reported|apparent|real|statistical|meaningful|relative|absolute)\s+){0,3}"
                r"(?:change|difference|trend|mean|average|estimate|measurement|concentration|stock|quantity)"
                r"(?:\s+(?:without adjustments?|with appropriate adjustments?|over time|across seasons|between samples))?|"
                r"(?:directly\s+)?(?:without|with)\s+(?:an?\s+)?adjustment)\s*", remainder,
            ):
                return None
            if kind == 'sampling_design' and (re.search(r"\bto\s+[a-z-]+\b", remainder)
                    or remainder.strip() and not re.match(r"\s*(?:in|across|from|without|using|with|over|of|at|between)\b", remainder)):
                return None
            if (has_unqualified_followup("Explain " + remainder)
                    or re.search(r"\bto\s+[a-z-]+\b", remainder)
                    or re.search(r"\b(?:should|must|ought|can|could|may|might|would|please)\b", remainder)
                    or re.search(r"\b(?:choose|select|set|use|start|stop|make|give|tell)\b", remainder)
                    or re.search(r"(?:^|[,;]|\b(?:and|then|also|to))\s*change\b", remainder)):
                return None
            requested = True
            kinds.append(kind)
            continue
        # Context precedes the requested analysis and contains a finite report,
        # not a proposal. Unknown request heads or later context fail closed.
        context_scope = re.sub(r"\b(?:and|but)\s+(?:also\s+)?(?=(?:fell|rose|increased|decreased|changed|improved|worsened)\b)", "while ", clause)
        context_scope = re.sub(
            r"\b(?:in|from|across|between)\s+(?:the\s+)?(?:treated|untreated|control|check|affected|normal|healthy)\s+and\s+"
            r"(?:treated|untreated|control|check|affected|normal|healthy)\s+(?:plots|areas|zones|samples)\b",
            "in comparator groups", context_scope,
        )
        report = re.match(
            r"(?P<subject>(?:if\s+)?(?:an?\s+|the\s+)?[a-z][a-z -]{0,75}?)\s+"
            r"(?:is|are|was|were|has|have|shows?|reports?|predicts?|indicates?|fell|falls?|rose|rises?|increases?|reduces?|drains?)\b", clause)
        subject = report['subject'] if report else ''
        nominal_subject = bool(subject and not re.search(
            r"\b(?:i|we|you|me|my|our|your|that|which|who|whether|to|please|tell|give|show|help|choose|select|recommend|use|make)\b", subject)
            and (re.match(r"^(?:if|an?|the)\b", subject)
                 or re.fullmatch(r"(?:(?:pest|insect|weed|plant|crop|treated|untreated|control|check|baseline|follow-up|population|sample|reported|measured)\s+){0,3}"
                     r"(?:counts?|measurements?|values?|samples?|results?|estimates?)", subject)))
        if (requested or re.match(r"(?:what|which|why|how|can|could|should|must|please|explain|describe)\b", clause)
                or re.search(r"\b(?:should|must|ought|may|might|would|please)\b", clause)
                or not nominal_subject
                or has_unqualified_followup("Explain " + context_scope)):
            return None
    return kinds[0] if kinds and len(set(kinds)) == 1 else None


def soil_test_repeatability_requested(text: str) -> bool:
    """A whole request for repeat-sampling comparability, not a soil map."""
    role = r"(?:locations?|depth|timing|handling|laboratory method)"
    return bool(re.fullmatch(
        r"\s*(?:(?:I|we) want to compare soil tests from (?:the )?same "
        r"(?:[a-z-]+\s+){0,3}field over time[.!?]\s*)?"
        rf"what should (?:stay|remain) consistent about sampling {role}"
        rf"(?:,?\s+(?:and\s+)?{role}){{1,5}} so (?:the|a) trend (?:is|remains) meaningful"
        r"[.!?]*\s*", text, re.I))


def seed_quality_workflow_requested(text: str) -> bool:
    """Distinguish seed-quality work from germination supplied as an operand.

    This selects a topical method only; it grants no answer or action bypass.
    A separately requested quality assessment retains its ordinary obligations.
    """
    quality_subject = r"(?:seed[- ]lots?|seed quality|germination (?:tests?|results|evidence)|germ test|cold test|accelerated aging|seed(?:ling)? vigou?r|vigou?r test)"
    topic = r"(?:germination|" + quality_subject + r")"
    if not re.search(r"\b" + topic + r"\b", text, re.I):
        return False
    arithmetic = re.search(r"\b(?:calculate|compute|convert|work out|how (?:many|much)|what seed(?:ing)? (?:rate|mass))\b", text, re.I)
    if not arithmetic or not re.search(
        rf"\b(?:seed(?:ing)? (?:rate|mass|count|population(?: density)?)|"
        rf"seeds?\s*(?:/|per)\s*(?:m[²2]|square met(?:re|er)s?)|TKW|thousand[- ]kernel|{SEED_TARGET_ROLE})\b", text, re.I
    ):
        return True
    # A germination percentage in the arithmetic does not request lot/vigor
    # selection. Inspect other explicit requests rather than the whole bag of
    # topical words; the original request remains intact for ordinary handling.
    if re.search(r"\b(?:instructions?|advice|help)\s+(?:on|for|with|about|to)\s+(?:how to\s+)?(?:(?:assess\w*|compar\w*|interpret\w*|evaluat\w*|choos\w*|select\w*)\s+(?:the\s+)?)?" + quality_subject + r"\b", text, re.I):
        return True
    head = r"(?:compare|contrast|assess|evaluate|interpret|choose|select|recommend|advise|explain|describe|check|which|what|how)\b"
    for clause in re.split(r",\s*(?!\d)|\b(?:and|then|also)\b|[!?;]|\.(?=\s|$)", text, flags=re.I):
        clause = re.sub(r"^\s*(?:(?:please\s+)?(?:can|could|would|will)\s+you\s+)?(?:please\s+)?", "", clause, flags=re.I)
        if re.match(r"how (?:many|much)\b|what seed(?:ing)? (?:rate|mass)\b", clause, re.I):
            continue
        if re.match(head, clause, re.I) and re.search(r"\b" + quality_subject + r"\b|\bwhich lot\b", clause, re.I):
            return True
    return False


def is_concept_comparison_scope(text: str) -> bool:
    """Consume one nominal comparison, without granting scope to extra commands.

    This is a structural check; personal decisions, authority, treatments and
    action intent are still checked by the shared answerability boundary.
    Unsupported multiword operands retain ordinary decision handling.
    """
    match = re.fullmatch(
        r"\s*(?:please\s+)?(?:(?:can|could)\s+you\s+)?(?:please\s+)?"
        r"(?:compare|contrast|distinguish)\s+([^.!?;]+?)(?:\s+in\s+(?:an?|the)\s+(?:sampling|scouting|survey|measurement|laboratory|statistical)\s+report)?[.!?]?\s*", text, re.I,
    )
    if match is None:
        return False
    if re.search(
        r"\b(?:rates?|doses?|thresholds?|programs?|schedules?|regimens?|spray intervals?|"
        r"products?|treatments?|options?|best|better|rank|rankings?|then|also|please)\b", match[1], re.I,
    ):
        # Rate-basis teaching has a separate whole-request contract. A nominal
        # product/treatment comparison does not establish concept-only intent.
        return False

    def nominal(phrase: str) -> bool:
        phrase = re.sub(r"^the\s+", "", phrase.strip(), flags=re.I)
        return bool(re.fullmatch(
            r"(?:[a-z][a-z-]*|"
            r"(?:soil|plant|crop|root|seed|carbon|nitrogen|phosphorus|potassium|sulfur|sulphur|nutrient|water|disease|pest|insect|weather)"
            r" (?!the\b|an?\b|my\b|our\b|your\b)[a-z-]+|"
            r"(?:(?:hybrid|variety|genetic|physical|chemical|biological|physiological|mechanical|"
            r"thermal|hydraulic|agronomic|sampling|measurement|soil|plant|crop|root|seed|water|nutrient) ){0,2}"
            r"(?:concepts?|traits?|properties|processes?|mechanisms?|principles?|"
            r"measurements?|units?|attributes?|definitions?|meanings?|characteristics?))",
            phrase, re.I,
        ))

    parts = re.split(r"\s+such as\s+", match[1], flags=re.I)
    if len(parts) > 2:
        return False
    operands = re.split(r"\s+(?:and|with|to|from|versus|vs\.?)\s+|,\s*(?:and\s+)?", parts[0], flags=re.I)
    if len(operands) < 2 or not all(nominal(part) for part in operands):
        return False
    if len(parts) == 2:
        examples = re.split(r"\s+and\s+|,\s*(?:and\s+)?", parts[1], flags=re.I)
        if not all(nominal(part) for part in examples):
            return False
    return True


def _calculation_value_is_owned(value: str, *, has_quantity: bool = False) -> bool:
    """Consume a data value, unit and bounded method qualifiers in full.

    Typed parsers still validate quantities. A recognized input name or
    preposition cannot grant ownership to arbitrary trailing instructions.
    """
    words = frozenset("""
        is are was were has have does include of with without not no the a an
        for per at in by or from over how much supplies labelled labeled
        to already including excluding all overall expected post germination
        germinated germinable viable sown seeds seed seedling seedlings stage
        before after among includes field survival
        mortality loss emergence emerge lab laboratory
        application efficiency upper lower maximum minimum base temperature
        cap caps negative values accumulation floored zero retained consecutive
        day days daily hour hours h min c f degree degrees kg g mg t tonne tonnes
        pound pounds lb lbs l litre litres liter liters cm mm m km ha hectare
        hectares ac acre acres plant plants ft square metre metres meter meters
        bu bushel bushels cad usd n p k o nitrogen phosphorus potassium
        dry mass matter grain total above ground biomass stand target product
        fertilizer nutrient removed applied volumetric water content moisture
        wet basis rate model standard conditions net irrigation percent volume
        thousand kernel weight nozzle nozzles boom tank sprayer unusable
        row rows apart average established
        cubic soil hypothetical uniform layer layers zone yielding yield
        blend arithmetic check liquid that monoammonium diammonium ammonium
        phosphate sulphate sulfate urea potash million whole farm
        gdd values one two three four five six seven eight nine ten
    """.split())
    value = re.sub(r"n['’]t\b", " not", value, flags=re.I)
    # A named material is data in this role; it does not supply analysis or
    # permission. Typed parsers must still account for every supplied quantity.
    value = re.sub(r"\bfrom\s+[a-z][a-z-]*(?=\s+label(?:l)?ed\b|\s*$)", "from product", value, flags=re.I)
    return bool(
        (has_quantity or re.search(r"\d", value))
        and re.fullmatch(r"[A-Za-z\d\s.,:%°²³₀₁₂₃₄₅₆₇₈₉/$×*+=()−-]*", value)
        and set(re.findall(r"[a-z]+", value.casefold())) <= words
    )


def _calculation_premise(part: str) -> bool:
    """Recognize input declarations; their values remain the parser's concern."""
    declarations = re.split(rf"\s+with\s+(?=(?:the\s+)?{ARITHMETIC_INPUT_ROLE_PATTERN}\b)", part, flags=re.I)
    if len(declarations) > 1:
        return all(_calculation_premise(item) for item in declarations)
    closed = (
        r"under (?:a|the) (?:simple )?incremental budget|"
        r"(?:ignoring unusable (?:tank )?volume|ignoring other nutrient credits for this arithmetic check|for this (?:product-mass )?calculation|"
        r"for a (?:teaching|hypothetical|illustrative) (?:GDD )?method|"
        r"for one day(?: in (?:an?|the) [a-z -]{1,60}field)?|for a [a-z -]{1,60}field|"
        r"(?:for|under) a uniform(?: [\d.]+ m root zone| profile)|"
        rf"(?:for|under) a {NUMBER} m root[- ]zone|"
        r"(?:for|under) a uniform[- ]profile assumption|"
        r"for a (?:(?:teaching|hypothetical|illustrative) )?standard-conditions model ETc\s*=\s*Kc\s*[×*]\s*ETo|"
        r"using (?:a )?[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*°?C base|"
        r"no (?:upper |lower |temperature )?caps?|"
        r"negative (?:values|accumulation) (?:(?:are )?floored at zero|retained)|"
        r"using (?:the [a-z '-]+ )?factor[- ]10 method|"
        r"(?:using )?(?:P|K|L/ha)\s*=\s*(?:(?:P2O5|K2O|P|K|Q|speed|spacing)|[\d.×*/()+ =-])+)")
    if re.fullmatch(closed, part, re.I):
        return True
    if re.fullmatch(rf"(?:an?|the) intervention costs?\s*(?:CAD|USD|\$)\s*{NUMBER}\s*/\s*{AREA_UNIT_PATTERN}", part, re.I):
        return True
    if re.fullmatch(rf"(?:crop|assumed selling) price\s*(?:is|of|:)?\s*(?:CAD|USD|\$)\s*{NUMBER}\s*/\s*{YIELD_UNIT_PATTERN}", part, re.I):
        return True
    if re.fullmatch(r"(?:but )?(?:the )?[a-z][a-z /²-]{0,55} (?:is|are) (?:not supplied|unknown|missing)", part, re.I):
        return True
    if re.fullmatch(r"(?:the )?unusable (?:tank )?volume (?:is |of )?(?:unknown|missing|not supplied)", part, re.I):
        return True
    if not re.search(r"\d", part):
        return False
    named = re.fullmatch(
        rf"(?:the\s+)?(?P<role>{ARITHMETIC_INPUT_ROLE_PATTERN})\s+(?P<value>[^!?;]+)",
        part, re.I,
    )
    if named:
        value = re.sub(r"^(?:(?:is|are|was|were|of)\b\s*|[:=]\s*)", "", named['value'], count=1, flags=re.I).strip()
        if not re.match(rf"(?:(?:CAD|USD|\$)\s*)?{NUMBER}", value, re.I):
            return False
        # A closed magnitude or whole-farm label remains parser-owned data;
        # canonical validation still clarifies unsupported notation/bases.
        money = rf"(?:(?:CAD|USD|\$)\s*)?{NUMBER}(?:\s*(?:billion|million|thousand|[kmb]))?"
        if re.fullmatch(MONEY_FLOW_ROLE_PATTERN, named['role'], re.I):
            return bool(re.fullmatch(rf"{money}(?:\s*(?:/|per\s+){AREA_UNIT_PATTERN})?(?:\s+(?:total for (?:the )?(?:whole )?farm|for (?:the )?whole[- ]farm|whole[- ]farm total))?", value, re.I))
        if re.fullmatch(BALANCE_SHEET_ROLE_PATTERN, named['role'], re.I):
            return bool(re.fullmatch(money, value, re.I))
        if re.fullmatch(YIELD_ROLE, named['role'], re.I):
            return bool(re.fullmatch(rf"{NUMBER}\s*{YIELD_UNIT_PATTERN}\s*(?:/|per\s+){AREA_UNIT_PATTERN}", value, re.I))
        return _calculation_value_is_owned(value)
    # Value-first biomass declarations retain explicit named roles. Do not
    # admit arbitrary crop prose or drop a later operational clause.
    biomass_role = r"(?:grain dry (?:mass|matter)|total above[- ]ground dry (?:biomass|mass|matter))"
    mass = rf"{NUMBER}\s*(?:kg|tonnes?|t|pounds?|lbs?)(?:\s*(?:/|per\s+)(?:ha|hectares?|ac|acres?))?"
    if re.fullmatch(rf"(?:(?:a|the) (?:(?:teaching|example|hypothetical) )?crop has )?{mass}\s+(?:of\s+)?{biomass_role}", part, re.I):
        return True
    # Bound the grammatical subject to the arithmetic owners' data roles.
    # Imperatives such as 'Mulch beds' have no supported input subject.
    subject = (
        r"(?:(?:these are measured values:\s*)?(?:an? |the )(?:[a-z\d,.-]+ ){0,4}"
        r"(?:field(?: plan)?|fertilizer(?: product)?|soil moisture probe|sprayer(?: tank)?|nozzle|"
        r"crop budget|soybean count|blend|mixture|plan|budget|example|prescription)|"
        r"seed TKW|soybeans in (?:an?|the) [a-z -]{1,60}field|grain (?:dry )?mass|"
        r"total above-ground dry biomass|Kc|ETo|"
        r"(?:measured )?volumetric water|travel speed|it)"
    )
    declaration = re.fullmatch(r"(?P<subject>" + subject + r")\s+(?:is|are|was|were|has|have|contains|requires|delivers|weighs|supplies|covers|receives|targets|reports|found|totals|needs|uses|calls for|travels at)\b\s+(?P<value>[^!?;]+)", part, re.I)
    if declaration:
        value = declaration['value']
        if re.search(r"\bsprayer(?: tank)?$", declaration['subject'], re.I):
            # A reported sprayer rate is data, not an imperative to apply.
            # Keep this grammatical role local to the explicit subject.
            value = re.sub(r"^applying\s+", "", value, flags=re.I)
            value = re.sub(r"\s+in (?:an?|the) (?:[A-Z][a-z]+ ){1,3}(?:[a-z]+ )?field$", "", value)
        return _calculation_value_is_owned(value)
    # Shared-subject or verbless input declarations following a comma/'and'.
    shared = re.fullmatch(
        r"(?:assumes\s+[^!?;]+|each flowing\s+[^!?;]+|"
        r"(?:(?:upper|lower) cap|base(?: temperature)?|target field capacity|field capacity|wilting point|"
        r"rooting depth|nozzle spacing)\s+[^!?;]+|"
        r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)%(?: application efficiency| germination)|"
        r"[+-]?(?:\d+(?:\.\d+)?|\.\d+) kg (?:P|N|K)/ha (?:applied|removed)|"
        r"a [\d.,]+ ha zone yielding [\d.,]+ bu/ac|"
        r"[+-]?[\d.,]+(?: for (?:[a-z]+|\d+) consecutive days)?|"
        r"[+-]?[\d.,]+(?: t at [\d.,]+%|%) wet-basis moisture)", part, re.I)
    if shared:
        # The broad shared-subject alternatives also need full value ownership.
        value = re.sub(r"^(?:assumes|each flowing|(?:(?:upper|lower) cap|base(?: temperature)?|target field capacity|field capacity|wilting point|rooting depth|nozzle spacing))\s+", "", part, flags=re.I)
        return _calculation_value_is_owned(value)
    return False


def topic_is_supplied_arithmetic_context(text: str, question_type: str) -> bool:
    """Qualify a topic as operands rather than an added management request.

    Only completeness/fallback selection uses this result. It neither executes
    partial arithmetic nor grants numeric support, field authority or a bypass.
    Unknown quantities, topic requests and references to using the result keep
    the ordinary management checks.
    """
    topics = {
        'soil_water': r"\b(?:water|irrigat\w*|drain\w*|rain\w*|wetness|moisture|ET[oc]?|rooting depth|water table)\b",
        'fertility_rate': r"\b(?:fertili[sz]\w*|nutrient\w*|nitrogen|phosphorus|potassium|manure|compost|credits?|product|rates?|placement|soil tests?|yield goal|N|P|K|P2O5|K2O)\b",
    }
    topic = topics.get(question_type)
    if topic is None:
        return False
    from agronomy_agent.decision_route import build_decision_route_state
    state = build_decision_route_state(text, question_type)
    if (state.decision == question_type or state.capsule is None
            or not state.capsule.is_specific):
        return False  # A distinct, concrete requested task must own the method.
    head = r"\b(?:calculate|compute|convert|work out|how (?:many|much))\b"
    parts = re.split(r",\s*(?!\d)|\b(?:and|then|also)\b|[!?;]|\.(?=\s|$)|\bwith\s+(?=(?:instructions?|advice|help)\b)", text, flags=re.I)
    arithmetic = []
    other = []
    found_head = False
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.search(head, part, re.I):
            arithmetic.append(part)
            found_head = True
        elif _calculation_premise(part):
            arithmetic.append(part)
        else:
            other.append(part)
    if not found_head or not other:
        return False
    for part in other:
        if (any(re.search(pattern, part, re.I) for pattern in topics.values()) or re.search(r"\d", part)
                or re.search(r"\b(?:it|this|that|these|those|calculated|apply|use|proceed)\b", part, re.I)):
            return False
    # The maintained planner must recognize the complete arithmetic fragment;
    # merely containing "calculate" does not establish a supplied calculation.
    from agronomy_agent.tool_planner import plan_tools
    plan = plan_tools('. '.join(arithmetic) + '.')
    return bool(plan.status == 'ready' and len(plan.invocations) == 1
                and plan.invocations[0].tool_id == 'agronomic_calculator')


def has_unqualified_followup(text: str, *, calculation: bool = False) -> bool:
    """Require each later request clause to fit the bypass's declared purpose.

    Unknown trailing instructions use ordinary decision handling. This is a
    positive scope check, so a new imperative need not be added to a verb list.
    Decimal points do not divide sentences.
    """
    if calculation and unit_owned_area_mass_total(text) is not None:
        return False  # The same full operand/request grammar owns parser scope.
    if calculation and supplied_depletion_request(text) is not None:
        return False  # Supplied p and TAW, with only the owned scope explanation.
    head = (r"(?:calculate|compute|convert|work out|how (?:many|much)|"
            r"what (?:is|are|yield(?: increase)? breaks even|seed(?:ing)? (?:rate|mass)))\b" if calculation else
            r"(?:why|how|explain|describe|define|what|which|compare|contrast|distinguish)\b")
    wrapper = r"(?:(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+|I['’]d like you to\s+)?"
    first = re.search(r"(?:^\s*|[.!?;]\s*)" + wrapper + head, text, re.I)
    if first is None and not calculation:
        return False
    if calculation:
        candidate = first or re.search(r"\b" + head, text, re.I)
        if candidate is not None:
            prefix_parts = [part.strip() for part in re.split(
                r",\s*(?!\d)|\b(?:and|then|also)\b|[!?;]|\.(?=\s|$)", text[:candidate.start()], flags=re.I) if part.strip()]
            if prefix_parts and not all(_calculation_premise(part) for part in prefix_parts):
                return True
            first = candidate
        # No recognized head does not prove completeness: inspect the entire
        # parser-owned operand-bearing request instead of returning early.
    if calculation and re.search(r"\b(?:gdd|growing degree[- ]days?)\b", text, re.I):
        # The GDD parser validates structured facts, including duplicate keys,
        # unknown fields and malformed objects. Do not treat JSON as prose
        # commands; retain text following a valid object for the scope check.
        position = text.find('{')
        if position >= 0:
            try:
                _, consumed = json.JSONDecoder().raw_decode(text[position:])
            except (ValueError, RecursionError):
                return False  # The owned GDD path returns its invalid-data clarification.
            remainder = text[position + consumed:]
            if '{' in remainder:
                return False  # Multiple objects are rejected by the GDD parser.
            prefix = re.sub(r"\bsupplied facts:\s*$", "", text[:position], flags=re.I)
            text = prefix + "Named input data" + remainder
    clauses = [clause.strip() for clause in re.split(r"[!?;]|\.(?=\s|$)", text[first.start() if first is not None else 0:]) if clause.strip()]
    if clauses and not calculation:
        clauses[0] = re.sub(r"^" + wrapper, "", clauses[0], count=1, flags=re.I)
    allowed = (r"(?:state (?:the )?(?:units|assumptions|arithmetic limits)|explain (?:its|the|their) (?:limits|limitations|boundaries))\b"
               if calculation else head)
    data_declaration = (
        r"(?:(?:but )?(?:I|we) (?:have not|haven['’]t) (?:supplied|provided) (?:the )?[a-z /²-]{1,80}|"
        r"(?:do not|don['’]t|never) (?:infer (?:crop|growth) stage|state (?:the )?weather provenance)|"
        r"[a-z][a-z /²-]{0,55} (?:is unknown|are unknown|is missing|are missing|is not supplied|are not supplied|has not been supplied|have not been supplied)|Named input data|(?:give|show|state) (?:the )?final (?:value|answer)(?: and units| in (?:kg/ha|lb/ac|GDD))|"
        r"this is (?:a math|an arithmetic|a numerical) exercise(?:,? not a rate recommendation)?|"
        r"(?:for this calculation,? )?field survival is [\d.,]+% of (?:all seeds sown|germinated seeds)|"
        r"the laboratory germination is [\d.,]+%|"
        r"explain whether (?:that|this) (?:alone )?(?:tells|establishes) (?:me )?plant[- ]available water)"
    )
    for clause in clauses[1:]:
        owned_output = r"(?:please\s+)?" + allowed
        if calculation:
            owned_output += r"(?:\s+and\s+(?:the\s+)?(?:units|assumptions|arithmetic limits))*"
        if (re.fullmatch(owned_output, clause, re.I) if calculation
                else re.match(owned_output, clause, re.I)):
            continue
        if calculation and re.fullmatch(data_declaration, clause, re.I):
            continue
        if (calculation and re.search(r"\bseed(?:ing)? (?:rate|mass)\b", clauses[0], re.I)
                and re.fullmatch(r"(?:calculate|compute) (?:the )?(?:overall )?seed(?:ing)? (?:rate|mass)", clause, re.I)):
            continue
        return True
    if calculation:
        premise = (r"(?:(?:an?\s+)?[+-]?(?:\d|\.\d)|(?:(?:the|an?)\s+)?(?:"
            r"measured tkw|field area|"
            r"measured volumetric water|kc|eto|net depth|application efficiency|travel speed|nozzle spacing|unusable (?:tank )?volume|radius|diameter|"
            r"grain dry (?:mass|matter)|total above[- ]ground dry (?:biomass|mass|matter)|"
            r"(?:upper|lower) cap|(?:no|without) (?:upper |lower |temperature )?caps?|negative (?:values|accumulation)|"
            r"total product|"
            r"(?:an? )?assumed price|(?:an? )?average of|(?:an? )?unspecified (?:upper|lower) cap|P2O5|K2O|P|K)\b)")
        presentation = (r"(?:(?:units|assumptions|arithmetic limits)(?: (?:stated|shown|included))?|with (?:all |the )?(?:units|assumptions|arithmetic limits|formula|calculation)(?: (?:stated|shown|included))?|without (?:showing|explaining) (?:the )?(?:arithmetic|formula|calculation)|(?:(?:show|give|state|include) (?:the )?(?:units|assumptions|arithmetic limits|formula|calculation)|"
            r"explain (?:its|the|their) (?:limits|limitations|boundaries)|"
            r"distinguish it from total carrier volume))")
        tails = []
        for clause in clauses:
            parts = re.split(r",\s*(?!\d)|\b(?:and|then|also)\b", clause, flags=re.I)
            tails.extend(parts[1:])
            # A prepositional request can occur inside the initial arithmetic
            # clause too. It needs the same complete ownership as a comma tail.
            for part in parts:
                tails.extend(part[match.start():] for match in re.finditer(r"\b(?:with|without)\b", part, re.I))
        for tail in tails:
            tail = re.sub(r"^\s*(?:(?:and|then|also)\s+)*", "", tail, flags=re.I).strip()
            if re.fullmatch(r"(?:ignoring (?:losses|(?:unusable )?(?:tank )?volume)|not a (?:recommended rate(?: or carrier[- ]water volume)?|rate recommendation)|assuming the label basis is correct|(?:not )?of (?:germinated seeds|(?:all )?seeds sown)|(?:not including|excluding|does(?: not|n['’]t) (?:already )?include|without(?: (?:already )?including)?) (?:laboratory )?germination|without (?:upper |lower |temperature )?caps?|seedling (?:loss|mortality))", tail, re.I):
                continue
            if re.fullmatch(data_declaration, tail, re.I):
                continue
            if re.fullmatch(r"(?:P2O5|K2O|P|K)", tail, re.I):
                continue
            if not tail or re.fullmatch(presentation, tail, re.I):
                continue
            data_tail = re.sub(r"^(?:with|of)\s+", "", tail, count=1, flags=re.I).replace('−', '-')
            absent_input = rf"(?:{premise}|{ARITHMETIC_INPUT_ROLE_PATTERN}\b)"
            if re.fullmatch(r"without\s+(?:(?:an?|the)\s+)?" + absent_input, tail, re.I) and not re.search(r"\d", tail):
                continue  # Explicitly absent operand: the typed parser clarifies.
            if _calculation_premise(data_tail):
                continue
            owner = re.match(premise, data_tail, re.I)
            if owner and _calculation_value_is_owned(
                    data_tail[owner.end():], has_quantity=bool(re.search(r"\d", owner.group()))):
                continue
            if re.search(r"\bgrain\b.*\bwet[- ]basis moisture\b", text, re.I) and re.match(r"equivalent (?:grain )?mass\b", tail, re.I):
                continue
            return True
        return False
    # A coordinated explanatory output must itself be analytical, or be a
    # shared impersonal predicate. Bare unknown commands after 'explain why'
    # do not acquire the causal auxiliary from some earlier sentence.
    for clause in clauses:
        if re.match(r"(?:compare|contrast|distinguish)\b", clause, re.I):
            if not is_concept_comparison_scope(clause):
                return True
            continue
        # A coordinated grammatical subject precedes its shared copula. It is
        # not a series of follow-on requests. Replace only that subject span;
        # coordination in the predicate and any later commands stays visible.
        clause = re.sub(
            r"^(?P<head>(?:(?:explain|describe)\s+)?(?:why|how)\s+)"
            r"[a-z][a-z-]*(?:,\s*[a-z][a-z-]*)*\s*(?:,?\s+and\s+[a-z][a-z-]*)"
            r"(?=\s+(?:are|were|is|was)\b)",
            lambda match: match['head'] + "the named subjects", clause, flags=re.I,
        )
        causal = re.match(r"(?:why|how)\s+(?:can|could|do|does|is|are)\b", clause, re.I)
        definition = re.match(r"(?:what (?:is|are)|define|explain(?!\s+(?:why|how|(?:the )?(?:mechanism|process))\b))\b", clause, re.I)
        for tail in re.split(r",\s*(?!\d)|\b(?:and|then|also)\b", clause, flags=re.I)[1:]:
            tail = re.sub(r"^\s*(?:(?:then|also)\s+)*", "", tail, flags=re.I).strip()
            if not tail or re.match(r"(?:why|how|what|which|explain|describe|its|their|matching (?:threshold |measurement )?units|the (?:limits|limitations|mechanism|process)|observations?)\b", tail, re.I):
                continue
            # Coordinated concepts in a definition are noun phrases, not
            # additional finite requests (texture, structure and porosity).
            if definition and (re.fullmatch(r"[a-z-]+[.!?]*", tail, re.I) or re.fullmatch(
                    r"(?:soil|plant|crop|root|seed|carbon|nitrogen|phosphorus|potassium|sulfur|sulphur|nutrient|water) (?!the\b|an?\b|my\b|our\b|your\b)[a-z-]+(?: [a-z-]+){0,2}[.!?]*", tail, re.I)):
                continue
            predicate = re.match(r"([a-z]+)\b", tail, re.I)
            finite = {'increases', 'decreases', 'reduces', 'raises', 'lowers',
                'changes', 'alters', 'affects', 'influences', 'delays', 'slows',
                'supplies', 'moves', 'carries', 'leaves', 'accumulates', 'limits',
                'causes', 'helps', 'results', 'contributes', 'disrupts', 'promotes',
                'improves', 'worsens', 'prevents', 'releases', 'retains'}
            if predicate and (predicate[1].casefold() in finite or
                    causal and predicate[1].casefold() in {'increase', 'decrease', 'reduce', 'raise', 'lower'}):
                continue
            return True
    return False

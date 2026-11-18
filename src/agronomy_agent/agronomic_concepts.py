"""General concept boundaries for prompts and localized claim correction.

Project-authored definitions, not retrieved evidence or field observations.
Rationale: Purdue's Field Drydown of Mature Corn Grain, UMN's Interpreting
soil tests for fruit and vegetable crops, and NPIC's Active Ingredients.
Lodging definitions also use Manitoba Crop Alliance lodging guidance.
Source links and qualification live in the package README. No evaluation
questions, answers, labels or numerical recommendations belong here.
"""
from __future__ import annotations

import re

from agronomy_agent.answerability import is_rate_basis_explanation, preferred_response_language


DRYDOWN_DEFINITION = (
    "In variety comparisons, harvest drydown concerns the loss of moisture from "
    "the crop or grain toward harvest; it is distinct from drought tolerance. "
    "The crop, maturity stage and weather affect its interpretation."
)
LODGING_DEFINITION = (
    "Lodging means crop plants lean or fall from their upright position because of "
    "root anchorage failure or stem bending or breakage. It can occur before maturity. "
    "Standability or lodging resistance describes the ability to remain upright."
)
NUTRIENT_DEFINITION = (
    "A fertilizer nutrient rate is related to product rate through the declared "
    "nutrient analysis and its stated mass basis. Pesticide active-ingredient "
    "concentration describes pest-control constituents and is not interchangeable "
    "with fertilizer nutrient analysis."
)


def _harvest_drydown_context(question: str) -> bool:
    # Cultivar comparisons also occur in water-deficit experiments. Resolve
    # the term's referent before treating an incidental crop/variety as harvest
    # scope; mixed soil/harvest requests cannot authorize a global rewrite.
    if re.search(r"\bsoil(?:[- ](?:water|moisture))?[- ]+dry[- ]?down\b|\bdry[- ]?down\s+(?:of|in)\s+(?:the\s+)?soil\b", question, re.I):
        return False
    for experiment in re.finditer(
            r"\bdry[- ]?down[- ]+(?:experiments?|treatments?|protocols?|cycles?|stud(?:y|ies))\b", question, re.I):
        if not re.search(
                r"\b(?:harvest(?:[- ]+grain)?|grain(?:[- ]+moisture)?|kernels?(?:[- ]+moisture)?)[- ]+$",
                question[:experiment.start()], re.I):
            # Grain yield elsewhere in a cultivar experiment does not turn
            # its dry-down treatment into a harvest-grain referent.
            return False
    return bool(re.search(r"\bdry[- ]?down\b", question, re.I) and re.search(
        r"\b(?:variet\w*|cultivars?|hybrids?|harvest\w*|grain)\b", question, re.I))


def _crop_lodging_context(question: str) -> bool:
    return bool(re.search(r"\blodging\b", question, re.I) and re.search(
        r"\b(?:crops?|plants?|rotation|variet\w*|cultivars?|hybrids?|standability|cereals?|corn|wheat|barley)\b",
        question, re.I))


_SOY_MATURITY_ID = re.compile(r"\b(?:maturity(?:[- ]group| rating)?|MG)\s*(?:is|of|:|=)?\s*(?P<identifier>0{1,3}(?:\.\d+)?)\b", re.I)


def _soybean_maturity_context(question: str) -> bool:
    return bool(re.search(r"\bsoybeans?\b", question, re.I) and _SOY_MATURITY_ID.search(question))


def _maturity_edits(sentence: str, question: str):
    """Restore only an unambiguous supplied identifier in an explicit role."""
    def collapsed(value):
        value = value.lstrip("0") or "0"
        return "0" + value if value.startswith(".") else value
    def named_subject(prefix):
        subject = re.search(r"\b([A-Za-z][A-Za-z0-9_-]*)(?:['’]s\s+|\s+has\s+)$", prefix)
        if subject is None:
            # Bare labels are explicit record subjects, not a modal's final
            # verb ("Y may have maturity..."). Named varieties use has/'s.
            subject = re.search(r"\b([A-Z](?:\d+)?)\s+$", prefix)
        if subject is None or subject[1].casefold() in {
                'soybean', 'soybeans', 'variety', 'cultivar', 'hybrid', 'the', 'a',
                'an', 'i', 'we', 'you', 'they', 'he', 'she', 'it', 'its', 'is',
                'have', 'has', 'may', 'could', 'would', 'should', 'must', 'will',
                'can', 'of', 'with', 'explain', 'which'}:
            return None
        return subject[1].casefold()
    groups = {}
    subjects = {}
    for match in _SOY_MATURITY_ID.finditer(question):
        identifier = match["identifier"]
        groups.setdefault(collapsed(identifier), set()).add(identifier)
        subject = named_subject(question[:match.start()])
        if subject:
            subjects.setdefault(identifier, set()).add(subject)
    edits = []
    def role_text(value):
        for pattern, replacement in (
            (r"\bcan['’]t\b|\bcannot\b", "can not"),
            (r"\bwon['’]t\b", "will not"),
            (r"\bshan['’]t\b", "shall not"),
        ):
            value = re.sub(pattern, replacement, value, flags=re.I)
        return re.sub(r"n['’]t\b", " not", value, flags=re.I)
    def restore(match):
        identifier = match["identifier"]
        before = sentence[:match.start()]
        after = sentence[match.end():]
        # Normalize only for role detection; replacement offsets and prose
        # remain bound to the original sentence. Negative comparisons must
        # never become false self-comparisons after restoring an identifier.
        before_role = role_text(before)
        after_role = role_text(after)
        clause_prefix = re.split(r"[;,!?]|\.(?=\s|$)|\b(?:but|whereas)\b", before, flags=re.I)[-1]
        if re.search(r"\b(?:if|suppose|supposing|assuming|hypothetical|another|other)\b|^\s*were\b", clause_prefix, re.I):
            return match.group()
        if (re.search(r"\b(?:not|if|rather than|instead of|different from|distinct from|differs from|versus|compared with|compared to|contrasts with)\s*$", before_role, re.I)
                or re.search(r"\b(?:not|never)\b[^;.!?]{0,60}\b(?:confused with|treated as|interpreted as|equated (?:to|with)|same (?:identifier )?as|equivalent to|mean)\s*$", before_role, re.I)
                or re.match(r"\s+(?:(?:is|are|was|were|would be|could be|does|do|did|can|could|would|should|must|will|shall|may|might|has|have)\s+)?(?:not|never|different|distinct|differs|versus|rather than|compared with|compared to|contrasts with)\b", after_role, re.I)):
            return match.group()
        supplied = groups.get(collapsed(identifier), set())
        if len(supplied) != 1 or identifier in supplied:
            return match.group()
        original = next(iter(supplied))
        if len(original) <= len(identifier):
            return match.group()
        # Restore an explicit entity/identifier assignment, not any mention of
        # a number that happens to collapse to the question's identifier.
        subject = named_subject(before)
        supplied_subjects = subjects.get(original, set())
        if subject is None or subject not in supplied_subjects:
            return match.group()
        if re.search(r"(?<![\d.])" + re.escape(original) + r"(?!\d|\.\d)", sentence):
            # Both identifiers are deliberate local operands. Rewriting one
            # would invent a relationship, even with an unfamiliar predicate.
            return match.group()
        start = match.start("identifier") - match.start()
        replacement = match.group()[:start] + original + match.group()[start+len(identifier):]
        edits.append({"reason": "soybean_maturity_identifier_changed", "original": match.group(), "replacement": replacement})
        return replacement
    return _SOY_MATURITY_ID.sub(restore, sentence), edits


def concept_prompt_guidance(question: str) -> tuple[str, ...]:
    """Ground an explanation without pretending these rules are source hits."""
    if preferred_response_language(question) == "fr" or re.search(r"\b(?:en fran[cç]ais|in french)\b", question, re.I):
        return ()
    notes = []
    if _harvest_drydown_context(question):
        notes.append(DRYDOWN_DEFINITION)
    if _crop_lodging_context(question):
        notes.append(LODGING_DEFINITION)
    if _soybean_maturity_context(question):
        notes.append("Soybean maturity-group identifiers retain their supplied leading zeroes. Groups 000, 00 and 0 are distinct adaptation classifications, not interchangeable decimal formatting. Do not cast these identifiers to ordinary decimal numbers or infer local suitability from the identifier alone.")
    if is_rate_basis_explanation(question) and re.search(r"\bnutrient\b", question, re.I):
        notes.append(NUTRIENT_DEFINITION)
    return tuple(notes)


def correct_concept_claims(answer: str, question: str) -> tuple[str, tuple[dict[str, str], ...]]:
    """Replace only an affirmative, bounded false definition or relationship.

    Other prose is byte-preserved. Correct contrasts, uncertainty, quoted
    misconceptions and discussion of drought affecting drydown are untouched.
    The caller must reassess the entire result before accepting a correction.
    This is deliberately not a general semantic correctness validator.
    """
    if preferred_response_language(question) == "fr" or re.search(r"\b(?:en fran[cç]ais|in french)\b", question, re.I):
        return answer, ()
    drydown = _harvest_drydown_context(question)
    lodging = _crop_lodging_context(question)
    nutrient = is_rate_basis_explanation(question) and bool(re.search(r"\bnutrient\b", question, re.I))
    edits: list[dict[str, str]] = []
    rate_subject: str | None = None

    def replace(match: re.Match[str]) -> str:
        nonlocal rate_subject
        sentence = answer[match.start():match.end()]
        prior_subject = rate_subject
        plain = re.sub(r"[*_`]", "", sentence)
        if "\n\n" in sentence:
            rate_subject = None
        subjects = re.findall(r"\b(nutrient|product|active[- ]ingredient)\s+rate\b", plain, re.I)
        rate_subject = subjects[0].lower() if len(subjects) == 1 else None
        # Do not silently turn a reported misconception or conditional into
        # an assertion. A correct negative contrast is not a defect.
        if re.search(r"\b(?:incorrect\w*|wrong\w*|misconception|mistaken\w*)\b|[\"“”]", sentence, re.I):
            return sentence
        replacement = ""
        reason = ""
        if _soybean_maturity_context(question):
            restored, maturity_edits = _maturity_edits(sentence, question)
            if maturity_edits:
                edits.extend(maturity_edits)
                return restored
        # Correct the term itself, never the distinct phrase "lodging resistance".
        # A bounded affirmative definition is required; preserve uncertainty,
        # negatives and reported misconceptions rather than changing their sense.
        lodging_definition = re.match(
            r"\s*(?:[-*]\s+)?(?P<claim>(?:\*\*|__|`)?lodging(?:\*\*|__|`)?"
            r"\s*(?::(?:\*\*|__|`)?|\s+(?:is|means|refers? to|describes?)\b)"
            r"(?P<property>[^,;.!?\n]+))", sentence, re.I)
        claim = lodging_definition["claim"] if lodging_definition else ""
        if (lodging and lodging_definition and re.match(
                r"\s*(?:(?:a|the)\s+)?(?:(?:plant|crop|variety)['’]s\s+)?(?:physical\s+)?"
                r"(?:resistance\s+to\s+falling\b|(?:ability|capacity)\s+to\s+(?:remain|stay|stand)\s+upright\b)",
                lodging_definition["property"], re.I) and not re.search(
                r"\b(?:not|never|rather than|instead of|may|might|could|if|whether)\b", claim, re.I)):
            replacement = LODGING_DEFINITION.rstrip(".")
            edits.append({"reason": "lodging_standability_conflation", "original": claim,
                          "replacement": replacement})
            return sentence[:lodging_definition.start("claim")] + replacement + sentence[lodging_definition.end("claim"):]
        definition = re.match(
            r"\s*(?:[-*]\s+)?(?P<claim>(?:\*\*|__|`)?dry[- ]?down(?:\*\*|__|`)?"
            r"\s+(?:is|means|refers? to|describes?)\b(?P<property>[^,;.!?\n]+))", sentence, re.I)
        # The false trait must be the definition's head property. Mentioning
        # drought tolerance as an experimental purpose or a separate trait
        # does not equate the two concepts.
        false_property = re.match(
            r"\s*(?:(?:a|an|the)\s+)?"
            r"(?:(?:plant|crop|variety|cultivar|hybrid)['’]s\s+)?"
            r"(?:(?:ability|capacity)\s+to\s+(?:(?:mature|grow)\s+and\s+)?"
            r"(?:survive|tolerate|withstand|resist|endure|cope\s+with)\s+"
            r"(?:(?:periods?|conditions?)\s+of\s+)?"
            r"(?:drought|moisture stress|water stress|water shortage)\b|"
            r"(?:tolerance|resistance)\s+(?:to|of|against)\s+"
            r"(?:drought|moisture stress|water stress|water shortage)\b|"
            r"(?:drought|moisture[- ]stress|water[- ]stress)\s+(?:tolerance|resistance)\b)",
            re.sub(r"[*_`]", "", definition["property"]) if definition else "", re.I)
        if (drydown and definition and false_property and not re.search(
            r"\b(?:not|never|rather than|instead of)\b",
            definition["claim"][:false_property.start()], re.I
        )):
            replacement = (
                "Drydown concerns the loss of moisture from the crop or grain toward harvest, "
                "rather than drought tolerance"
            )
            end = definition.end("claim")
            denied_moisture_loss = re.match(
                r",\s*not\s+(?:(?:grain|crop)[- ])?(?:moisture|water)[- ]loss(?=[.!?;]|$)",
                sentence[end:], re.I)
            if denied_moisture_loss:
                end += denied_moisture_loss.end()
            edits.append({"reason": "drydown_drought_conflation", "original": sentence[definition.start("claim"):end],
                          "replacement": replacement})
            return sentence[:definition.start("claim")] + replacement + sentence[end:]
        if nutrient and re.search(r"\bactive[- ]ingredients?\s*(?:\(s\))?\b", plain, re.I):
            supplies_nutrients = re.search(
                r"\bactive[- ]ingredients?\s*(?:\(s\))?\s+(?:that\s+)?"
                r"(?:deliver\w*|suppl\w*|provid\w*)\b[^.;!?]{0,65}\bnutrients?\b", plain, re.I)
            # Supplying a material that is also a nutrient is not itself a
            # false claim (copper/sulfur have dual roles). Require the explicit
            # rate/basis relationship, not merely the word 'nutrient'.
            rate_equivalence = re.search(
                r"\b(?:these two (?:values|rates)|(?:product|nutrient) rates?)\b"
                r"[^.;!?]{0,60}\brelated\b", plain, re.I)
            nutrient_rate_relation = re.search(
                r"\b(?:nutrient rate|this rate)\b[^.;!?]{0,90}"
                r"\b(?:derived|calculat\w*|determin\w*|depend\w*)\b[^.;!?]{0,150}"
                r"\bactive[- ]ingredient", plain, re.I)
            relation_context = bool(
                    re.search(r"\bnutrient rate\b", plain, re.I)
                    or prior_subject == "nutrient")
            relation = rate_equivalence if supplies_nutrients else nutrient_rate_relation if relation_context else None
            if relation and not re.search(r"\b(?:not|never|rather than|instead of)\b", relation.group(), re.I):
                replacement, reason = NUTRIENT_DEFINITION, "nutrient_active_ingredient_conflation"
        if not replacement:
            return sentence
        prefix = re.match(r"\s*(?:[-*]\s*)?", sentence).group()
        tail = re.search(r"[,;]\s*(?:while|whereas|but|and|also)\b|[.!?]+\s*$|\s+$", sentence)
        end = tail.start() if tail else len(sentence)
        replacement = replacement.rstrip(".")
        edits.append({"reason": reason, "original": sentence[len(prefix):end], "replacement": replacement})
        return prefix + replacement + sentence[end:]

    # Mask only abbreviation punctuation for segmentation; equal-length masks
    # retain original span offsets and never enter the returned prose. 'This
    # rate' may inherit only the immediately preceding explicit rate subject.
    segmentation = re.sub(r"\b(?:e\.g\.|i\.e\.)", lambda m: m.group().replace(".", "_"), answer, flags=re.I)
    corrected = "".join(replace(m) for m in re.finditer(r".+?(?:[.!?]+(?=\s|$)|\n+|$)", segmentation, re.S))
    return corrected, tuple(edits)

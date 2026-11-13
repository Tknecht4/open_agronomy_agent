"""General concept boundaries for prompts and localized claim correction.

Project-authored definitions, not retrieved evidence or field observations.
Rationale: Purdue's Field Drydown of Mature Corn Grain, UMN's Interpreting
soil tests for fruit and vegetable crops, and NPIC's Active Ingredients.
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
NUTRIENT_DEFINITION = (
    "A fertilizer nutrient rate is related to product rate through the declared "
    "nutrient analysis and its stated mass basis. Pesticide active-ingredient "
    "concentration describes pest-control constituents and is not interchangeable "
    "with fertilizer nutrient analysis."
)


def _harvest_drydown_context(question: str) -> bool:
    return bool(re.search(r"\bdry[- ]?down\b", question, re.I) and re.search(
        r"\b(?:variet\w*|cultivars?|hybrids?|harvest\w*|grain)\b", question, re.I))


def concept_prompt_guidance(question: str) -> tuple[str, ...]:
    """Ground an explanation without pretending these rules are source hits."""
    if preferred_response_language(question) == "fr":
        return ()
    notes = []
    if _harvest_drydown_context(question):
        notes.append(DRYDOWN_DEFINITION)
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
    if preferred_response_language(question) == "fr":
        return answer, ()
    drydown = _harvest_drydown_context(question)
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
        definition = re.match(
            r"\s*(?:[-*]\s+)?(?P<claim>(?:\*\*|__|`)?dry[- ]?down(?:\*\*|__|`)?"
            r"\s+(?:is|means|refers? to|describes?)\b[^,;.!?\n]+)", sentence, re.I)
        false_property = re.search(
            r"\b(?:ability|capacity|toleran\w*|resistan\w*)\b[^.;!?]{0,100}"
            r"\b(?:drought|moisture stress|water stress|water shortage)\b|"
            r"\b(?:drought|moisture[- ]stress|water[- ]stress)\s+(?:tolerance|resistance)\b",
            definition["claim"] if definition else "", re.I)
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

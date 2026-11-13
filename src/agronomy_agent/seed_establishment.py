"""Keep the denominator of a supplied seed establishment percentage explicit.

Overall emergence is plants established per seed sown. Post-germination
survival is plants established per germinated seed. Neither selects a field
population or estimates survival from crop, location or laboratory germination.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Any
from agronomy_agent.supplied_numeric_inputs import NUMBER as SUPPLIED_NUMBER

SEED_SURVIVAL_BASES = ("seeds_sown", "germinated_seeds")
SEED_SURVIVAL_BASIS_GAP = "the survival denominator (all seeds sown or only germinated seeds)"
SEED_LOSS_MODEL_GAP = "the seedling-loss definition: supply overall emergence of seeds sown, or mortality among germinated seeds"
SEED_GERMINATION_GAP = "seed-lot germination percent for post-germination survival"
_NUMBER = rf"({SUPPLIED_NUMBER})"


def established_fraction(survival_pct: Decimal, basis: str,
                         germination_pct: Decimal | None) -> tuple[Decimal, str]:
    if basis not in SEED_SURVIVAL_BASES:
        raise ValueError("survival_basis must be seeds_sown or germinated_seeds")
    survival = survival_pct / Decimal(100)
    if basis == "seeds_sown":
        note = "overall emergence is of seeds sown and already includes germination"
        if germination_pct is not None:
            note += "; supplied laboratory germination is retained as context, not multiplied again"
        return survival, note
    if germination_pct is None:
        raise ValueError("germination_pct is required for survival of germinated seeds")
    return germination_pct / Decimal(100) * survival, "established fraction = germination × post-germination survival"


def _germination_inclusion(text: str) -> tuple[bool, bool]:
    """Read one bound inclusion cue; a negative cannot grant inclusion."""
    noun = r"(?:lab(?:oratory)?\s+)?germination\b"
    excluded = bool(re.search(
        r"\b(?:(?:not|doesn['’]t|does\s+not|without)\s+(?:already\s+)?includ(?:e|es|ing)|"
        r"exclud(?:e|es|ing)|without)\s+" + noun, text))
    included = bool(not excluded and re.search(
        r"\b(?:already\s+)?includ(?:e|es|ing)\s+" + noun, text))
    return excluded, included


def parse_seed_establishment(text: str, *, bindings: list[re.Match[str]] | None = None,
                             unqualified_basis: list[bool] | None = None) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Extract one supplied establishment model; ambiguity is never a default."""
    def matches(*patterns: str) -> list[re.Match[str]]:
        return [m for pattern in patterns for m in re.finditer(pattern, text, re.IGNORECASE)]

    def value(found: list[re.Match[str]]) -> float | None:
        values = {float(m.group(1).replace(",", "")) for m in found}
        return next(iter(values)) if len(values) == 1 else None

    germ_matches = matches(
        rf"{_NUMBER}\s*%\s*(?:(?:seed[- ]lot|lab(?:oratory)?)\s+)?germination\b",
        rf"\bgermination\s*(?:rate\s*)?(?:is|of|:)?\s*{_NUMBER}\s*%",
    )
    survival_matches = matches(
        rf"{_NUMBER}\s*%\s*(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:survival|emergence)\b",
        rf"\b(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:survival|emergence)\s*(?:rate\s*)?(?:is|of|:)?\s*{_NUMBER}\s*%",
        rf"{_NUMBER}\s*%\s+of\s+(?:all\s+)?(?:seeds?\s+(?:sown|planted)|germinated\s+seeds?)\s+(?:emerge|survive)\b",
    )
    loss_matches = matches(
        rf"{_NUMBER}\s*%\s*(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:loss|mortality)\b",
        rf"\b(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:loss|mortality)\s*(?:is|of|:)?\s*{_NUMBER}\s*%",
    )
    if bindings is not None:
        bindings.extend(germ_matches + survival_matches + loss_matches)
    germination, survival, loss = value(germ_matches), value(survival_matches), value(loss_matches)
    inputs: dict[str, Any] = {}
    missing: list[str] = []
    if germination is not None:
        inputs["germination_pct"] = germination
    if loss is not None:
        inputs["mortality_pct"] = loss
    if any(len({float(m.group(1).replace(',', '')) for m in found}) > 1
           for found in [germ_matches, survival_matches, loss_matches]):
        missing.append("invalid conflicting seed establishment percentages: supply one value for each quantity")
    if survival is not None and loss is not None and abs(survival + loss - 100) > 0.0001:
        missing.append("invalid inconsistent survival and mortality percentages")
    if survival is None and loss is not None:
        survival = 100 - loss
    if survival is not None:
        inputs["field_survival_pct"] = survival

    bases: set[str] = set()
    unsupported_seedling_loss = False
    for match in survival_matches + loss_matches:
        role = match.group(0).casefold()
        before = text[max(0, match.start() - 48):match.start()].casefold()
        after = text[match.end():match.end() + 100].casefold()
        # A later sentence's "overall seed rate" is not this percentage's
        # denominator. A decimal point within a percentage is not a boundary.
        after = re.split(r"(?<!\d)\.(?!\d)|[!?;]", after, maxsplit=1)[0]
        before = re.split(r"(?<!\d)\.(?!\d)|[!?;]", before)[-1]
        context = role + after
        denied_basis = bool(re.search(
            r"\b(?:not|rather than|instead of)\s+(?:of\s+)?(?:all\s+)?(?:germinated seeds?|viable seeds?|seeds? sown|seeds? planted|post[- ]germination)", context))
        # Explicit negation of a denominator must not activate that denominator.
        context = re.sub(r"\b(?:not|rather than|instead of)\s+(?:of\s+)?(?:all\s+)?(?:germinated seeds?|viable seeds?|seeds? sown|seeds? planted|post[- ]germination)", "", context)
        excludes_germination, includes_germination = _germination_inclusion(context)
        conditional = bool(re.search(r"post[- ]germination|\b(?:of|among)\s+(?:the\s+)?(?:germinated|viable)\s+seeds?\b", context)
                           or re.search(r"post[- ]germination\s*[:,-]?\s*$", before))
        overall = bool(re.search(r"\boverall\b", role)
                       or re.match(r"\s*overall\b", after)
                       or re.search(r"\b(?:of|among)\s+(?:all\s+|the\s+)?seeds?\s+(?:sown|planted)\b", context)
                       or includes_germination)
        # Keep stage language with this percentage, stopping before another
        # supplied quantity or sentence; never scan the whole question.
        quantity_tail = re.split(SUPPLIED_NUMBER, after, maxsplit=1)[0]
        stage_specific_loss = bool(
            re.search(r"\bseedlings?\b|\b(?:after|following)\s+germination\b", role + quantity_tail)
            # A germination percentage can itself be part of the stage
            # qualifier, rather than the start of an unrelated quantity.
            or re.search(rf"\b(?:after|following)\s+{SUPPLIED_NUMBER}\s*%\s+germination\b", context)
            or re.search(r"\b(?:seedling(?:\s+stage)?|(?:after|following)\s+germination)[\s,:-]*$", before))
        # Inclusion attached to a later percentage cannot redefine this loss.
        _, loss_includes_germination = _germination_inclusion(role + quantity_tail)
        if match in loss_matches and stage_specific_loss and not conditional and not loss_includes_germination:
            # Stage-specific deaths per seed sown are additional to failed
            # germination, not the complement of overall establishment.
            # This calculator owns only explicit overall or conditional rates.
            unsupported_seedling_loss = True
        if unqualified_basis is not None:
            # Keep qualification attached to this percentage's role and clause;
            # "overall germination" or a later "overall seed rate" is not a
            # denominator for an earlier unqualified survival percentage.
            unqualified_basis.append(not (overall or conditional or excludes_germination
                                           or denied_basis or "emerg" in role))
        if overall and excludes_germination:
            missing.append("invalid overall emergence cannot also exclude germination; confirm the percentage denominator")
        if conditional:
            bases.add("germinated_seeds")
        if overall:
            bases.add("seeds_sown")
        # In extension usage, unqualified emergence is a seeds-sown fraction.
        # Plain survival/mortality has multiple uses and needs a denominator.
        if not conditional and not overall and not excludes_germination and "emerg" in role:
            bases.add("seeds_sown")
    if len(bases) == 1:
        inputs["survival_basis"] = next(iter(bases))
    elif len(bases) > 1:
        missing.append("invalid conflicting survival bases: distinguish seeds sown from germinated seeds")
    elif survival is not None:
        missing.append(SEED_SURVIVAL_BASIS_GAP)
    if survival is None:
        missing.append("supplied overall emergence, or post-germination survival/mortality with its denominator")
    if inputs.get("survival_basis") == "germinated_seeds" and germination is None:
        missing.append(SEED_GERMINATION_GAP)
    for key, label in [("germination_pct", "germination"), ("field_survival_pct", "field survival")]:
        if key in inputs and not 0 < inputs[key] <= 100:
            missing.append(f"invalid {label}: use a percentage above zero and at most 100")
    if loss is not None and not 0 <= loss < 100:
        missing.append("invalid mortality: use a percentage from zero to below 100")
    if unsupported_seedling_loss:
        missing = [item for item in missing if item not in {SEED_SURVIVAL_BASIS_GAP, SEED_GERMINATION_GAP}]
        missing.append(SEED_LOSS_MODEL_GAP)
        if not survival_matches:
            inputs.pop("field_survival_pct", None)
            inputs.pop("survival_basis", None)
    return inputs, tuple(dict.fromkeys(missing))

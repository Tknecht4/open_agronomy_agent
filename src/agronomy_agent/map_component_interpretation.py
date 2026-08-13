"""Recognition for factual explanations of mapped soil components.

This intent is deliberately narrower than a soil-management question.  It
allows the answer path to explain supplied map attributes without turning an
incidental slope, drainage class, or component name into an unsolicited
erosion, drainage, fertility, or tillage recommendation.
"""

from __future__ import annotations

import re


_EXPLANATION_PATTERN = re.compile(
    r"\b(?:explain|describe|tell me about|what (?:do|does|is|are)|"
    r"what(?:'s| is) the difference|how do (?:i|you) read|mean)\b|"
    r"\b(?:expliquer|d[eé]crire|que (?:signifie|veut dire)|"
    r"quelle est la diff[eé]rence)\b",
    re.IGNORECASE,
)
_MAP_COMPONENT_PATTERN = re.compile(
    r"\b(?:soil (?:type|types|series|name|names|component|components|map unit|map units)|"
    r"map(?:ped)? (?:soil|component|unit)|soil[- ]map|soil[- ]survey|"
    r"type(?:s)? de sol|s[eé]rie(?:s)? de sol|unit[eé](?:s)? cartographique(?:s)?|"
    r"composante(?:s)? de sol|carte des sols)\b",
    re.IGNORECASE,
)
_MANAGEMENT_PATTERN = re.compile(
    r"\b(?:what should i do|should i|recommend|recommendation|manage(?:ment)?|"
    r"apply|rate|fertili[sz]|plant|seed|crop selection|irrigat|drain(?:age)?|"
    r"till(?:age)?|erosion control|conservation plan|prescription|"
    r"que devrais-je|recommande[rz]?|g[eé]rer|appliqu|fertili[sz]|planter|irrig|drainage)\b",
    re.IGNORECASE,
)


def is_map_component_explanation_question(question: str | None) -> bool:
    """Whether the user asks to interpret map-component facts, not manage them."""

    text = str(question or "").strip()
    return bool(
        text
        and _EXPLANATION_PATTERN.search(text)
        and _MAP_COMPONENT_PATTERN.search(text)
        and not _MANAGEMENT_PATTERN.search(text)
    )

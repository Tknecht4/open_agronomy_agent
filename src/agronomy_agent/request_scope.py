"""Shared detection of operational directives in otherwise benign requests."""
from __future__ import annotations

import re

FIELD_ACTION_PATTERN = (
    r"(?:apply|spray|irrigate|fertilize|drain|mow|drive|graze|sell|buy|till|cultivate|prune|operate|enter|increase|decrease|reduce|raise|"
    r"lower(?!\s+cap\b)|spread(?!\s+rate\b)|water(?!\s+(?:storage|depth|content|balance|capacity|volume|needed|deficit)\b)|"
    r"harvest(?!\s+index\b)|plant(?![-\s]+(?:population|density|available)\b)|seed(?![-\s]+(?:rate|mass|count|cost|tkw|quality|germination)\b)|"
    r"feed(?!\s+(?:conversion|intake|mass|rate|cost)\b)|récoltez|semez|plantez|fauchez|conduisez|pâturez|nourrissez)"
)


def has_action_directive(text: str, *, coordinated: bool = True) -> bool:
    start = r"(?:^|[.!?;]\s*|\b(?:and|also|then)\s+)" if coordinated else r"(?:^|[.!?;]\s*)"
    return bool(re.search(
        start + r"(?:please\s+)?(?:" + FIELD_ACTION_PATTERN +
        r"|proceed|go ahead|carry out|execute|perform|implement|undertake|turn|begin|commence)\b|"
        + start + r"(?:please\s+)?(?:give|provide|write|show|develop|create|design)\b[^.!?;]{0,55}\b(?:instructions|directions|steps|plan)\b",
        text, re.I,
    ))

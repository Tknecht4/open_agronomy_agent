"""Whole-token input coverage for bounded natural-language arithmetic."""
from __future__ import annotations

import re

# Ordinary decimals and correctly grouped comma thousands are supported.
# Assertions prevent backtracking into a valid substring of a malformed token,
# exponent or arithmetic expression. Attached supported units remain possible.
NUMBER = r"(?<![\w.,+-])[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?!\d|\.\d|,\s*\d|[eE]|[+*/-]\s*\d)"

# Matches whole numeric-looking tokens, including unsupported notation, so a
# shorter valid prefix cannot masquerade as the supplied operand. Digits inside
# names/units (P2O5, m3/m3) are not independent quantities.
_NUMERIC_TOKEN = re.compile(r"(?<![\w.,])[+-]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[A-Za-z][\w+-]*|(?:[/×*+-]\d+(?:[.,]\d+)*)+)?")


def supplied_numeric_gaps(text: str, matches: list[re.Match[str]]) -> tuple[str, ...]:
    """Every supplied quantity must have a recognized role or method constant.

    A complete match includes the bound unit, allowing attached units while
    rejecting a scalar prefix of an exponent, decimal comma or extra operand.
    This checks request coverage only; typed validators still govern arithmetic.
    """
    spans = [match.span() for match in matches]
    if any(not any(start <= token.start() and token.end() <= end for start, end in spans)
           for token in _NUMERIC_TOKEN.finditer(text)):
        return ('invalid unrepresented numeric input: this calculation does not account for every supplied quantity or its notation; use ordinary decimals and a calculation that includes all relevant terms',)
    return ()


def extended_unit(match: re.Match[str]) -> bool:
    """A supported unit cannot be the prefix of a different compound unit."""
    return bool(re.match(r"\s*(?:/|per\b|\^|[⁻−-]\s*\d)", match.string[match.end():], re.I))


def area_unit_extension_gaps(text: str) -> tuple[str, ...]:
    """No current calculator represents another denominator after ha or ac."""
    if re.search(r"\b(?:ha|hectares?|ac|acres?)\s*(?:/|per\b|\^|[⁻−-]\s*\d)", text, re.I):
        return ('invalid compound unit: an extra denominator after area is not supported by this calculation',)
    return ()

"""Shared detection of operational directives in otherwise benign requests."""
from __future__ import annotations

import json
import re

FIELD_ACTION_PATTERN = (
    r"(?:apply|spray|irrigate|fertilize|drain|mow|drive|graze|sell|buy|till|cultivate|prune|operate|enter|thin|reseed|mix|increase|decrease|reduce|raise|"
    r"lower(?!\s+cap\b)|spread(?!\s+rate\b)|water(?!\s+(?:storage|depth|content|potential|balance|capacity|volume|needed|deficit)\b)|"
    r"harvest(?!\s+index\b)|plant(?![-\s]+(?:population|density|available)\b)|seed(?![-\s]+(?:rate|mass|count|cost|tkw|quality|germination)\b)|"
    r"feed(?!\s+(?:conversion|intake|mass|rate|cost)\b)|récoltez|semez|plantez|fauchez|conduisez|pâturez|nourrissez)"
)


def has_action_directive(text: str) -> bool:
    start = r"(?:^|[.!?;,]\s*|\b(?:and|also|then)\s+)"
    pattern = (start + r"(?:please\s+)?(?:(?P<verb>" + FIELD_ACTION_PATTERN +
        r"|proceed|go ahead|carry out|execute|perform|implement|undertake|turn|begin|commence)\b|"
        r"(?:give|provide|write|show|develop|create|design)\b[^.!?;]{0,55}\b(?:instructions|directions|steps|plan)\b)")
    for match in re.finditer(pattern, text, re.I):
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


def has_unqualified_followup(text: str, *, calculation: bool = False) -> bool:
    """Require each later request clause to fit the bypass's declared purpose.

    Unknown trailing instructions use ordinary decision handling. This is a
    positive scope check, so a new imperative need not be added to a verb list.
    Decimal points do not divide sentences.
    """
    head = (r"(?:calculate|compute|convert|work out|how (?:many|much)|what (?:is|are))\b" if calculation else
            r"(?:why|how|explain|describe|define|what|which)\b")
    first = re.search(r"(?:^|[.!?;]\s*)(?:please\s+)?" + head, text, re.I)
    if first is None:
        return False
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
    clauses = [clause.strip() for clause in re.split(r"[!?;]|\.(?=\s|$)", text[first.start():]) if clause.strip()]
    allowed = (r"(?:state (?:the )?(?:units|assumptions|arithmetic limits)|explain (?:its|the|their) (?:limits|limitations|boundaries))\b"
               if calculation else head)
    data_declaration = (
        r"(?:(?:but )?(?:I|we) (?:have not|haven['’]t) (?:supplied|provided) (?:the )?[a-z /²-]{1,80}|"
        r"(?:do not|don['’]t|never) (?:infer (?:crop|growth) stage|state (?:the )?weather provenance)|"
        r"[a-z][a-z -]{0,55} (?:is unknown|are unknown|is not supplied|are not supplied|has not been supplied|have not been supplied)|Named input data|(?:give|show|state) (?:the )?final (?:value|answer)(?: and units| in (?:kg/ha|lb/ac|GDD))|"
        r"this is (?:a math|an arithmetic|a numerical) exercise(?:,? not a rate recommendation)?|"
        r"(?:for this calculation,? )?field survival is [\d.,]+% of (?:all seeds sown|germinated seeds)|"
        r"the laboratory germination is [\d.,]+%|"
        r"explain whether (?:that|this) (?:alone )?(?:tells|establishes) (?:me )?plant[- ]available water)"
    )
    for clause in clauses[1:]:
        if re.match(r"(?:please\s+)?" + allowed, clause, re.I):
            continue
        if calculation and re.fullmatch(data_declaration, clause, re.I):
            continue
        if (calculation and re.search(r"\bseed(?:ing)? (?:rate|mass)\b", clauses[0], re.I)
                and re.fullmatch(r"(?:calculate|compute) (?:the )?(?:overall )?seed(?:ing)? (?:rate|mass)", clause, re.I)):
            continue
        return True
    if calculation:
        premise = (r"(?:(?:an?\s+)?[+-]?(?:\d|\.\d)|(?:of|with|without|does(?: not|n['’]t)|is|are|has|have)\b|(?:(?:the|an?)\s+)?(?:base(?: temperature)?|tmin|tmax|"
            r"(?:lab(?:oratory)? )?germination|(?:(?:expected|post[- ]germination) )?field (?:survival|mortality|loss)|expected emergence|target (?:stand|population)|"
            r"(?:measured )?tkw|(?:(?:expected|overall|field|seedling|post[- ]germination|lab(?:oratory)?) )*(?:survival|emergence|mortality|loss|germination)|seed[- ]lot germination|rooting depth|root[- ]zone depth|field (?:area|capacity)|wilting point|"
            r"measured volumetric water|kc|eto|net depth|application efficiency|travel speed|nozzle spacing|"
            r"grain dry (?:mass|matter)|total above[- ]ground dry (?:biomass|mass|matter)|"
            r"(?:upper|lower) cap|(?:no|without) (?:upper |lower |temperature )?caps?|negative (?:values|accumulation)|"
            r"(?:added|lost) revenue|(?:added|saved) costs?|current (?:assets?|liabilities)|total (?:debt|assets?|product)|"
            r"expected yield|(?:an? )?assumed price|operating cost|total cost|(?:an? )?unspecified (?:upper|lower) cap|P2O5|K2O|P|K)\b)")
        presentation = (r"(?:units|assumptions|arithmetic limits|(?:(?:show|give|state|include) (?:the )?(?:units|assumptions|arithmetic limits|formula|calculation)|"
            r"explain (?:its|the|their) (?:limits|limitations|boundaries)|"
            r"distinguish it from total carrier volume))\b")
        for tail in [tail for clause in clauses for tail in re.split(r",\s*(?!\d)|\b(?:and|then|also)\b", clause, flags=re.I)[1:]]:
            tail = re.sub(r"^\s*(?:(?:and|then|also)\s+)*", "", tail, flags=re.I).strip()
            if re.fullmatch(r"(?:ignoring (?:losses|(?:unusable )?(?:tank )?volume)|not a (?:recommended rate|rate recommendation)|assuming the label basis is correct|not of (?:germinated seeds|seeds sown)|(?:not including|excluding) germination)", tail, re.I):
                continue
            if re.fullmatch(data_declaration, tail, re.I):
                continue
            if not tail or re.match(premise, tail, re.I) or re.match(presentation, tail, re.I):
                continue
            if re.search(r"\bgrain\b.*\bwet[- ]basis moisture\b", text, re.I) and re.match(r"equivalent (?:grain )?mass\b", tail, re.I):
                continue
            return True
        return False
    # A coordinated explanatory output must itself be analytical, or be a
    # shared impersonal predicate. Bare unknown commands after 'explain why'
    # do not acquire the causal auxiliary from some earlier sentence.
    for clause in clauses:
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

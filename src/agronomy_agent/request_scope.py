"""Shared detection of operational directives in otherwise benign requests."""
from __future__ import annotations

import json
import re

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
    if not arithmetic or not re.search(r"\b(?:seed(?:ing)? (?:rate|mass)|TKW|thousand[- ]kernel|target (?:stand|population))\b", text, re.I):
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
        r"(?:compare|contrast)\s+([^.!?;]+)[.!?]?\s*", text, re.I,
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
            r"(?:soil|plant|crop|root|seed|carbon|nitrogen|phosphorus|potassium|sulfur|sulphur|nutrient|water)"
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
    operands = re.split(r"\s+(?:and|with|to|versus|vs\.?)\s+|,\s*(?:and\s+)?", parts[0], flags=re.I)
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
    closed = (
        r"(?:ignoring unusable (?:tank )?volume|ignoring other nutrient credits for this arithmetic check|for this (?:product-mass )?calculation|for a teaching method|"
        r"for one day(?: in (?:an?|the) [a-z -]{1,60}field)?|for a [a-z -]{1,60}field|"
        r"(?:for|under) a uniform(?: [\d.]+ m root zone| profile)|"
        r"for a standard-conditions model ETc\s*=\s*Kc\s*[×*]\s*ETo|"
        r"using (?:a )?[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*°?C base|"
        r"no (?:upper |lower |temperature )?caps?|"
        r"negative (?:values|accumulation) (?:(?:are )?floored at zero|retained)|"
        r"using (?:the [a-z '-]+ )?factor[- ]10 method|"
        r"(?:using )?(?:P|K|L/ha)\s*=\s*(?:(?:P2O5|K2O|P|K|Q|speed|spacing)|[\d.×*/()+ =-])+)")
    if re.fullmatch(closed, part, re.I):
        return True
    if re.fullmatch(r"(?:but )?(?:the )?[a-z][a-z /²-]{0,55} (?:is|are) (?:not supplied|unknown|missing)", part, re.I):
        return True
    if re.fullmatch(r"(?:the )?unusable (?:tank )?volume (?:is |of )?(?:unknown|missing|not supplied)", part, re.I):
        return True
    if not re.search(r"\d", part):
        return False
    # Value-first biomass declarations retain explicit named roles. Do not
    # admit arbitrary crop prose or drop a later operational clause.
    from agronomy_agent.supplied_numeric_inputs import NUMBER
    biomass_role = r"(?:grain dry (?:mass|matter)|total above[- ]ground dry (?:biomass|mass|matter))"
    mass = rf"{NUMBER}\s*(?:kg|tonnes?|t|pounds?|lbs?)(?:\s*(?:/|per\s+)(?:ha|hectares?|ac|acres?))?"
    if re.fullmatch(rf"(?:(?:a|the) (?:(?:teaching|example|hypothetical) )?crop has )?{mass}\s+(?:of\s+)?{biomass_role}", part, re.I):
        return True
    # Bound the grammatical subject to the arithmetic owners' data roles.
    # Imperatives such as 'Mulch beds' have no supported input subject.
    subject = (
        r"(?:(?:these are measured values:\s*)?(?:an? |the )(?:[a-z\d,.-]+ ){0,4}"
        r"(?:field(?: plan)?|fertilizer(?: product)?|soil moisture probe|sprayer(?: tank)?|nozzle|"
        r"crop budget|soybean count|blend|plan|budget|example|prescription)|"
        r"(?:the )?target stand|(?:seed )?TKW|germination|expected (?:field survival|emergence)|soybeans in (?:an?|the) [a-z -]{1,60}field|(?:daily mean|mean daily|maximum|minimum) temperature|grain (?:dry )?mass|"
        r"total above-ground dry biomass|field survival|Kc|ETo|field capacity|"
        r"(?:measured )?volumetric water|travel speed|it)"
    )
    declaration = re.fullmatch(subject + r"\s+(?:is|are|was|were|has|have|contains|requires|delivers|weighs|supplies|covers|receives|targets|reports|found|totals|needs|uses|calls for|travels at)\b\s+(?P<value>[^!?;]+)", part, re.I)
    if declaration:
        return _calculation_value_is_owned(declaration['value'])
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
    head = (r"(?:calculate|compute|convert|work out|how (?:many|much)|"
            r"what (?:is|are|yield breaks even|seed(?:ing)? (?:rate|mass)))\b" if calculation else
            r"(?:why|how|explain|describe|define|what|which|compare|contrast)\b")
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
        premise = (r"(?:(?:an?\s+)?[+-]?(?:\d|\.\d)|(?:(?:the|an?)\s+)?(?:base(?: temperature)?|tmin|tmax|"
            r"(?:lab(?:oratory)? )?germination|(?:(?:expected|post[- ]germination) )?field (?:survival|mortality|loss)|expected emergence|target (?:stand|population)|"
            r"(?:measured )?tkw|(?:(?:expected|overall|field|seedling|post[- ]germination|lab(?:oratory)?) )*(?:survival|emergence|mortality|loss|germination)|seed[- ]lot germination|rooting depth|root[- ]zone depth|field (?:area|capacity)|wilting point|"
            r"measured volumetric water|kc|eto|net depth|application efficiency|travel speed|nozzle spacing|unusable (?:tank )?volume|radius|diameter|"
            r"grain dry (?:mass|matter)|total above[- ]ground dry (?:biomass|mass|matter)|"
            r"(?:upper|lower) cap|(?:no|without) (?:upper |lower |temperature )?caps?|negative (?:values|accumulation)|"
            r"(?:added|lost) revenue|(?:added|saved) costs?|current (?:assets?|liabilities)|total (?:debt|assets?|product)|"
            r"expected yield|(?:an? )?assumed price|(?:an? )?average of|operating cost|total cost|(?:an? )?unspecified (?:upper|lower) cap|P2O5|K2O|P|K)\b)")
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
        if re.match(r"(?:compare|contrast)\b", clause, re.I):
            if not is_concept_comparison_scope(clause):
                return True
            continue
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

"""Separate current host/symptom questions from reported soil-disease history.

The fields classify the user's statements and requested workflow. They never
confirm an organism, a current field observation or the accuracy of a report.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_HOST = r'canola|rapeseed|mustard|brassica\w*|crucifer\w*|cole crops?|cabbage|broccoli|cauliflower|brussels sprouts|kale|kohlrabi|radish|rutabaga|turnip'
_OTHER_CROP = r'corn|maize|soybeans?|barley|wheat|oats?|carrots?|potatoes|potato'
_HISTORY = re.compile(r'\b(?:previous|prior|earlier|historical|history|last (?:year|season|crop)|past (?:year|season|crop))\b|\b(?:had (?:root )?galls?|roots? (?:were|had been) swollen)\b', re.I)
_CURRENT = re.compile(r'\b(?:now|currently|today|this (?:year|season|crop))\b', re.I)
_SYMPTOMS = re.compile(r'\b(?:swollen roots?|roots?\s+(?:are|look|appear)\s+(?:(?:now|currently|visibly)\s+)?swollen|(?:root )?galls?|dying patch)\b', re.I)
_DIAGNOSIS = re.compile(r'\bclubroot\s*\?|\b(?:enough to confirm|confirm (?:the )?clubroot|diagnos(?:e|ing) clubroot|is (?:this|that|it) (?:really )?clubroot|could (?:this|that|it) be clubroot)\b', re.I)
_SOIL_REQUEST = re.compile(r'\b(?:soil[- ]movement|biosecurity|hygiene|sanitation|precautions?|contain\w*|restrict\w* traffic|equipment clean\w*|clean\w* equipment|prevent\w* (?:the )?spread)\b', re.I)
_NEGATED_SYMPTOMS = re.compile(
    r"\b(?:no|without|absence of|no evidence of)\s+(?:visible\s+|current\s+|observed\s+)?(?:root\s+)?(?:galls?|swelling)\b|"
    r"\b(?:no|without)\s+(?:visible\s+)?swollen roots?\b|\broots? (?:are|look|appear) not swollen\b|"
    r"\b(?:do not|don't|does not|doesn't) (?:have|show) (?:any )?(?:root )?galls?\b|"
    r"\b(?:root )?galls? (?:are|were) (?:absent|not present)\b", re.I)


# A declared subject/predicate keeps observations separate from definitions,
# quotations, historical reports and commands. Crop identity stays open: the
# article/possessive form accepts multiword crops without a host whitelist.
_ROOT_SUBJECT = r"(?:(?:my|our|the|these|this)\s+(?:[a-z][a-z-]*\s+){0,3}|(?:[a-z][a-z-]*\s+)?)roots?"
_ROOT_DECLARATION = re.compile(
    rf"(?:{_ROOT_SUBJECT}\s+(?:is|are|look|looks|appear|appears|seem|seems)\s+"
    r"(?:(?:now|currently|visibly)\s+)?swollen|"
    r"(?:(?:my|our|the|these|this)\s+)?[a-z][a-z-]*\s+(?:have|has)\s+swollen roots?|"
    r"(?:i|we)\s+(?:see|notice|found|have found|can see)\s+swollen roots?"
    r"(?:\s+(?:on|in)\s+(?:(?:my|our|the|these)\s+)?(?:[a-z][a-z-]*\s*){1,3})?)"
    r"(?:\s+(?:today|now|currently))?", re.I,
)
_ROOT_INSPECTION_REQUEST = re.compile(
    r"(?:what|which)\s+(?:should|can|could|do)\s+(?:i|we)\s+"
    r"(?:inspect|check|examine|look for)(?:\s+(?:today|now|next|first|in the field))?"
    r"|how\s+(?:(?:should|can|could|do)\s+(?:i|we)\s+)?"
    r"(?:inspect|check|examine|sample)\s+(?:(?:my|our|the|these)\s+)?roots?", re.I,
)


_ROOT_CLAUSE_CONNECTOR = re.compile(
    r"\b(?:then|also|please|because|if|when|unless|before|after|or|to|should|could|must|may|will|would)\b", re.I,
)


def _declared_root_match(clause: str) -> re.Match[str] | None:
    match = _ROOT_DECLARATION.match(clause)
    if match is None or _ROOT_CLAUSE_CONNECTOR.search(match.group()):
        return None
    if match.end() != len(clause) and not clause[match.end()].isspace():
        return None
    return match


def current_root_swelling_clauses(question: str) -> tuple[str, ...]:
    """Retain direct current root observations, never infer a cause or host.

    Historical scope carries through comma/conjunction clauses until an explicit
    current transition. Crop association uses only the matched observation span,
    excluding neighbouring or reference plants in its suffix.
    """
    from agronomy_agent.request_scope import has_action_directive
    found = []
    text = ' '.join(question.casefold().split())
    for sentence in re.split(r"[.!?;]", text):
        historical = False
        for clause in re.split(r",|\b(?:and|while|whereas|but)\b", sentence):
            clause = clause.strip()
            positive = _NEGATED_SYMPTOMS.sub('', clause)
            match = _declared_root_match(positive)
            history = _HISTORY.search(clause)
            current = _CURRENT.search(match.group()) if match is not None else None
            if history is not None and not (current is not None and current.start() < history.start()):
                historical = True
                continue
            if historical:
                if current is None:
                    continue
                historical = False
            if has_action_directive(clause):
                continue
            if match is not None:
                found.append(match.group().strip())
    return tuple(found)


def root_inspection_requested(question: str) -> bool:
    """Recognize an explicit observation request about current root swelling."""
    return bool(current_root_swelling_clauses(question) and _ROOT_INSPECTION_REQUEST.search(question))


def root_inspection_only_request(question: str) -> bool:
    """Qualify the complete observation task before omitting a decision plan."""
    if not root_inspection_requested(question):
        return False
    clauses = [p.strip() for p in re.split(r'[.!?;]', question) if p.strip()]
    if len(clauses) < 2 or not _ROOT_INSPECTION_REQUEST.fullmatch(clauses[-1]):
        return False
    # Every preceding sentence must itself be a complete declared observation.
    # Unknown prefixes, extra commands and more complex compounds retain plans.
    def declared_observation(clause: str) -> bool:
        match = _declared_root_match(clause)
        if match is None or not current_root_swelling_clauses(clause):
            return False
        tail = clause[match.end():].strip()
        if not tail:
            return True
        # A current report can include a bounded historical noun phrase, but
        # that phrase cannot consume an additional command or sequence.
        return bool(_CURRENT.search(match.group()) and re.fullmatch(
            r"(?:after|following)\s+(?:last (?:year|season)['’]s|previous|prior)\s+"
            r"(?:[a-z][a-z-]*\s*){1,3}", tail, re.I,
        ) and not _ROOT_CLAUSE_CONNECTOR.search(re.sub(r"^(?:after|following)\s+", "", tail, flags=re.I)))
    return all(declared_observation(clause) for clause in clauses[:-1])


def current_root_inspection_is_soybean(question: str) -> bool:
    """Only a directly named current affected soybean supports nodule guidance."""
    return any(re.search(r"\bsoybeans?\s+(?:plants?\s+)?roots?\b|"
                         r"\bsoybeans?\s+(?:have|has)\s+swollen roots?\b|"
                         r"\bswollen roots?\s+(?:on|in)\s+(?:(?:my|our|the|these)\s+)?soybeans?\b", clause, re.I)
               for clause in current_root_swelling_clauses(question))


@dataclass(frozen=True)
class ClubrootQuestionScope:
    current_crops: tuple[str, ...]
    host_scope: str
    current_symptoms: bool
    diagnosis_requested: bool
    soil_biosecurity_requested: bool
    history_reported: bool
    explicit_clubroot: bool
    negative_root_symptoms: bool = False
    symptomatic_other_crop: bool = False
    negated_root_observations: tuple[str, ...] = ()

    @property
    def workflow_applicable(self) -> bool:
        return ((self.explicit_clubroot and self.soil_biosecurity_requested)
                or (self.host_scope == 'susceptible'
                    and (self.current_symptoms or self.explicit_clubroot)))

    @property
    def confirmation_requested(self) -> bool:
        return self.host_scope == 'susceptible' and (self.current_symptoms or self.diagnosis_requested)


def clubroot_question_scope(question: str) -> ClubrootQuestionScope:
    text = ' '.join(question.casefold().split())
    current_clauses = [];history_reported = False
    # Keep a relative clause about previous roots with its historical sentence;
    # a contrast can reset the time frame only when it names a current period.
    for sentence in re.split(r'(?<=[.!?;])\s+', text):
        historical_context = False
        # An explicit present period after a comma/conjunction starts a new
        # current clause. The historical prefix must not erase that crop.
        for clause in re.split(r'\bbut\b|,|\band\b(?=[^,;.!?]{0,100}\b(?:now|currently|today|this (?:year|season|crop))\b)', sentence):
            history = _HISTORY.search(clause);present = _CURRENT.search(clause)
            if history is not None:
                history_reported = True;historical_context = True
                if present is not None and present.start() < history.start():
                    current_clauses.append(clause[:history.start()])
                continue
            if historical_context and present is None:
                continue
            current_clauses.append(clause)
    current = ' '.join(current_clauses)
    # A healthy neighbouring/reference crop is not the affected host. Keep all
    # current crop mentions for provenance, but derive workflow host scope only
    # from clauses that are not explicitly healthy comparisons.
    clauses = [part.strip() for clause in current_clauses for part in re.split(
        rf'\b(?:while|whereas)\b|\band\b(?=[^.!?;,]{{0,65}}\b(?:{_HOST}|{_OTHER_CROP})\b)', clause)]
    healthy = r'(?:healthy|normal|unaffected|symptom[- ]free)'
    healthy_subject = re.compile(
        rf'\b(?:(?:adjacent|nearby|neighboring|neighbouring|reference)\s+)?(?:{_HOST}|{_OTHER_CROP})\s+(?:(?:roots?|plants?|crop)\s+)?(?:is|are|looks?|appears?)\s+{healthy}\b|'
        rf'\b{healthy}\s+(?:{_HOST}|{_OTHER_CROP}|plants?|roots?|crop)\b', re.I)
    clauses = [healthy_subject.sub('', clause) for clause in clauses]
    relevant = ' '.join(clauses)
    all_hosts = {m.group() for m in re.finditer(rf'\b(?:{_HOST})\b', current, re.I)}
    all_others = {m.group() for m in re.finditer(rf'\b(?:{_OTHER_CROP})\b', current, re.I)}
    hosts = {m.group() for m in re.finditer(rf'\b(?:{_HOST})\b', relevant, re.I)}
    others = {m.group() for m in re.finditer(rf'\b(?:{_OTHER_CROP})\b', relevant, re.I)}
    host_scope = 'mixed' if hosts and others else 'susceptible' if hosts else 'other' if others else 'unknown'
    symptoms = bool(_SYMPTOMS.search(_NEGATED_SYMPTOMS.sub('', relevant)))
    other_symptoms = any(re.search(rf'\b(?:{_OTHER_CROP})\b', clause, re.I)
        and re.search(r'\b(?:symptoms?|stunt\w*|yellow\w*|wilting|dying|swollen|galls?|root\s+(?:damage|rot|injury))\b',
                      _NEGATED_SYMPTOMS.sub('', clause), re.I) for clause in clauses)
    return ClubrootQuestionScope(tuple(sorted(all_hosts | all_others)), host_scope, symptoms,
        bool(_DIAGNOSIS.search(current)), bool(_SOIL_REQUEST.search(text)), history_reported,
        bool(re.search(r'\bclubroot\b', text)), bool(_NEGATED_SYMPTOMS.search(relevant)), other_symptoms,
        tuple(m.group().strip() for m in _NEGATED_SYMPTOMS.finditer(relevant)))


def clubroot_workflow_applicable(question: str) -> bool:
    return clubroot_question_scope(question).workflow_applicable


def clubroot_confirmation_requested(question: str) -> bool:
    return clubroot_question_scope(question).confirmation_requested


def clubroot_short_rotation_requested(question: str) -> bool:
    return bool(re.search(r'\b(?:one|1|single)\s+(?:(?:non[- ]?host|rotation)\s+)?year\b', question, re.I))

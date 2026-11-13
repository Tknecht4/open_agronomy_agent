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


@dataclass(frozen=True)
class ClubrootQuestionScope:
    current_crops: tuple[str, ...]
    host_scope: str
    current_symptoms: bool
    diagnosis_requested: bool
    soil_biosecurity_requested: bool
    history_reported: bool
    explicit_clubroot: bool

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
        for clause in re.split(r'\bbut\b', sentence):
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
    hosts = {m.group() for m in re.finditer(rf'\b(?:{_HOST})\b', current, re.I)}
    others = {m.group() for m in re.finditer(rf'\b(?:{_OTHER_CROP})\b', current, re.I)}
    host_scope = 'mixed' if hosts and others else 'susceptible' if hosts else 'other' if others else 'unknown'
    symptoms = bool(_SYMPTOMS.search(_NEGATED_SYMPTOMS.sub('', current)))
    return ClubrootQuestionScope(tuple(sorted(hosts | others)), host_scope, symptoms,
        bool(_DIAGNOSIS.search(current)), bool(_SOIL_REQUEST.search(text)), history_reported,
        bool(re.search(r'\bclubroot\b', text)))


def clubroot_workflow_applicable(question: str) -> bool:
    return clubroot_question_scope(question).workflow_applicable


def clubroot_confirmation_requested(question: str) -> bool:
    return clubroot_question_scope(question).confirmation_requested


def clubroot_short_rotation_requested(question: str) -> bool:
    return bool(re.search(r'\b(?:one|1|single)\s+(?:(?:non[- ]?host|rotation)\s+)?year\b', question, re.I))

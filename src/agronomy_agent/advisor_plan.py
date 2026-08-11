from __future__ import annotations

import re

from agronomy_agent.router import QueryRoute


def answer_coverage_checklist(question: str, route: QueryRoute) -> tuple[str, ...]:
    q = question.lower()
    items: list[str] = []

    if _has(r"\b(4r|right source|right rate|right time|right place|nutrient management plan|manure history|tile drainage)\b", q):
        return (
            "right source",
            "right rate",
            "right time",
            "right place",
            "soil test and yield goal",
            "manure analysis and manure or legume credit",
            "tile drainage, leaching, runoff, or water quality risk",
            "records",
        )

    if _has(r"\b(photo|leaf spot|spots)\b", q):
        return (
            "diagnosis or identify the problem",
            "crop stage",
            "field history",
            "photos or sample",
            "scout upper leaves and distribution",
            "do not recommend product before identification",
            "label if treatment is later considered",
        )

    if route.question_type.startswith("fertility"):
        items.extend(["soil test", "local calibration", "crop and yield goal"])
        if _has(r"\b(4r|right source|right rate|right time|right place|nutrient management plan|manure history|tile drainage)\b", q):
            items = [
                "right source",
                "right rate",
                "right time",
                "right place",
                "soil test and yield goal",
                "manure analysis and manure or legume credit",
                "tile drainage, leaching, runoff, or water quality risk",
                "records",
            ]
        if _has(r"\b(nitrogen|n loss|nitrate|increase nitrogen|rain|rainfall|wet|leach|leaching)\b", q):
            items = [
                "soil test",
                "local calibration",
                "crop and yield goal",
                "credits, manure, or previous crop",
                "recent rainfall, irrigation, drainage, or leaching risk",
                "split application or timing",
            ]
        if _has(r"\b(no soil test|no tissue test|phone description|yellow corn|yellowing)\b", q):
            items = [
                "not enough to diagnose from the phone description",
                "field pattern",
                "soil test or tissue test",
                "photos or scouting details",
                "weather, drainage, and recent rainfall context",
            ]
        if _has(r"\blime|low ph|buffer ph\b", q):
            items = [
                "soil test",
                "buffer pH or lime requirement",
                "target pH",
                "crop or rotation",
                "CCE, ECCE, or neutralizing value of the lime source",
            ]
        if _has(r"\bsulfur|sulphur\b", q):
            items = [
                "sandy or low organic matter soil",
                "recent rainfall, irrigation, or leaching",
                "field pattern",
                "soil test or tissue test",
                "nitrogen or other deficiency",
            ]
        if _has(r"\bphosphorus|water quality|ditch|runoff\b", q):
            items = [
                "soil test phosphorus",
                "soil test method",
                "Bray, Olsen, and Mehlich are not interchangeable without calibration",
                "runoff, erosion, ditch, or water quality pathway",
                "setback or buffer",
                "manure history",
                "crop removal or drawdown",
                "avoid additional phosphorus when risk is high",
            ]
        if _has(r"\b(phosphorus|bray|olsen|mehlich)\b", q) and _has(r"\b(does not say|unknown|without|missing|method)\b", q):
            items = [
                "soil test method or lab method",
                "Bray, Olsen, and Mehlich are not interchangeable without calibration",
                "local calibration or critical level",
                "soil pH",
                "crop and yield goal",
                "crop removal",
            ]

    if route.question_type == "soil_water":
        if _has(r"\b(restrictive layer|hardpan|plow pan|ponding|shallow roots?|compaction|traffic|cart)\b", q):
            items = [
                "compaction, hardpan, plow pan, or restrictive layer",
                "ponding or infiltration",
                "traffic pattern",
                "penetrometer, probe, or soil pit",
                "soil moisture at diagnosis",
                "rooting depth",
                "controlled traffic, targeted tillage, or cover crop options",
            ]
        elif _has(r"\bcover crops?|dryland\b", q):
            items = [
                "water use or soil moisture",
                "erosion or residue benefit",
                "species or mix",
                "termination timing and termination plan",
                "crop rotation and next-crop planting window",
            ]
        elif _has(r"\bsalinity|sodicity|saline|sodic|white crust|stunting\b", q):
            items = [
                "soil test",
                "electrical conductivity or EC",
                "soil EC or salinity test",
                "irrigation water test",
                "sodium, SAR, or ESP",
                "drainage and leaching",
            ]
        else:
            items.extend(["soil texture", "drainage", "water table", "runoff or leaching"])

    if route.question_type == "product_label":
        items.extend(["current local label", "jurisdiction", "crop and target pest or use"])
        if _has(r"\b(health|safety|environmental checks?|ppe|personal protective|restricted entry|rei\b|preharvest|phi\b|storage|handling|sensitive area)\b", q):
            items = [
                "current local label",
                "personal protective equipment or PPE",
                "restricted entry interval or REI",
                "preharvest interval or PHI when relevant",
                "buffer and drift controls",
                "water or sensitive-area protection",
                "storage, handling, disposal, and records",
            ]
        if _has(r"\b(resistance|resistant|escapes?|same herbicide|mode of action|site of action|rotate)\b", q):
            items = [
                "weed species or target pest",
                "field history and previous herbicide program",
                "scout escapes",
                "mode of action or site of action",
                "rotate or mix multiple effective modes of action",
                "nonchemical tactics such as crop rotation or mechanical control",
                "current local label",
            ]
        if _has(r"\bvolatile|dicamba|drift|wind|sensitive|downwind\b", q):
            items = [
                "do not spray or delay until conditions are verified",
                "current local label",
                "wind speed, wind direction, and gusts",
                "downwind sensitive crops",
                "buffer or drift restrictions",
            ]
        if _has(r"\bfungicide|price|retailer|roi\b", q):
            items = [
                "disease level or scouting severity",
                "hybrid susceptibility",
                "growth stage",
                "weather favorability",
                "yield potential and economics",
                "current local label",
            ]

    if route.question_type == "seed_treatment":
        items = [
            "early planting date",
            "soil temperature or cool wet planting conditions",
            "pest history",
            "seedcorn maggot, bean leaf beetle, wireworm, or grub risk",
            "threshold or risk level",
            "field history and pest pressure",
        ]

    if route.question_type == "crop_management":
        if _has(r"\b(planting window|plant into|supporting the planting|crop establishment)\b", q):
            items = [
                "soil temperature",
                "soil moisture or wet-dry field condition",
                "seedbed condition and sidewall compaction risk",
                "short forecast",
                "emergence or stand risk",
            ]
        elif _has(r"\breplant|uneven stand|stand\b", q):
            items = [
                "stand count or population",
                "uniformity and gaps",
                "growth stage and survival",
                "calendar or planting date",
                "hybrid maturity",
                "yield potential and economics",
            ]
        elif _has(r"\bwhite mold\b", q):
            items = [
                "variety tolerance and variety ratings",
                "variety ratings",
                "field history",
                "canopy, row spacing, and population",
                "rotation",
                "fungicide timing or disease risk",
            ]
        elif _has(r"\bharvest|storage|moisture\b", q):
            items = [
                "grain moisture",
                "drying, dryer, or aeration",
                "test weight or quality",
                "mold or mycotoxin risk",
                "storage plan",
                "weather forecast",
                "field loss or standability",
            ]

    if route.question_type == "field_data":
        items = [
            "soil tests and zones",
            "expected yield response or response curve",
            "expected response",
            "fertilizer cost and crop price",
            "partial budget, ROI, or profit",
            "check strip or trial",
            "check strips or trials",
            "validated layers and audit trail",
        ]

    return tuple(dict.fromkeys(items))


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None

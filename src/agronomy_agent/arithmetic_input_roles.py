"""Named input roles shared by arithmetic extraction and request qualification.

These noncapturing patterns name existing operands, not calculation intents,
units, methods or field actions. Parsers still bind every supplied quantity;
scope checks must consume the entire value and the rest of the request.
"""

SEED_WEIGHT_ROLE = r"(?:thousand[- ]kernel weight|tkw)"
SEED_TARGET_ROLE = r"target(?: established)? (?:stand|population)"
GERMINATION_ROLE = r"(?:overall\s+)?(?:(?:seed[- ]lot|lab(?:oratory)?)\s+)?germination"
SURVIVAL_ROLE = r"(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:survival|emergence)"
SEED_LOSS_ROLE = r"(?:(?:expected|overall|field|seedling|post[- ]germination)\s+)*(?:loss|mortality)"

MEAN_TEMPERATURE_ROLE = r"(?:mean daily|daily mean|average daily|daily average) temperature"
MAX_TEMPERATURE_ROLE = r"(?:tmax|max(?:imum)?(?: temp(?:erature)?)?|high)"
MIN_TEMPERATURE_ROLE = r"(?:tmin|min(?:imum)?(?: temp(?:erature)?)?|low)"
BASE_TEMPERATURE_ROLE = r"base(?: temperature)?"

FIELD_CAPACITY_ROLE = r"(?:target )?field capacity"
WILTING_POINT_ROLE = r"(?:permanent )?wilting point"
ROOT_DEPTH_ROLE = r"(?:rooting|root[- ]zone) depth"

ADDED_RETURNS_ROLE = r"(?:added|additional|increased)\s+(?:revenue|returns?|income)"
REDUCED_COSTS_ROLE = r"(?:(?:reduced|saved|lower)\s+costs?|cost\s+savings?)"
ADDED_COSTS_ROLE = r"(?:added|additional|increased)\s+costs?"
REDUCED_RETURNS_ROLE = r"(?:lost|foregone|reduced)\s+(?:revenue|returns?|income)"
YIELD_ROLE = r"(?:(?:expected|harvested|target)\s+)?yield"
VALUE_FIRST_COST_BASIS_ROLE = r"(?:total|operating)"
COST_BASIS_ROLE = rf"(?:total economic|{VALUE_FIRST_COST_BASIS_ROLE})"
BUDGET_TOTAL_ROLE = r"(?:crop\s+)?budget\s+totals?"
UNQUALIFIED_COST_ROLE = r"costs?"
COST_ROLE = rf"(?:{COST_BASIS_ROLE}\s+{UNQUALIFIED_COST_ROLE}|{BUDGET_TOTAL_ROLE}|{UNQUALIFIED_COST_ROLE})"
CURRENT_ASSETS_ROLE = r"current assets?"
CURRENT_LIABILITIES_ROLE = r"current liabilities"
TOTAL_DEBT_ROLE = r"(?:total\s+)?debt"
TOTAL_ASSETS_ROLE = r"(?:total\s+)?assets"

# These existing financial basis labels also need one definition wherever a
# supplied value is recognized. They do not select a currency or output basis.
AREA_UNIT_PATTERN = r"(?:ac|acre|acres|ha|hectare|hectares)"
YIELD_UNIT_PATTERN = r"(?:bu|bushels?|tonnes?|t|kg|lb)"
MONEY_FLOW_ROLES = (
    ADDED_RETURNS_ROLE, REDUCED_COSTS_ROLE, ADDED_COSTS_ROLE,
    REDUCED_RETURNS_ROLE, COST_ROLE,
)
BALANCE_SHEET_ROLES = (
    CURRENT_ASSETS_ROLE, CURRENT_LIABILITIES_ROLE, TOTAL_DEBT_ROLE,
    TOTAL_ASSETS_ROLE,
)
MONEY_FLOW_ROLE_PATTERN = "(?:" + "|".join(MONEY_FLOW_ROLES) + ")"
BALANCE_SHEET_ROLE_PATTERN = "(?:" + "|".join(BALANCE_SHEET_ROLES) + ")"

ARITHMETIC_INPUT_ROLES = (
    SEED_WEIGHT_ROLE, SEED_TARGET_ROLE, GERMINATION_ROLE, SURVIVAL_ROLE,
    SEED_LOSS_ROLE, MEAN_TEMPERATURE_ROLE, MAX_TEMPERATURE_ROLE,
    MIN_TEMPERATURE_ROLE, BASE_TEMPERATURE_ROLE, FIELD_CAPACITY_ROLE,
    WILTING_POINT_ROLE, ROOT_DEPTH_ROLE, ADDED_RETURNS_ROLE,
    REDUCED_COSTS_ROLE, ADDED_COSTS_ROLE, REDUCED_RETURNS_ROLE, YIELD_ROLE,
    COST_ROLE, *BALANCE_SHEET_ROLES,
)
ARITHMETIC_INPUT_ROLE_PATTERN = "(?:" + "|".join(ARITHMETIC_INPUT_ROLES) + ")"

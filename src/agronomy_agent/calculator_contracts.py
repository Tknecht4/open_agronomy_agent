"""Current typed-calculator identities shared by planning and verification."""

CALCULATOR_VERSION = "agronomic_calculator_v2"
LEGACY_CALCULATOR_VERSION = "agronomic_calculator_v1"
CALCULATOR_SCHEMA_VERSION = "open_agronomy_agent.agronomic_calculator.schema.v2"
TOOL_PLANNER_VERSION = "open_agronomy_agent.tool_planner.v2"
EXPLICIT_ARITHMETIC_SELECTOR_ID = "explicit_arithmetic_parser_v2"

FOUNDATION_OPERATIONS = frozenset({
    "seed_rate_mass_imperial",
    "break_even_price",
    "break_even_yield",
    "current_ratio",
    "debt_to_asset_percent",
})


def tool_version_for(operation: str) -> str:
    """Keep the frozen v1 operation family distinct from v2 additions."""

    return CALCULATOR_VERSION if operation in FOUNDATION_OPERATIONS else LEGACY_CALCULATOR_VERSION


def format_calculator_clarification(missing_inputs: tuple[str, ...]) -> str:
    """One text contract for planner output and answerability replay."""

    if any(item.startswith("invalid ") for item in missing_inputs):
        return "I can't calculate from these inputs: " + "; ".join(
            item.removeprefix("invalid ") for item in missing_inputs
        ) + "."
    return "To calculate this, provide " + ", ".join(missing_inputs) + "."

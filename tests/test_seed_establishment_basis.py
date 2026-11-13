from decimal import Decimal

import pytest

from agronomy_agent.agronomic_calculations import calculate_agronomic
from agronomy_agent.tool_planner import plan_and_execute_tools


def _plan(suffix, *, germination="germination is 96%, and ", imperial=False):
    density = "8 plants/ft²" if imperial else "80 plants/m²"
    return plan_and_execute_tools(
        f"Calculate seed rate: target stand is {density}, TKW is 4.5 g, {germination}{suffix}."
    )


@pytest.mark.parametrize("suffix,germination,value,basis", [
    ("expected emergence is 75% overall of seeds sown (already including germination)", "germination is 96%, and ", 4.8, "seeds_sown"),
    ("field survival is 75% of germinated seeds", "germination is 96%, and ", 5.0, "germinated_seeds"),
    ("75% post-germination survival", "germination is 96%, and ", 5.0, "germinated_seeds"),
    ("expected emergence is 75%", "germination is 96%, and ", 4.8, "seeds_sown"),
    ("overall emergence is 75%", "", 4.8, "seeds_sown"),
    ("75% of seeds sown emerge", "", 4.8, "seeds_sown"),
    ("overall field survival is 75%", "", 4.8, "seeds_sown"),
    ("field survival is 75% of seeds sown, not of germinated seeds", "germination is 96%, and ", 4.8, "seeds_sown"),
    ("field survival is 75% of germinated seeds, not of seeds sown", "germination is 96%, and ", 5.0, "germinated_seeds"),
    ("field survival is 75% of germinated seeds. Compute the overall seed rate", "germination is 96%, and ", 5.0, "germinated_seeds"),
])
def test_supplied_denominator_is_preserved(suffix, germination, value, basis):
    plan, results = _plan(suffix, germination=germination)
    assert plan.status == "ready"
    result = results[0].payload
    assert result["value"] == pytest.approx(value)
    assert result["inputs"]["survival_basis"] == basis
    assert ("germination_pct" in result["inputs"]) == bool(germination)
    if germination:
        assert result["inputs"]["germination_pct"] == 96
    assert "effective established fraction" in result["answer"]
    assert "seeds sown" in result["answer"] if basis == "seeds_sown" else "post-germination survival" in result["answer"]


@pytest.mark.parametrize("suffix", ["field survival is 75%", "75% seedling survival", "25% mortality", "seedling mortality is 25%"])
def test_unqualified_survival_or_mortality_needs_one_denominator_question(suffix):
    plan, results = _plan(suffix, germination="")
    assert plan.status == "clarification_required"
    assert not results
    assert "seeds sown" in plan.clarification and "germinated seeds" in plan.clarification
    assert "germination percent" not in plan.clarification


@pytest.mark.parametrize("suffix", [
    "expected emergence is 75%, not including germination",
    "expected emergence is 75%, excluding germination",
    "expected emergence is 75% and does not include germination",
    "expected emergence is 75% and doesn't include germination",
    "expected emergence is 75% and doesn’t include germination",
    "expected emergence is 75% without germination",
])
def test_excluded_germination_does_not_activate_the_overall_emergence_default(suffix):
    plan, results = _plan(suffix)
    assert plan.status == "clarification_required" and not results
    assert "seeds sown" in plan.clarification


def test_overall_laboratory_germination_does_not_change_the_survival_denominator():
    plan, results = _plan("post-germination field survival is 75%", germination="overall germination is 96%, and ")
    assert plan.status == "ready"
    assert results[0].payload["value"] == 5


def test_laboratory_percentage_and_singular_viable_seed_preserve_the_conditional_model():
    plan, results = _plan("field survival is 75% of viable seed", germination="96% laboratory germination, and ")
    assert plan.status == "ready"
    assert results[0].payload["value"] == 5
    assert results[0].payload["inputs"]["germination_pct"] == 96


@pytest.mark.parametrize("suffix", [
    "field survival is 75% overall of seeds sown and of germinated seeds",
    "75% post-germination survival and 10% post-germination mortality",
    "75% overall emergence or 80% overall emergence",
])
def test_conflicting_bases_or_percentages_cannot_execute(suffix):
    plan, results = _plan(suffix)
    assert plan.status == "clarification_required"
    assert not results
    assert "invalid" in plan.invocations[0].missing_inputs[0]


def test_post_germination_loss_is_retained_and_applied_once():
    plan, results = _plan("25% post-germination mortality")
    assert plan.status == "ready"
    assert results[0].payload["value"] == pytest.approx(5)
    assert results[0].payload["inputs"]["mortality_pct"] == 25
    assert results[0].payload["inputs"]["field_survival_pct"] == 75


@pytest.mark.parametrize("basis,germination", [("seeds_sown", None), ("seeds_sown", 96), ("germinated_seeds", 96)])
@pytest.mark.parametrize("method", ["dimensional", "published_factor_10", "compare"])
def test_imperial_uses_same_establishment_denominator(basis, germination, method):
    inputs = {"target_plants_per_ft2": 8, "tkw_g": 4.5, "field_survival_pct": 75, "survival_basis": basis, "method": method}
    if germination is not None:
        inputs["germination_pct"] = germination
    result = calculate_agronomic("seed_rate_mass_imperial", inputs)
    fraction = Decimal("0.75") * (Decimal("0.96") if basis == "germinated_seeds" else 1)
    expected = Decimal(8) * Decimal("4.5") / (fraction * 10) if method == "published_factor_10" else Decimal(8) * Decimal("4.5") * 43560 / (fraction * 1000 * Decimal("453.59237"))
    assert result.value == expected
    assert result.inputs.get("germination_pct") == (Decimal(96) if germination else None)


def test_imperial_natural_language_uses_overall_emergence_without_germination():
    plan, results = _plan("75% overall emergence", germination="", imperial=True)
    assert plan.status == "ready"
    assert results[0].payload["unit"] == "lb/ac"
    assert "germination_pct" not in results[0].payload["inputs"]
    assert results[0].payload["inputs"]["survival_basis"] == "seeds_sown"


@pytest.mark.parametrize("extra,error", [
    ({}, "missing required fields"),
    ({"survival_basis": "germinated_seeds"}, "germination_pct is required"),
    ({"survival_basis": "unknown"}, "survival_basis"),
    ({"survival_basis": "seeds_sown", "mortality_pct": 10}, "complementary"),
    ({"survival_basis": "seeds_sown", "germination_pct": True}, "numeric"),
])
def test_structured_seed_contract_requires_explicit_valid_basis(extra, error):
    with pytest.raises(ValueError, match=error):
        calculate_agronomic("seed_rate_mass", {"target_plants_per_m2": 80, "tkw_g": 4.5, "field_survival_pct": 75, **extra})


@pytest.mark.parametrize("operation,target_key,extra", [
    ("seed_rate_mass", "target_plants_per_m2", {}),
    ("seed_rate_mass_imperial", "target_plants_per_ft2", {"method": "dimensional"}),
])
def test_seed_validator_rejects_nonrepresentable_results_before_dispatch(operation, target_key, extra):
    from agronomy_agent.agronomic_calculations import validate_seed_rate_inputs
    inputs = {target_key: "1e200", "tkw_g": "1e200", "field_survival_pct": 75, "survival_basis": "seeds_sown", **extra}
    with pytest.raises(ValueError, match="numeric output range"):
        validate_seed_rate_inputs(operation, inputs)
    with pytest.raises(ValueError, match="numeric output range"):
        calculate_agronomic(operation, inputs)


@pytest.mark.parametrize("target,tkw", [("1e400", "1e-400"), ("1e-400", "1e400"), ("1e-400", "1"), ("1e-320", "1e-20")])
def test_seed_record_cannot_overflow_operands_or_underflow_nonzero_result(target, tkw):
    from agronomy_agent.agronomic_calculations import validate_seed_rate_inputs
    inputs = {"target_plants_per_m2": target, "tkw_g": tkw, "field_survival_pct": 75, "survival_basis": "seeds_sown"}
    with pytest.raises(ValueError, match="numeric output range"):
        validate_seed_rate_inputs("seed_rate_mass", inputs)
    with pytest.raises(ValueError, match="numeric output range"):
        calculate_agronomic("seed_rate_mass", inputs)


@pytest.mark.parametrize("suffix", ["20% seedling mortality", "20% seedling mortality of all seeds sown", "seedling mortality is 20% overall", "20% mortality of seedlings",
    "20% mortality of all seeds sown at the seedling stage",
    "20% mortality of all seeds sown after germination",
    "20% mortality of all seeds sown after 96% germination"])
def test_stage_specific_seedling_loss_does_not_become_overall_survival(suffix):
    from agronomy_agent.seed_establishment import SEED_LOSS_MODEL_GAP
    plan, results = _plan(suffix)
    assert plan.status == "clarification_required" and not results
    assert SEED_LOSS_MODEL_GAP in plan.invocations[0].missing_inputs
    assert "field_survival_pct" not in plan.invocations[0].inputs
    assert "survival_basis" not in plan.invocations[0].inputs
    assert plan.invocations[0].inputs["mortality_pct"] == 20


def test_explicit_seedling_mortality_among_germinated_seeds_is_preserved():
    plan, results = _plan("20% seedling mortality among germinated seeds")
    assert plan.status == "ready"
    assert results[0].payload["value"] == pytest.approx(80 * 4.5 / (.96 * .8 * 100))
    assert results[0].payload["inputs"]["survival_basis"] == "germinated_seeds"


def test_explicit_total_mortality_including_germination_remains_overall():
    plan, results = _plan("20% overall mortality including germination and seedling loss")
    assert plan.status == "ready"
    assert results[0].payload["inputs"]["survival_basis"] == "seeds_sown"
    assert results[0].payload["value"] == pytest.approx(4.5)


def test_later_sentence_stage_language_does_not_requalify_total_mortality():
    from agronomy_agent.seed_establishment import parse_seed_establishment, SEED_LOSS_MODEL_GAP
    inputs, gaps = parse_seed_establishment("germination 90%; 20% mortality of all seeds sown. The seedling stage is discussed separately.")
    assert inputs["field_survival_pct"] == 80 and inputs["survival_basis"] == "seeds_sown"
    assert SEED_LOSS_MODEL_GAP not in gaps


def test_loss_stage_prefix_is_not_an_overall_complement_or_a_whole_request_bypass():
    from agronomy_agent.seed_establishment import parse_seed_establishment, SEED_LOSS_MODEL_GAP
    text = "germination 96%, and after germination, 20% mortality of all seeds sown"
    inputs, gaps = parse_seed_establishment(text)
    assert "field_survival_pct" not in inputs and SEED_LOSS_MODEL_GAP in gaps
    plan, results = _plan("after germination, 20% mortality of all seeds sown")
    assert plan.status != "ready" and not results


@pytest.mark.parametrize("exclusion", [
    "without including germination", "without already including germination",
    "not already including germination", "does not already include germination",
    "doesn't include germination", "doesn’t already include germination",
    "without laboratory germination",
])
def test_negative_inclusion_cue_cannot_authorize_an_overall_seedling_loss(exclusion):
    from agronomy_agent.seed_establishment import SEED_LOSS_MODEL_GAP
    plan, results = _plan("20% seedling mortality " + exclusion)
    assert plan.status == "clarification_required" and not results
    assert "field_survival_pct" not in plan.invocations[0].inputs
    assert SEED_LOSS_MODEL_GAP in plan.invocations[0].missing_inputs


@pytest.mark.parametrize("inclusion", ["including germination", "already includes germination", "does include laboratory germination"])
def test_affirmative_total_loss_inclusion_is_not_treated_as_an_exclusion(inclusion):
    from agronomy_agent.seed_establishment import parse_seed_establishment
    inputs, gaps = parse_seed_establishment("germination 96%; 20% overall mortality " + inclusion + " and seedling loss")
    assert not gaps and inputs["field_survival_pct"] == 80 and inputs["survival_basis"] == "seeds_sown"


def test_later_emergence_inclusion_cannot_redefine_the_earlier_seedling_loss():
    from agronomy_agent.seed_establishment import SEED_LOSS_MODEL_GAP
    plan, results = _plan("20% seedling mortality, overall emergence 80% including germination")
    assert plan.status == "clarification_required" and not results
    assert SEED_LOSS_MODEL_GAP in plan.invocations[0].missing_inputs
    # The explicitly supplied emergence remains a user input; the unresolved
    # additional loss is not falsely executed as its total-loss complement.
    assert plan.invocations[0].inputs["field_survival_pct"] == 80

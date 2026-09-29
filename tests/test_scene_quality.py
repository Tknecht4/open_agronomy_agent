"""Analytic receipt contracts for provider-neutral scene support ranking."""

from copy import deepcopy
from itertools import permutations

import pytest

from agronomy_agent.geospatial.scene_quality import (
    POLICY_VERSION, assess_support, rank_candidates, validate_policy,
)


def policy(*, index="NDVI", support="field", minimum=0.5):
    return {"version": POLICY_VERSION, "index": index, "support": support,
            "min_valid_fraction": minimum}


def stat(area, value=0.3):
    return {"area_m2": area, "mean": value if area else None,
            "min": value if area else None, "max": value if area else None}


def receipt(*, field=100, clear=80, ndvi=70, ndmi=40, interior=50,
            interior_clear=40, interior_ndvi=35, interior_ndmi=20):
    return {"status": "available" if clear else "empty_valid_area",
            "qa": {"field_area_m2": field, "valid_area_m2": clear,
                   "interior_field_area_m2": interior,
                   "interior_valid_area_m2": interior_clear},
            "zonal_stats": {"NDVI": stat(ndvi), "NDMI": stat(ndmi)},
            "interior_zonal_stats": {"NDVI": stat(interior_ndvi),
                                     "NDMI": stat(interior_ndmi)}}


def test_policy_requires_explicit_finite_threshold_and_fixed_ranking():
    normalized = validate_policy(policy())
    assert normalized["ranking"] == "valid_fraction_desc_acquired_desc_scene_id_asc"
    assert validate_policy(normalized) == normalized
    for change in ({"min_valid_fraction": True}, {"min_valid_fraction": float("nan")},
                   {"min_valid_fraction": float("inf")}, {"min_valid_fraction": -0.1},
                   {"min_valid_fraction": 1.1}, {"index": "EVI"},
                   {"support": "scene"}, {"version": "future"},
                   {"ranking": "cloud_percent_asc"}):
        with pytest.raises(ValueError):
            validate_policy(policy() | change)
    with pytest.raises(ValueError):
        validate_policy({"version": POLICY_VERSION, "index": "NDVI", "support": "field"})


def test_selected_index_area_controls_fraction_not_qa_clear_or_index_value():
    item = receipt()
    assert assess_support(item, policy())["valid_fraction"] == pytest.approx(0.7)
    assert assess_support(item, policy(index="NDMI"))["valid_fraction"] == pytest.approx(0.4)
    assert assess_support(item, policy(index="NDMI"))["reason"] == "below_min_valid_fraction"
    item["zonal_stats"]["NDVI"]["mean"] = 0.9
    item["zonal_stats"]["NDVI"]["max"] = 0.9
    assert assess_support(item, policy())["valid_fraction"] == pytest.approx(0.7)


def test_field_and_interior_denominators_are_distinct():
    item = receipt()
    field = assess_support(item, policy())
    interior = assess_support(item, policy(support="interior"))
    assert field["valid_fraction"] == pytest.approx(0.7)
    assert interior["valid_fraction"] == pytest.approx(0.7)
    item["interior_zonal_stats"]["NDVI"]["area_m2"] = 20
    assert assess_support(item, policy(support="interior"))["valid_fraction"] == pytest.approx(0.4)
    assert assess_support(item, policy())["valid_fraction"] == pytest.approx(0.7)


def test_empty_support_never_wins_even_at_zero_threshold():
    item = receipt(clear=0, ndvi=0, ndmi=0, interior_clear=0,
                   interior_ndvi=0, interior_ndmi=0)
    assert assess_support(item, policy(minimum=0))["reason"] == "no_valid_index_support"
    item = receipt(interior=0, interior_clear=0, interior_ndvi=0, interior_ndmi=0)
    assessment = assess_support(item, policy(support="interior", minimum=0))
    assert assessment["status"] == "rejected"
    assert assessment["reason"] == "empty_interior"
    assert assessment["valid_fraction"] is None
    del item["interior_zonal_stats"]
    assert assess_support(item, policy(support="interior"))["status"] == "unavailable"


def test_zero_denominator_does_not_absorb_positive_area_roundoff():
    item = receipt(interior=0, interior_clear=0, interior_ndvi=0, interior_ndmi=0)
    item["qa"]["interior_valid_area_m2"] = 5e-7
    assert assess_support(item, policy(support="interior"))["status"] == "unavailable"
    item = receipt(clear=0, ndvi=0, ndmi=0, interior_clear=0,
                   interior_ndvi=0, interior_ndmi=0)
    item["zonal_stats"]["NDVI"] = stat(5e-7)
    assert assess_support(item, policy(minimum=0))["status"] == "unavailable"


def test_tolerated_area_roundoff_normalizes_consistently_for_ranking():
    chosen = policy(minimum=1)
    item = receipt(field=1, clear=1, ndvi=1.0000005, ndmi=0,
                   interior=0, interior_clear=0, interior_ndvi=0, interior_ndmi=0)
    assessed = assess_support(item, chosen)
    assert assessed["status"] == "eligible"
    assert assessed["valid_fraction"] == 1
    ranked = rank_candidates([{"scene_id": "s", "acquired_at": "2024-01-01T00:00:00Z",
                               "assessment": assessed}], chosen)
    assert ranked["selected_scene_id"] == "s"


@pytest.mark.parametrize("change", [
    lambda r: r["qa"].pop("field_area_m2"),
    lambda r: r["qa"].update(field_area_m2=True),
    lambda r: r["qa"].update(field_area_m2=float("nan")),
    lambda r: r["qa"].update(valid_area_m2=-1),
    lambda r: r["qa"].update(valid_area_m2=101),
    lambda r: r["zonal_stats"]["NDVI"].update(area_m2=81),
    lambda r: r["zonal_stats"]["NDVI"].update(area_m2=-1),
    lambda r: r["zonal_stats"]["NDVI"].update(area_m2=float("inf")),
    lambda r: r["zonal_stats"]["NDVI"].update(mean=None),
    lambda r: r["zonal_stats"]["NDVI"].update(mean=float("nan")),
    lambda r: r.update(status="empty_valid_area"),
])
def test_bad_field_metadata_is_unavailable(change):
    item = receipt()
    change(item)
    assessed = assess_support(item, policy())
    assert assessed["status"] == "unavailable"
    assert assessed["valid_fraction"] is None


@pytest.mark.parametrize("change", [
    lambda r: r["qa"].pop("interior_field_area_m2"),
    lambda r: r["qa"].update(interior_field_area_m2=101),
    lambda r: r["qa"].update(interior_valid_area_m2=51),
    lambda r: r["qa"].update(interior_valid_area_m2=float("nan")),
    lambda r: r["interior_zonal_stats"]["NDVI"].update(area_m2=41),
    lambda r: r["interior_zonal_stats"]["NDVI"].update(area_m2=71),
    lambda r: r["interior_zonal_stats"]["NDVI"].update(min=0.5),
])
def test_bad_interior_metadata_is_unavailable(change):
    item = receipt()
    change(item)
    assert assess_support(item, policy(support="interior"))["status"] == "unavailable"


def test_processing_failures_are_unavailable():
    for status in ("failed", "resource_limit", "no_scene", None):
        item = receipt()
        item["status"] = status
        assert assess_support(item, policy())["reason"] == "processing_unavailable"


def test_ranking_is_order_independent_and_support_first():
    chosen = policy()
    rows = [
        {"scene_id": "z", "acquired_at": "2024-01-03T00:00:00Z",
         "assessment": assess_support(receipt(ndvi=60), chosen)},
        {"scene_id": "b", "acquired_at": "2024-01-02T00:00:00+00:00",
         "assessment": assess_support(receipt(), chosen)},
        {"scene_id": "a", "acquired_at": "2024-01-01T17:00:00-07:00",
         "assessment": assess_support(receipt(), chosen)},
    ]
    for ordering in permutations(rows):
        ranked = rank_candidates(list(ordering), chosen)
        assert ranked["status"] == "selected"
        assert ranked["ranked_scene_ids"] == ["a", "b", "z"]
        assert ranked["selected_scene_id"] == "a"


def test_unavailable_attempt_prevents_complete_winner():
    chosen = policy()
    good = {"scene_id": "good", "acquired_at": "2024-01-01T00:00:00Z",
            "assessment": assess_support(receipt(), chosen)}
    bad = {"scene_id": "bad", "acquired_at": "2024-01-02T00:00:00Z",
           "assessment": assess_support({"status": "failed"}, chosen)}
    result = rank_candidates([good, bad], chosen)
    assert result == {"status": "incomplete", "selected_scene_id": None,
                      "ranked_scene_ids": ["good"], "evaluated_count": 2,
                      "rejected_count": 0, "unavailable_count": 1}
    assert rank_candidates([], chosen)["status"] == "no_eligible_scene"


def test_duplicate_or_ambiguous_candidate_rows_are_rejected():
    chosen = policy()
    row = {"scene_id": "s", "acquired_at": "2024-01-01T00:00:00Z",
           "assessment": assess_support(receipt(), chosen)}
    with pytest.raises(ValueError):
        rank_candidates([row, deepcopy(row)], chosen)
    for bad in ("2024-01-01", "garbage", ""):
        with pytest.raises(ValueError):
            rank_candidates([row | {"acquired_at": bad}], chosen)
    with pytest.raises(ValueError):
        rank_candidates([row | {"scene_id": " s "}], chosen)
    for change in ({"valid_fraction": True}, {"valid_fraction": float("nan")},
                   {"valid_fraction": 0.8}, {"valid_area_m2": 120},
                   {"status": "rejected"}):
        with pytest.raises(ValueError):
            rank_candidates([row | {"assessment": row["assessment"] | change}], chosen)

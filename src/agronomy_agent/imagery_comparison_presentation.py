"""Shared wording and limits for the map service and the answer renderer."""

COMPARISON_QUESTION = "What changed between these satellite images, and do dated field observations give me a place to scout?"


def grower_message(result: dict) -> str:
    dates = ""
    if "before" in result and "after" in result:
        dates = f"{result['before']['acquired_at'][:10]} to {result['after']['acquired_at'][:10]} (UTC). "
    if result["status"] == "descriptive_only":
        statements = []
        for name, item in result["indices"].items():
            if item["status"] == "observed_on_overlap":
                fraction = item["field_fraction"]
                if fraction < .001:
                    coverage = "less than 0.1%"
                elif fraction >= 1 - 1e-7:
                    coverage = "100%"
                elif fraction > .999:
                    coverage = "more than 99.9%"
                else:
                    coverage = f"{fraction:.1%}"
                delta = item["mean_delta"]
                change = f"changed by {delta:+.3g}" if delta else "showed no difference"
                hectares = item["area_m2"] / 10_000
                area = "less than 0.001 ha" if hectares < .001 else f"{hectares:.3g} ha"
                statements.append(f"{name} {change} on shared usable pixels covering {coverage} of the field ({area}).")
            else:
                statements.append(f"{name} has no pixels usable on both dates.")
        summary = " ".join(statements)
    else:
        reason = {
            "not_configured": "The local imagery worker is unavailable.",
            "busy": "The imagery worker is busy. Try again shortly.",
            "unavailable_source": "One or both saved analyses could not be verified.",
            "polygon_required": "Select two analyses on the same saved field boundary.",
            "different_grid": "The two images use grids that do not line up.",
            "no_grid_overlap": "The two image grids share no cells.",
            "no_field_overlap": "The overlapping image cells fall outside this saved field.",
            "no_common_valid_pixels": "The images have no pixels usable for the same index on both dates.",
            "same_acquisition_date": "Choose images from two different dates.",
            "different_processing": "The images use different processing recipes.",
            "different_or_unknown_baseline": "The images have different or unconfirmed processing baselines.",
        }.get(result["status"], "The inputs could not be verified for comparison on this field.")
        summary = f"No comparison shown. {reason}"
    return dates + summary + " These images give no verified location to scout."


def comparison_answer(result: dict) -> str:
    import re

    overview = grower_message(result)
    if observation := result.get("scouting_observation"):
        location = re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", observation["location"])
        date = observation["date"] + (" (UTC)" if observation.get("date_basis") == "utc" else "")
        return (
            f"{overview}\n\nYour dated field observation on {date} recorded **{location}**. "
            "Use that recorded location for a ground check."
        )
    return f"{overview} Add a dated field observation with a location to guide a ground check."

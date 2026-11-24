from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
import check_public_docs


ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


def triggers(config: dict) -> dict:
    # PyYAML's YAML 1.1 resolver treats the GitHub key `on` as True.
    return config.get("on", config.get(True))


def gate_matches(condition: str, event: str, ref: str, flag: bool | None) -> bool:
    """Evaluate only the three-comparison gates used by these workflows."""
    comparisons = condition.split(" && ")
    assert len(comparisons) == 3
    results = []
    for comparison in comparisons:
        match = re.fullmatch(
            r"(github\.event_name|github\.ref|inputs\.\w+) (==|!=) ('[^']*'|true)",
            comparison,
        )
        assert match, comparison
        key, operator, literal = match.groups()
        expected = True if literal == "true" else literal[1:-1]
        actual = event if key == "github.event_name" else ref if key == "github.ref" else flag
        results.append(actual == expected if operator == "==" else actual != expected)
    return all(results)


def authority_steps(config: dict, flag: str) -> list[dict]:
    steps = [step for job in config["jobs"].values() for step in job["steps"]]
    return [
        step for step in steps
        if f"inputs.{flag}" in step.get("if", "") and "github.ref ==" in step["if"]
    ]


def test_manual_publication_has_false_typed_default_and_no_extra_triggers():
    config = workflow("docs.yml")
    events = triggers(config)
    assert set(events) == {"pull_request", "push", "workflow_dispatch"}
    assert events["workflow_dispatch"]["inputs"]["publish_docs"]["type"] == "boolean"
    assert events["workflow_dispatch"]["inputs"]["publish_docs"]["default"] is False
    assert len(authority_steps(config, "publish_docs")) == 2
    assert "${{ inputs.publish_docs == true }}" in config["concurrency"]["group"]
    assert config["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(
    "event,ref,flag_value,expected",
    [
        ("pull_request", "refs/pull/10/merge", True, False),
        ("pull_request", "refs/heads/main", True, False),
        ("pull_request_target", "refs/heads/main", True, False),
        ("push", "refs/heads/main", True, False),
        ("workflow_run", "refs/heads/main", True, False),
        ("workflow_dispatch", "refs/heads/main", None, False),
        ("workflow_dispatch", "refs/heads/main", False, False),
        ("workflow_dispatch", "refs/heads/main", True, True),
        ("workflow_dispatch", "refs/heads/topic", True, False),
        ("workflow_dispatch", "refs/tags/main", True, False),
    ],
)
def test_publication_steps_require_dispatch_opt_in_and_main(event, ref, flag_value, expected):
    config = workflow("docs.yml")
    conditions = [step["if"] for step in authority_steps(config, "publish_docs")]
    conditions.append(config["jobs"]["deploy"]["if"])
    expected_gate = ("github.event_name == 'workflow_dispatch' && inputs.publish_docs == true"
                     " && github.ref == 'refs/heads/main'")
    assert conditions and all(condition == expected_gate for condition in conditions)
    assert all(gate_matches(condition, event, ref, flag_value) is expected
               for condition in conditions)


def test_wrong_branch_explicit_request_fails_before_setup():
    config = workflow("docs.yml")
    steps = next(iter(config["jobs"].values()))["steps"]
    rejection = steps[1]
    assert "exit 1" in rejection["run"]
    assert gate_matches(rejection["if"], "workflow_dispatch", "refs/heads/topic", True)
    assert not gate_matches(rejection["if"], "workflow_dispatch", "refs/heads/main", True)
    assert not gate_matches(rejection["if"], "pull_request", "refs/pull/10/merge", True)


def test_ordinary_ci_and_source_contracts_are_still_automatic():
    for filename, jobs in [("ci.yml", {"python", "frontend"}), ("docs.yml", {"build"}),
                           ("release-evaluation.yml", {"deterministic-foundation"})]:
        config = workflow(filename)
        events = triggers(config)
        assert "pull_request" in events
        assert events["push"]["branches"] == ["main"]
        assert all("if" not in config["jobs"][job] for job in jobs)


def test_pages_publication_entrypoints_are_gated():
    docs = workflow("docs.yml")
    guarded = authority_steps(docs, "publish_docs")
    for step in docs["jobs"]["build"]["steps"]:
        if any(action in step.get("uses", "") for action in
               ["actions/configure-pages@", "actions/upload-pages-artifact@"]):
            assert step in guarded
    deploy = docs["jobs"]["deploy"]
    assert deploy["needs"] == "build"
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}


@pytest.mark.parametrize(
    "original,replacement,error",
    [
        ("default: false", "default: true", "manual_publication_must_default_off"),
        ("type: boolean", "type: string", "manual_publication_must_default_off"),
        ("inputs.publish_docs == true && ", "", "deploy_not_explicit_main_dispatch_only"),
        ("github.ref == 'refs/heads/main'", "github.ref != 'refs/heads/main'",
         "deploy_not_explicit_main_dispatch_only"),
        ("needs: build", "needs: []", "deploy_must_require_audited_build"),
        ("github.event_name == 'workflow_dispatch' && inputs.publish_docs == true",
         "github.event_name == 'push'", "deploy_not_explicit_main_dispatch_only"),
    ],
)
def test_publication_auditor_rejects_automatic_or_unbound_publication(tmp_path, original,
                                                                   replacement, error):
    text = (ROOT / ".github/workflows/docs.yml").read_text()
    assert original in text
    candidate = tmp_path / "docs.yml"
    candidate.write_text(text.replace(original, replacement))
    assert f"pages_workflow:{error}" in check_public_docs.audit_pages_workflow(candidate)

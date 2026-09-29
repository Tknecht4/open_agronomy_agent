# Contributing to Open Agronomy Agent

Thanks for helping improve the local field workspace and research foundation. Start with the [README](README.md), [architecture](ARCHITECTURE.md), and [developer guide](docs/public/developer/index.md). The exercised source-checkout target is an Apple Silicon Mac; other environments are welcome for investigation but are not qualified by that setup. Maintainer response times are best effort, with no support or review SLA.

## Choose a route

- **Reproducible bug:** [open a bug report](https://github.com/Tknecht4/open_agronomy_agent/issues/new/choose) with a minimal, sanitized reproduction and the observed result.
- **Question, idea, or help with setup:** use [GitHub Discussions](https://github.com/Tknecht4/open_agronomy_agent/discussions). A scoped change can become an issue or pull request after its behavior and evidence boundary are clear.
- **Potential vulnerability:** follow [SECURITY.md](SECURITY.md) and report it privately. Do not include exploit details in a public issue or discussion.
- **Community behavior:** follow the [Code of Conduct](CODE_OF_CONDUCT.md).

Public reports, logs, tests, screenshots, and PRs must not contain farmer or field records, credentials, tokens, pairing URLs, private trace or database content, precise coordinates, or other identifying locations. Use synthetic or redacted examples. Remove secrets from attachments and Git history before publishing; merely deleting a line in a later commit does not remove its earlier copy. If a reproduction needs private data, describe its shape and the observed behavior without uploading it.

## Prepare a change

1. Check open issues and Discussions, then keep the PR focused on one behavior. For a broad design or a new evidence source, discuss scope and authority before implementation.
2. Work from a branch and add or update the narrow tests for the behavior. Read the nearest subsystem README and the active config. Do not alter frozen benchmark artifacts or place evaluation cases in runtime retrieval or training.
3. Explain the before/after behavior, exact commands run, failures or skips, and remaining limits in the PR template. Preserve negative results and contradictory evidence. State what is observed versus inferred.
4. For source, graph, field-data, model, or agronomic changes, include origin, rights, jurisdiction, dates, hashes or stable identities, transformations, intended runtime role, and applicability limits. New material needs the relevant admission and evaluation gates; a green software test is not agronomic validation or permission to activate a candidate.

The [testing guide](docs/public/developer/testing.md) explains focused checks and repository-wide gates. Before a repository-wide claim, run the Python suite, public-documentation checker, strict MkDocs build, and frontend typecheck/tests/build listed in [AGENTS.md](AGENTS.md), plus corpus, retrieval, release, or model gates when their controlling inputs change. Report any unavailable gate honestly; do not label a subset a full pass.

Project-authored contributions are offered under [Apache-2.0](LICENSE). Third-party code, data, model weights, and evaluation material retain their own terms; check [third-party notices](THIRD_PARTY_NOTICES.md) and document any additional rights before adding them. Do not paste material from another project unless its license and attribution requirements are understood and satisfied.

## Review and merge

Use a pull request so CI and the change record are visible. `@Tknecht4` is the repository maintainer and review owner. Contributions from others require maintainer review before merge. Because this is currently a one-maintainer project, the maintainer may merge their own PR after required CI and applicable domain gates without an impossible self-approval requirement. Passing CI alone does not promote a source, model, benchmark claim, or release.

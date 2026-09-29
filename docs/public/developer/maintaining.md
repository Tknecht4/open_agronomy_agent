# Maintaining the project

The maintainer owns scope, review, release decisions, and public claims. A new
issue is a request for assessment, not a delivery commitment. See
[contributing and help](contributing.md) for the public intake routes.

## Triage and review

Review new reports when capacity allows. First check for exposed private data
or a security report, then duplicates, a reproducible example, affected version,
and supported environment. Request synthetic inputs when reproduction would
otherwise disclose farm records. Close out-of-scope requests with a reason;
keep potentially useful, uncommitted ideas in Discussions.

Prioritize security and data-loss defects, then broken supported workflows,
then usability and optional extensions. Agree on scope before substantial
outside work. Ask for a focused PR, reproducible checks, and an explicit account
of failures or unavailable tests. Source/authority, model, and agronomic claims
retain their separate admission and evaluation gates.

The [repository policy](https://github.com/Tknecht4/open_agronomy_agent/blob/main/configs/github_repository_policy.json)
records the intended GitHub settings; it is not proof of live enforcement.
The default branch requires a PR, current passing `python`, `frontend`, and
documentation `build` checks from GitHub Actions, and resolved conversations.
Administrators follow the same checks; force pushes and branch deletion are
blocked. Documentation runs on every PR so its required check cannot disappear
because of path filtering. Desktop qualification runs when its inputs change
and must be reviewed when triggered.

While there is one maintainer, GitHub's mandatory approval count is zero;
outside PRs require maintainer review by policy. This avoids an impossible
self-approval requirement. Add required independent approval when another
trusted maintainer can provide it. `CODEOWNERS` routes review requests; it does
not confer write access or replace review. Keep fork workflows read-only and
release credentials out of PR jobs.

## Dependency maintenance

Dependabot proposes weekly Python, frontend, and GitHub Actions updates with
bounded open-PR counts. Security updates are also enabled. These proposals
receive the normal review and CI gates; there is no automatic merge.

Backend and desktop CI audit the installed third-party dependency inventory
using the pinned scanner in `requirements-security.txt`. The scanner runs in
its own environment. Only the editable project itself is excluded: local code
is assessed by source review/tests, not by a package advisory lookup. A missing
or empty inventory, collection error, or reported advisory fails the job. The
frontend retains its high-severity npm audit. An advisory lookup requires
network access and does not prove the absence of undisclosed vulnerabilities.

Python declarations are still ranges and the Mac constraints remain a specific
candidate environment, not portable hash locks. Record newly resolved versions
and rerun the affected checks when updating them. Do not suppress an advisory
just to obtain a green build. If an exception is unavoidable, it requires a
documented scope, evidence, expiry, and maintainer decision.

## Distribution and recovery

Use the [split source distribution](source-distribution.md) when a contributor
needs code separately from data/evidence. Both packs are required to reconstruct
the runnable public tree. This does not reduce Git history or qualify a smaller
desktop installer. Keep immutable, hash-bound replacements before removing any
historical payload from the repository.

Before a desktop release, complete the [release checks](release-readiness.md)
and the [Mac candidate qualification](https://github.com/Tknecht4/open_agronomy_agent/blob/main/macos_app/README.md).
The published release record must identify source, dependency inventory,
archive checksums, compressed and installed sizes, required model bytes,
supported OS/hardware, and known limitations.

Upgrade qualification must exercise a representative existing workspace:
stop the owned backend, create and verify a backup of the database and relevant
private files, upgrade, check records and a real answer, and rehearse recovery
to the prior version. Existing backup/restore primitives do not establish this
installed-app workflow. Developer ID signing, notarization, downloaded-app
launch, minimum-hardware testing, and update/rollback remain separate gates;
do not publish the ad hoc candidate as if those gates had passed.

As adoption grows, prefer small compatibility-preserving changes: documented
schemas and API changes, bounded field-history queries, and extraction of
coherent services from central modules. Keep model/corpus behavior fixed when
measuring implementation performance. Integrations such as a farmOS importer
need their own reviewed identity, units, provenance, privacy, and mapping
contracts before implementation.

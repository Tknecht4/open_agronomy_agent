# Governance

## Privacy and egress

Local field records, geometry, attachments, questions, answers, and traces may be sensitive. Local development stores them under ignored runtime paths. A public adapter or semantic judge may receive only the explicitly authorized, minimized payload for its declared task. Offline and field-LAN modes block public adapter calls before execution.

Never put credentials, pairing URLs, private absolute paths, farmer records, raw benchmark answers, model caches, or local trace databases in Git, documentation, screenshots, or Pages artifacts.

## Source and licensing

Project-authored code/documentation is PolyForm Noncommercial 1.0.0 except material with its own explicit licence or a preserved earlier grant. This is source-available software for permitted non-commercial and institutional purposes, including research and evaluation; see [Licensing and permitted use](licensing.md). Earlier Apache grants remain valid. Third-party sources retain their terms, including any non-commercial, attribution, and share-alike obligations; PolyForm does not replace them or admit previously excluded data. Every admitted source should preserve publisher, URL, date, jurisdiction, rights, exact-byte/content hash, derivation, runtime role, and limitations. Extraction is not permission; inclusion is not authority.

## Evidence authority

- Field records and measurements are observations with time/method/source—not unquestioned truth.
- Retrieved guidance supports only its applicable scope and currency.
- Graph and map relationships are context.
- Current regulated actions require current applicable authority.
- Model generation and automated judging are interpretations/advisory signals.
- Human approval is explicit and cannot be inferred from a passing check.

## Contribution boundary

Contributions that change knowledge, capabilities, graphs, routing, validation, benchmark design, or public claims must include provenance, typed contracts, negative/failure tests, and explicit limits. Keep external evaluation separate from tuning. Retain contradictions and failed results instead of rewriting history to pass a gate.

Use the [contribution guide](developer/contributing.md) for intake, review, safe public examples, and verification. The repository also publishes [support](https://github.com/Tknecht4/open_agronomy_agent/blob/main/SUPPORT.md), [security](https://github.com/Tknecht4/open_agronomy_agent/blob/main/SECURITY.md), and [conduct](https://github.com/Tknecht4/open_agronomy_agent/blob/main/CODE_OF_CONDUCT.md) policies. Outside contributions receive maintainer review. The sole maintainer may merge their own PR after required CI and applicable domain gates; a required self-approval would block that workflow.

## Documentation publication

The GitHub Pages workflow builds only `docs/public` with strict links and runs a publication-scope audit. Pull requests and main pushes validate documentation without publishing it. Publication requires a separate manual Documentation workflow run on `main` with `publish_docs` selected; it uses that run's audited artifact through the `github-pages` environment. A manual run with the default unchecked input only validates documentation.

The Mac workflow retains dependency audits and desktop source-contract checks on matching pull requests. Building the app, installing the pinned model, executing model smoke checks and archiving the candidate require a separate manual run on `main` with `run_native_candidate` selected. The input defaults to false; a source-only check is not native or model qualification.

The public repository manifest explicitly includes the site/workflow/checker and forbids `outputs/`, models, adapters, private knowledge, and raw data except narrow lineage records. Review the rendered artifact before enabling Pages.

## Project change record

Use Git history and dated review/release receipts as the change record. A future curated changelog may summarize releases, but it must link to exact implementation and evidence identities and must not turn candidate or historical results into current validation.

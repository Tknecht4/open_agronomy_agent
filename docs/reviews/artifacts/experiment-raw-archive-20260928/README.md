# Historical raw experiment archive locator

This catalog records the exact 22 raw experiment and answer-rich files
retained in a verified private archive. The catalog records the verified
archive and exact 22-file restore proof supporting the reviewed migration out
of the current public tree. Nothing in this directory is a runtime retrieval or training source.

The [catalog](catalog.json) binds each former path to its byte count, SHA-256,
source commit and archive identity. The [public run-manifest projection](run-manifests-public.json)
retains identity and compact status metadata without the original prompts,
answers, questions or per-turn text. It cannot reconstruct the original
`run-manifests.json`, ledgers, grading packets or exact replay inputs. The current
public tree alone cannot replay all raw grades or answer-level diagnostics.
Historical Git commits and existing clones can still expose the original bytes;
this migration does not rewrite Git history.

After private archive verification, an authorized operator may restore the
original files into a new directory outside the checkout and run
`verify_private_restore.py` against this catalog with an independently pinned
catalog SHA-256. The verifier checks all 22 restored files before any raw file
is opened for analysis. The private retention bundle must keep the unchanged
original files, the migration plan and helper, and the archive manifest. The
retained helper requires an explicit `--repo-root` when run from its private
location. A public catalog is a locator, not access to the private data.

The historical scripts `portable-residual-20260928/remote_run.py`,
`verifier_probe.py` and `verifier-trigger-probe.py` refer to the original
ledgers. They are archival records; do not rerun them against the current tree
or substitute new ledgers. Use an independently reviewed reproduction wrapper
with a verified private restore if that experiment is repeated.

# Repair evidence

These are public synthetic and source-bound engineering diagnostics, not
agronomic performance or corpus-activation evidence. Initial rejected evidence
is retained beside the corrected result. The parent checkpoint report explains
the two GPU source identities and final deterministic replay.

Local reproduction scripts were authored under
`outputs/residual-repair-20260928/`. To reproduce, create that directory and copy
the desired script there unchanged, then run it from the repository root with
`PYTHONPATH=src .venv/bin/python outputs/residual-repair-20260928/SCRIPT.py`.
The contrast scripts read immutable fixtures from the preceding investigation;
the baseline uses `git show 8380b8b`. The independent probe uses the checked-in
candidate manifest and writes a new candidate-addressed output.

Remote driver/setup paths are Colab-specific execution records. The source
capsule manifests bind every transferred file. Both exact transferred source
archives are retained as `capsule-initial.zip` and `capsule-second.zip`; their
contents include only public source, synthetic inputs and drivers. Model weights
are not bundled. The raw
result ZIP contains only the two synthetic runs and their public model/runtime
receipts. Usage receipts omit absolute account balances.

The exact source capsules and raw result ZIP are indexed by the
[raw archive catalog](../experiment-raw-archive-20260928/catalog.json).
They remain historical private-retention candidates; this compact public
record alone cannot replay the runs.

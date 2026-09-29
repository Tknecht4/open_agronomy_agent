# Split source distribution

The [public repository manifest](https://github.com/Tknecht4/open_agronomy_agent/blob/main/configs/public_repository_manifest.json)
selects the curated shareable tree. The ordinary public repository builder
still produces the full tree, regenerates its runtime manifest, and writes
`PUBLIC_RELEASE_RECEIPT.json`. The split distribution packages that same tree
into two archives:

| Archive | Contents | Use |
|---|---|---|
| `source.tar.gz` | Code, configuration, ordinary documentation, public release receipt | Smaller developer download for inspection and editing |
| `evidence.tar.gz` | Every selected `data/` file and selected `docs/reviews/artifacts/` file | Checked-in corpus, evaluation material, manifests, lineage, and retained evidence |

The source archive alone is incomplete. In particular, the active hash-bound
corpus is in the evidence archive; do not run the app or claim corpus validity
from the source archive alone. Both archives reconstruct the exact curated
public tree, not the complete Git checkout. This packaging does not change
runtime admission, evaluation separation, installed Mac app size, or Git history.

First inspect the planned input split without creating archives:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/build_source_distribution.py plan
```

After checking disk space, build into a **new** directory:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/build_source_distribution.py build \
  --destination /tmp/open-agronomy-distribution-new
```

The command prints `plan_sha256`. Record that digest through a trusted
channel alongside the archives. The plan lists the hash and size of each
archive and every reconstructed file. To verify and reconstruct into a new
directory, supply the recorded digest explicitly:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/build_source_distribution.py reconstruct \
  --distribution /tmp/open-agronomy-distribution-new \
  --destination /tmp/open-agronomy-reconstructed-new \
  --expected-plan-sha256 THE_RECORDED_64_CHARACTER_DIGEST
```

The verifier checks the independently supplied plan digest, exact distribution
file set, archive hashes, expected members, member types and sizes, individual
file hashes, and the original public release receipt before placing the new
tree at the destination. It rejects existing destinations, links, paths that
escape the tree, duplicates, missing or extra members, and distributions over
fixed file-count and uncompressed-size limits. It streams regular files into a
temporary tree rather than using general tar extraction. It also checks the
complete gzip stream and tar end padding, including gzip integrity trailers,
before publishing the tree with an atomic no-replace operation. If the
platform cannot provide that operation, reconstruction fails closed. An
untrusted plan digest supplied from the same download has no independent authentication
value; obtain it through a separate trusted release record.

To perform all those checks without writing a reconstructed tree, use
`verify` with `--distribution` and `--expected-plan-sha256` instead of
`reconstruct`. This is useful when disk space cannot hold a second copy of
the corpus.

The build stages the curated tree temporarily. On APFS, the public builder
uses copy-on-write cloning for this stage; the final compressed archives still
need their actual disk space. The `plan` command reports input bytes, not a
predicted compressed size. Set `SOURCE_DATE_EPOCH` for a chosen receipt time;
otherwise the split builder uses epoch zero to make its generated receipt and
archives reproducible for identical input bytes.

The full curated input tree has a 1.1 GB uncompressed size budget in the public
manifest, in addition to per-file and per-prefix limits. Increasing that budget
requires an explicit reviewed change; compression is not a substitute for it.

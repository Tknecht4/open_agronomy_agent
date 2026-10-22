# Licensing and permitted use

## Project software

From the licensing change dated **2026-10-22**, project-authored software and
documentation are offered under the **PolyForm Noncommercial License 1.0.0**,
except material with its own explicit licence or a preserved earlier grant.
The SPDX identifier is `PolyForm-Noncommercial-1.0.0`. The complete terms are
in the [repository LICENSE](https://github.com/Tknecht4/open_agronomy_agent/blob/main/LICENSE)
and the [official licence text](https://polyformproject.org/licenses/noncommercial/1.0.0).

The project-specific copyright and required attribution are in
[NOTICE](https://github.com/Tknecht4/open_agronomy_agent/blob/main/NOTICE).
The example company in the unmodified standard licence is illustrative;
it is not the project licensor or an unfinished attribution field.

This is source-available software for non-commercial use, including research
and evaluation. PolyForm also permits other non-commercial purposes and use
by the charitable, educational, public research, public safety or health,
environmental protection, and government institutions listed in the licence,
regardless of funding source or obligations. It is therefore broader than a
research-only licence. These descriptions summarize the standard licence;
they do not add restrictions or exceptions to it.

Selling the application, providing paid consulting or hosted services, and
using it in commercial farm operations are not permitted merely because the
source is visible or the application is free to download. Any use must fall
within a permitted purpose in the licence or have separate permission from
the relevant rights holders. Permission for project software alone cannot
clear third-party material.

Recipients may copy, modify, and redistribute the software as permitted by
PolyForm and must preserve its terms and required notices. Contributions
are offered under the same project licence; contributors must have authority
to submit their work. See [Contributing](developer/contributing.md).

## Earlier Apache releases

The change is integrated from main revision
`7f8974cbb3cbaf0372fa678348e9140e35f25a9f`. Earlier project versions were
offered under Apache-2.0. Earlier versions made available under
Apache-2.0 retain their existing permissions, including commercial use, for
recipients complying with those terms. This change does not revoke those
grants or restrict independently obtained Apache-licensed copies.

The earlier text is retained at
[LICENSES/Apache-2.0.txt](https://github.com/Tknecht4/open_agronomy_agent/blob/main/LICENSES/Apache-2.0.txt).
It is a notice for earlier and separately licensed material, not an alternative
licence for new PolyForm-licensed contributions. Existing checksum-bound
corpus releases, graph manifests, research receipts, and evaluation artifacts
keep their recorded licences and identities. In particular, the curated seed
graph and frozen production-foundations v1/v2 text retain their Apache grant.

Historical source registries also retain their original distribution-profile
descriptions, including earlier references to an open-source or potentially
commercial bundle. Hash-bound retention receipts depend on those exact bytes.
Those descriptions record the original source-rights review; they do not grant
commercial permission for the current project software or override `LICENSE`,
`NOTICE`, or a source's own terms.

## Data, models, and dependencies

Third-party data, publications, evaluation material, models, dependencies,
map services, and private uploads retain their own terms. Their attribution,
non-commercial, share-alike, privacy, access, and redistribution conditions
apply independently. They are not relicensed under PolyForm.

For example, UBC-derived research material remains **CC BY-NC-SA 4.0** where
identified: its non-commercial restriction and applicable attribution and
share-alike obligations continue to apply. PolyForm's institutional permissions
do not override a source's narrower conditions. Unknown rights, local research
access, or public availability do not establish permission to redistribute.
Changing the software licence does not admit an excluded source to a public
package, runtime retrieval, or training.

Model configuration `license` fields describe the upstream weights, not the
project software. Existing Apache-2.0 model declarations therefore remain.
Psycopg retains LGPL-3.0 terms; the optional document-processing tooling uses
PyMuPDF under AGPL/commercial terms. Distribution of dependencies or combined
works must satisfy those terms; the project licence is not a dependency
compliance clearance.

Consult the
[third-party notices](https://github.com/Tknecht4/open_agronomy_agent/blob/main/THIRD_PARTY_NOTICES.md)
and each source's manifest and original licence before use or redistribution.

Production frontend builds include `LICENSE.txt`, `NOTICE.txt`, and
`THIRD_PARTY_LICENSES.txt`. The latter preserves copyright and full licence
texts for the installed, lockfile-verified production dependencies and Vite's
bundled helpers. Missing required packages, version mismatches, or absent
licence texts fail the build. Container and Mac builds copy these files with
the generated frontend. The native builder additionally inventories the actual PyInstaller inputs,
checks every bundled Mach-O owner, preserves complete upstream notices, and
ships the required package and native-library source/build inputs in the app
`Contents/Resources/legal/`. Optional OpenCV/GPL codecs, AGPL document tools,
and Postgres drivers are excluded from the SQLite desktop profile. GEOS,
SpatiaLite and libquadmath retain LGPL rights, including modification and
replacement. Missing source, notices, ownership or a reviewed native version
blocks the app build. See the [native distribution procedure](operations/native-licensing.md).

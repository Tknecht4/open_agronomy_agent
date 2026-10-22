# Native distribution licensing

Every Mac app build runs `scripts/native_app_licenses.py` against the same
PyInstaller Analysis that produced its backend. The gate inventories collected
Python packages and native inputs, fails unknown owners and prohibited optional
components, retains full wheel and source notices, and supplies exact source
archives and build inputs in `Contents/Resources/legal/`. This includes
Python, PyInstaller, MLX, the geospatial libraries and compiler runtimes;
third-party licences remain independent of PolyForm Noncommercial.

`macos_app/native_components.json` is the reviewed native version/source
registry. Update it deliberately when a constrained dependency changes.
Native components include libraries embedded inside wheels, including the
GEOS/SpatiaLite code statically linked into a replaceable GDAL dylib. Package
metadata alone is insufficient to determine their terms. Upstream source
archives and their patches/build recipes accompany each app; LGPL modification,
reverse-engineering for debugging, and library replacement remain permitted.
The complete procedure is bundled in `legal/README.md` and maintained in
`macos_app/THIRD_PARTY_RUNTIME.md`.

Build on a clean macOS arm64 builder using the [native setup](native-setup.md)
and `macos_app/README.md`. Build-time downloads acquire exact source archives;
the inventory retains their identities, URLs and hashes. The About page links
the complete frontend dependency notices; the native source archives can be
opened with Finder **Show Package Contents**. Missing compliance inputs fail
before an app is promoted to the output path.

The Mac workflow’s explicit `verify_native_licenses` input builds the actual
distribution on the selected branch, verifies its licensing payload and records
every signed Mach-O hash in the build receipt. Ordinary PRs run source checks.
The model, first-run and offline-answer smoke checks remain separately
authorized main qualification. Ad hoc signing is local signing; Developer ID,
notarization and release publication keep their existing separate gates.

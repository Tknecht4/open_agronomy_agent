# Third-party software in the Mac app

The project software uses PolyForm Noncommercial 1.0.0. Each component in
`inventory.json` keeps its original licence. The project restriction does not
apply to independently licensed third-party libraries or their source archives.
The inventory identifies the actual PyInstaller inputs and complete upstream
copyright, licence and notice files in `notices/`. Required package source archives
and native-library source/build inputs are in `sources/` inside the app at
`Contents/Resources/legal/`. These are supplied with every app, not a promise
to obtain them later. The browser's About page provides the notices; Finder's
**Show Package Contents** exposes the sources without a developer installation.

GEOS, SpatiaLite, and libquadmath retain their LGPL rights, including commercial
use of those libraries and modification. You may reverse engineer the combined
work to debug modifications to these libraries. Nothing in the project licence
restricts those LGPL rights. Certifi, tqdm and other MPL-covered files retain
their MPL rights; their exact source archives accompany this distribution.
Python is built by Homebrew with its configuration, installation-layout and
sysconfig changes; the matching build recipe and patch accompany its source.
PyInstaller freezes and relocates that build. PyInstaller's standard
bootloader exception permits the generated application to use the project
licence; its own complete original terms are retained separately.

This software is based in part on the work of the Independent JPEG Group.

## Rebuild and replace LGPL libraries

Use the complete corresponding library sources and upstream build recipes
listed in the inventory. For Shapely's GEOS use the matching GEOS archive and
Shapely's `ci/install_geos.sh`. For GDAL use the matching pyogrio release's
`ci/vcpkg.json`, `ci/custom-triplets/arm64-osx-dynamic-release.cmake` and pinned
vcpkg tree; the latter includes every port's patches. Build GDAL with the same
features, including GEOS and SpatiaLite, using that recipe. For libquadmath use
the matching GCC sources and compiler build recipe. Preserve the binary ABI,
arm64 architecture, minimum system version, library names and install names.

Quit Open Agronomy, copy the app to a writable location, and use **Show Package
Contents**. The shared libraries are under
`Contents/Helpers/OpenAgronomyBackend.app/Contents/Frameworks/`, including
`shapely/__dot__dylibs/`, `pyogrio/__dot__dylibs/` and
`scipy/__dot__dylibs/` (PyInstaller replaces dots in framework directory names). Replace the matching
dylib with the rebuilt ABI-compatible version; replace the whole `libgdal`
shared library when changing its statically linked LGPL components. Use
`otool -L` and `install_name_tool` to retain the original relative dependency
paths. Ad hoc sign each replacement with `codesign --force --sign -`, then
sign the inner and outer apps, inside out. Verify with
`codesign --verify --deep --strict` and rerun the packaged backend's health and
geometry checks. This is a user-modified copy; the upstream distribution's
signature and hashes no longer describe it. The app does not prohibit running
such a modified library and supplies no installation key requirement.

The Apple system frameworks and libraries at `/System/Library/` and `/usr/lib/`
are supplied by macOS and are not copied into the application. Model weights
are downloaded explicitly at their pinned revision; they keep their upstream
terms and are separate from the application's own licence. Dataset notices and
source-specific restrictions remain in `runtime/THIRD_PARTY_NOTICES.md` and the
bundled source manifests.

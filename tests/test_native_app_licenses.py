from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest

from scripts import native_app_licenses as licenses


def test_analysis_is_data_and_inventories_nested_collected_inputs(tmp_path: Path) -> None:
    toc = tmp_path / 'Analysis-00.toc'
    toc.write_text(repr(([('pkg', '/external/pkg.py', 'PYMODULE')], [('pkg/lib.dylib', '/external/lib.dylib', 'BINARY')])))
    assert licenses.analysis_inputs(toc) == [('pkg', '/external/pkg.py', 'PYMODULE'), ('pkg/lib.dylib', '/external/lib.dylib', 'BINARY')]
    toc.write_text("__import__('os').system('false')")
    with pytest.raises(ValueError):
        licenses.analysis_inputs(toc)


def test_archive_notices_never_extract_paths(tmp_path: Path) -> None:
    import io
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as t:
        item = tarfile.TarInfo('../../LICENSE')
        item.size = 17
        t.addfile(item, io.BytesIO(b'Copyright Example'))
        symlink = tarfile.TarInfo('link-LICENSE')
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = '/etc/passwd'
        t.addfile(symlink)
    assert licenses._archive_notices(archive) == {'../../LICENSE': b'Copyright Example'}
    assert not (tmp_path / 'LICENSE').exists()


def test_actual_bundle_rejects_unaccounted_native_and_prohibited_codecs(tmp_path: Path) -> None:
    app = tmp_path / 'App.app'
    legal = app / 'Contents/Resources/legal'
    legal.mkdir(parents=True)
    source = legal / 'source.tar'
    source.write_bytes(b'exact corresponding source')
    notice = legal / 'LICENSE'
    notice.write_bytes(b'original licence and copyright')
    binary = app / 'Contents/MacOS/OpenAgronomy'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
    report = {'packages': [{'source': {'path': source.name, 'sha256': licenses.sha256(source)},
                            'notices': [{'file': notice.name, 'sha256': licenses.sha256(notice)}], 'native_inputs': []}],
              'components': [], 'interpreter_inputs': [], 'bundled_native_inputs': []}
    assert licenses.verify_bundle(app, report)['native_file_count'] == 1
    extra = binary.with_name('unaccounted.dylib')
    extra.write_bytes(binary.read_bytes())
    with pytest.raises(ValueError, match='unaccounted bundled Mach-O'):
        licenses.verify_bundle(app, report)
    extra.unlink()
    extra = binary.with_name('libx264.164.dylib')
    extra.write_bytes(binary.read_bytes())
    with pytest.raises(ValueError, match='prohibited bundled component'):
        licenses.verify_bundle(app, report)
    extra.unlink()
    source.write_bytes(b'altered source')
    with pytest.raises(ValueError, match='source archive changed'):
        licenses.verify_bundle(app, report)


def test_collector_rejects_native_version_before_acquiring_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'checkout'
    (root / 'macos_app').mkdir(parents=True)
    (root / 'macos_app/native_components.json').write_text(json.dumps({'native_packages': [], 'interpreter_binary_patterns': [], 'python_version': __import__('sys').version.split()[0]}))
    external = tmp_path / 'external'
    external.mkdir()
    library = external / 'libtest.dylib'
    library.write_bytes(b'native')
    dist = SimpleNamespace(metadata={'Name': 'test-lib', 'License-Expression': 'MIT'}, version='99.0', files=[Path(library.name)], locate_file=lambda f: external / f)
    toc = tmp_path / 'Analysis-00.toc'
    toc.write_text(repr([('libtest.dylib', str(library), 'BINARY')]))
    monkeypatch.setattr(licenses, '_sdist', lambda *_: pytest.fail('unreviewed native source must not be fetched'))
    with pytest.raises(ValueError, match='unreviewed native wheel: test-lib==99.0'):
        licenses.collect_licenses(root, tmp_path / 'App.app', toc, distributions=[dist])


def test_source_hash_checks_fail_for_corrupt_cached_archive(tmp_path: Path) -> None:
    archive = tmp_path / 'source.tar.gz'
    archive.write_bytes(b'corrupted cache')
    with pytest.raises(ValueError, match='source archive hash mismatch'):
        licenses._download('https://example.invalid/source.tar.gz', archive, '0' * 64)
    expected = hashlib.sha512(archive.read_bytes()).hexdigest()
    assert licenses._download('https://example.invalid/source.tar.gz', archive, expected) == licenses.sha256(archive)


@pytest.mark.parametrize('legacy_metadata', [False, True])
def test_collection_binds_the_exact_bundle_paths_and_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_metadata: bool) -> None:
    root = tmp_path / 'checkout'
    native = root / 'macos_app'
    native.mkdir(parents=True)
    (native / 'native_components.json').write_text(json.dumps({
        'python_version': __import__('sys').version.split()[0], 'native_packages': ['test-lib==1.0'],
        'interpreter_binary_patterns': [r'liblzma\.5\.dylib'],
        'license_metadata_exceptions': {'test-lib==1.0': 'Reviewed historical GPL-compatible wording in BSD/PSF notices'},
        'interpreter_library_sources': {'liblzma.5.dylib': {'formula': 'xz', 'versions': ['5.8.4']}}, 'sources': []}))
    (native / 'rust_dependency_licenses.json').write_text(json.dumps({'package_versions': {}}))
    (native / 'native_source_provenance.json').write_text('{}')
    (native / 'THIRD_PARTY_RUNTIME.md').write_text('Upstream terms remain applicable.')
    external = tmp_path / 'external'
    external.mkdir()
    library = external / 'libtest.dylib'
    library.write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
    (external / 'LICENSE').write_text('Copyright Example\nPermission is hereby granted under the MIT licence.')
    dist = SimpleNamespace(metadata={'Name': 'test-lib', 'License-Expression': 'MIT'}, version='1.0', files=[Path('libtest.dylib'), Path('LICENSE')], locate_file=lambda f: external / f)
    if legacy_metadata:
        dist.metadata = {'Name': 'test-lib', 'License': 'BSD terms\nPSF history: GPL-compatible does not mean licensed under GPL.'}
    framework_version = f'{licenses.sys.version_info.major}.{licenses.sys.version_info.minor}'
    interpreter = tmp_path / f'Python.framework/Versions/{framework_version}'
    plist = interpreter / 'Resources/Info.plist'
    plist.parent.mkdir(parents=True)
    plist.write_text('Python framework metadata')
    monkeypatch.setattr(licenses.sys, 'base_prefix', str(interpreter))
    lzma = tmp_path / 'Cellar/xz/5.8.4/lib/liblzma.5.dylib'
    lzma.parent.mkdir(parents=True)
    lzma.write_bytes(library.read_bytes())
    alias = tmp_path / 'liblzma.5.dylib'
    alias.symlink_to(lzma)
    toc = tmp_path / 'Analysis-00.toc'
    collected = [('libtest.dylib', str(library), 'BINARY'),
                 (f'Python.framework/Versions/{framework_version}/Resources/Info.plist', str(plist), 'DATA'),
                 ('liblzma.5.dylib', str(alias), 'BINARY')]
    toc.write_text(repr(collected))
    toc.with_name('BUNDLE-00.toc').write_text(repr([
        ('Contents/Frameworks/libtest.dylib', str(library), 'BINARY'),
        ('Contents/Frameworks/liblzma.5.dylib', str(alias), 'BINARY')]))
    app = tmp_path / 'App.app'
    shipped = app / 'Contents/Helpers/OpenAgronomyBackend.app/Contents/Frameworks/libtest.dylib'
    shipped.parent.mkdir(parents=True)
    shipped.write_bytes(library.read_bytes())
    (shipped.parent / 'liblzma.5.dylib').write_bytes(lzma.read_bytes())
    index = app / 'Contents/Resources/runtime/frontend/dist/LICENSE_NOTICES.html'
    index.parent.mkdir(parents=True)
    index.write_text('<!-- native-notices -->')
    def download(_url: str, target: Path, _expected: str | None = None) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Copyright OpenSSL\nApache License Version 2.0')
        return licenses.sha256(target)
    monkeypatch.setattr(licenses, '_download', download)
    def sdist(_name: str, _version: str, destination: Path) -> dict:
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / 'test-lib-1.0.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            t.add(external / 'LICENSE', arcname='test-lib-1.0/vendor/LICENSE')
        return {'path': 'sources/' + archive.name, 'sha256': licenses.sha256(archive), 'url': 'https://example.invalid/test-lib-1.0.tar.gz'}
    monkeypatch.setattr(licenses, '_sdist', sdist)
    report = licenses.collect_licenses(root, app, toc, distributions=[dist])
    assert report['interpreter_resources'][0]['sha256'] == licenses.sha256(plist)
    assert report['interpreter_inputs'][0]['source_version'] == '5.8.4'
    assert licenses.verify_bundle(app, report)['native_file_count'] == 2
    duplicate = shipped.parent / 'extra/libtest.dylib'
    duplicate.parent.mkdir()
    duplicate.write_bytes(library.read_bytes())
    with pytest.raises(ValueError, match='unaccounted bundled Mach-O'):
        licenses.verify_bundle(app, report)
    duplicate.unlink()
    shipped.write_bytes(library.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='bundled native input changed'):
        licenses.verify_bundle(app, report)
    toc.write_text(repr(collected + [('unrelated-framework/Info.plist', str(plist), 'DATA')]))
    with pytest.raises(ValueError, match='unowned third-party input: unrelated-framework/Info.plist'):
        licenses.collect_licenses(root, app, toc, distributions=[dist])
    unrelated = external / 'Info.plist'
    unrelated.write_bytes(plist.read_bytes())
    toc.write_text(repr(collected + [('unrelated/Info.plist', str(unrelated), 'DATA')]))
    with pytest.raises(ValueError, match='unowned third-party input: unrelated/Info.plist'):
        licenses.collect_licenses(root, app, toc, distributions=[dist])
    unreviewed = tmp_path / 'Cellar/xz/5.8.5/lib/liblzma.5.dylib'
    unreviewed.parent.mkdir(parents=True)
    unreviewed.write_bytes(lzma.read_bytes())
    toc.write_text(repr([(d, str(unreviewed) if d == 'liblzma.5.dylib' else s, k) for d, s, k in collected]))
    with pytest.raises(ValueError, match='unreviewed interpreter library source'):
        licenses.collect_licenses(root, app, toc, distributions=[dist])
    toc.write_text(repr(collected))
    dist.metadata['License-Expression'] = 'GPL-3.0-only'
    with pytest.raises(ValueError, match='copyleft package requires a separately reviewed combination'):
        licenses.collect_licenses(root, tmp_path / 'Rejected.app', toc, distributions=[dist])

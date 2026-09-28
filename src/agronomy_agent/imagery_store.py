"""Private, integrity-checked sidecar index for derived public imagery chips."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any
import zipfile

SCHEMA_VERSION = 2
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_LIMITS = {"npz": 128 * 1024 * 1024, "png": 8 * 1024 * 1024,
           "receipt": 2 * 1024 * 1024}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ImageryStore:
    def __init__(self, root: str | Path, *, read_only: bool = False):
        self.read_only = read_only
        self._readable = False
        supplied = Path(root).expanduser()
        if supplied.is_symlink():
            raise ValueError("imagery cache root cannot be a symlink")
        self.root = supplied.resolve()
        self.database = self.root / "imagery-v1.sqlite3"  # Retain existing index identity.
        if self.database.is_symlink():
            raise ValueError("imagery index cannot be a symlink")
        if read_only:
            self._readable = self._read_only_preflight()
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError("imagery cache root must be a directory")
        self.root.chmod(0o700)
        if not self.database.exists():
            try:
                fd = os.open(self.database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except FileExistsError:
                if self.database.is_symlink():
                    raise ValueError("imagery index cannot be a symlink")
        self.database.chmod(0o600)
        with self._connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_identity(version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS chips(
                    chip_hash TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                    geometry_hash TEXT NOT NULL, process_hash TEXT NOT NULL,
                    provider_id TEXT NOT NULL, collection TEXT NOT NULL,
                    scene_id TEXT NOT NULL, acquired_at TEXT,
                    availability_at TEXT, asset_ids_json TEXT NOT NULL,
                    source_json TEXT NOT NULL, qa_json TEXT NOT NULL,
                    zonal_json TEXT NOT NULL, model_refs_json TEXT NOT NULL,
                    npz_name TEXT NOT NULL, png_name TEXT NOT NULL,
                    receipt_name TEXT NOT NULL, created_at TEXT NOT NULL,
                    minx REAL NOT NULL, miny REAL NOT NULL,
                    maxx REAL NOT NULL, maxy REAL NOT NULL,
                    npz_sha256 TEXT, png_sha256 TEXT,
                    receipt_sha256 TEXT, receipt_file_sha256 TEXT
                );
                CREATE INDEX IF NOT EXISTS chips_request ON chips(request_hash);
                CREATE VIRTUAL TABLE IF NOT EXISTS chip_bounds USING rtree(
                    rowid, minx, maxx, miny, maxy
                );
                CREATE TRIGGER IF NOT EXISTS chip_bounds_insert AFTER INSERT ON chips BEGIN
                    INSERT INTO chip_bounds(rowid,minx,maxx,miny,maxy)
                    VALUES(new.rowid,new.minx,new.maxx,new.miny,new.maxy);
                END;
                CREATE TRIGGER IF NOT EXISTS chip_bounds_delete AFTER DELETE ON chips BEGIN
                    DELETE FROM chip_bounds WHERE rowid=old.rowid;
                END;
            """)
            versions = [row[0] for row in db.execute("SELECT version FROM schema_identity")]
            if not versions:
                db.execute("INSERT INTO schema_identity VALUES (?)", (SCHEMA_VERSION,))
            elif versions == [1]:
                for name in ("npz_sha256", "png_sha256", "receipt_sha256", "receipt_file_sha256"):
                    db.execute(f"ALTER TABLE chips ADD COLUMN {name} TEXT")
                db.execute("UPDATE schema_identity SET version=?", (SCHEMA_VERSION,))
            elif versions != [SCHEMA_VERSION]:
                raise RuntimeError("unsupported imagery index version")

    def _read_only_preflight(self) -> bool:
        """Reject absent, legacy, and WAL indexes without creating sidecars."""
        if not self.root.is_dir() or not self.database.exists():
            return False
        if not self.database.is_file():
            raise ValueError("imagery index is not a regular file")
        for suffix in ("-wal", "-shm"):
            sidecar = self.root / (self.database.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise RuntimeError("WAL-mode imagery index unavailable for read-only lookup")
        try:
            fd = os.open(self.database, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                header = os.read(fd, 100)
            finally:
                os.close(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("imagery index is not a regular file")
            if info.st_size == 0:
                return False
            if info.st_size < 100 or header[:16] != b"SQLite format 3\x00":
                raise ValueError("invalid imagery index header")
            if header[18:20] != b"\x01\x01":
                raise RuntimeError("WAL-mode or unsupported imagery index unavailable for read-only lookup")
            # mode=ro still obeys rollback-journal locks. WAL is rejected above
            # and in the header; immutable=1 would ignore active WAL commits.
            self._readable = True
            with self._connect() as db:
                versions = [row[0] for row in db.execute("SELECT version FROM schema_identity")]
                if versions == [1]:
                    return False
                if versions != [SCHEMA_VERSION]:
                    raise RuntimeError("unsupported imagery index version")
                columns = {row[1] for row in db.execute("PRAGMA table_info(chips)")}
                if not {
                    "npz_sha256", "png_sha256", "receipt_sha256", "receipt_file_sha256"
                }.issubset(columns):
                    raise RuntimeError("incomplete hashed imagery index schema")
                if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                    raise RuntimeError("unsupported imagery index journal mode")
            return True
        except sqlite3.Error as exc:
            raise RuntimeError("imagery index unreadable") from exc
        except OSError as exc:
            raise RuntimeError("imagery index cannot be opened read-only") from exc
        finally:
            self._readable = False

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self._readable:
                raise RuntimeError("read-only imagery index unavailable")
            db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=15)
            db.execute("PRAGMA query_only=ON")
        else:
            db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def _file_bytes(self, name: str, kind: str) -> bytes:
        if (kind not in _LIMITS or not isinstance(name, str) or
                not re.fullmatch(r"[0-9a-f]{64}\.(?:npz|png|json)", name) or
                not name.endswith({"npz": ".npz", "png": ".png", "receipt": ".json"}[kind])):
            raise ValueError("invalid imagery cache filename")
        path = self.root / name
        if path.is_symlink():
            raise ValueError("imagery cache file cannot be a symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _LIMITS[kind]:
                raise ValueError("invalid imagery cache file")
            if not self.read_only:
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(_LIMITS[kind] + 1)
            if len(data) > _LIMITS[kind]:
                raise ValueError("imagery cache file exceeds limit")
            return data
        finally:
            os.close(fd)

    @staticmethod
    def _names(receipt: dict[str, Any]) -> dict[str, str]:
        chip_hash = receipt["chip_hash"]
        if not isinstance(chip_hash, str) or not _HASH.fullmatch(chip_hash):
            raise ValueError("invalid chip hash")
        names = receipt["cache_files"]
        expected = {"npz": chip_hash + ".npz", "png": chip_hash + ".png",
                    "receipt": chip_hash + ".json"}
        if names != expected:
            raise ValueError("cache files do not match chip identity")
        return expected

    def _payloads(self, names: dict[str, str]) -> dict[str, bytes]:
        return {kind: self._file_bytes(name, kind) for kind, name in names.items()}

    def put(self, receipt: dict[str, Any], bounds: tuple[float, float, float, float]) -> None:
        if self.read_only:
            raise RuntimeError("read-only imagery store cannot write")
        from agronomy_agent.imagery_sampling import POINT_PROCESS_VERSION
        if "sampling" in receipt or receipt.get("process_version") == POINT_PROCESS_VERSION:
            from agronomy_agent.imagery_receipts import validate_point_receipt
            expected_bounds = validate_point_receipt(receipt)
            if len(bounds) != 4 or any(not math.isclose(a, b, abs_tol=1e-9, rel_tol=0)
                                       for a, b in zip(bounds, expected_bounds)):
                raise ValueError("sampling footprint index bounds mismatch")
        names = self._names(receipt)
        payloads = self._payloads(names)
        stored = json.loads(payloads["receipt"])
        if _canonical(stored) != _canonical(receipt):
            raise ValueError("receipt file differs from submitted receipt")
        source = receipt["source"]
        hashes = (_sha(payloads["npz"]), _sha(payloads["png"]),
                  _sha(_canonical(receipt)), _sha(payloads["receipt"]))
        row = (
            receipt["chip_hash"], receipt["request_hash"], receipt["geometry_hash"],
            receipt["process_hash"], receipt["provider_id"], source["collection"],
            source["scene_id"], source.get("acquired_at"), source.get("availability_at"),
            json.dumps(source["asset_ids"], sort_keys=True), json.dumps(source, sort_keys=True),
            json.dumps(receipt["qa"], sort_keys=True), json.dumps(receipt["zonal_stats"], sort_keys=True),
            json.dumps(receipt.get("model_refs", []), sort_keys=True), names["npz"],
            names["png"], names["receipt"], receipt["created_at"], *bounds, *hashes,
        )
        with self._connect() as db:
            db.execute("DELETE FROM chips WHERE chip_hash=?", (receipt["chip_hash"],))
            db.execute("INSERT INTO chips VALUES (" + ",".join("?" for _ in row) + ")", row)

    def _row_matches_receipt(self, row: sqlite3.Row, receipt: dict[str, Any]) -> bool:
        try:
            from agronomy_agent.imagery_sampling import POINT_PROCESS_VERSION
            if "sampling" in receipt or receipt.get("process_version") == POINT_PROCESS_VERSION:
                from agronomy_agent.imagery_receipts import validate_point_receipt
                expected_bounds = validate_point_receipt(receipt)
                if any(not math.isclose(row[name], value, abs_tol=1e-9, rel_tol=0)
                       for name, value in zip(("minx", "miny", "maxx", "maxy"), expected_bounds)):
                    return False
            names = self._names(receipt)
            source = receipt["source"]
            return (
                receipt["chip_hash"] == row["chip_hash"] and
                receipt["request_hash"] == row["request_hash"] and
                receipt["geometry_hash"] == row["geometry_hash"] and
                receipt["process_hash"] == row["process_hash"] and
                receipt["provider_id"] == row["provider_id"] and
                receipt["created_at"] == row["created_at"] and
                source["collection"] == row["collection"] and
                source["scene_id"] == row["scene_id"] and
                source.get("acquired_at") == row["acquired_at"] and
                source.get("availability_at") == row["availability_at"] and
                source["asset_ids"] == json.loads(row["asset_ids_json"]) and
                source == json.loads(row["source_json"]) and
                receipt["qa"] == json.loads(row["qa_json"]) and
                receipt["zonal_stats"] == json.loads(row["zonal_json"]) and
                receipt.get("model_refs", []) == json.loads(row["model_refs_json"]) and
                names == {"npz": row["npz_name"], "png": row["png_name"],
                          "receipt": row["receipt_name"]}
            )
        except (KeyError, ValueError, TypeError):
            return False

    def _attest_legacy_v2(self, row: sqlite3.Row, receipt: dict[str, Any],
                          payloads: dict[str, bytes]) -> bool:
        """Migrate only full native-v2 rows whose pixels still bind their chip ID.

        Older v1 and partial-v2 rows remain on disk but never become cache hits.
        """
        try:
            import numpy as np
            from PIL import Image
            from agronomy_agent.imagery_analytics import BAND_KEYS, PROCESS_VERSION, _png
            if (receipt.get("process_version") != PROCESS_VERSION or
                    receipt.get("source_native_grid") is not True or
                    receipt.get("grid", {}).get("resampling_method") != "nearest" or
                    not isinstance(receipt["grid"].get("native_asset_grid"), dict)):
                return False
            with zipfile.ZipFile(io.BytesIO(payloads["npz"])) as archive:
                if sum(info.file_size for info in archive.infolist()) > 16 * 1024 * 1024:
                    return False
            with np.load(io.BytesIO(payloads["npz"]), allow_pickle=False) as chip:
                bands, fmask = chip["bands"], chip["fmask"]
                weights, valid, ndvi = chip["field_weights"], chip["valid_mask"], chip["ndvi"]
                field_mask = chip["field_mask"]
                metadata = json.loads(str(chip["metadata_json"]))
            if (bands.shape[0] != 6 or bands.shape[1:] != fmask.shape or
                    weights.shape != fmask.shape or valid.shape != fmask.shape or
                    field_mask.shape != fmask.shape or
                    ndvi.shape != fmask.shape or bands.shape[1] > 256 or bands.shape[2] > 256 or
                    metadata.get("process_version") != PROCESS_VERSION or
                    metadata.get("source_native_grid") is not True or
                    metadata.get("native_asset_grid") != receipt["grid"]["native_asset_grid"] or
                    metadata.get("resampling_method") != "nearest" or
                    metadata.get("source") != receipt["source"] or
                    metadata.get("crs") != receipt["grid"]["crs"] or
                    metadata.get("transform") != receipt["grid"]["transform"] or
                    metadata.get("width") != receipt["grid"]["width"] or
                    metadata.get("height") != receipt["grid"]["height"] or
                    metadata.get("band_names") != ["Blue", "Green", "Red", "NarrowNIR", "SWIR1", "SWIR2"]):
                return False
            if (not np.array_equal(valid, np.all(np.isfinite(bands), axis=0)) or
                    not np.array_equal(field_mask, weights > 0)):
                return False
            denominator = bands[3] + bands[2]
            expected_ndvi = np.full(ndvi.shape, np.nan, dtype=np.float32)
            np.divide(bands[3] - bands[2], denominator, out=expected_ndvi,
                      where=valid & (np.abs(denominator) > 1e-6))
            if not np.allclose(ndvi, expected_ndvi, rtol=1e-6, atol=1e-6, equal_nan=True):
                return False
            preview = np.asarray(Image.open(io.BytesIO(payloads["png"])).convert("RGBA"))
            expected = np.asarray(Image.open(io.BytesIO(_png(ndvi, valid, weights, Image))).convert("RGBA"))
            if not np.array_equal(preview, expected):
                return False
            qa = receipt["qa"]
            field_area, valid_area = float(weights.sum() * 900), float(weights[valid].sum() * 900)
            if (not math.isclose(qa["field_area_m2"], field_area, rel_tol=1e-5) or
                    not math.isclose(qa["valid_area_m2"], valid_area, rel_tol=1e-5)):
                return False
            _, band_keys = BAND_KEYS[receipt["provider_id"]]
            asset_ids = [receipt["source"]["asset_ids"][key] for key in (*band_keys, "Fmask")]
            array_hash = _sha(bands.tobytes() + fmask.tobytes() + weights.tobytes())
            chip_binding = {"request": receipt["request_hash"], "scene": receipt["scene_id"],
                            "asset_ids": asset_ids, "process": receipt["process_hash"],
                            "arrays": array_hash, "grid": receipt["grid"]}
            return _sha(_canonical(chip_binding)) == row["chip_hash"]
        except (KeyError, ValueError, TypeError, OSError, ImportError, EOFError,
                IndexError, OverflowError, zipfile.BadZipFile):
            return False

    def _verified_row(self, row: sqlite3.Row) -> dict[str, Any] | None:
        try:
            if self.read_only and any(row[name] is None for name in
                    ("npz_sha256", "png_sha256", "receipt_sha256", "receipt_file_sha256")):
                return None
            names = {"npz": row["npz_name"], "png": row["png_name"],
                     "receipt": row["receipt_name"]}
            if names != {"npz": row["chip_hash"] + ".npz",
                         "png": row["chip_hash"] + ".png",
                         "receipt": row["chip_hash"] + ".json"}:
                return None
            payloads = self._payloads(names)
            receipt = json.loads(payloads["receipt"])
            if not isinstance(receipt, dict) or not self._row_matches_receipt(row, receipt):
                return None
            if any(row[name] is None for name in ("npz_sha256", "png_sha256", "receipt_sha256", "receipt_file_sha256")):
                if not self._attest_legacy_v2(row, receipt, payloads):
                    return None
                hashes = (_sha(payloads["npz"]), _sha(payloads["png"]),
                          _sha(_canonical(receipt)), _sha(payloads["receipt"]))
                with self._connect() as db:
                    db.execute("""UPDATE chips SET npz_sha256=?,png_sha256=?,receipt_sha256=?,
                                  receipt_file_sha256=? WHERE chip_hash=? AND npz_sha256 IS NULL""",
                               (*hashes, row["chip_hash"]))
            else:
                hashes = (row["npz_sha256"], row["png_sha256"],
                          row["receipt_sha256"], row["receipt_file_sha256"])
            if hashes != (_sha(payloads["npz"]), _sha(payloads["png"]),
                          _sha(_canonical(receipt)), _sha(payloads["receipt"])):
                return None
            return receipt
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, sqlite3.Error):
            return None

    def get(self, request_hash: str, *, scene_id: str | None = None) -> dict[str, Any] | None:
        if self.read_only and not self._readable:
            return None
        with self._connect() as db:
            if scene_id is None:
                rows = db.execute("SELECT * FROM chips WHERE request_hash=? ORDER BY acquired_at DESC,scene_id",
                                  (request_hash,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM chips WHERE request_hash=? AND scene_id=?",
                                  (request_hash, scene_id)).fetchall()
        for row in rows:
            receipt = self._verified_row(row)
            if receipt is not None:
                return receipt
        return None

    def get_by_chip_hash(self, chip_hash: str) -> dict[str, Any] | None:
        """Resolve only intact chips for an authenticated preview route."""
        if not isinstance(chip_hash, str) or not _HASH.fullmatch(chip_hash):
            return None
        if self.read_only and not self._readable:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM chips WHERE chip_hash=?", (chip_hash,)).fetchone()
        return self._verified_row(row) if row is not None else None

    def read_verified_artifact(self, chip_hash: str, kind: str) -> bytes | None:
        """Return verified bytes directly, avoiding a preview path race."""
        receipt = self.get_by_chip_hash(chip_hash)
        if receipt is None or kind not in ("png", "npz", "receipt"):
            return None
        try:
            data = self._file_bytes(receipt["cache_files"][kind], kind)
            with self._connect() as db:
                column = {"npz": "npz_sha256", "png": "png_sha256",
                          "receipt": "receipt_file_sha256"}[kind]
                row = db.execute(f"SELECT {column} FROM chips WHERE chip_hash=?", (chip_hash,)).fetchone()
            return data if row is not None and _sha(data) == row[0] else None
        except (OSError, ValueError):
            return None

    def preview_bytes(self, chip_hash: str) -> bytes | None:
        """Return integrity-checked PNG bytes for an authorized caller."""
        return self.read_verified_artifact(chip_hash, "png")

    def intersects(self, bounds: tuple[float, float, float, float]) -> list[str]:
        if self.read_only and not self._readable:
            return []
        minx, miny, maxx, maxy = bounds
        with self._connect() as db:
            hashes = [row[0] for row in db.execute("""
                SELECT c.chip_hash FROM chips c JOIN chip_bounds b ON c.rowid=b.rowid
                WHERE b.maxx>=? AND b.minx<=? AND b.maxy>=? AND b.miny<=?
                ORDER BY c.acquired_at,c.scene_id
            """, (minx, maxx, miny, maxy))]
        return [chip_hash for chip_hash in hashes if self.get_by_chip_hash(chip_hash) is not None]

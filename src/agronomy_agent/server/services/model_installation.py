"""Explicit, local-only installation of configured and verified model snapshots."""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Iterator

from agronomy_agent.model_assets import pinned_model_assets, verified_model_asset
from agronomy_agent.paths import repo_path

_LOG = logging.getLogger(__name__)
_DOWNLOAD_RESERVE = 128 * 1024**2
_HUB = "https://huggingface.co"


class ModelInstallError(RuntimeError):
    """An installation failure whose message can be shown to the operator."""


class ModelInstallation:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: str | None = None
        self._failures: dict[str, str] = {}

    def status(self, model_id: str) -> tuple[str | None, str | None]:
        with self._lock:
            if self._active == model_id:
                return "downloading", None
            failure = self._failures.get(model_id)
            return ("failed", failure) if failure else (None, None)

    def start(self, model_id: str) -> bool:
        with self._lock:
            if self._active == model_id:
                return False
            if self._active is not None:
                raise ModelInstallError("Wait for the current model download to finish.")
            self._failures.pop(model_id, None)
            self._active = model_id
            return True

    def run(self, model_id: str, revision: str) -> None:
        failure = None
        try:
            install_model(model_id, revision)
        except ModelInstallError as error:
            failure = str(error)
        except Exception as error:
            _LOG.warning("Local model installation failed for %s: %s", model_id, type(error).__name__)
            failure = "Could not download and verify the model. Check your connection and try again."
        finally:
            with self._lock:
                if failure:
                    self._failures[model_id] = failure
                self._active = None


@contextmanager
def _lock_cache(cache: Path) -> Iterator[None]:
    import fcntl

    lock_fd = os.open(cache / ".open-agronomy-install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ModelInstallError("Another model download is using this cache. Try again shortly.") from None
        yield


def install_model(model_id: str, revision: str) -> None:
    from huggingface_hub import hf_hub_download

    assets = pinned_model_assets(model_id, revision)
    if not assets:
        raise ModelInstallError("This model is unavailable for download.")
    cache = Path(os.environ.get("HF_HUB_CACHE") or repo_path(".hf_cache/hub")).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    cache = cache.resolve(strict=True)
    repo = cache / ("models--" + model_id.replace("/", "--"))

    with _lock_cache(cache):
        snapshot = repo / "snapshots" / revision
        if snapshot.resolve() != snapshot or (repo / "blobs").resolve() != repo / "blobs":
            raise ModelInstallError("The model cache location is invalid.")
        pending = []
        required = 0
        for asset in assets:
            pointer = snapshot / asset.name
            if verified_model_asset(pointer, repo, asset):
                continue
            blob = repo / "blobs" / asset.blob_id
            blob_ready = verified_model_asset(blob, repo, asset)
            if not blob_ready:
                required += asset.size
            pending.append((asset, pointer, blob, blob_ready))
        if required and shutil.disk_usage(cache).free < required + _DOWNLOAD_RESERVE:
            needed_gb = (required + _DOWNLOAD_RESERVE) / 10**9
            raise ModelInstallError(f"Free at least {needed_gb:.1f} GB in the model cache and try again.")

        for asset, pointer, blob, blob_ready in pending:
            # A Hub download leaves some existing snapshot pointers in place.
            # Only remove the invalid leaf under the pinned snapshot.
            pointer_outdated = pointer.exists() or pointer.is_symlink()
            pointer.unlink(missing_ok=True)
            if blob_ready:
                snapshot.mkdir(parents=True, exist_ok=True)
                pointer.symlink_to(Path("../../blobs") / asset.blob_id)
                continue
            repair = blob.exists() or blob.is_symlink() or pointer_outdated
            if blob.is_symlink():
                blob.unlink()
            hf_hub_download(repo_id=model_id, filename=asset.name, revision=revision, cache_dir=cache,
                            endpoint=_HUB, token=False, force_download=repair)
        if any(not verified_model_asset(snapshot / asset.name, repo, asset) for asset in assets):
            raise ModelInstallError("The downloaded model did not match the verified files. Try again.")

from __future__ import annotations

import signal
import subprocess

import pytest

from scripts.run_cockpit import _stop_frontend_process


class _FakeProcess:
    def __init__(self, *, timeouts: int = 0) -> None:
        self.timeouts = timeouts
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False
        self.waits = 0

    def poll(self):  # noqa: ANN201
        return None

    def send_signal(self, value: int) -> None:
        self.signals.append(value)

    def wait(self, timeout: float):  # noqa: ANN201
        self.waits += 1
        if self.waits <= self.timeouts:
            raise subprocess.TimeoutExpired("vite", timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_frontend_cleanup_prefers_sigint() -> None:
    process = _FakeProcess()

    assert _stop_frontend_process(process, timeout_seconds=0.01) == "stopped_sigint"
    assert process.signals == [signal.SIGINT]
    assert not process.terminated
    assert not process.killed


def test_frontend_cleanup_escalates_boundedly() -> None:
    process = _FakeProcess(timeouts=2)

    assert _stop_frontend_process(process, timeout_seconds=0.01) == "stopped_kill"
    assert process.signals == [signal.SIGINT]
    assert process.terminated
    assert process.killed


@pytest.mark.parametrize("custom_services_root", [False, True])
def test_frontend_launch_discovers_field_services_and_uses_validated_ipv6_loopback(tmp_path, monkeypatch, custom_services_root):
    import sys
    from types import SimpleNamespace
    import scripts.run_cockpit as launcher
    observed = {}
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(launcher.os, "environ", launcher.os.environ.copy())
    for name in ("AGRONOMY_AGENT_ADMINISTRATIVE_PACK_ROOT", "AGRONOMY_AGENT_IMAGERY_PYTHON",
                 "AGRONOMY_AGENT_IMAGERY_CACHE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    services = (tmp_path / "custom-services" if custom_services_root else
                tmp_path / "Library/Application Support/OpenAgronomyAgent/field-services")
    worker = services / "imagery/bin/python"
    worker.parent.mkdir(parents=True)
    worker.touch(mode=0o700)
    pack = services / "spatial-pack/field-location-v1"
    pack.mkdir(parents=True)
    argv = ["run_cockpit.py", "--host", "::1", "--port", "8123", "--frontend",
            "--frontend-port", "6199", "--db-path", str(tmp_path / "db.sqlite3"),
            "--artifact-root", str(tmp_path / "artifacts")]
    if custom_services_root:
        argv.extend(["--field-services-root", str(services)])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(launcher,'create_app',lambda settings: observed.update(settings=settings) or object())
    class Process(_FakeProcess):
        pass
    def popen(*args,**kwargs):
        observed['env']=kwargs['env']
        return Process()
    monkeypatch.setattr(launcher.subprocess,'Popen',popen)
    class Config:
        def __init__(self,*args,**kwargs):observed['config']=kwargs
    class Server:
        def __init__(self,config):pass
        def run(self):return 0
    # Exercise launcher wiring without requiring the optional server runtime.
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(Config=Config, Server=Server))
    assert launcher.main()==0
    assert observed['env']['VITE_API_TARGET']=='http://[::1]:8123'
    assert 'http://[::1]:6199' in observed['settings'].local_dev_origins
    assert 'http://localhost:6199' in observed['settings'].local_dev_origins
    assert observed['config']['proxy_headers'] is False
    assert observed['settings'].imagery_worker_python == worker
    assert observed['settings'].imagery_cache_root == services / 'cache/imagery'
    assert launcher.os.environ['AGRONOMY_AGENT_ADMINISTRATIVE_PACK_ROOT'] == str(pack)

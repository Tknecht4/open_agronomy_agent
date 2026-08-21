from __future__ import annotations

import signal
import subprocess

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

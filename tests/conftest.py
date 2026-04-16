"""Shared fixtures.

The load-bearing fixture is `fake_subprocess_runner` — it monkeypatches
`videotoframes.io.subproc.run` with a callable that returns canned
`subprocess.CompletedProcess` values based on matching predicates on
the argv. Tests that forget to register a matcher for a command they
trigger will get a `RuntimeError` naming the unmatched command; real
subprocess calls never happen.

Also owns the `--run-validation` pytest option used by the validation
suite at tests/validation/ — defined here because pytest_addoption
must live in a top-level conftest to be collected before test
modules load.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-validation",
        action="store_true",
        default=False,
        help="Run vision-backed validation tests (requires Ollama or OPENROUTER_API_KEY).",
    )


@dataclass
class _Matcher:
    predicate: Callable[[list[str]], bool]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class FakeSubprocessRunner:
    matchers: list[_Matcher] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)

    def register(
        self,
        predicate: Callable[[list[str]], bool],
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        self.matchers.append(
            _Matcher(
                predicate=predicate,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
            )
        )

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        timeout: float,
        check: bool = True,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        argv = list(cmd)
        self.calls.append(argv)
        for m in self.matchers:
            if m.predicate(argv):
                cp: Any = subprocess.CompletedProcess(
                    args=argv,
                    returncode=m.returncode,
                    stdout=m.stdout,
                    stderr=m.stderr,
                )
                if check and m.returncode != 0:
                    raise subprocess.CalledProcessError(
                        m.returncode, argv, output=m.stdout, stderr=m.stderr
                    )
                return cp
        raise RuntimeError(
            f"fake_subprocess_runner: no matcher for command {argv[:3]}..."
        )


@pytest.fixture
def fake_subprocess_runner(monkeypatch):
    """Monkeypatch the single subprocess boundary.

    Tests register predicates via `runner.register(pred, stdout=..., ...)`.
    Any real `subprocess.run` call below the runner boundary would be a
    test-design bug.
    """
    runner = FakeSubprocessRunner()
    monkeypatch.setattr("videotoframes.io.subproc.run", runner)
    return runner

import subprocess
from collections.abc import Callable
from pathlib import Path

CommandRunner = Callable[[list[str]], str]


def default_runner(root: Path) -> CommandRunner:
    """A CommandRunner that shells out from `root`, returning stdout (or "" on error)."""

    def run(args: list[str]) -> str:
        result = subprocess.run(
            args, cwd=root, capture_output=True, encoding="utf-8", errors="replace"
        )
        return result.stdout if result.returncode == 0 else ""

    return run


def checked_runner(root: Path) -> CommandRunner:
    """A CommandRunner that shells out from `root`, raising on non-zero exit.

    Use this for live (push) operations where a silently-swallowed failure
    (default_runner's behavior) would falsely report success. The raised
    RuntimeError carries the command and captured stderr.
    """

    def run(args: list[str]) -> str:
        result = subprocess.run(
            args, cwd=root, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"command failed ({result.returncode}): {' '.join(args)}\n"
                f"{(result.stderr or '').strip()}"
            )
        return result.stdout

    return run

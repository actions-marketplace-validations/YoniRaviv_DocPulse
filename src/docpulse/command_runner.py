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

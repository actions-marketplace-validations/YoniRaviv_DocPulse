import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

# Issue keys are ABC-123 style; require >=2 leading uppercase letters so encoding
# strings like UTF-8 / CP-1252 are not mistaken for tickets.
_TICKET = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*-\d+\b")

CommandRunner = Callable[[list[str]], str]


def _default_runner(root: Path) -> CommandRunner:
    def run(args: list[str]) -> str:
        result = subprocess.run(
            args, cwd=root, capture_output=True, encoding="utf-8", errors="replace"
        )
        return result.stdout if result.returncode == 0 else ""

    return run


class GitContext:
    """ContextProvider sourcing intent from PR env vars, else commit messages.

    PR title/body are read from env (the Phase 6 Action workflow injects them);
    a live `gh pr view` fallback is deferred to Phase 6 to keep this network-free.
    Ticket IDs matching `ABC-123` are appended so the verifier can weigh them.
    """

    def __init__(
        self,
        root: Path,
        base: str,
        head: str = "HEAD",
        env: dict[str, str] | None = None,
        run_command: CommandRunner | None = None,
    ) -> None:
        self.root = root
        self.base = base
        self.head = head
        self.env = dict(os.environ) if env is None else env
        self.run_command = run_command or _default_runner(root)

    def get_intent(self) -> str:
        parts: list[str] = []
        title = self.env.get("DOCPULSE_PR_TITLE") or self.env.get("PR_TITLE", "")
        body = self.env.get("DOCPULSE_PR_BODY") or self.env.get("PR_BODY", "")
        pr_lines: list[str] = []
        if title:
            pr_lines.append(f"PR: {title}")
        if body:
            pr_lines.append(body)
        if pr_lines:
            parts.append("\n\n".join(pr_lines))
        commits = self.run_command(
            ["git", "log", "--format=%s%n%b", f"{self.base}..{self.head}"]
        ).strip()
        if commits:
            parts.append(f"Commits:\n{commits}")
        blob = "\n\n".join(p for p in parts if p).strip()
        tickets = sorted(set(_TICKET.findall(blob)))
        if tickets:
            blob = f"{blob}\n\nTickets: {', '.join(tickets)}".strip()
        return blob

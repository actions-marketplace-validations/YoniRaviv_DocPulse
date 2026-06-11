from typing import Protocol

from docpulse.models import RunResult


class Destination(Protocol):
    """Where DocPulse publishes its findings and fixes."""

    def summarize(self, result: RunResult) -> None: ...
    def publish_findings(self, result: RunResult) -> None: ...
    def publish_fix(self, result: RunResult) -> str:
        """Publish the doc fixes; returns a reference to the fix (e.g. branch name)."""
        ...

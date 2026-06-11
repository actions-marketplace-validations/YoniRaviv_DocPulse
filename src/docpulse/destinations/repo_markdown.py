from pathlib import Path

from docpulse.command_runner import CommandRunner, default_runner
from docpulse.config import Config
from docpulse.models import DocSection, RunResult
from docpulse.report.summary import render_summary


def _content_lines(content: str) -> list[str]:
    """Split section content into lines, inverting doc_parser's `"\\n".join(...)`.

    `"\\n".join(L)` drops the trailing separator, so when a section ends on a blank
    line (content ends with "\\n"), `str.splitlines()` loses that final empty line.
    Re-appending it makes this the exact inverse of how doc_parser builds content.
    """
    lines = content.splitlines()
    if content.endswith("\n"):
        lines.append("")
    return lines


def replace_sections(file_text: str, edits: list[tuple[DocSection, str]]) -> str:
    """Apply (section, new_content) replacements to one file's text.

    Each section is replaced by its 1-based inclusive [start_line, end_line] range.
    Edits are applied bottom-up (highest start_line first) so an earlier edit that
    changes line count never shifts a later section's range. Uses str.splitlines()
    to match doc_parser's line model; the file's trailing newline is preserved.

    Note: line endings are normalized to "\\n" (CRLF input is rewritten to LF).
    """
    lines = file_text.splitlines()
    for section, new_content in sorted(edits, key=lambda e: e[0].start_line, reverse=True):
        lines[section.start_line - 1 : section.end_line] = _content_lines(new_content)
    trailing = "\n" if file_text.endswith("\n") else ""
    return "\n".join(lines) + trailing


class RepoMarkdownDestination:
    """Plans a companion-PR + flag comment for a repo-markdown destination.

    Phase 5 is dry-run: it constructs the branch/commit/PR-body and the `gh`/`git`
    commands but does not push or open a PR (deferred to Phase 6). `summarize` and
    `publish_findings` print to stdout.
    """

    def __init__(
        self,
        root: Path,
        sections_by_id: dict[str, DocSection],
        config: Config,
        head_sha: str,
        run_command: CommandRunner | None = None,
        dry_run: bool = True,
    ) -> None:
        self.root = root
        self.sections_by_id = sections_by_id
        self.config = config
        self.head_sha = head_sha
        self.run_command = run_command or default_runner(root)
        self.dry_run = dry_run

    def flag_comment(self, result: RunResult) -> str:
        """Markdown comment listing stale sections at/above flag_threshold."""
        threshold = self.config.confidence.flag_threshold
        flagged = [
            v for v in result.verdicts
            if v.status == "stale" and v.confidence >= threshold
        ]
        if not flagged:
            return ""
        lines = ["## \U0001fa7a DocPulse — flagged documentation", ""]
        for v in flagged:
            section = self.sections_by_id.get(v.section_id)
            loc = section.path if section else v.section_id
            evidence = f" _(evidence: {', '.join(v.evidence)})_" if v.evidence else ""
            lines.append(f"- **{v.section_id}** ({loc}) — {v.diagnosis}{evidence}")
        return "\n".join(lines)

    def publish_findings(self, result: RunResult) -> None:
        comment = self.flag_comment(result)
        if comment:
            print(comment)

    def summarize(self, result: RunResult) -> None:
        print(render_summary(result))

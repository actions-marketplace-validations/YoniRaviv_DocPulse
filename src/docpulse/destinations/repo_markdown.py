from dataclasses import dataclass
from pathlib import Path

from docpulse.command_runner import CommandRunner, default_runner
from docpulse.config import Config
from docpulse.models import DocSection, Repair, RunResult
from docpulse.repair.routing import Tier, route
from docpulse.report.summary import render_summary


@dataclass
class FixPlan:
    """The dry-run companion-PR plan. Phase 6 turns `commands` into real calls."""

    branch: str
    commit_message: str
    pr_title: str
    pr_body: str
    file_writes: dict[str, str]   # repo-relative path -> full new file content
    commands: list[list[str]]     # git/gh argv lists Phase 6 would execute


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
        base_branch: str | None = None,
        pr_number: str | None = None,
    ) -> None:
        self.root = root
        self.sections_by_id = sections_by_id
        self.config = config
        self.head_sha = head_sha
        self.run_command = run_command or default_runner(root)
        self.dry_run = dry_run
        self.base_branch = base_branch
        self.pr_number = pr_number

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
        if not comment:
            return
        if not self.dry_run and self.pr_number:
            self.run_command(["gh", "pr", "comment", self.pr_number, "--body", comment])
        else:
            print(comment)

    def summarize(self, result: RunResult) -> None:
        print(render_summary(result))

    def _routed_for_pr(self, result: RunResult) -> list[tuple[Repair, Tier]]:
        """(repair, tier) pairs whose tier means 'include in the companion PR'."""
        verdicts = {v.section_id: v for v in result.verdicts}
        out: list[tuple[Repair, Tier]] = []
        for repair_obj in result.repairs:
            verdict = verdicts.get(repair_obj.section_id)
            if verdict is None:
                continue
            tier = route(verdict, repair_obj, self.config)
            if tier in ("auto_fix", "draft"):
                out.append((repair_obj, tier))
        return out

    def build_fix_plan(self, result: RunResult) -> "FixPlan | None":
        """Construct the companion-PR plan, or None if nothing is applyable."""
        applied = self._routed_for_pr(result)
        if not applied:
            return None
        edits_by_path: dict[str, list[tuple[DocSection, str]]] = {}
        body_lines: list[str] = []
        for repair_obj, tier in applied:
            section = self.sections_by_id.get(repair_obj.section_id)
            if section is None:
                continue
            edits_by_path.setdefault(section.path, []).append(
                (section, repair_obj.new_content)
            )
            body_lines.append(f"- **{section.id}** ({tier}): {repair_obj.rationale}")
        if not edits_by_path:
            return None
        file_writes: dict[str, str] = {}
        for path, edits in edits_by_path.items():
            original = (self.root / path).read_text()
            file_writes[path] = replace_sections(original, edits)
        branch = f"docpulse/fix-{self.head_sha[:8]}"
        commit_message = "docs: sync stale sections (DocPulse)"
        pr_title = "\U0001f4dd DocPulse: sync docs with code changes"
        pr_body = "DocPulse detected and fixed stale documentation:\n\n" + "\n".join(body_lines)
        pr_create = ["gh", "pr", "create", "--title", pr_title, "--body", pr_body]
        if self.base_branch:
            pr_create += ["--base", self.base_branch]
        commands = [
            ["git", "checkout", "-b", branch],
            *[["git", "add", path] for path in sorted(file_writes)],
            ["git", "commit", "-m", commit_message],
            ["git", "push", "-u", "origin", branch],
            pr_create,
        ]
        return FixPlan(branch, commit_message, pr_title, pr_body, file_writes, commands)

    def publish_fix(self, result: RunResult) -> str:
        """Open the companion fix PR.

        Dry-run: returns the planned branch name without running anything.
        Live: writes the doc edits, runs the git/gh commands (a failing command
        raises via the checked runner), and returns the created PR URL.
        """
        plan = self.build_fix_plan(result)
        if plan is None:
            return ""
        if self.dry_run:
            return plan.branch
        # Live path. NOTE: writes+commands are not atomic — a failure mid-way
        # leaves the working tree partially modified; recoverable because all
        # changes land on the fresh `docpulse/fix-<sha>` branch.
        for path, new_text in plan.file_writes.items():
            (self.root / path).write_text(new_text)
        pr_url = ""
        for command in plan.commands:
            out = self.run_command(command)
            if command[:3] == ["gh", "pr", "create"]:
                pr_url = out.strip()
        return pr_url or plan.branch

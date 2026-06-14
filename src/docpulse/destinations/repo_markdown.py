from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from docpulse.command_runner import CommandRunner, default_runner
from docpulse.config import Config
from docpulse.models import DocSection, Repair, RunResult
from docpulse.repair.routing import Tier, route
from docpulse.report.summary import render_summary


@dataclass
class FixPlan:
    """The doc-sync commit plan: file rewrites + the git commands to land them.

    `--push` commits these doc edits onto the current branch and pushes, so the
    fix lands in the same PR via the doc-sync commit.
    """

    commit_message: str
    file_writes: dict[str, str]   # repo-relative path -> full new file content
    commands: list[list[str]]     # git argv lists the live path executes


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
    """Repo-markdown destination: flag comment + a doc-sync commit.

    `publish_findings` posts (live) or prints the flag comment. In `--push`
    (live) mode `publish_fix` commits the doc fixes onto the current branch and
    pushes; dry-run only builds the plan. `summarize` prints the health line.
    """

    def __init__(
        self,
        root: Path,
        sections_by_id: dict[str, DocSection],
        config: Config,
        head_sha: str,
        run_command: CommandRunner | None = None,
        dry_run: bool = True,
        pr_number: str | None = None,
        comment_out: Path | None = None,
        comment_via: Literal["gh", "none"] = "gh",
        bot_name: str = "docpulse[bot]",
        bot_email: str = "docpulse-bot@users.noreply.github.com",
    ) -> None:
        self.root = root
        self.sections_by_id = sections_by_id
        self.config = config
        self.head_sha = head_sha
        self.run_command = run_command or default_runner(root)
        self.dry_run = dry_run
        self.pr_number = pr_number
        self.comment_out = comment_out
        self.comment_via = comment_via
        self.bot_name = bot_name
        self.bot_email = bot_email

    def flag_comment(self, result: RunResult) -> str:
        """Markdown comment listing stale sections at/above flag_threshold."""
        threshold = self.config.confidence.flag_threshold
        flagged = [
            v for v in result.verdicts
            if v.status == "stale" and v.confidence >= threshold
        ]
        if not flagged:
            return ""
        n = len(flagged)
        count_phrase = f"**{n} section{'s' if n != 1 else ''}**"
        lines = [
            "## \U0001fa7a DocPulse — flagged documentation",
            "",
            f"{count_phrase} may be out of sync with this PR's code changes.",
        ]
        for v in flagged:
            section = self.sections_by_id.get(v.section_id)
            lines.append("")
            lines.append("---")
            lines.append("")
            if section:
                lines.append(f"### {section.path}")
                if section.heading_path:
                    trail = " › ".join(section.heading_path)
                    lines.append(f"**{trail}**")
            else:
                lines.append(f"### {v.section_id}")
            lines.append("")
            lines.append(v.diagnosis.strip())
            if v.evidence:
                k = len(v.evidence)
                items = "\n".join(
                    f"- {item.replace(chr(10), ' ').strip()}" for item in v.evidence
                )
                lines.append("")
                lines.append(f"<details><summary>Evidence ({k})</summary>")
                lines.append("")
                lines.append(items)
                lines.append("</details>")
        return "\n".join(lines)

    def publish_findings(self, result: RunResult) -> None:
        comment = self.flag_comment(result)
        if not comment:
            return
        if self.comment_out is not None:
            self.comment_out.write_text(comment)
        if self.comment_via == "gh" and not self.dry_run and self.pr_number:
            self.run_command(["gh", "pr", "comment", self.pr_number, "--body", comment])
            return  # posted to the PR; stdout not needed
        if self.comment_out is None:
            print(comment)  # no artifact + not posted -> log it

    def summarize(self, result: RunResult) -> None:
        committed = not self.dry_run and any(r.validation_passed for r in result.repairs)
        print(render_summary(result, fix_ref="committed to branch" if committed else None))

    def _routed_for_commit(self, result: RunResult) -> list[tuple[Repair, Tier]]:
        """(repair, tier) pairs whose tier warrants inclusion in the doc-sync commit."""
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
        """Plan the doc-sync commit, or None if nothing is applyable."""
        applied = self._routed_for_commit(result)
        if not applied:
            return None
        edits_by_path: dict[str, list[tuple[DocSection, str]]] = {}
        for repair_obj, _tier in applied:
            section = self.sections_by_id.get(repair_obj.section_id)
            if section is None:
                continue
            edits_by_path.setdefault(section.path, []).append(
                (section, repair_obj.new_content)
            )
        if not edits_by_path:
            return None
        file_writes: dict[str, str] = {}
        for path, edits in edits_by_path.items():
            original = (self.root / path).read_text()
            file_writes[path] = replace_sections(original, edits)
        commit_message = "docs: sync stale sections with code changes (DocPulse)"
        commands = [
            *[["git", "add", path] for path in sorted(file_writes)],
            ["git", "-c", f"user.name={self.bot_name}",
             "-c", f"user.email={self.bot_email}", "commit", "-m", commit_message],
            ["git", "push", "origin", "HEAD"],
        ]
        return FixPlan(
            commit_message=commit_message, file_writes=file_writes, commands=commands
        )

    def publish_fix(self, result: RunResult) -> str:
        """Commit the doc fixes onto the current branch and push.

        Dry-run: returns "" without running anything (callers print the plan).
        Live: writes the doc edits, then runs git add/commit/push (a failing
        command raises via the checked runner). Returns the commit message as a
        short confirmation, or "" when there was nothing to fix.
        """
        plan = self.build_fix_plan(result)
        if plan is None:
            return ""
        if self.dry_run:
            return ""
        # NOTE: writes+commands are not atomic — a failure mid-way leaves the
        # working tree partially modified. The edits land on the current PR
        # branch, so a re-run reconciles them.
        for path, new_text in plan.file_writes.items():
            (self.root / path).write_text(new_text)
        for command in plan.commands:
            self.run_command(command)
        return plan.commit_message

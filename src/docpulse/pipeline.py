import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docpulse.config import Config
from docpulse.context.base import ContextProvider
from docpulse.diffing.change_filter import meaningful_changed_chunks
from docpulse.diffing.git_diff import diff_range, show_file
from docpulse.diffing.suspects import select_suspects
from docpulse.indexing.code_chunker import chunk_source
from docpulse.models import Index, Repair, RunResult, Suspect, Verdict
from docpulse.report.summary import compute_exit_code
from docpulse.verification.verifier import VerifyBundle, verify


def _seed_code(root: Path, base: str, head: str, suspect: Suspect) -> tuple[str, str]:
    """Best-effort (old_code, new_code) seed for a suspect's changed chunks.

    Re-chunks each changed file at base and head and pairs by chunk id, so the
    verifier is seeded with the before/after of exactly the changed symbols. The
    verifier's read tools can inspect further; this is only the starting evidence.
    """
    base_by_id = {}
    head_by_id = {}
    for path in sorted({sc.chunk.path for sc in suspect.changed_chunks}):
        base_text = show_file(root, base, path)
        head_text = show_file(root, head, path)
        if base_text:
            base_by_id.update({c.id: c for c in chunk_source(path, base_text)})
        if head_text:
            head_by_id.update({c.id: c for c in chunk_source(path, head_text)})
    old_parts: list[str] = []
    new_parts: list[str] = []
    for sc in suspect.changed_chunks:
        old = base_by_id.get(sc.chunk.id)
        new = head_by_id.get(sc.chunk.id)
        old_parts.append(old.content if old else f"(symbol {sc.chunk.name} did not exist before)")
        new_parts.append(new.content if new else f"(symbol {sc.chunk.name} was removed)")
    return "\n\n".join(old_parts), "\n\n".join(new_parts)


def build_verify_bundle(
    root: Path, base: str, head: str, suspect: Suspect, intent: str
) -> VerifyBundle:
    """Assemble the verifier's seed bundle for one suspect section."""
    old_code, new_code = _seed_code(root, base, head, suspect)
    return VerifyBundle(
        section_id=suspect.section.id,
        doc_content=suspect.section.content,
        old_code=old_code,
        new_code=new_code,
        intent=intent,
    )


def _rev_parse(root: Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", ref], cwd=root, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _stderr_warn(message: str) -> None:
    print(message, file=sys.stderr)


def run_pipeline(
    root: Path,
    base: str,
    head: str,
    config: Config,
    client: Any,
    index: Index,
    context: ContextProvider,
    mode: str = "check",
    three_dot: bool = True,
    warn: Callable[[str], None] = _stderr_warn,
) -> RunResult:
    """Full pipeline: diff -> suspects -> verify (-> repair) -> RunResult.

    `mode` is "check" (verdicts only) or "repair" (also repair+validate the stale
    verdicts whose confidence clears flag_threshold). `client` must expose
    `complete(...)` and (optionally) `tokens_used` (see LLMClient).
    """
    indexed_sha = _rev_parse(root, index.base_commit)
    head_sha = _rev_parse(root, head)
    if indexed_sha and head_sha and indexed_sha != head_sha:
        warn(
            f"warning: index built at {index.base_commit[:12]} but checking {head}; "
            f"results may be stale — re-run `docpulse index`"
        )

    diffs = diff_range(root, base, head, three_dot=three_dot)
    changed = meaningful_changed_chunks(root, diffs, config, base, head)
    suspects, total = select_suspects(changed, index, config.budget.max_suspects_per_run)
    intent = context.get_intent()

    verdicts: list[Verdict] = [
        verify(
            client, root, index,
            build_verify_bundle(root, base, head, suspect, intent),
            config.budget.max_tool_calls_per_suspect,
        )
        for suspect in suspects
    ]

    repairs: list[Repair] = []
    if mode == "repair":
        repairs = _repair_stale(root, base, head, config, client, suspects, verdicts, intent)

    return RunResult(
        verdicts=verdicts,
        repairs=repairs,
        suspects_checked=len(suspects),
        suspects_total=total,
        tokens_used=getattr(client, "tokens_used", 0),
        exit_code=compute_exit_code(verdicts, config.confidence.flag_threshold),
    )


def _repair_stale(root, base, head, config, client, suspects, verdicts, intent):  # noqa: ANN001
    return []

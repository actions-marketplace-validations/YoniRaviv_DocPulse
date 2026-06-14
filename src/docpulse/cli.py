import difflib
import os
import re
import shlex
import subprocess
from pathlib import Path

import typer

from docpulse.command_runner import checked_runner
from docpulse.config import Config, DocGlob, load_config
from docpulse.context.git_context import GitContext
from docpulse.destinations.repo_markdown import RepoMarkdownDestination
from docpulse.diffing.change_filter import meaningful_changed_chunks
from docpulse.diffing.git_diff import diff_range
from docpulse.diffing.suspects import select_suspects
from docpulse.eval.harness import evaluate
from docpulse.eval.repair_harness import evaluate_repairs
from docpulse.indexing.embeddings import Embedder
from docpulse.indexing.index_store import build_index, load_index, save_index
from docpulse.llm import LLMClient
from docpulse.pipeline import run_pipeline

app = typer.Typer(
    help="DocPulse — docs that stay in sync with the heartbeat of the codebase.",
    no_args_is_help=True,
)


_DEFAULT_BOT_NAME = "docpulse[bot]"
_DEFAULT_BOT_EMAIL = "docpulse-bot@users.noreply.github.com"


@app.callback()
def _main() -> None:
    """DocPulse — docs that stay in sync with the heartbeat of the codebase."""


def _head_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _pr_number(env: dict[str, str]) -> str | None:
    """PR number for `gh pr comment`, from explicit env or GITHUB_REF."""
    explicit = env.get("DOCPULSE_PR_NUMBER") or env.get("PR_NUMBER")
    if explicit:
        return explicit
    match = re.match(r"refs/pull/(\d+)/", env.get("GITHUB_REF", ""))
    return match.group(1) if match else None


def _bot_identity(env: dict[str, str]) -> tuple[str, str]:
    """(name, email) for the doc-sync commit + loop guard, from env or defaults."""
    return (
        env.get("DOCPULSE_BOT_NAME") or _DEFAULT_BOT_NAME,
        env.get("DOCPULSE_BOT_EMAIL") or _DEFAULT_BOT_EMAIL,
    )


def _build_destination(
    *, root: Path, sections_by_id, config, head_sha, dry_run, pr_number=None
):
    run_command = checked_runner(root) if not dry_run else None
    return RepoMarkdownDestination(
        root, sections_by_id, config, head_sha,
        run_command=run_command, dry_run=dry_run,
        pr_number=pr_number,
    )


@app.command("index")
def index(
    root: Path = typer.Option(Path("."), help="Repo root"),
    config_path: Path | None = typer.Option(None, "--config", help="Path to docpulse.yml"),
    heuristics_only: bool = typer.Option(False, help="Skip embeddings (no API key needed)"),
    base_commit: str | None = typer.Option(None, help="Override base commit recorded in the index"),
) -> None:
    """Build the code<->docs link index and save it to .docpulse/index.json."""
    config = load_config(config_path or root / "docpulse.yml")
    embedder = (
        None
        if heuristics_only
        else Embedder(config.embedding_model, root / ".docpulse" / "embeddings.json")
    )
    result = build_index(root, config, embedder, base_commit or _head_commit(root))
    save_index(result, root / ".docpulse" / "index.json")
    typer.echo(
        f"indexed {len(result.chunks)} chunks, {len(result.sections)} sections, "
        f"{len(result.links)} links"
    )


def _print_suspects(suspects: list, total: int) -> None:
    if not suspects:
        typer.echo("no suspect doc sections")
        return
    sections_word = "section" if len(suspects) == 1 else "sections"
    candidates_word = "candidate" if total == 1 else "candidates"
    typer.echo(f"{len(suspects)} suspect {sections_word} (of {total} {candidates_word}):")
    for suspect in suspects:
        chunk_names = ", ".join(sc.chunk.name for sc in suspect.changed_chunks)
        typer.echo(f"  {suspect.section.id}  score={suspect.score:.2f}  changed: {chunk_names}")


@app.command("check")
def check(
    base: str = typer.Option(..., "--base", help="Base git ref to diff against"),
    head: str = typer.Option("HEAD", help="Head git ref"),
    root: Path = typer.Option(Path("."), help="Repo root"),
    config_path: Path | None = typer.Option(None, "--config", help="Path to docpulse.yml"),
    model: str | None = typer.Option(None, "--model", help="LiteLLM model (overrides config)"),
    suspects_only: bool = typer.Option(
        False, "--suspects-only", help="LLM-less: just list suspect sections (no API key)"
    ),
    two_dot: bool = typer.Option(
        False, "--two-dot", help="Diff literal base..head instead of merge-base base...head"
    ),
    push: bool = typer.Option(
        False, "--push", help="Live: post the flag comment to the PR (needs gh + GH_TOKEN)"
    ),
) -> None:
    """Verify doc sections against base..head and report drift (exit 1 on stale)."""
    index_path = root / ".docpulse" / "index.json"
    if not index_path.exists():
        typer.echo("no index found — run `docpulse index` first", err=True)
        raise typer.Exit(2)
    try:
        config = load_config(config_path or root / "docpulse.yml")
        index = load_index(index_path)
    except FileNotFoundError as exc:
        typer.echo(f"config not found: {exc.filename}", err=True)
        raise typer.Exit(2) from exc

    if suspects_only:
        try:
            diffs = diff_range(root, base, head, three_dot=not two_dot)
            changed = meaningful_changed_chunks(root, diffs, config, base, head)
        except RuntimeError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        suspects, total = select_suspects(changed, index, config.budget.max_suspects_per_run)
        _print_suspects(suspects, total)
        return

    try:
        client = LLMClient(model or config.model)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    context = GitContext(root, base, head)
    try:
        result = run_pipeline(
            root, base, head, config, client, index, context,
            mode="check", three_dot=not two_dot,
        )
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    dest = _build_destination(
        root=root, sections_by_id={s.id: s for s in index.sections},
        config=config, head_sha=_head_commit(root),
        dry_run=not push, pr_number=_pr_number(dict(os.environ)),
    )
    try:
        dest.publish_findings(result)
    except RuntimeError as exc:
        typer.echo(
            f"live publish failed: {exc}\n"
            "hint: ensure gh is installed and GH_TOKEN has pull-requests:write",
            err=True,
        )
        raise typer.Exit(2) from exc
    dest.summarize(result)
    raise typer.Exit(result.exit_code)


@app.command("repair")
def repair_cmd(
    base: str = typer.Option(..., "--base", help="Base git ref to diff against"),
    head: str = typer.Option("HEAD", help="Head git ref"),
    root: Path = typer.Option(Path("."), help="Repo root"),
    config_path: Path | None = typer.Option(None, "--config", help="Path to docpulse.yml"),
    model: str | None = typer.Option(None, "--model", help="LiteLLM model (overrides config)"),
    write: bool = typer.Option(
        False, "--write", help="Apply fixes to doc files locally (no push)"
    ),
    two_dot: bool = typer.Option(
        False, "--two-dot", help="Diff literal base..head instead of merge-base base...head"
    ),
    push: bool = typer.Option(
        False, "--push", help="Live: commit+push doc fixes onto the current branch (needs GH_TOKEN)"
    ),
) -> None:
    """Verify, repair stale sections, and print the dry-run fix plan."""
    index_path = root / ".docpulse" / "index.json"
    if not index_path.exists():
        typer.echo("no index found — run `docpulse index` first", err=True)
        raise typer.Exit(2)
    try:
        config = load_config(config_path or root / "docpulse.yml")
        index = load_index(index_path)
    except FileNotFoundError as exc:
        typer.echo(f"config not found: {exc.filename}", err=True)
        raise typer.Exit(2) from exc

    try:
        client = LLMClient(model or config.resolve_repair_model())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    context = GitContext(root, base, head)
    try:
        result = run_pipeline(
            root, base, head, config, client, index, context,
            mode="repair", three_dot=not two_dot,
        )
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    dest = _build_destination(
        root=root, sections_by_id={s.id: s for s in index.sections},
        config=config, head_sha=_head_commit(root),
        dry_run=not push,
        pr_number=_pr_number(dict(os.environ)),
    )
    try:
        dest.publish_findings(result)
        plan = dest.build_fix_plan(result)
        if plan is not None and push:
            dest.publish_fix(result)
            typer.echo("\npushed a doc-sync commit to the current branch")
        elif plan is not None:
            for path, new_text in sorted(plan.file_writes.items()):
                original = (root / path).read_text()
                diff = difflib.unified_diff(
                    original.splitlines(), new_text.splitlines(),
                    fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
                )
                typer.echo("\n".join(diff))
            if write:
                for path, new_text in plan.file_writes.items():
                    (root / path).write_text(new_text)
                typer.echo(
                    f"\nwrote {len(plan.file_writes)} file(s) on the working tree; "
                    f"re-run with --push to commit and push to the current branch"
                )
            else:
                typer.echo("\n# --push would run:")
                for command in plan.commands:
                    typer.echo("  " + " ".join(shlex.quote(part) for part in command))
    except RuntimeError as exc:
        typer.echo(
            f"live publish failed: {exc}\n"
            "hint: ensure gh is installed and GH_TOKEN has contents+pull-requests:write",
            err=True,
        )
        raise typer.Exit(2) from exc
    dest.summarize(result)
    raise typer.Exit(result.exit_code)


@app.command("eval")
def eval_cmd(
    cases: Path = typer.Option(Path("evals/cases"), "--cases", help="Eval cases directory"),
    model: str | None = typer.Option(None, "--model", help="LiteLLM model (overrides config)"),
    config_path: Path | None = typer.Option(None, "--config", help="Path to docpulse.yml"),
    root: Path = typer.Option(Path("."), help="Repo root (for config lookup)"),
    min_precision: float | None = typer.Option(
        None, "--min-precision", help="Fail (exit 1) if precision is below this"
    ),
    max_tool_calls: int = typer.Option(10, help="Tool-call budget per case"),
    repair: bool = typer.Option(
        False, "--repair", help="Also run the repair eval (preservation + rubric)"
    ),
) -> None:
    """Run the verifier over labeled eval cases and report precision/recall."""
    chosen_model = model
    if chosen_model is None:
        cfg = config_path or root / "docpulse.yml"
        if cfg.exists():
            chosen_model = load_config(cfg).model
    try:
        client = LLMClient(chosen_model)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if not cases.is_dir():
        typer.echo(f"no cases directory: {cases}", err=True)
        raise typer.Exit(2)

    report = evaluate(client, cases, max_tool_calls)
    typer.echo(f"{'case':<28} {'expected':<10} {'predicted':<11} conf")
    for row in report.rows:
        flag = "" if row.expected == row.predicted else "  <-- mismatch"
        typer.echo(
            f"{row.name:<28} {row.expected:<10} {row.predicted:<11} {row.confidence:.2f}{flag}"
        )
    typer.echo(
        f"\nprecision={report.precision:.2f}  recall={report.recall:.2f}  "
        f"(n={report.total}, tokens={client.tokens_used})"
    )
    if min_precision is not None and report.precision < min_precision:
        typer.echo(
            f"precision {report.precision:.2f} below gate {min_precision:.2f}", err=True
        )
        raise typer.Exit(1)

    if repair:
        repair_cfg_path = config_path or root / "docpulse.yml"
        repair_model = chosen_model
        config = Config(docs=[DocGlob(path="**/*.md")])  # no config: default to all markdown
        if repair_cfg_path.exists():
            repair_cfg = load_config(repair_cfg_path)  # single load, used twice below
            repair_model = repair_cfg.resolve_repair_model() or chosen_model
            config = repair_cfg
        repair_client = LLMClient(repair_model)
        repair_report = evaluate_repairs(repair_client, cases, config)
        typer.echo("\n--- repair eval (stale cases) ---")
        typer.echo(f"{'case':<28} {'preserve':<9} {'surgical':<9} {'tier':<9} acc/cmp/sty  flag")
        for row in repair_report.rows:
            r = row.rubric
            flag = "FLAG" if r.needs_human_review else ""
            typer.echo(
                f"{row.name:<28} {row.preservation:<9.2f} {row.surgical:<9.2f} {row.tier:<9} "
                f"{r.accuracy}/{r.completeness}/{r.style_fidelity}        {flag}"
            )
        typer.echo(
            f"\nmean preservation={repair_report.mean_preservation:.2f}  "
            f">=95% preserved={repair_report.pct_preserved_95:.0%}  "
            f"mean surgical={repair_report.mean_surgical:.2f}  "
            f">=95% surgical={repair_report.pct_surgical_95:.0%}  "
            f"rubric acc={repair_report.mean_accuracy:.1f} "
            f"cmp={repair_report.mean_completeness:.1f} "
            f"sty={repair_report.mean_style_fidelity:.1f}  "
            f"flagged={repair_report.n_flagged}  "
            f"(repair tokens={repair_client.tokens_used})"
        )
        for row in repair_report.rows:
            if row.diff:
                typer.echo(f"\n# diff: {row.name}\n{row.diff}")

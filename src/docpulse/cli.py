import subprocess
from pathlib import Path

import typer

from docpulse.config import Config, DocGlob, load_config
from docpulse.diffing.change_filter import meaningful_changed_chunks
from docpulse.diffing.git_diff import diff_range
from docpulse.diffing.suspects import select_suspects
from docpulse.eval.harness import evaluate
from docpulse.eval.repair_harness import evaluate_repairs
from docpulse.indexing.embeddings import Embedder
from docpulse.indexing.index_store import build_index, load_index, save_index
from docpulse.llm import LLMClient

app = typer.Typer(
    help="DocPulse — docs that stay in sync with the heartbeat of the codebase.",
    no_args_is_help=True,
)


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


@app.command("check")
def check(
    base: str = typer.Option(..., "--base", help="Base git ref to diff against"),
    head: str = typer.Option("HEAD", help="Head git ref"),
    root: Path = typer.Option(Path("."), help="Repo root"),
    config_path: Path | None = typer.Option(None, "--config", help="Path to docpulse.yml"),
) -> None:
    """Diff base..head and print doc sections suspected stale (no LLM yet)."""
    index_path = root / ".docpulse" / "index.json"
    if not index_path.exists():
        typer.echo("no index found — run `docpulse index` first", err=True)
        raise typer.Exit(2)
    try:
        config = load_config(config_path or root / "docpulse.yml")
        index = load_index(index_path)
        diffs = diff_range(root, base, head)
        changed = meaningful_changed_chunks(root, diffs, config, base, head)
    except FileNotFoundError as exc:
        typer.echo(f"config not found: {exc.filename}", err=True)
        raise typer.Exit(2) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    suspects, total = select_suspects(changed, index, config.budget.max_suspects_per_run)
    if not suspects:
        typer.echo("no suspect doc sections")
        return
    sections_word = "section" if len(suspects) == 1 else "sections"
    candidates_word = "candidate" if total == 1 else "candidates"
    typer.echo(f"{len(suspects)} suspect {sections_word} (of {total} {candidates_word}):")
    for suspect in suspects:
        chunk_names = ", ".join(sc.chunk.name for sc in suspect.changed_chunks)
        typer.echo(f"  {suspect.section.id}  score={suspect.score:.2f}  changed: {chunk_names}")


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
        typer.echo(f"{'case':<28} {'preserve':<9} {'tier':<9} acc/cmp/sty  flag")
        for row in repair_report.rows:
            r = row.rubric
            flag = "FLAG" if r.needs_human_review else ""
            typer.echo(
                f"{row.name:<28} {row.preservation:<9.2f} {row.tier:<9} "
                f"{r.accuracy}/{r.completeness}/{r.style_fidelity}        {flag}"
            )
        typer.echo(
            f"\nmean preservation={repair_report.mean_preservation:.2f}  "
            f">=95% preserved={repair_report.pct_preserved_95:.0%}  "
            f"rubric acc={repair_report.mean_accuracy:.1f} "
            f"cmp={repair_report.mean_completeness:.1f} "
            f"sty={repair_report.mean_style_fidelity:.1f}  "
            f"flagged={repair_report.n_flagged}  "
            f"(repair tokens={repair_client.tokens_used})"
        )
        for row in repair_report.rows:
            if row.diff:
                typer.echo(f"\n# diff: {row.name}\n{row.diff}")

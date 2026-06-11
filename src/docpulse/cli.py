import subprocess
from pathlib import Path

import typer

from docpulse.config import load_config
from docpulse.diffing.change_filter import meaningful_changed_chunks
from docpulse.diffing.git_diff import diff_range
from docpulse.diffing.suspects import select_suspects
from docpulse.indexing.embeddings import Embedder
from docpulse.indexing.index_store import build_index, load_index, save_index

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

import subprocess
from pathlib import Path

import typer

from docpulse.config import load_config
from docpulse.indexing.embeddings import Embedder
from docpulse.indexing.index_store import build_index, save_index

app = typer.Typer(
    help="DocPulse — docs that stay in sync with the heartbeat of the codebase.",
    no_args_is_help=True,
)


def _head_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
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


@app.command("version")
def version() -> None:
    """Show the DocPulse version."""
    typer.echo("0.1.0")

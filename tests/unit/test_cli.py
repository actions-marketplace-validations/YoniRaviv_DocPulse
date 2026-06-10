# tests/unit/test_cli.py
from pathlib import Path

from typer.testing import CliRunner

from docpulse.cli import app
from docpulse.indexing.index_store import load_index

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mini_repo"
runner = CliRunner()


def test_index_command_heuristics_only(tmp_path):
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    result = runner.invoke(
        app, ["index", "--root", str(repo), "--heuristics-only", "--base-commit", "abc"]
    )
    assert result.exit_code == 0, result.output

    index = load_index(repo / ".docpulse" / "index.json")
    languages = {c.language for c in index.chunks}
    assert languages == {"python", "typescript", "csharp"}
    linked_sections = {link.section_id for link in index.links}
    assert any("auth.md" in s for s in linked_sections)
    assert any("pricing.md" in s for s in linked_sections)
    assert "chunks" in result.output  # summary line printed

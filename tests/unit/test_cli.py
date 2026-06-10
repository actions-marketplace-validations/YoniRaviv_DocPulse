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


def test_symbol_free_section_is_not_heuristically_linked(tmp_path):
    """Documents the known Phase 1 limitation that motivates embedding linking.

    behavior.md describes formatPrice without naming it -> heuristics can't link it.
    This is the gap embedding links close; recall on real repos is measured in Phase 2+.
    """
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    runner.invoke(app, ["index", "--root", str(repo), "--heuristics-only", "--base-commit", "x"])
    index = load_index(repo / ".docpulse" / "index.json")
    behavior_links = [link for link in index.links if "behavior.md" in link.section_id]
    assert behavior_links == []  # known gap, embedding linking required

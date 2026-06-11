# tests/unit/test_cli.py
import subprocess
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


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _committed_fixture(tmp_path) -> tuple[Path, str]:
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    # Remove any pre-built index so tests start from a clean state.
    shutil.rmtree(repo / ".docpulse", ignore_errors=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_check_surfaces_linked_section_on_param_rename(tmp_path):
    repo, base = _committed_fixture(tmp_path)
    index_result = runner.invoke(
        app, ["index", "--root", str(repo), "--heuristics-only", "--base-commit", base]
    )
    assert index_result.exit_code == 0

    auth = repo / "src" / "auth.py"
    auth.write_text(auth.read_text().replace("user: str", "username: str"))
    _git(repo, "commit", "-am", "rename login param")

    result = runner.invoke(app, ["check", "--root", str(repo), "--base", base, "--suspects-only"])
    assert result.exit_code == 0, result.output
    assert "docs/auth.md#authentication/login" in result.output
    assert "AuthService.login" in result.output
    assert "pricing.md" not in result.output
    assert "sessions" not in result.output
    assert "1 suspect section (of 1 candidate)" in result.output


def test_check_comment_only_change_surfaces_nothing(tmp_path):
    repo, base = _committed_fixture(tmp_path)
    index_result = runner.invoke(
        app, ["index", "--root", str(repo), "--heuristics-only", "--base-commit", base]
    )
    assert index_result.exit_code == 0

    cart = repo / "src" / "cart.ts"
    cart.write_text(
        cart.read_text().replace(
            "  return `$${(cents / 100).toFixed(2)}`;",
            "  // cents arrive pre-tax\n  return `$${(cents / 100).toFixed(2)}`;",
        )
    )
    _git(repo, "commit", "-am", "comment only")

    result = runner.invoke(app, ["check", "--root", str(repo), "--base", base, "--suspects-only"])
    assert result.exit_code == 0, result.output
    assert "no suspect doc sections" in result.output


def test_check_without_index_exits_2(tmp_path):
    repo, base = _committed_fixture(tmp_path)
    result = runner.invoke(app, ["check", "--root", str(repo), "--base", base])
    assert result.exit_code == 2


def test_check_bad_base_ref_exits_2_with_message(tmp_path):
    repo, base = _committed_fixture(tmp_path)
    runner.invoke(app, ["index", "--root", str(repo), "--heuristics-only", "--base-commit", base])
    result = runner.invoke(app, ["check", "--root", str(repo), "--base", "no-such-ref", "--suspects-only"])
    assert result.exit_code == 2
    assert "no-such-ref" in result.output or "failed" in result.output

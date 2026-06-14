import subprocess
from pathlib import Path

from docpulse.ci import loop_guard

BOT = "docpulse-bot@users.noreply.github.com"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo_with_commit(tmp_path: Path, email: str) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "f.txt")
    _git(repo, "-c", f"user.email={email}", "-c", "user.name=T", "commit", "-q", "-m", "c")
    return repo


def test_loop_guard_true_for_bot_author(tmp_path):
    repo = _repo_with_commit(tmp_path, BOT)
    assert loop_guard(repo, BOT) is True


def test_loop_guard_false_for_human_author(tmp_path):
    repo = _repo_with_commit(tmp_path, "dev@example.com")
    assert loop_guard(repo, BOT) is False


def test_loop_guard_false_when_no_commits(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    assert loop_guard(repo, BOT) is False

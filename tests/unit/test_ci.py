import subprocess
from pathlib import Path

import docpulse.ci as ci
from docpulse.ci import ensure_safe_directory, loop_guard, resolve_base_ref

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


def test_loop_guard_false_when_git_unavailable(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(ci.subprocess, "run", boom)
    assert loop_guard(tmp_path, BOT) is False


def test_resolve_base_ref_noop_when_ref_resolves(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    # HEAD always resolves; must do nothing and not raise.
    resolve_base_ref(repo, "HEAD")


def test_resolve_base_ref_swallows_fetch_failure(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    # origin/main does not resolve and there is no 'origin' remote -> must not raise.
    resolve_base_ref(repo, "origin/main")


def test_resolve_base_ref_fetches_parsed_remote_branch(tmp_path, monkeypatch):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    calls = []

    class _R:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        return _R()

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    resolve_base_ref(repo, "origin/feature/x")
    assert [
        "git", "fetch", "--no-tags", "--depth=50", "origin",
        "+refs/heads/feature/x:refs/remotes/origin/feature/x",
    ] in calls


def test_is_dubious_ownership_detects_message():
    assert ci._is_dubious_ownership(
        "fatal: detected dubious ownership in repository at '/work'"
    )
    assert not ci._is_dubious_ownership("")
    assert not ci._is_dubious_ownership("fatal: not a git repository")


def test_ensure_safe_directory_noop_on_clean_repo(tmp_path):
    repo = _repo_with_commit(tmp_path, "d@e.f")
    before = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, text=True,
    ).stdout
    ensure_safe_directory(repo)  # same-uid repo -> probe succeeds -> no mutation
    after = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, text=True,
    ).stdout
    assert before == after

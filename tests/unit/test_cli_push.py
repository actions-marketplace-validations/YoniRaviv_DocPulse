import subprocess

from typer.testing import CliRunner

import docpulse.cli as cli_mod
from docpulse.cli import _bot_identity, _pr_number, app
from docpulse.models import RunResult

runner = CliRunner()


def test_pr_number_explicit_env():
    assert _pr_number({"DOCPULSE_PR_NUMBER": "12"}) == "12"
    assert _pr_number({"PR_NUMBER": "13"}) == "13"


def test_pr_number_from_github_ref():
    assert _pr_number({"GITHUB_REF": "refs/pull/99/merge"}) == "99"


def test_pr_number_none_when_absent():
    assert _pr_number({}) is None


def test_bot_identity_defaults():
    name, email = _bot_identity({})
    assert name == "docpulse[bot]"
    assert email == "docpulse-bot@users.noreply.github.com"


def test_bot_identity_env_override():
    name, email = _bot_identity(
        {"DOCPULSE_BOT_NAME": "Custom Bot", "DOCPULSE_BOT_EMAIL": "bot@corp.test"}
    )
    assert name == "Custom Bot"
    assert email == "bot@corp.test"


def test_bot_identity_partial_override():
    name, email = _bot_identity({"DOCPULSE_BOT_NAME": "MyBot"})
    assert name == "MyBot"
    assert email == "docpulse-bot@users.noreply.github.com"


class _FakeDest:
    last = None

    def __init__(self, **kwargs):
        _FakeDest.last = kwargs
        self.published = False

    def publish_findings(self, result):
        self.published = True

    def summarize(self, result):
        print("SUMMARY")

    def publish_fix(self, result):
        return "https://example/pull/1"

    def build_fix_plan(self, result):
        return None


def _init_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".docpulse").mkdir()
    (repo / ".docpulse" / "index.json").write_text(
        '{"version":1,"base_commit":"x","chunks":[],"sections":[],"links":[]}'
    )
    (repo / "docpulse.yml").write_text("model: anthropic/claude-haiku-4-5\ndocs:\n  - path: '**/*.md'\n")
    return repo


def test_check_push_passes_live_kwargs(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FakeDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    monkeypatch.setattr(
        cli_mod, "run_pipeline",
        lambda *a, **k: RunResult(verdicts=[], repairs=[], suspects_checked=0,
                                  suspects_total=0, tokens_used=0, exit_code=0),
    )
    monkeypatch.setattr(cli_mod, "GitContext", lambda *a, **k: type("C", (), {"get_intent": lambda self: ""})())
    monkeypatch.setenv("DOCPULSE_PR_NUMBER", "55")
    result = runner.invoke(app, ["check", "--base", "origin/main", "--root", str(repo), "--push"])
    assert result.exit_code == 0, result.output
    assert _FakeDest.last["dry_run"] is False
    assert _FakeDest.last["pr_number"] == "55"


def test_repair_push_commits_to_branch(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)

    class _FixDest(_FakeDest):
        def build_fix_plan(self, result):
            return object()  # non-None sentinel; push path skips diff printing
        def publish_fix(self, result):
            return "docs: sync stale sections with code changes (DocPulse)"

    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FixDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    monkeypatch.setattr(
        cli_mod, "run_pipeline",
        lambda *a, **k: RunResult(verdicts=[], repairs=[], suspects_checked=0,
                                  suspects_total=0, tokens_used=0, exit_code=1),
    )
    monkeypatch.setattr(cli_mod, "GitContext", lambda *a, **k: type("C", (), {"get_intent": lambda self: ""})())
    result = runner.invoke(app, ["repair", "--base", "origin/main", "--root", str(repo), "--push"])
    assert result.exit_code == 1, result.output     # drift exit preserved
    assert _FakeDest.last["dry_run"] is False
    assert "pushed a doc-sync commit" in result.output


def test_repair_push_skips_when_head_is_bot_commit(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    # make the loop guard fire regardless of the repo's real HEAD
    monkeypatch.setattr(cli_mod.ci, "loop_guard", lambda root, email: True)
    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FakeDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    called = {"pipeline": False}

    def _pipeline(*a, **k):
        called["pipeline"] = True
        raise AssertionError("pipeline must not run when the loop guard fires")

    monkeypatch.setattr(cli_mod, "run_pipeline", _pipeline)
    result = runner.invoke(
        app, ["repair", "--base", "origin/main", "--root", str(repo), "--push"]
    )
    assert result.exit_code == 0, result.output
    assert "skipping to avoid a loop" in result.output
    assert called["pipeline"] is False


def test_check_passes_comment_options_to_destination(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(cli_mod, "_build_destination", lambda **kw: _FakeDest(**kw))
    monkeypatch.setattr(cli_mod, "LLMClient", lambda model: object())
    monkeypatch.setattr(
        cli_mod, "run_pipeline",
        lambda *a, **k: RunResult(verdicts=[], repairs=[], suspects_checked=0,
                                  suspects_total=0, tokens_used=0, exit_code=0),
    )
    monkeypatch.setattr(cli_mod, "GitContext", lambda *a, **k: type("C", (), {"get_intent": lambda self: ""})())
    out = tmp_path / "flag.md"
    result = runner.invoke(app, [
        "check", "--base", "origin/main", "--root", str(repo),
        "--comment-out", str(out), "--comment-via", "none",
    ])
    assert result.exit_code == 0, result.output
    assert _FakeDest.last["comment_out"] == out
    assert _FakeDest.last["comment_via"] == "none"

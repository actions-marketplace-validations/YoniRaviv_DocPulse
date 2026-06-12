import subprocess

from typer.testing import CliRunner

import docpulse.cli as cli_mod
from docpulse.cli import _base_branch, _pr_number, app
from docpulse.models import RunResult

runner = CliRunner()


def test_base_branch_strips_origin_prefix():
    assert _base_branch("origin/main") == "main"
    assert _base_branch("origin/feature/x") == "feature/x"
    assert _base_branch("main") == "main"


def test_pr_number_explicit_env():
    assert _pr_number({"DOCPULSE_PR_NUMBER": "12"}) == "12"
    assert _pr_number({"PR_NUMBER": "13"}) == "13"


def test_pr_number_from_github_ref():
    assert _pr_number({"GITHUB_REF": "refs/pull/99/merge"}) == "99"


def test_pr_number_none_when_absent():
    assert _pr_number({}) is None


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

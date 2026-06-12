import pytest

from docpulse.command_runner import checked_runner, default_runner


def test_default_runner_returns_empty_on_failure(tmp_path):
    run = default_runner(tmp_path)
    assert run(["git", "rev-parse", "definitely-not-a-ref"]) == ""


def test_checked_runner_returns_stdout_on_success(tmp_path):
    run = checked_runner(tmp_path)
    out = run(["git", "--version"])
    assert "git version" in out


def test_checked_runner_raises_on_failure(tmp_path):
    run = checked_runner(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        run(["git", "rev-parse", "definitely-not-a-ref"])
    msg = str(exc.value)
    assert "git" in msg  # includes the command

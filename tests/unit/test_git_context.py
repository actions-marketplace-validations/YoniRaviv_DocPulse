from pathlib import Path

from docpulse.context.git_context import GitContext


def test_intent_from_env_includes_tickets():
    ctx = GitContext(
        Path("."), "base", "head",
        env={"PR_TITLE": "Fix login flow", "PR_BODY": "Closes PROJ-42 and JIRA-7"},
        run_command=lambda args: "",
    )
    intent = ctx.get_intent()
    assert "Fix login flow" in intent
    assert "Closes PROJ-42" in intent
    assert "Tickets: JIRA-7, PROJ-42" in intent  # sorted, de-duped


def test_intent_falls_back_to_commit_messages():
    ctx = GitContext(
        Path("."), "base", "head",
        env={},
        run_command=lambda args: "rename login param\n\ndetailed body\n",
    )
    intent = ctx.get_intent()
    assert "Commits:" in intent
    assert "rename login param" in intent


def test_intent_empty_when_nothing_available():
    ctx = GitContext(Path("."), "b", "h", env={}, run_command=lambda args: "")
    assert ctx.get_intent() == ""


def test_get_intent_satisfies_protocol():
    from docpulse.context.base import ContextProvider

    ctx: ContextProvider = GitContext(Path("."), "b", "h", env={}, run_command=lambda a: "")
    assert isinstance(ctx, ContextProvider)


def test_intent_combines_pr_env_and_commits():
    ctx = GitContext(
        Path("."), "base", "head",
        env={"PR_TITLE": "Add logout", "PR_BODY": "see PROJ-1"},
        run_command=lambda args: "implement logout endpoint\n",
    )
    intent = ctx.get_intent()
    assert "PR: Add logout" in intent
    assert "Commits:" in intent
    assert "implement logout endpoint" in intent
    assert "Tickets: PROJ-1" in intent


def test_intent_body_only_has_no_dangling_pr_label():
    ctx = GitContext(
        Path("."), "base", "head",
        env={"PR_BODY": "just a body, no title"},
        run_command=lambda args: "",
    )
    intent = ctx.get_intent()
    assert "just a body" in intent
    assert "PR: \n" not in intent  # no dangling empty "PR:" label

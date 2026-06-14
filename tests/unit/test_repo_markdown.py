import pytest
from pathlib import Path

from docpulse.config import Config, DocGlob
from docpulse.destinations.repo_markdown import RepoMarkdownDestination, replace_sections
from docpulse.indexing.doc_parser import parse_markdown
from docpulse.models import DocSection, Repair, RunResult, Verdict


def test_replace_single_section():
    text = "# Title\n\nold body line\n"
    section = parse_markdown("d.md", text)[0]
    out = replace_sections(text, [(section, "# Title\n\nnew body line")])
    assert "new body line" in out
    assert "old body line" not in out
    assert out.endswith("\n")  # trailing newline preserved


def test_replace_sections_bottom_up_no_line_drift():
    text = "# A\nline a1\nline a2\n# B\nline b1\nline b2\n"
    secs = parse_markdown("d.md", text)
    a, b = secs[0], secs[1]
    # Shrink A (3 lines -> 2) and rewrite B; B must still be replaced correctly.
    out = replace_sections(text, [(a, "# A\nNEW A"), (b, "# B\nNEW B")])
    lines = out.splitlines()
    assert lines[:2] == ["# A", "NEW A"]
    assert lines[2:] == ["# B", "NEW B"]
    assert "line a1" not in out and "line b1" not in out


def test_round_trip_preserves_blank_separators():
    text = "# A\nbody\n\n# B\nother\n"
    secs = parse_markdown("d.md", text)
    # Re-applying each section's own content must reproduce the file byte-for-byte.
    assert replace_sections(text, [(s, s.content) for s in secs]) == text


def _section(sid="docs/auth.md#login", path="docs/auth.md"):
    return DocSection(id=sid, path=path, heading_path=["login"], content="c",
                      content_hash="h", mentions=[], start_line=1, end_line=1)


def _dest(sections, dry_run=True):
    return RepoMarkdownDestination(
        root=Path("."),
        sections_by_id={s.id: s for s in sections},
        config=Config(docs=[DocGlob(path="**/*.md")]),
        head_sha="abcdef1234567890",
        dry_run=dry_run,
    )


def test_flag_comment_lists_stale_above_threshold():
    section = _section()
    result = RunResult(
        verdicts=[
            Verdict(section_id=section.id, status="stale", confidence=0.8,
                    diagnosis="param renamed", evidence=["auth.py:2"]),
            Verdict(section_id="other", status="stale", confidence=0.2,
                    diagnosis="weak", evidence=[]),  # below threshold -> excluded
            Verdict(section_id="acc", status="accurate", confidence=0.0,
                    diagnosis="fine", evidence=[]),
        ],
        repairs=[], suspects_checked=3, suspects_total=3, tokens_used=0, exit_code=1,
    )
    comment = _dest([section]).flag_comment(result)
    assert "param renamed" in comment
    assert "auth.py:2" in comment
    assert "weak" not in comment  # below flag_threshold
    assert "fine" not in comment  # accurate not flagged


def test_flag_comment_empty_when_nothing_flagged():
    result = RunResult(verdicts=[], repairs=[], suspects_checked=0, suspects_total=0,
                       tokens_used=0, exit_code=0)
    assert _dest([]).flag_comment(result) == ""


def test_flag_comment_excludes_unverified_above_threshold():
    result = RunResult(
        verdicts=[Verdict(section_id="s", status="unverified", confidence=0.9,
                          diagnosis="cannot tell", evidence=[])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=0,
    )
    assert _dest([]).flag_comment(result) == ""  # unverified never flagged


def test_flag_comment_without_evidence_omits_evidence_suffix():
    section = _section()
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.8,
                          diagnosis="renamed", evidence=[])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    comment = _dest([section]).flag_comment(result)
    assert "renamed" in comment
    assert "evidence:" not in comment  # no evidence -> no evidence suffix


def test_build_fix_plan_groups_edits_and_routes(tmp_path):
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "auth.md"
    doc.write_text("# Login\n\nCall login with a user.\n")
    section = parse_markdown("docs/auth.md", doc.read_text())[0]

    dest = RepoMarkdownDestination(
        root=tmp_path,
        sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]),
        head_sha="abcdef1234567890",
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="renamed", evidence=["auth.py:2"])],
        repairs=[Repair(section_id=section.id, new_content="# Login\n\nCall login with a username.",
                        confidence=0.95, validation_passed=True, rationale="user->username")],
        suspects_checked=1, suspects_total=1, tokens_used=10, exit_code=1,
    )
    plan = dest.build_fix_plan(result)
    assert plan is not None
    assert "docs/auth.md" in plan.file_writes
    assert "username" in plan.file_writes["docs/auth.md"]
    # commands: git add, git commit, git push origin HEAD
    assert ["git", "add", "docs/auth.md"] in plan.commands
    assert [
        "git", "-c", "user.name=docpulse[bot]",
        "-c", "user.email=docpulse-bot@users.noreply.github.com",
        "commit", "-m", plan.commit_message,
    ] in plan.commands
    assert ["git", "push", "origin", "HEAD"] in plan.commands
    # no gh pr create or branch-checkout commands (doc-sync commit only)
    assert not any(c[:3] == ["gh", "pr", "create"] for c in plan.commands)
    assert not any(c[:3] == ["git", "checkout", "-b"] for c in plan.commands)


def test_build_fix_plan_skips_failed_validation(tmp_path):
    section = _section()
    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abc",
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="d", evidence=[])],
        repairs=[Repair(section_id=section.id, new_content="x", confidence=0.95,
                        validation_passed=False, rationale="failed")],  # route -> skip
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    assert dest.build_fix_plan(result) is None


def test_publish_fix_dry_run_returns_empty_without_running_commands(tmp_path):
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "auth.md"
    doc.write_text("# Login\n\nCall login with a user.\n")
    section = parse_markdown("docs/auth.md", doc.read_text())[0]
    ran: list[list[str]] = []
    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        run_command=lambda args: ran.append(args) or "", dry_run=True,
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="d", evidence=[])],
        repairs=[Repair(section_id=section.id, new_content="# Login\n\nfixed",
                        confidence=0.95, validation_passed=True, rationale="r")],
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    ret = dest.publish_fix(result)
    assert ret == ""  # dry-run: returns empty string
    assert ran == []  # dry-run: no git commands executed
    assert doc.read_text() == "# Login\n\nCall login with a user.\n"  # file untouched in dry-run


def test_build_fix_plan_groups_two_repairs_in_one_file(tmp_path):
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "api.md"
    doc.write_text("# A\nold a\n\n# B\nold b\n")
    secs = parse_markdown("docs/api.md", doc.read_text())
    a, b = secs[0], secs[1]
    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={a.id: a, b.id: b},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
    )
    result = RunResult(
        verdicts=[
            Verdict(section_id=a.id, status="stale", confidence=0.95, diagnosis="d", evidence=[]),
            Verdict(section_id=b.id, status="stale", confidence=0.95, diagnosis="d", evidence=[]),
        ],
        repairs=[
            Repair(section_id=a.id, new_content="# A\nNEW A", confidence=0.95,
                   validation_passed=True, rationale="fix a"),
            Repair(section_id=b.id, new_content="# B\nNEW B", confidence=0.95,
                   validation_passed=True, rationale="fix b"),
        ],
        suspects_checked=2, suspects_total=2, tokens_used=0, exit_code=1,
    )
    plan = dest.build_fix_plan(result)
    assert plan is not None
    assert list(plan.file_writes) == ["docs/api.md"]  # one file, both edits merged
    written = plan.file_writes["docs/api.md"]
    assert "NEW A" in written and "NEW B" in written
    assert "old a" not in written and "old b" not in written


def test_flag_comment_uses_heading_trail_and_collapsed_evidence():
    section = DocSection(
        id="docs/concepts/models.md#basic-model-usage/model-methods",
        path="docs/concepts/models.md",
        heading_path=["Basic model usage", "Model methods and properties"],
        content="c", content_hash="h", mentions=[], start_line=1, end_line=2,
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.8,
                          diagnosis="model_copy default changed",
                          evidence=["pydantic/main.py:393", "docs/concepts/models.md:160"])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    comment = _dest([section]).flag_comment(result)
    assert "### docs/concepts/models.md" in comment
    assert "Basic model usage › Model methods and properties" in comment
    assert "model_copy default changed" in comment
    assert "<details><summary>Evidence (2)</summary>" in comment
    assert "- pydantic/main.py:393" in comment
    assert "(docs/concepts/models.md)" not in comment  # no redundant path duplication


def test_flag_comment_singular_count():
    section = _section()
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.9,
                          diagnosis="d", evidence=[])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    assert "**1 section**" in _dest([section]).flag_comment(result)


def _stale_result(section):
    return RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.8,
                          diagnosis="param renamed", evidence=["auth.py:2"])],
        repairs=[], suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )


def test_publish_findings_live_posts_comment_to_pr():
    section = _section()
    calls = []
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        run_command=lambda args: calls.append(args) or "",
        dry_run=False, pr_number="42",
    )
    dest.publish_findings(_stale_result(section))
    assert calls == [["gh", "pr", "comment", "42", "--body", dest.flag_comment(_stale_result(section))]]


def test_publish_findings_writes_comment_out_file(tmp_path):
    section = _section()
    out = tmp_path / "flag.md"
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abc",
        dry_run=True, comment_out=out,
    )
    dest.publish_findings(_stale_result(section))
    assert "param renamed" in out.read_text()


def test_publish_findings_comment_via_none_skips_gh():
    section = _section()
    calls = []
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abc",
        run_command=lambda a: calls.append(a) or "",
        dry_run=False, pr_number="42", comment_via="none",
    )
    dest.publish_findings(_stale_result(section))
    assert calls == []  # gh never invoked when comment_via='none'


def test_build_fix_plan_commit_is_bot_authored(tmp_path):
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "auth.md"
    doc.write_text("# Login\n\nCall login with a user.\n")
    section = parse_markdown("docs/auth.md", doc.read_text())[0]
    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        bot_name="docpulse[bot]", bot_email="docpulse-bot@users.noreply.github.com",
    )
    result = RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="renamed", evidence=[])],
        repairs=[Repair(section_id=section.id,
                        new_content="# Login\n\nCall login with a username.",
                        confidence=0.95, validation_passed=True, rationale="r")],
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )
    plan = dest.build_fix_plan(result)
    assert [
        "git", "-c", "user.name=docpulse[bot]",
        "-c", "user.email=docpulse-bot@users.noreply.github.com",
        "commit", "-m", plan.commit_message,
    ] in plan.commands


def test_publish_findings_live_without_pr_number_prints(capsys):
    section = _section()
    dest = RepoMarkdownDestination(
        root=Path("."), sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        run_command=lambda args: "", dry_run=False, pr_number=None,
    )
    dest.publish_findings(_stale_result(section))
    assert "param renamed" in capsys.readouterr().out  # falls back to print


def _fixable_result(section):
    return RunResult(
        verdicts=[Verdict(section_id=section.id, status="stale", confidence=0.95,
                          diagnosis="d", evidence=[])],
        repairs=[Repair(section_id=section.id, new_content="# login\nfixed",
                        confidence=0.95, validation_passed=True, rationale="r")],
        suspects_checked=1, suspects_total=1, tokens_used=0, exit_code=1,
    )


def test_publish_fix_live_commits_and_pushes(tmp_path):
    md = tmp_path / "docs" / "auth.md"
    md.parent.mkdir(parents=True)
    md.write_text("# login\nold\n")
    section = DocSection(id="docs/auth.md#login", path="docs/auth.md",
                         heading_path=["login"], content="# login\nold",
                         content_hash="h", mentions=[], start_line=1, end_line=2)
    calls = []

    def fake_runner(args):
        calls.append(args)
        return ""

    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        run_command=fake_runner, dry_run=False,
    )
    commit_msg = dest.publish_fix(_fixable_result(section))
    assert commit_msg == "docs: sync stale sections with code changes (DocPulse)"  # returns the commit message
    assert md.read_text().splitlines()[:2] == ["# login", "fixed"]  # file written
    # first command(s) are git add
    assert calls[0][:2] == ["git", "add"]
    # last command is git push origin HEAD
    assert calls[-1] == ["git", "push", "origin", "HEAD"]
    # no gh pr create anywhere
    assert not any(c[:3] == ["gh", "pr", "create"] for c in calls)


def test_publish_fix_live_propagates_runner_error(tmp_path):
    md = tmp_path / "docs" / "auth.md"
    md.parent.mkdir(parents=True)
    md.write_text("# login\nold\n")
    section = DocSection(id="docs/auth.md#login", path="docs/auth.md",
                         heading_path=["login"], content="# login\nold",
                         content_hash="h", mentions=[], start_line=1, end_line=2)

    def boom(args):
        raise RuntimeError("no write permission")

    dest = RepoMarkdownDestination(
        root=tmp_path, sections_by_id={section.id: section},
        config=Config(docs=[DocGlob(path="**/*.md")]), head_sha="abcdef1234567890",
        run_command=boom, dry_run=False,
    )
    with pytest.raises(RuntimeError, match="no write permission"):
        dest.publish_fix(_fixable_result(section))

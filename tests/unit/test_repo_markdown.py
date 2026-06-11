from pathlib import Path

from docpulse.config import Config, DocGlob
from docpulse.destinations.repo_markdown import RepoMarkdownDestination, replace_sections
from docpulse.indexing.doc_parser import parse_markdown
from docpulse.models import DocSection, RunResult, Verdict


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

from docpulse.indexing.doc_parser import parse_markdown
from docpulse.destinations.repo_markdown import replace_sections


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

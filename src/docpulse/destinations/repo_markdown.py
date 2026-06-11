from docpulse.models import DocSection


def _content_lines(content: str) -> list[str]:
    """Split section content into lines, inverting doc_parser's `"\\n".join(...)`.

    `"\\n".join(L)` drops the trailing separator, so when a section ends on a blank
    line (content ends with "\\n"), `str.splitlines()` loses that final empty line.
    Re-appending it makes this the exact inverse of how doc_parser builds content.
    """
    lines = content.splitlines()
    if content.endswith("\n"):
        lines.append("")
    return lines


def replace_sections(file_text: str, edits: list[tuple[DocSection, str]]) -> str:
    """Apply (section, new_content) replacements to one file's text.

    Each section is replaced by its 1-based inclusive [start_line, end_line] range.
    Edits are applied bottom-up (highest start_line first) so an earlier edit that
    changes line count never shifts a later section's range. Uses str.splitlines()
    to match doc_parser's line model; the file's trailing newline is preserved.

    Note: line endings are normalized to "\\n" (CRLF input is rewritten to LF).
    """
    lines = file_text.splitlines()
    for section, new_content in sorted(edits, key=lambda e: e[0].start_line, reverse=True):
        lines[section.start_line - 1 : section.end_line] = _content_lines(new_content)
    trailing = "\n" if file_text.endswith("\n") else ""
    return "\n".join(lines) + trailing

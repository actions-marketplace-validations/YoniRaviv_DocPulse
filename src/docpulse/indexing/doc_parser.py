import hashlib
import re

from docpulse.models import DocSection

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^(```|~~~)")
_BACKTICKED = re.compile(r"`([A-Za-z_][\w.]*)`")
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b")
_CAMEL = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+(?:\.[A-Za-z_]\w*)*)\b")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def _mentions(content: str) -> list[str]:
    found: list[str] = []
    for pattern in (_BACKTICKED, _SNAKE, _CAMEL):
        found.extend(pattern.findall(content))
    return sorted(set(found))


def parse_markdown(path: str, text: str) -> list[DocSection]:
    lines = text.splitlines()
    sections: list[DocSection] = []
    # (level, title) stack of ancestor headings
    stack: list[tuple[int, str]] = []
    current_start: int | None = None
    current_path: list[str] = []
    in_fence = False

    def close(end_line: int) -> None:
        if current_start is None:
            return
        content = "\n".join(lines[current_start - 1 : end_line])
        sections.append(
            DocSection(
                id=f"{path}#" + "/".join(_slug(h) for h in current_path),
                path=path,
                heading_path=list(current_path),
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                mentions=_mentions(content),
                start_line=current_start,
                end_line=end_line,
            )
        )

    for lineno, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        close(lineno - 1)
        level, title = len(match.group(1)), match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_path = [title for _, title in stack]
        current_start = lineno
    close(len(lines))
    return sections

import re
from pathlib import Path
from typing import Any, Callable

from docpulse.models import Index

MAX_GREP_HITS = 50


class ToolError(RuntimeError):
    """A tool was called with bad/unsafe arguments; surfaced back to the model."""


def _resolve_in_root(root: Path, rel: str) -> Path:
    """Resolve `rel` under `root`, refusing anything that escapes the root."""
    root = root.resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise ToolError(f"path escapes workspace root: {rel}")
    return target


def read_file(root: Path, path: str, start: int, end: int) -> str:
    """Return lines [start, end] (1-based, inclusive) prefixed with line numbers."""
    target = _resolve_in_root(root, path)
    if not target.is_file():
        raise ToolError(f"not a file: {path}")
    lines = target.read_text(errors="replace").splitlines()
    start = max(1, start)
    end = min(len(lines), end)
    if start > end:
        raise ToolError(f"empty range {start}-{end} for {path} ({len(lines)} lines)")
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))


def grep(root: Path, pattern: str, glob: str) -> str:
    """Search files matching `glob` under root for `pattern`; return file:line: text."""
    if Path(glob).is_absolute() or ".." in Path(glob).parts:
        raise ToolError(f"unsafe glob: {glob}")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"bad regex: {exc}") from exc
    root = root.resolve()
    hits: list[str] = []
    for file in sorted(root.glob(glob)):
        if not file.is_file() or root not in file.resolve().parents:
            continue  # skip non-files and anything resolving outside root (symlinks)
        rel = file.relative_to(root)
        for lineno, line in enumerate(file.read_text(errors="replace").splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{lineno}: {line.rstrip()}")
                if len(hits) >= MAX_GREP_HITS:
                    hits.append(f"... (truncated at {MAX_GREP_HITS} matches)")
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "no matches"


def list_symbols(index: Index, path: str) -> str:
    """List symbols (name + signature + line range) the index knows for `path`."""
    rows = [
        f"{c.name}  L{c.start_line}-{c.end_line}: {c.signature}"
        for c in index.chunks
        if c.path == path
    ]
    return "\n".join(rows) if rows else f"no indexed symbols in {path}"


def make_dispatch(root: Path, index: Index) -> Callable[[str, dict[str, Any]], str]:
    """Return a callable(name, args) -> str that runs a tool and stringifies errors.

    Errors are returned as strings (not raised) so the agent loop can feed them
    back to the model instead of crashing.
    """

    def dispatch(name: str, args: dict[str, Any]) -> str:
        try:
            if name == "read_file":
                return read_file(root, args["path"], int(args["start"]), int(args["end"]))
            if name == "grep":
                return grep(root, args["pattern"], args.get("glob", "**/*"))
            if name == "list_symbols":
                return list_symbols(index, args["path"])
            return f"error: unknown tool {name!r}"
        except (ToolError, KeyError, ValueError, TypeError) as exc:
            return f"error: {exc}"

    return dispatch


READ_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read an inclusive 1-based line range from a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "repo-relative path"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["path", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Regex-search files matching a glob; returns path:line: text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex"},
                    "glob": {"type": "string", "description": "e.g. '**/*.py' (optional, defaults to **/*)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_symbols",
            "description": "List indexed symbols (name, signature, line range) for a file path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

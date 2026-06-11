import pytest

from docpulse.models import Index
from docpulse.verification.tools import (
    READ_TOOL_SCHEMAS,
    ToolError,
    grep,
    list_symbols,
    make_dispatch,
    read_file,
)
from tests.unit.test_models import make_chunk


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_read_file_returns_numbered_slice(tmp_path):
    _write(tmp_path, "a.py", "line1\nline2\nline3\nline4\n")
    out = read_file(tmp_path, "a.py", 2, 3)
    assert out == "2: line2\n3: line3"


def test_read_file_rejects_escape_outside_root(tmp_path):
    _write(tmp_path, "a.py", "x")
    with pytest.raises(ToolError, match="escapes workspace root"):
        read_file(tmp_path, "../secrets.txt", 1, 1)


def test_read_file_missing_file_is_tool_error(tmp_path):
    with pytest.raises(ToolError):
        read_file(tmp_path, "nope.py", 1, 1)


def test_grep_returns_path_and_line(tmp_path):
    _write(tmp_path, "src/a.py", "def login(user):\n    return user\n")
    _write(tmp_path, "src/b.py", "x = 1\n")
    out = grep(tmp_path, r"def login", "**/*.py")
    assert "src/a.py:1: def login(user):" in out
    assert "b.py" not in out


def test_grep_no_match_says_so(tmp_path):
    _write(tmp_path, "src/a.py", "x = 1\n")
    assert grep(tmp_path, "zzz", "**/*.py") == "no matches"


def test_list_symbols_for_path():
    index = Index(
        version=1, base_commit="x",
        chunks=[make_chunk(id="src/auth.py::AuthService.login", path="src/auth.py")],
        sections=[], links=[],
    )
    out = list_symbols(index, "src/auth.py")
    assert "AuthService.login" in out
    assert "def login(self, user: str) -> Token:" in out  # signature included


def test_dispatch_routes_by_name(tmp_path):
    _write(tmp_path, "a.py", "hello\nworld\n")
    index = Index(version=1, base_commit="x", chunks=[], sections=[], links=[])
    dispatch = make_dispatch(tmp_path, index)
    assert dispatch("read_file", {"path": "a.py", "start": 1, "end": 1}) == "1: hello"
    assert dispatch("unknown_tool", {}).startswith("error:")


def test_schemas_cover_three_tools():
    names = {s["function"]["name"] for s in READ_TOOL_SCHEMAS}
    assert names == {"read_file", "grep", "list_symbols"}


def test_grep_rejects_escaping_glob(tmp_path):
    _write(tmp_path, "a.py", "secret\n")
    with pytest.raises(ToolError):
        grep(tmp_path, "secret", "../*")


def test_dispatch_never_raises_on_bad_args(tmp_path):
    index = Index(version=1, base_commit="x", chunks=[], sections=[], links=[])
    dispatch = make_dispatch(tmp_path, index)
    assert dispatch("read_file", None).startswith("error:")        # non-dict args
    assert dispatch("grep", []).startswith("error:")               # list args
    assert dispatch("read_file",
                    {"path": "a.py", "start": "x", "end": "y"}).startswith("error:")  # bad int


def test_grep_truncates_at_max_hits(tmp_path):
    _write(tmp_path, "big.py", "\n".join(f"match {i}" for i in range(60)) + "\n")
    out = grep(tmp_path, r"match", "**/*.py")
    assert "truncated at 50 matches" in out
    assert out.count("big.py:") == 50  # exactly 50 hit lines before truncation marker
